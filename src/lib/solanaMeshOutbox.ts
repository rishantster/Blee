import { getAddress, isAddress } from 'viem';
import type { SolanaMeshDeliveryAckV1, SolanaMeshPaymentEnvelopeV1 } from '../types/domain';
import { BleeStore } from './bleeStore';
import { verifyMeshCapabilitiesV1 } from './meshCapabilities';
import { looksLikeSolanaPublicKey } from './solanaGateway';
import { signalSolanaActivityChanged } from './solanaActivitySignal';

export const SOLANA_MESH_OUTBOX_KEY = 'mesh.solana-outbox.v1';
const OUTBOX_VERSION = 1;
const MAX_OUTBOX_ENTRIES = 64;
const SHA256_HEX_RE = /^[0-9a-f]{64}$/;
const BASE64_RE = /^[A-Za-z0-9+/]+={0,2}$/;
const MAX_WIRE_TRANSACTION_BYTES = 1232;
const MAX_WIRE_TRANSACTION_B64_CHARS = 4096;

type SolanaMeshOutboundState = 'prepared' | 'broadcast' | 'delivered';

export type StoredOutboundSolanaMeshPayment = {
  version: 1;
  senderEvm: string;
  envelope: SolanaMeshPaymentEnvelopeV1;
  state: SolanaMeshOutboundState;
  attempts: number;
  createdAt: number;
  updatedAt: number;
  lastBroadcastAt?: number;
  deliveredAt?: number;
};

type StoredSolanaMeshOutbox = {
  version: 1;
  networkId: 'solana-mainnet';
  entries: StoredOutboundSolanaMeshPayment[];
  updatedAt: number;
};

let mutationTail: Promise<void> = Promise.resolve();

function withOutboxLock<T>(operation: () => Promise<T>): Promise<T> {
  const task = mutationTail.then(operation, operation);
  mutationTail = task.then(() => undefined, () => undefined);
  return task;
}

async function ensureStore(): Promise<void> {
  const result = await BleeStore.init();
  if (!result.ready) throw new Error('Blee payment storage is unavailable');
}

function validTimestamp(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0;
}

function decodeWireTransaction(value: string): Uint8Array {
  const clean = value.trim();
  if (!clean || clean.length > MAX_WIRE_TRANSACTION_B64_CHARS || clean.length % 4 !== 0 || !BASE64_RE.test(clean)) {
    throw new Error('Stored SOL transaction is not canonical base64');
  }
  let bytes: Uint8Array;
  try {
    const binary = atob(clean);
    bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  } catch {
    throw new Error('Stored SOL transaction is not valid base64');
  }
  if (bytes.byteLength <= 64 || bytes.byteLength > MAX_WIRE_TRANSACTION_BYTES) {
    throw new Error('Stored SOL transaction has an invalid wire size');
  }
  return bytes;
}

