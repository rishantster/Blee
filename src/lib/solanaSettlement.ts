import { getAddress, isAddress } from 'viem';
import { BleeStore } from './bleeStore';
import {
  getSolanaSignatureStatuses,
  getSolanaTransaction,
  looksLikeSolanaPublicKey,
  looksLikeSolanaSignature,
  sendSignedSolanaTransaction,
  SolanaGatewayError,
} from './solanaGateway';
import { signalSolanaActivityChanged } from './solanaActivitySignal';
import { validateSolanaMeshPaymentEnvelope } from './solanaMeshEnvelope';
import { loadOutboundSolanaMeshPayments } from './solanaMeshOutbox';
import { loadStoredSolanaMeshPayments } from './solanaMeshStore';
import {
  listSolanaNonceSlots,
  rearmAdvancedSolanaNonceSlot,
  reconcileSolanaNoncePool,
} from './solanaNoncePool';

export const SOLANA_SETTLEMENT_JOURNAL_KEY = 'solana.settlement.v1';

const JOURNAL_VERSION = 1;
const MAX_ENTRIES = 64;
const MAX_PAYMENT_ID_LENGTH = 160;
const MAX_WIRE_TRANSACTION_B64_CHARS = 4096;
const SHA256_HEX_RE = /^[0-9a-f]{64}$/;
const RETRY_DELAY_MS = 30_000;

type SolanaSettlementState = 'pending' | 'submitted' | 'confirmed' | 'finalized' | 'failed';
type SolanaSettlementSource = 'sender' | 'recipient' | 'courier';

export type SolanaSettlementRecord = {
  version: 1;
  railId: 'solana-sol';
  networkId: 'solana-mainnet';
  paymentId: string;
  signedTransactionSha256: string;
  signedTransactionBase64: string;
  senderEvm: string;
  senderSolana: string;
  recipientEvm: string;
  recipientSolana: string;
  amountLamports: string;
  nonceAccountAddress: string;
  nonce: string;
  source: SolanaSettlementSource;
  state: SolanaSettlementState;
  attempts: number;
  createdAt: number;
  updatedAt: number;
  lastAttemptAt?: number;
  nextRetryAt?: number;
  signature?: string;
  submittedAt?: number;
  confirmedAt?: number;
  finalizedAt?: number;
  lastCheckedAt?: number;
  nonceRearmedAt?: number;
  lastError?: string;
};

type StoredSolanaSettlementJournal = {
  version: 1;
  networkId: 'solana-mainnet';
  entries: SolanaSettlementRecord[];
  updatedAt: number;
};

type SettlementCandidate = Omit<SolanaSettlementRecord,
  'version' | 'railId' | 'networkId' | 'state' | 'attempts' | 'updatedAt'
> & {
  source: SolanaSettlementSource;
};

let mutationTail: Promise<void> = Promise.resolve();
let cycleTail: Promise<SolanaSettlementRecord[]> = Promise.resolve([]);

function withJournalLock<T>(operation: () => Promise<T>): Promise<T> {
  const task = mutationTail.then(operation, operation);
  mutationTail = task.then(() => undefined, () => undefined);
  return task;
}

function withCycleLock(operation: () => Promise<SolanaSettlementRecord[]>): Promise<SolanaSettlementRecord[]> {
  const task = cycleTail.then(operation, operation);
  cycleTail = task.then((rows) => rows, () => []);
  return task;
}

async function ensureStore(): Promise<void> {
  const result = await BleeStore.init();
  if (!result.ready) throw new Error('Blee payment storage is unavailable');
}

function validTimestamp(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0;
}

function cleanError(value: unknown): string {
  const message = value instanceof Error ? value.message : String(value || 'Solana settlement unavailable');
  return message.replace(/\s+/g, ' ').trim().slice(0, 240) || 'Solana settlement unavailable';
}

function validPaymentId(value: unknown): string {
  const clean = String(value || '').trim();
  if (!clean || clean.length > MAX_PAYMENT_ID_LENGTH) throw new Error('Stored SOL settlement payment ID is invalid');
  return clean;
}

