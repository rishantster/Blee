import { getAddress, isAddress } from 'viem';
import type { MeshPacket, SolanaMeshPaymentEnvelopeV1 } from '../types/domain';
import { BleeStore } from './bleeStore';
import { looksLikeSolanaPublicKey } from './solanaGateway';
import { validateSolanaMeshPaymentEnvelope } from './solanaMeshEnvelope';

export const SOLANA_MESH_INBOX_KEY = 'mesh.solana-inbox.v1';
const INBOX_VERSION = 1;
const MAX_STORED_ENVELOPES = 64;

type SolanaMeshCustodyRole = 'recipient' | 'courier';

export type StoredSolanaMeshPayment = {
  version: 1;
  role: SolanaMeshCustodyRole;
  packet: MeshPacket;
  firstReceivedAt: number;
  lastReceivedAt: number;
};

type StoredSolanaMeshInbox = {
  version: 1;
  networkId: 'solana-mainnet';
  entries: StoredSolanaMeshPayment[];
  updatedAt: number;
};

let mutationTail: Promise<void> = Promise.resolve();

function withInboxLock<T>(operation: () => Promise<T>): Promise<T> {
  const task = mutationTail.then(operation, operation);
  mutationTail = task.then(() => undefined, () => undefined);
  return task;
}

async function ensureStore(): Promise<void> {
  const result = await BleeStore.init();
  if (!result.ready) throw new Error('Blee payment storage is unavailable');
}

function emptyInbox(): StoredSolanaMeshInbox {
  return {
    version: INBOX_VERSION,
    networkId: 'solana-mainnet',
    entries: [],
    updatedAt: Date.now(),
  };
}

function validTimestamp(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0;
}

async function validateStoredEntry(input: unknown): Promise<StoredSolanaMeshPayment> {
  const row = input as Partial<StoredSolanaMeshPayment> | null | undefined;
  if (!row || row.version !== 1 || (row.role !== 'recipient' && row.role !== 'courier')) {
    throw new Error('Stored SOL mesh payment is damaged');
  }
  if (!validTimestamp(row.firstReceivedAt) || !validTimestamp(row.lastReceivedAt)) {
    throw new Error('Stored SOL mesh payment timestamps are invalid');
  }
  if (!row.packet || typeof row.packet !== 'object') throw new Error('Stored SOL mesh packet is missing');
  await validateSolanaMeshPaymentEnvelope(row.packet);
  return {
    version: 1,
    role: row.role,
    packet: row.packet,
    firstReceivedAt: row.firstReceivedAt,
    lastReceivedAt: row.lastReceivedAt,
  };
}

async function readInbox(): Promise<StoredSolanaMeshInbox> {
  await ensureStore();
  const { value } = await BleeStore.getValue({ key: SOLANA_MESH_INBOX_KEY });
  if (!value) return emptyInbox();

  let parsed: Partial<StoredSolanaMeshInbox>;
  try { parsed = JSON.parse(value) as Partial<StoredSolanaMeshInbox>; } catch {
    throw new Error('Solana mesh inbox is damaged');
  }
  if (
    parsed.version !== INBOX_VERSION
    || parsed.networkId !== 'solana-mainnet'
    || !Array.isArray(parsed.entries)
    || parsed.entries.length > MAX_STORED_ENVELOPES
    || !validTimestamp(parsed.updatedAt)
  ) {
    throw new Error('Solana mesh inbox is invalid');
  }

  const entries: StoredSolanaMeshPayment[] = [];
  for (const row of parsed.entries) entries.push(await validateStoredEntry(row));
  return {
    version: INBOX_VERSION,
    networkId: 'solana-mainnet',
    entries,
    updatedAt: parsed.updatedAt,
  };
}

async function persistInbox(inbox: StoredSolanaMeshInbox): Promise<void> {
  inbox.updatedAt = Date.now();
  await BleeStore.setValue({ key: SOLANA_MESH_INBOX_KEY, value: JSON.stringify(inbox) });
}

function envelopeConflict(
  a: SolanaMeshPaymentEnvelopeV1,
  b: SolanaMeshPaymentEnvelopeV1,
  aOrigin: string,
  bOrigin: string,
): boolean {
  return (
    aOrigin.toLowerCase() !== bOrigin.toLowerCase()
    || a.signedTransactionSha256 !== b.signedTransactionSha256
    || a.senderSolana !== b.senderSolana
    || a.recipientEvm.toLowerCase() !== b.recipientEvm.toLowerCase()
    || a.recipientSolana !== b.recipientSolana
    || a.amountLamports !== b.amountLamports
    || a.nonceAccountAddress !== b.nonceAccountAddress
    || a.nonce !== b.nonce
  );
}