async function wireDigest(value: string): Promise<string> {
  const bytes = decodeWireTransaction(value);
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', copy.buffer));
  copy.fill(0);
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function validateEnvelope(senderEvmInput: string, input: unknown): Promise<SolanaMeshPaymentEnvelopeV1> {
  if (!isAddress(senderEvmInput)) throw new Error('Stored SOL sender Blee identity is invalid');
  const senderEvm = getAddress(senderEvmInput);
  const raw = input as Partial<SolanaMeshPaymentEnvelopeV1> | null | undefined;
  if (!raw || raw.version !== 1 || raw.railId !== 'solana-sol' || raw.networkId !== 'solana-mainnet') {
    throw new Error('Stored SOL payment envelope is invalid');
  }
  if (!raw.paymentId || typeof raw.paymentId !== 'string' || raw.paymentId.length > 160) {
    throw new Error('Stored SOL payment ID is invalid');
  }
  if (!isAddress(String(raw.recipientEvm || ''))) throw new Error('Stored SOL recipient Blee identity is invalid');
  const senderSolana = String(raw.senderSolana || '').trim();
  const recipientSolana = String(raw.recipientSolana || '').trim();
  const nonceAccountAddress = String(raw.nonceAccountAddress || '').trim();
  const nonce = String(raw.nonce || '').trim();
  if (!looksLikeSolanaPublicKey(senderSolana)) throw new Error('Stored SOL sender address is invalid');
  if (!looksLikeSolanaPublicKey(recipientSolana)) throw new Error('Stored SOL recipient address is invalid');
  if (!looksLikeSolanaPublicKey(nonceAccountAddress)) throw new Error('Stored SOL nonce account is invalid');
  if (!looksLikeSolanaPublicKey(nonce)) throw new Error('Stored SOL nonce is invalid');

  let amountLamports: bigint;
  try { amountLamports = BigInt(String(raw.amountLamports || '')); } catch { throw new Error('Stored SOL amount is invalid'); }
  if (amountLamports <= 0n) throw new Error('Stored SOL amount is invalid');

  const digest = String(raw.signedTransactionSha256 || '').trim().toLowerCase();
  if (!SHA256_HEX_RE.test(digest)) throw new Error('Stored SOL transaction digest is invalid');
  const signedTransactionBase64 = String(raw.signedTransactionBase64 || '').trim();
  if (await wireDigest(signedTransactionBase64) !== digest) {
    throw new Error('Stored SOL transaction bytes do not match their digest');
  }

  const senderCapabilities = await verifyMeshCapabilitiesV1(senderEvm, raw.senderCapabilities);
  if (
    !senderCapabilities
    || !senderCapabilities.rails.includes('solana-sol')
    || !senderCapabilities.solana
    || senderCapabilities.solana.networkId !== 'solana-mainnet'
    || senderCapabilities.solana.address !== senderSolana
  ) {
    throw new Error('Stored SOL sender capability proof is invalid');
  }

  return {
    version: 1,
    railId: 'solana-sol',
    networkId: 'solana-mainnet',
    paymentId: raw.paymentId,
    senderSolana,
    recipientEvm: getAddress(String(raw.recipientEvm)),
    recipientSolana,
    amountLamports: amountLamports.toString(),
    nonceAccountAddress,
    nonce,
    signedTransactionBase64,
    signedTransactionSha256: digest,
    senderCapabilities,
  };
}

async function validateEntry(input: unknown): Promise<StoredOutboundSolanaMeshPayment> {
  const raw = input as Partial<StoredOutboundSolanaMeshPayment> | null | undefined;
  if (!raw || raw.version !== 1 || (raw.state !== 'prepared' && raw.state !== 'broadcast' && raw.state !== 'delivered')) {
    throw new Error('Stored SOL outbox entry is invalid');
  }
  if (!Number.isInteger(raw.attempts) || (raw.attempts as number) < 0) throw new Error('Stored SOL outbox attempts are invalid');
  if (!validTimestamp(raw.createdAt) || !validTimestamp(raw.updatedAt)) throw new Error('Stored SOL outbox timestamps are invalid');
  if (raw.lastBroadcastAt !== undefined && !validTimestamp(raw.lastBroadcastAt)) throw new Error('Stored SOL broadcast timestamp is invalid');
  if (raw.deliveredAt !== undefined && !validTimestamp(raw.deliveredAt)) throw new Error('Stored SOL delivery timestamp is invalid');
  const senderEvm = getAddress(String(raw.senderEvm || ''));
  const envelope = await validateEnvelope(senderEvm, raw.envelope);
  return {
    version: 1,
    senderEvm,
    envelope,
    state: raw.state,
    attempts: raw.attempts as number,
    createdAt: raw.createdAt,
    updatedAt: raw.updatedAt,
    lastBroadcastAt: raw.lastBroadcastAt,
    deliveredAt: raw.deliveredAt,
  };
}

function emptyOutbox(): StoredSolanaMeshOutbox {
  return { version: OUTBOX_VERSION, networkId: 'solana-mainnet', entries: [], updatedAt: Date.now() };
}

async function readOutbox(): Promise<StoredSolanaMeshOutbox> {
  await ensureStore();
  const { value } = await BleeStore.getValue({ key: SOLANA_MESH_OUTBOX_KEY });
  if (!value) return emptyOutbox();
  let parsed: Partial<StoredSolanaMeshOutbox>;
  try { parsed = JSON.parse(value) as Partial<StoredSolanaMeshOutbox>; } catch { throw new Error('Solana mesh outbox is damaged'); }
  if (
    parsed.version !== OUTBOX_VERSION
    || parsed.networkId !== 'solana-mainnet'
    || !Array.isArray(parsed.entries)
    || parsed.entries.length > MAX_OUTBOX_ENTRIES
    || !validTimestamp(parsed.updatedAt)
  ) {
    throw new Error('Solana mesh outbox is invalid');
  }
  const entries: StoredOutboundSolanaMeshPayment[] = [];
  for (const row of parsed.entries) entries.push(await validateEntry(row));
  return { version: 1, networkId: 'solana-mainnet', entries, updatedAt: parsed.updatedAt };
}

async function persistOutbox(outbox: StoredSolanaMeshOutbox): Promise<void> {
  outbox.updatedAt = Date.now();
  await BleeStore.setValue({ key: SOLANA_MESH_OUTBOX_KEY, value: JSON.stringify(outbox) });
  signalSolanaActivityChanged();
}

function envelopesConflict(a: SolanaMeshPaymentEnvelopeV1, b: SolanaMeshPaymentEnvelopeV1, aSenderEvm: string, bSenderEvm: string): boolean {
  return (
    aSenderEvm.toLowerCase() !== bSenderEvm.toLowerCase()
    || a.signedTransactionSha256 !== b.signedTransactionSha256
    || a.senderSolana !== b.senderSolana
    || a.recipientEvm.toLowerCase() !== b.recipientEvm.toLowerCase()
    || a.recipientSolana !== b.recipientSolana
    || a.amountLamports !== b.amountLamports
    || a.nonceAccountAddress !== b.nonceAccountAddress
    || a.nonce !== b.nonce
  );
}

/**
 * BLEE_SOLANA_MESH_OUTBOX_V1
 *
 * Persists the authenticated envelope before any BLE frame is emitted. The
 * exact signed Solana transaction remains unchanged across retries; only the
 * outer Blee mesh packet may be re-signed with a new packet id so a recipient
 * can safely re-ACK after a lost acknowledgement.
 */
export async function persistOutboundSolanaMeshPayment(input: {
  senderEvm: string;
  envelope: SolanaMeshPaymentEnvelopeV1;
}): Promise<StoredOutboundSolanaMeshPayment> {
  const senderEvm = getAddress(input.senderEvm);
  const envelope = await validateEnvelope(senderEvm, input.envelope);
  return withOutboxLock(async () => {
    const outbox = await readOutbox();
    const index = outbox.entries.findIndex((row) => row.envelope.paymentId === envelope.paymentId);
    if (index >= 0) {
      const existing = outbox.entries[index];
      if (envelopesConflict(existing.envelope, envelope, existing.senderEvm, senderEvm)) {
        throw new Error('Blee SOL payment ID conflicts with a different outbound transaction');
      }
      return { ...existing, envelope: { ...existing.envelope } };
    }
    if (outbox.entries.length >= MAX_OUTBOX_ENTRIES) throw new Error('Solana mesh outbox is full');
    const now = Date.now();
    const row: StoredOutboundSolanaMeshPayment = {
      version: 1,
      senderEvm,
      envelope,
      state: 'prepared',
      attempts: 0,
      createdAt: now,
      updatedAt: now,
    };
    outbox.entries.push(row);
    await persistOutbox(outbox);
    return { ...row, envelope: { ...row.envelope } };
  });
}

export async function recordOutboundSolanaMeshBroadcast(input: {
  paymentId: string;
  signedTransactionSha256: string;
  recipients: number;
}): Promise<StoredOutboundSolanaMeshPayment> {
  return withOutboxLock(async () => {
    const outbox = await readOutbox();
    const index = outbox.entries.findIndex((row) => row.envelope.paymentId === input.paymentId);
    if (index < 0) throw new Error('Outbound SOL payment is not durably prepared');
    const row = outbox.entries[index];
    if (row.envelope.signedTransactionSha256 !== input.signedTransactionSha256.toLowerCase()) {
      throw new Error('Outbound SOL broadcast digest mismatch');
    }
    const now = Date.now();
    const updated: StoredOutboundSolanaMeshPayment = {
      ...row,
      state: row.state === 'delivered' ? 'delivered' : (input.recipients > 0 ? 'broadcast' : 'prepared'),
      attempts: row.attempts + 1,
      lastBroadcastAt: now,
      updatedAt: now,
    };
    outbox.entries[index] = updated;
    await persistOutbox(outbox);
    return { ...updated, envelope: { ...updated.envelope } };
  });
}

/** Applies a cryptographically verified recipient ACK to this device's outbox. */
export async function applyVerifiedSolanaDeliveryAck(input: {
  ack: SolanaMeshDeliveryAckV1;
  packetOrigin: string;
}): Promise<boolean> {
  if (!isAddress(input.packetOrigin) || input.packetOrigin.toLowerCase() !== input.ack.recipientEvm.toLowerCase()) {
    throw new Error('SOL delivery ACK origin mismatch');
  }
  return withOutboxLock(async () => {
    const outbox = await readOutbox();
    const index = outbox.entries.findIndex((row) => row.envelope.paymentId === input.ack.paymentId);
    if (index < 0) return false;
    const row = outbox.entries[index];
    if (
      row.envelope.signedTransactionSha256 !== input.ack.signedTransactionSha256.toLowerCase()
      || row.envelope.recipientEvm.toLowerCase() !== input.ack.recipientEvm.toLowerCase()
      || row.envelope.recipientSolana !== input.ack.recipientSolana
    ) {
      throw new Error('SOL delivery ACK conflicts with the durable outbound payment');
    }
    const now = Date.now();
    outbox.entries[index] = { ...row, state: 'delivered', deliveredAt: row.deliveredAt || now, updatedAt: now };
    await persistOutbox(outbox);
    return true;
  });
}

export async function loadOutboundSolanaMeshPayments(): Promise<StoredOutboundSolanaMeshPayment[]> {
  const outbox = await readOutbox();
  return outbox.entries.map((row) => ({ ...row, envelope: { ...row.envelope } }));
}