function validDigest(value: unknown): string {
  const clean = String(value || '').trim().toLowerCase();
  if (!SHA256_HEX_RE.test(clean)) throw new Error('Stored SOL settlement digest is invalid');
  return clean;
}

function validLamports(value: unknown): string {
  let amount: bigint;
  try { amount = BigInt(String(value || '')); } catch { throw new Error('Stored SOL settlement amount is invalid'); }
  if (amount <= 0n) throw new Error('Stored SOL settlement amount is invalid');
  return amount.toString();
}

function validWireTransaction(value: unknown): string {
  const clean = String(value || '').trim();
  if (!clean || clean.length > MAX_WIRE_TRANSACTION_B64_CHARS) {
    throw new Error('Stored SOL settlement transaction is invalid');
  }
  return clean;
}

function validState(value: unknown): SolanaSettlementState {
  if (value === 'pending' || value === 'submitted' || value === 'confirmed' || value === 'finalized' || value === 'failed') return value;
  throw new Error('Stored SOL settlement state is invalid');
}

function validSource(value: unknown): SolanaSettlementSource {
  if (value === 'sender' || value === 'recipient' || value === 'courier') return value;
  throw new Error('Stored SOL settlement source is invalid');
}

function validateRecord(input: unknown): SolanaSettlementRecord {
  const raw = input as Partial<SolanaSettlementRecord> | null | undefined;
  if (!raw || raw.version !== 1 || raw.railId !== 'solana-sol' || raw.networkId !== 'solana-mainnet') {
    throw new Error('Stored SOL settlement record is invalid');
  }
  if (!isAddress(String(raw.senderEvm || '')) || !isAddress(String(raw.recipientEvm || ''))) {
    throw new Error('Stored SOL settlement Blee identity is invalid');
  }
  const senderSolana = String(raw.senderSolana || '').trim();
  const recipientSolana = String(raw.recipientSolana || '').trim();
  const nonceAccountAddress = String(raw.nonceAccountAddress || '').trim();
  const nonce = String(raw.nonce || '').trim();
  if (!looksLikeSolanaPublicKey(senderSolana) || !looksLikeSolanaPublicKey(recipientSolana)) {
    throw new Error('Stored SOL settlement address is invalid');
  }
  if (!looksLikeSolanaPublicKey(nonceAccountAddress) || !looksLikeSolanaPublicKey(nonce)) {
    throw new Error('Stored SOL settlement nonce is invalid');
  }
  const state = validState(raw.state);
  const signature = raw.signature === undefined ? undefined : String(raw.signature).trim();
  if (signature !== undefined && !looksLikeSolanaSignature(signature)) {
    throw new Error('Stored SOL settlement signature is invalid');
  }
  if ((state === 'submitted' || state === 'confirmed' || state === 'finalized') && !signature) {
    throw new Error('Stored SOL settlement signature is missing');
  }
  if (!Number.isInteger(raw.attempts) || Number(raw.attempts) < 0) {
    throw new Error('Stored SOL settlement attempt count is invalid');
  }
  if (!validTimestamp(raw.createdAt) || !validTimestamp(raw.updatedAt)) {
    throw new Error('Stored SOL settlement timestamps are invalid');
  }

  const record: SolanaSettlementRecord = {
    version: 1,
    railId: 'solana-sol',
    networkId: 'solana-mainnet',
    paymentId: validPaymentId(raw.paymentId),
    signedTransactionSha256: validDigest(raw.signedTransactionSha256),
    signedTransactionBase64: validWireTransaction(raw.signedTransactionBase64),
    senderEvm: getAddress(String(raw.senderEvm)),
    senderSolana,
    recipientEvm: getAddress(String(raw.recipientEvm)),
    recipientSolana,
    amountLamports: validLamports(raw.amountLamports),
    nonceAccountAddress,
    nonce,
    source: validSource(raw.source),
    state,
    attempts: Number(raw.attempts),
    createdAt: raw.createdAt,
    updatedAt: raw.updatedAt,
  };
  for (const key of ['lastAttemptAt', 'nextRetryAt', 'submittedAt', 'confirmedAt', 'finalizedAt', 'lastCheckedAt', 'nonceRearmedAt'] as const) {
    const value = raw[key];
    if (value !== undefined) {
      if (!validTimestamp(value)) throw new Error(`Stored SOL settlement ${key} is invalid`);
      record[key] = value;
    }
  }
  if (signature) record.signature = signature;
  if (raw.lastError !== undefined) record.lastError = cleanError(raw.lastError);
  return record;
}