async function storeValidatedInboundSolanaMeshPayment(input: {
  packet: MeshPacket;
  envelope: SolanaMeshPaymentEnvelopeV1;
  localEvmAddress: string;
  localSolanaAddress?: string | null;
  allowCourier: boolean;
}): Promise<{ stored: StoredSolanaMeshPayment; envelope: SolanaMeshPaymentEnvelopeV1; duplicate: boolean } | null> {
  if (!isAddress(input.localEvmAddress)) throw new Error('Local Blee identity is invalid');
  const localEvmAddress = getAddress(input.localEvmAddress);
  const envelope = input.envelope;

  let role: SolanaMeshCustodyRole;
  if (envelope.recipientEvm.toLowerCase() === localEvmAddress.toLowerCase()) {
    const localSolanaAddress = String(input.localSolanaAddress || '').trim();
    if (!looksLikeSolanaPublicKey(localSolanaAddress)) {
      throw new Error('Local Solana identity is unavailable for an addressed SOL payment');
    }
    if (localSolanaAddress !== envelope.recipientSolana) {
      throw new Error('SOL mesh payment targets a different Solana identity');
    }
    role = 'recipient';
  } else {
    if (!input.allowCourier) return null;
    role = 'courier';
  }

  return withInboxLock(async () => {
    const inbox = await readInbox();
    const now = Date.now();
    let matchIndex = -1;
    let existingEnvelope: SolanaMeshPaymentEnvelopeV1 | null = null;

    for (let index = 0; index < inbox.entries.length; index += 1) {
      const candidate = inbox.entries[index];
      const candidateEnvelope = await validateSolanaMeshPaymentEnvelope(candidate.packet);
      if (candidateEnvelope.paymentId === envelope.paymentId) {
        matchIndex = index;
        existingEnvelope = candidateEnvelope;
        break;
      }
    }

    if (matchIndex >= 0 && existingEnvelope) {
      const existing = inbox.entries[matchIndex];
      if (envelopeConflict(existingEnvelope, envelope, existing.packet.origin, input.packet.origin)) {
        throw new Error('Blee SOL payment ID conflicts with different signed transaction bytes');
      }
      const updated: StoredSolanaMeshPayment = {
        ...existing,
        role: existing.role === 'recipient' || role === 'recipient' ? 'recipient' : 'courier',
        lastReceivedAt: now,
      };
      inbox.entries[matchIndex] = updated;
      await persistInbox(inbox);
      return { stored: { ...updated }, envelope, duplicate: true };
    }

    if (inbox.entries.length >= MAX_STORED_ENVELOPES) {
      throw new Error('Solana mesh inbox is full; connect to settle stored payments');
    }

    const stored: StoredSolanaMeshPayment = {
      version: 1,
      role,
      packet: input.packet,
      firstReceivedAt: now,
      lastReceivedAt: now,
    };
    inbox.entries.push(stored);
    await persistInbox(inbox);
    return { stored: { ...stored }, envelope, duplicate: false };
  });
}

/**
 * BLEE_SOLANA_MESH_DURABLE_CUSTODY_V1
 *
 * Persists exact authenticated SOL payment bytes before a recipient ever ACKs
 * or a courier claims custody. Replays with the same paymentId are idempotent
 * only when the signed-transaction digest and all routing/payment metadata are
 * identical. A conflicting replay fails closed.
 *
 * This store does not submit transactions. Recipient/courier custody is an
 * offline transport state, not proof of on-chain settlement.
 */
export async function storeInboundSolanaMeshPayment(input: {
  packet: MeshPacket;
  localEvmAddress: string;
  localSolanaAddress?: string | null;
  allowCourier: boolean;
}): Promise<{ stored: StoredSolanaMeshPayment; envelope: SolanaMeshPaymentEnvelopeV1; duplicate: boolean } | null> {
  const envelope = await validateSolanaMeshPaymentEnvelope(input.packet);
  return storeValidatedInboundSolanaMeshPayment({ ...input, envelope });
}

/**
 * Live mesh path used only after meshProtocol has authenticated the outer EVM
 * packet and validateAuthenticatedSolanaMeshPaymentEnvelope has verified the
 * SOL capability proof and exact signed-byte digest. This avoids recursively
 * re-entering verifyMeshPacket while preserving the same SQLite durability and
 * paymentId conflict rules as the standalone entry point.
 */
export async function storeVerifiedInboundSolanaMeshPayment(input: {
  packet: MeshPacket;
  envelope: SolanaMeshPaymentEnvelopeV1;
  localEvmAddress: string;
  localSolanaAddress?: string | null;
  allowCourier: boolean;
}): Promise<{ stored: StoredSolanaMeshPayment; envelope: SolanaMeshPaymentEnvelopeV1; duplicate: boolean } | null> {
  if (input.packet.type !== 'sol-payment') throw new Error('Verified SOL custody requires a SOL payment packet');
  const raw = input.packet.payload as Partial<SolanaMeshPaymentEnvelopeV1> | null;
  if (
    !raw
    || raw.paymentId !== input.envelope.paymentId
    || String(raw.signedTransactionSha256 || '').toLowerCase() !== input.envelope.signedTransactionSha256
  ) {
    throw new Error('Verified SOL custody envelope does not match its packet');
  }
  return storeValidatedInboundSolanaMeshPayment(input);
}

export async function loadStoredSolanaMeshPayments(): Promise<StoredSolanaMeshPayment[]> {
  const inbox = await readInbox();
  return inbox.entries.map((row) => ({ ...row }));
}