function emptyJournal(): StoredSolanaSettlementJournal {
  return { version: JOURNAL_VERSION, networkId: 'solana-mainnet', entries: [], updatedAt: Date.now() };
}

async function readJournal(): Promise<StoredSolanaSettlementJournal> {
  await ensureStore();
  const { value } = await BleeStore.getValue({ key: SOLANA_SETTLEMENT_JOURNAL_KEY });
  if (!value) return emptyJournal();
  let parsed: Partial<StoredSolanaSettlementJournal>;
  try { parsed = JSON.parse(value) as Partial<StoredSolanaSettlementJournal>; } catch {
    throw new Error('Solana settlement journal is damaged');
  }
  if (
    parsed.version !== JOURNAL_VERSION
    || parsed.networkId !== 'solana-mainnet'
    || !Array.isArray(parsed.entries)
    || parsed.entries.length > MAX_ENTRIES
    || !validTimestamp(parsed.updatedAt)
  ) {
    throw new Error('Solana settlement journal is invalid');
  }
  const entries = parsed.entries.map(validateRecord);
  const ids = new Map<string, string>();
  for (const row of entries) {
    const previousDigest = ids.get(row.paymentId);
    if (previousDigest && previousDigest !== row.signedTransactionSha256) {
      throw new Error('Solana settlement journal contains a conflicting payment ID');
    }
    ids.set(row.paymentId, row.signedTransactionSha256);
  }
  return { version: 1, networkId: 'solana-mainnet', entries, updatedAt: parsed.updatedAt };
}

async function persistJournal(journal: StoredSolanaSettlementJournal): Promise<void> {
  journal.updatedAt = Date.now();
  await BleeStore.setValue({ key: SOLANA_SETTLEMENT_JOURNAL_KEY, value: JSON.stringify(journal) });
  signalSolanaActivityChanged();
}

function sourcePriority(source: SolanaSettlementSource): number {
  return source === 'sender' ? 3 : source === 'recipient' ? 2 : 1;
}

function sameCandidate(a: SolanaSettlementRecord, b: SettlementCandidate): boolean {
  return (
    a.signedTransactionSha256 === b.signedTransactionSha256
    && a.senderEvm.toLowerCase() === b.senderEvm.toLowerCase()
    && a.senderSolana === b.senderSolana
    && a.recipientEvm.toLowerCase() === b.recipientEvm.toLowerCase()
    && a.recipientSolana === b.recipientSolana
    && a.amountLamports === b.amountLamports
    && a.nonceAccountAddress === b.nonceAccountAddress
    && a.nonce === b.nonce
    && a.signedTransactionBase64 === b.signedTransactionBase64
  );
}

async function collectCandidates(): Promise<SettlementCandidate[]> {
  const [outbox, inbox] = await Promise.all([
    loadOutboundSolanaMeshPayments(),
    loadStoredSolanaMeshPayments(),
  ]);
  const byPaymentId = new Map<string, SettlementCandidate>();

  const put = (candidate: SettlementCandidate) => {
    const existing = byPaymentId.get(candidate.paymentId);
    if (!existing) {
      byPaymentId.set(candidate.paymentId, candidate);
      return;
    }
    if (
      existing.signedTransactionSha256 !== candidate.signedTransactionSha256
      || existing.signedTransactionBase64 !== candidate.signedTransactionBase64
      || existing.senderEvm.toLowerCase() !== candidate.senderEvm.toLowerCase()
      || existing.recipientEvm.toLowerCase() !== candidate.recipientEvm.toLowerCase()
    ) {
      throw new Error('Conflicting durable SOL payment copies cannot enter settlement');
    }
    if (sourcePriority(candidate.source) > sourcePriority(existing.source)) {
      byPaymentId.set(candidate.paymentId, candidate);
    }
  };

  for (const row of outbox) {
    const envelope = row.envelope;
    put({
      paymentId: envelope.paymentId,
      signedTransactionSha256: envelope.signedTransactionSha256,
      signedTransactionBase64: envelope.signedTransactionBase64,
      senderEvm: row.senderEvm,
      senderSolana: envelope.senderSolana,
      recipientEvm: envelope.recipientEvm,
      recipientSolana: envelope.recipientSolana,
      amountLamports: envelope.amountLamports,
      nonceAccountAddress: envelope.nonceAccountAddress,
      nonce: envelope.nonce,
      source: 'sender',
      createdAt: row.createdAt,
    });
  }

  for (const row of inbox) {
    const envelope = await validateSolanaMeshPaymentEnvelope(row.packet);
    put({
      paymentId: envelope.paymentId,
      signedTransactionSha256: envelope.signedTransactionSha256,
      signedTransactionBase64: envelope.signedTransactionBase64,
      senderEvm: row.packet.origin,
      senderSolana: envelope.senderSolana,
      recipientEvm: envelope.recipientEvm,
      recipientSolana: envelope.recipientSolana,
      amountLamports: envelope.amountLamports,
      nonceAccountAddress: envelope.nonceAccountAddress,
      nonce: envelope.nonce,
      source: row.role,
      createdAt: row.firstReceivedAt,
    });
  }

  return [...byPaymentId.values()].sort((a, b) => a.createdAt - b.createdAt);
}

async function registerCandidates(candidates: SettlementCandidate[]): Promise<void> {
  if (!candidates.length) return;
  await withJournalLock(async () => {
    const journal = await readJournal();
    for (const candidate of candidates) {
      const index = journal.entries.findIndex((row) => row.paymentId === candidate.paymentId);
      if (index >= 0) {
        const existing = journal.entries[index];
        if (!sameCandidate(existing, candidate)) {
          throw new Error('Blee SOL payment ID conflicts with a different settlement transaction');
        }
        if (sourcePriority(candidate.source) > sourcePriority(existing.source)) {
          journal.entries[index] = { ...existing, source: candidate.source, updatedAt: Date.now() };
        }
        continue;
      }
      if (journal.entries.length >= MAX_ENTRIES) throw new Error('Solana settlement journal is full');
      const now = Date.now();
      journal.entries.push({
        version: 1,
        railId: 'solana-sol',
        networkId: 'solana-mainnet',
        paymentId: candidate.paymentId,
        signedTransactionSha256: candidate.signedTransactionSha256,
        signedTransactionBase64: candidate.signedTransactionBase64,
        senderEvm: getAddress(candidate.senderEvm),
        senderSolana: candidate.senderSolana,
        recipientEvm: getAddress(candidate.recipientEvm),
        recipientSolana: candidate.recipientSolana,
        amountLamports: candidate.amountLamports,
        nonceAccountAddress: candidate.nonceAccountAddress,
        nonce: candidate.nonce,
        source: candidate.source,
        state: 'pending',
        attempts: 0,
        createdAt: candidate.createdAt || now,
        updatedAt: now,
      });
    }
    await persistJournal(journal);
  });
}

async function updateRecord(
  paymentId: string,
  digest: string,
  update: (row: SolanaSettlementRecord) => SolanaSettlementRecord,
): Promise<SolanaSettlementRecord> {
  return withJournalLock(async () => {
    const journal = await readJournal();
    const index = journal.entries.findIndex((row) => row.paymentId === paymentId);
    if (index < 0) throw new Error('SOL settlement record was not found');
    const current = journal.entries[index];
    if (current.signedTransactionSha256 !== digest) throw new Error('SOL settlement digest mismatch');
    const next = validateRecord(update({ ...current }));
    journal.entries[index] = next;
    await persistJournal(journal);
    return { ...next };
  });
}

function terminalGatewayError(error: unknown): boolean {
  if (!(error instanceof SolanaGatewayError)) return false;
  return new Set([
    'SOL_INVALID_ADDRESS',
    'SOL_INVALID_SIGNATURE',
    'SOL_INVALID_TRANSACTION',
    'SOL_TRANSACTION_SHAPE_REJECTED',
    'SOL_TRANSACTION_TOO_LARGE',
    'SOL_PAYMENT_ID_CONFLICT',
    'SOL_NONCE_INVALID',
    'SOL_PROVIDER_REJECTED_TRANSACTION',
  ]).has(error.code);
}

async function recordSubmissionFailure(row: SolanaSettlementRecord, error: unknown): Promise<SolanaSettlementRecord> {
  const now = Date.now();
  const terminal = terminalGatewayError(error);
  return updateRecord(row.paymentId, row.signedTransactionSha256, (current) => ({
    ...current,
    state: terminal ? 'failed' : current.state,
    attempts: current.attempts + 1,
    lastAttemptAt: now,
    nextRetryAt: terminal ? undefined : now + RETRY_DELAY_MS,
    lastError: cleanError(error),
    updatedAt: now,
  }));
}

async function submitPending(row: SolanaSettlementRecord): Promise<SolanaSettlementRecord> {
  const now = Date.now();
  if (row.nextRetryAt && row.nextRetryAt > now) return row;
  try {
    const result = await sendSignedSolanaTransaction({
      paymentId: row.paymentId,
      signedTransactionBase64: row.signedTransactionBase64,
    });
    if (!looksLikeSolanaSignature(result.signature)) throw new Error('Gateway returned an invalid Solana transaction signature');
    const submittedAt = Date.now();
    return updateRecord(row.paymentId, row.signedTransactionSha256, (current) => ({
      ...current,
      state: current.state === 'pending' ? 'submitted' : current.state,
      signature: result.signature,
      attempts: current.attempts + 1,
      lastAttemptAt: submittedAt,
      submittedAt: current.submittedAt || submittedAt,
      nextRetryAt: undefined,
      lastError: undefined,
      updatedAt: submittedAt,
    }));
  } catch (error) {
    return recordSubmissionFailure(row, error);
  }
}

function assertTransactionSummary(row: SolanaSettlementRecord, summary: {
  signature: string;
  sender?: string;
  recipient?: string;
  amountLamports?: string;
}): void {
  if (!row.signature || summary.signature !== row.signature) throw new Error('Solana transaction summary signature mismatch');
  if (summary.sender !== row.senderSolana) throw new Error('Solana transaction summary sender mismatch');
  if (summary.recipient !== row.recipientSolana) throw new Error('Solana transaction summary recipient mismatch');
  if (String(summary.amountLamports || '') !== row.amountLamports) throw new Error('Solana transaction summary amount mismatch');
}

async function refreshSubmitted(row: SolanaSettlementRecord): Promise<SolanaSettlementRecord> {
  if (!row.signature) return row;
  try {
    const statuses = await getSolanaSignatureStatuses([row.signature]);
    const status = statuses.find((candidate) => candidate.signature === row.signature) || statuses[0];
    const checkedAt = Date.now();
    if (!status) {
      return updateRecord(row.paymentId, row.signedTransactionSha256, (current) => ({
        ...current,
        lastCheckedAt: checkedAt,
        lastError: undefined,
        updatedAt: checkedAt,
      }));
    }
    if (status.err !== undefined && status.err !== null) {
      return updateRecord(row.paymentId, row.signedTransactionSha256, (current) => ({
        ...current,
        state: 'failed',
        lastCheckedAt: checkedAt,
        lastError: 'Solana reported a transaction execution error',
        updatedAt: checkedAt,
      }));
    }
    const confirmation = status.confirmationStatus;
    if (confirmation !== 'confirmed' && confirmation !== 'finalized') {
      return updateRecord(row.paymentId, row.signedTransactionSha256, (current) => ({
        ...current,
        lastCheckedAt: checkedAt,
        lastError: undefined,
        updatedAt: checkedAt,
      }));
    }

    // Finality is accepted only after the gateway returns an independently
    // decoded transaction summary matching the immutable payment envelope.
    const summary = await getSolanaTransaction(row.signature);
    assertTransactionSummary(row, summary);
    return updateRecord(row.paymentId, row.signedTransactionSha256, (current) => ({
      ...current,
      state: confirmation === 'finalized' ? 'finalized' : 'confirmed',
      confirmedAt: current.confirmedAt || checkedAt,
      finalizedAt: confirmation === 'finalized' ? (current.finalizedAt || checkedAt) : current.finalizedAt,
      lastCheckedAt: checkedAt,
      lastError: undefined,
      updatedAt: checkedAt,
    }));
  } catch (error) {
    const checkedAt = Date.now();
    return updateRecord(row.paymentId, row.signedTransactionSha256, (current) => ({
      ...current,
      lastCheckedAt: checkedAt,
      lastError: cleanError(error),
      updatedAt: checkedAt,
    }));
  }
}

async function maybeRearmFinalizedSenderNonce(input: {
  row: SolanaSettlementRecord;
  localEvmAddress?: string | null;
  localSolanaAddress?: string | null;
}): Promise<SolanaSettlementRecord> {
  const { row } = input;
  if (
    row.state !== 'finalized'
    || row.nonceRearmedAt
    || row.source !== 'sender'
    || !input.localEvmAddress
    || !input.localSolanaAddress
    || !isAddress(input.localEvmAddress)
    || getAddress(input.localEvmAddress).toLowerCase() !== row.senderEvm.toLowerCase()
    || input.localSolanaAddress !== row.senderSolana
  ) {
    return row;
  }

  try {
    await reconcileSolanaNoncePool(row.senderSolana);
    const slots = await listSolanaNonceSlots(row.senderSolana);
    const slot = slots.find((candidate) => candidate.paymentId === row.paymentId && candidate.address === row.nonceAccountAddress);
    if (!slot || slot.state !== 'advanced') return row;
    await rearmAdvancedSolanaNonceSlot({
      authority: row.senderSolana,
      slotId: slot.id,
      paymentId: row.paymentId,
    });
    const now = Date.now();
    return updateRecord(row.paymentId, row.signedTransactionSha256, (current) => ({
      ...current,
      nonceRearmedAt: current.nonceRearmedAt || now,
      lastError: undefined,
      updatedAt: now,
    }));
  } catch (error) {
    const checkedAt = Date.now();
    return updateRecord(row.paymentId, row.signedTransactionSha256, (current) => ({
      ...current,
      lastError: cleanError(error),
      updatedAt: checkedAt,
    }));
  }
}

/**
 * BLEE_SOLANA_SETTLEMENT_V1
 *
 * Registers exact signed SOL bytes from durable mesh custody before any gateway
 * request. Any Blee node holding an authenticated copy may broadcast those exact
 * bytes when online; no node rebuilds or re-signs the payment. Submission and
 * finality state are journaled independently from nearby-delivery state.
 */
export async function runSolanaSettlementCycle(input: {
  localEvmAddress?: string | null;
  localSolanaAddress?: string | null;
  limit?: number;
} = {}): Promise<SolanaSettlementRecord[]> {
  return withCycleLock(async () => {
    const candidates = await collectCandidates();
    await registerCandidates(candidates);
    const journal = await readJournal();
    const limit = Math.max(1, Math.min(8, Math.trunc(input.limit || 4)));
    const actionable = journal.entries
      .filter((row) => row.state !== 'finalized' || !row.nonceRearmedAt)
      .sort((a, b) => a.updatedAt - b.updatedAt)
      .slice(0, limit);

    for (let row of actionable) {
      if (row.state === 'pending') row = await submitPending(row);
      if (row.state === 'submitted' || row.state === 'confirmed') row = await refreshSubmitted(row);
      if (row.state === 'finalized') {
        row = await maybeRearmFinalizedSenderNonce({
          row,
          localEvmAddress: input.localEvmAddress,
          localSolanaAddress: input.localSolanaAddress,
        });
      }
    }
    return loadSolanaSettlementRecords();
  });
}

export async function loadSolanaSettlementRecords(): Promise<SolanaSettlementRecord[]> {
  const journal = await readJournal();
  return journal.entries.map((row) => ({ ...row, signedTransactionBase64: row.signedTransactionBase64 }));
}
