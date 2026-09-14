import { BleeStore } from './bleeStore';
import {
  getSolanaNonceAccount,
  looksLikeSolanaPublicKey,
  type SolanaNonceState,
} from './solanaGateway';

export const SOLANA_NONCE_POOL_KEY = 'solana.nonce-pool.v1';
export const SOLANA_NONCE_ACCOUNT_SPACE = 80;
export const DEFAULT_SOLANA_NONCE_POOL_TARGET = 4;

const POOL_VERSION = 1;
const MAX_NONCE_SLOTS = 16;
const MAX_PAYMENT_ID_LENGTH = 160;
const MAX_SIGNED_TRANSACTION_B64_CHARS = 48_000;
const U64_MAX = 18_446_744_073_709_551_615n;

type SolanaNonceSlotState = 'ready' | 'reserved' | 'advanced' | 'invalid';

export type SolanaNonceSlot = {
  id: string;
  index: number;
  address: string;
  authority: string;
  nonce: string;
  lamports: string;
  lamportsPerSignature: string;
  state: SolanaNonceSlotState;
  paymentId?: string;
  recipient?: string;
  amountLamports?: string;
  reservedAt?: number;
  signedAt?: number;
  signedTransactionBase64?: string;
  signedTransactionSha256?: string;
  observedNonce?: string;
  lastError?: string;
  createdAt: number;
  updatedAt: number;
};

type StoredSolanaNoncePool = {
  version: 1;
  networkId: 'solana-mainnet';
  authority: string;
  slots: SolanaNonceSlot[];
  updatedAt: number;
};

export type SolanaNonceReservation = {
  slotId: string;
  nonceAccountAddress: string;
  nonce: string;
  authority: string;
  paymentId: string;
  recipient: string;
  amountLamports: string;
  signedTransactionBase64?: string;
  signedTransactionSha256?: string;
};

let mutationTail: Promise<void> = Promise.resolve();

function withPoolLock<T>(operation: () => Promise<T>): Promise<T> {
  const task = mutationTail.then(operation, operation);
  mutationTail = task.then(() => undefined, () => undefined);
  return task;
}

function assertPublicKey(value: string, label: string): string {
  const clean = value.trim();
  if (!looksLikeSolanaPublicKey(clean)) throw new Error(`${label} is not a valid Solana address`);
  return clean;
}

function assertPaymentId(value: string): string {
  const clean = value.trim();
  if (!clean || clean.length > MAX_PAYMENT_ID_LENGTH) throw new Error('Invalid Blee payment ID');
  return clean;
}

function assertLamports(value: string): string {
  const clean = value.trim();
  let amount: bigint;
  try { amount = BigInt(clean); } catch { throw new Error('Invalid SOL amount'); }
  if (amount <= 0n || amount > U64_MAX) throw new Error('SOL amount is outside the supported range');
  return amount.toString();
}

function assertUnsignedLamports(value: string, label: string): string {
  const clean = value.trim();
  let amount: bigint;
  try { amount = BigInt(clean); } catch { throw new Error(`${label} is invalid`); }
  if (amount < 0n || amount > U64_MAX) throw new Error(`${label} is invalid`);
  return amount.toString();
}

function assertNonce(value: string): string {
  return assertPublicKey(value, 'Solana durable nonce');
}

function slotId(index: number): string {
  if (!Number.isInteger(index) || index < 0 || index >= MAX_NONCE_SLOTS) {
    throw new Error('Solana nonce slot index is invalid');
  }
  return `solana-mainnet:${index}`;
}

async function ensureStore(): Promise<void> {
  const result = await BleeStore.init();
  if (!result.ready) throw new Error('Blee payment storage is unavailable');
}

function emptyPool(authority: string): StoredSolanaNoncePool {
  return {
    version: POOL_VERSION,
    networkId: 'solana-mainnet',
    authority,
    slots: [],
    updatedAt: Date.now(),
  };
}

function validateSlot(input: unknown, authority: string): SolanaNonceSlot {
  const slot = input as Partial<SolanaNonceSlot> | null | undefined;
  if (!slot || typeof slot !== 'object') throw new Error('Solana nonce slot is damaged');
  if (slot.id !== slotId(slot.index as number)) throw new Error('Solana nonce slot identity is invalid');
  if (slot.authority !== authority) throw new Error('Solana nonce slot authority mismatch');

  const state = slot.state;
  if (state !== 'ready' && state !== 'reserved' && state !== 'advanced' && state !== 'invalid') {
    throw new Error('Solana nonce slot state is invalid');
  }

  const validated: SolanaNonceSlot = {
    id: slot.id,
    index: slot.index as number,
    address: assertPublicKey(String(slot.address || ''), 'Solana nonce account'),
    authority,
    nonce: assertNonce(String(slot.nonce || '')),
    lamports: assertUnsignedLamports(String(slot.lamports ?? ''), 'Solana nonce balance'),
    lamportsPerSignature: assertUnsignedLamports(String(slot.lamportsPerSignature ?? ''), 'Solana nonce fee'),
    state,
    createdAt: Number(slot.createdAt),
    updatedAt: Number(slot.updatedAt),
  };

  if (!Number.isFinite(validated.createdAt) || validated.createdAt <= 0 || !Number.isFinite(validated.updatedAt) || validated.updatedAt <= 0) {
    throw new Error('Solana nonce slot timestamps are invalid');
  }

  if (slot.paymentId !== undefined) validated.paymentId = assertPaymentId(String(slot.paymentId));
  if (slot.recipient !== undefined) validated.recipient = assertPublicKey(String(slot.recipient), 'SOL recipient');
  if (slot.amountLamports !== undefined) validated.amountLamports = assertLamports(String(slot.amountLamports));
  if (slot.reservedAt !== undefined) {
    const reservedAt = Number(slot.reservedAt);
    if (!Number.isFinite(reservedAt) || reservedAt <= 0) throw new Error('Solana nonce reservation timestamp is invalid');
    validated.reservedAt = reservedAt;
  }
  if (slot.signedAt !== undefined) {
    const signedAt = Number(slot.signedAt);
    if (!Number.isFinite(signedAt) || signedAt <= 0) throw new Error('Solana signed transaction timestamp is invalid');
    validated.signedAt = signedAt;
  }
  if (slot.signedTransactionBase64 !== undefined) {
    const raw = String(slot.signedTransactionBase64).trim();
    if (!raw || raw.length > MAX_SIGNED_TRANSACTION_B64_CHARS) throw new Error('Stored signed Solana transaction is invalid');
    validated.signedTransactionBase64 = raw;
  }
  if (slot.signedTransactionSha256 !== undefined) {
    const digest = String(slot.signedTransactionSha256).toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(digest)) throw new Error('Stored signed Solana transaction digest is invalid');
    validated.signedTransactionSha256 = digest;
  }
  if (slot.observedNonce !== undefined) validated.observedNonce = assertNonce(String(slot.observedNonce));
  if (slot.lastError !== undefined) validated.lastError = String(slot.lastError).slice(0, 240);

  const reservationFieldsPresent = Boolean(validated.paymentId && validated.recipient && validated.amountLamports && validated.reservedAt);
  if ((state === 'reserved' || state === 'advanced') && !reservationFieldsPresent) {
    throw new Error('Solana nonce reservation is incomplete');
  }
  if (validated.signedTransactionBase64 && !validated.signedTransactionSha256) {
    throw new Error('Signed Solana transaction digest is missing');
  }
  if (validated.signedTransactionSha256 && !validated.signedTransactionBase64) {
    throw new Error('Signed Solana transaction bytes are missing');
  }

  return validated;
}

function validatePool(input: unknown, authority: string): StoredSolanaNoncePool {
  const pool = input as Partial<StoredSolanaNoncePool> | null | undefined;
  if (!pool || pool.version !== POOL_VERSION || pool.networkId !== 'solana-mainnet') {
    throw new Error('Unsupported Solana nonce pool version');
  }
  if (pool.authority !== authority) throw new Error('Solana nonce pool belongs to a different wallet');
  if (!Array.isArray(pool.slots) || pool.slots.length > MAX_NONCE_SLOTS) throw new Error('Solana nonce pool is invalid');

  const slots = pool.slots.map((item) => validateSlot(item, authority));
  const ids = new Set(slots.map((slot) => slot.id));
  const addresses = new Set(slots.map((slot) => slot.address));
  if (ids.size !== slots.length || addresses.size !== slots.length) throw new Error('Solana nonce pool contains duplicate slots');

  const updatedAt = Number(pool.updatedAt);
  if (!Number.isFinite(updatedAt) || updatedAt <= 0) throw new Error('Solana nonce pool timestamp is invalid');
  return { version: POOL_VERSION, networkId: 'solana-mainnet', authority, slots, updatedAt };
}

async function readPool(authorityInput: string): Promise<StoredSolanaNoncePool> {
  const authority = assertPublicKey(authorityInput, 'Solana wallet');
  await ensureStore();
  const { value } = await BleeStore.getValue({ key: SOLANA_NONCE_POOL_KEY });
  if (!value) return emptyPool(authority);
  let parsed: unknown;
  try { parsed = JSON.parse(value) as unknown; } catch { throw new Error('Solana nonce pool is damaged'); }
  return validatePool(parsed, authority);
}

async function persistPool(pool: StoredSolanaNoncePool): Promise<void> {
  pool.updatedAt = Date.now();
  await BleeStore.setValue({ key: SOLANA_NONCE_POOL_KEY, value: JSON.stringify(pool) });
}

function reservationFromSlot(slot: SolanaNonceSlot): SolanaNonceReservation {
  if (!slot.paymentId || !slot.recipient || !slot.amountLamports) throw new Error('Solana nonce reservation is incomplete');
  return {
    slotId: slot.id,
    nonceAccountAddress: slot.address,
    nonce: slot.nonce,
    authority: slot.authority,
    paymentId: slot.paymentId,
    recipient: slot.recipient,
    amountLamports: slot.amountLamports,
    signedTransactionBase64: slot.signedTransactionBase64,
    signedTransactionSha256: slot.signedTransactionSha256,
  };
}

function validateGatewayNonce(state: SolanaNonceState, expectedAuthority: string): SolanaNonceState {
  const address = assertPublicKey(state.address, 'Solana nonce account');
  const authority = assertPublicKey(state.authority, 'Solana nonce authority');
  if (!state.valid) throw new Error(`Solana nonce account ${address} is not initialized`);
  if (authority !== expectedAuthority) throw new Error(`Solana nonce account ${address} has the wrong authority`);
  assertNonce(state.nonce);
  assertUnsignedLamports(state.lamports, 'Solana nonce balance');
  assertUnsignedLamports(state.lamportsPerSignature, 'Solana nonce fee');
  return state;
}

async function sha256Base64Payload(value: string): Promise<string> {
  let bytes: Uint8Array;
  try {
    const binary = atob(value);
    bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  } catch {
    throw new Error('Signed Solana transaction is not valid base64');
  }
  if (bytes.byteLength < 64 || bytes.byteLength > 1232) throw new Error('Signed Solana transaction has an invalid wire size');
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/**
 * Registers an already-created, initialized nonce account after independently
 * verifying it through the Blee gateway. Account creation lands in Sprint 4B;
 * this function is the durable boundary between on-chain preparation and the
 * offline signing pool.
 */
export async function registerPreparedSolanaNonceSlot(input: {
  index: number;
  address: string;
  authority: string;
}): Promise<SolanaNonceSlot> {
  const authority = assertPublicKey(input.authority, 'Solana wallet');
  const address = assertPublicKey(input.address, 'Solana nonce account');
  const id = slotId(input.index);
  const remote = validateGatewayNonce(await getSolanaNonceAccount(address), authority);

  return withPoolLock(async () => {
    const pool = await readPool(authority);
    const duplicateAddress = pool.slots.find((slot) => slot.address === address && slot.id !== id);
    if (duplicateAddress) throw new Error('Solana nonce account is already assigned to another slot');

    const existing = pool.slots.find((slot) => slot.id === id);
    if (existing && (existing.state === 'reserved' || existing.state === 'advanced')) {
      throw new Error('Cannot replace a Solana nonce slot while a payment owns it');
    }

    const now = Date.now();
    const next: SolanaNonceSlot = {
      id,
      index: input.index,
      address,
      authority,
      nonce: assertNonce(remote.nonce),
      lamports: assertUnsignedLamports(remote.lamports, 'Solana nonce balance'),
      lamportsPerSignature: assertUnsignedLamports(remote.lamportsPerSignature, 'Solana nonce fee'),
      state: 'ready',
      createdAt: existing?.createdAt || now,
      updatedAt: now,
    };

    pool.slots = [...pool.slots.filter((slot) => slot.id !== id), next].sort((a, b) => a.index - b.index);
    await persistPool(pool);
    return { ...next };
  });
}

/**
 * Reserves exactly one prepared nonce for one SOL payment before any signature
 * is produced. A crash after this write leaves the slot reserved, so another
 * payment can never reuse the same durable nonce.
 */
export async function reserveSolanaNonceSlot(input: {
  authority: string;
  paymentId: string;
  recipient: string;
  amountLamports: string;
}): Promise<SolanaNonceReservation> {
  const authority = assertPublicKey(input.authority, 'Solana wallet');
  const paymentId = assertPaymentId(input.paymentId);
  const recipient = assertPublicKey(input.recipient, 'SOL recipient');
  const amountLamports = assertLamports(input.amountLamports);

  return withPoolLock(async () => {
    const pool = await readPool(authority);
    const alreadyOwned = pool.slots.find((slot) => slot.paymentId === paymentId && (slot.state === 'reserved' || slot.state === 'advanced'));
    if (alreadyOwned) {
      if (alreadyOwned.recipient !== recipient || alreadyOwned.amountLamports !== amountLamports) {
        throw new Error('Blee payment ID is already bound to a different SOL payment');
      }
      return reservationFromSlot(alreadyOwned);
    }

    const slot = pool.slots.filter((candidate) => candidate.state === 'ready').sort((a, b) => a.index - b.index)[0];
    if (!slot) throw new Error('No prepared offline SOL nonce is available');

    const now = Date.now();
    slot.state = 'reserved';
    slot.paymentId = paymentId;
    slot.recipient = recipient;
    slot.amountLamports = amountLamports;
    slot.reservedAt = now;
    slot.updatedAt = now;
    delete slot.signedAt;
    delete slot.signedTransactionBase64;
    delete slot.signedTransactionSha256;
    delete slot.observedNonce;
    delete slot.lastError;
    await persistPool(pool);
    return reservationFromSlot(slot);
  });
}

/**
 * Persists the exact signed transaction bytes in the same atomic pool record as
 * the reservation. BLE/gateway layers must replay these exact bytes; they must
 * never rebuild or re-sign a transaction during retry.
 */
export async function persistSignedSolanaTransaction(input: {
  authority: string;
  paymentId: string;
  slotId: string;
  signedTransactionBase64: string;
}): Promise<SolanaNonceReservation> {
  const authority = assertPublicKey(input.authority, 'Solana wallet');
  const paymentId = assertPaymentId(input.paymentId);
  const signedTransactionBase64 = input.signedTransactionBase64.trim();
  if (!signedTransactionBase64 || signedTransactionBase64.length > MAX_SIGNED_TRANSACTION_B64_CHARS) {
    throw new Error('Signed Solana transaction is too large');
  }
  const digest = await sha256Base64Payload(signedTransactionBase64);

  return withPoolLock(async () => {
    const pool = await readPool(authority);
    const slot = pool.slots.find((candidate) => candidate.id === input.slotId);
    if (!slot || slot.state !== 'reserved' || slot.paymentId !== paymentId) {
      throw new Error('Solana nonce reservation is not owned by this payment');
    }

    if (slot.signedTransactionSha256 && slot.signedTransactionSha256 !== digest) {
      throw new Error('Blee payment already has different signed SOL transaction bytes');
    }

    slot.signedTransactionBase64 = signedTransactionBase64;
    slot.signedTransactionSha256 = digest;
    slot.signedAt = slot.signedAt || Date.now();
    slot.updatedAt = Date.now();
    await persistPool(pool);
    return reservationFromSlot(slot);
  });
}

export async function getReservedSolanaPayment(
  authorityInput: string,
  paymentIdInput: string,
): Promise<SolanaNonceReservation | null> {
  const authority = assertPublicKey(authorityInput, 'Solana wallet');
  const paymentId = assertPaymentId(paymentIdInput);
  const pool = await readPool(authority);
  const slot = pool.slots.find((candidate) => candidate.paymentId === paymentId && (candidate.state === 'reserved' || candidate.state === 'advanced'));
  return slot ? reservationFromSlot(slot) : null;
}

/**
 * Online reconciliation never releases a reserved nonce simply because a retry
 * happened. If the on-chain nonce changed, the slot becomes `advanced` and is
 * quarantined until the payment settlement lifecycle explicitly rearms it.
 */
export async function reconcileSolanaNoncePool(authorityInput: string): Promise<SolanaNonceSlot[]> {
  const authority = assertPublicKey(authorityInput, 'Solana wallet');
  return withPoolLock(async () => {
    const pool = await readPool(authority);
    for (const slot of pool.slots) {
      const remote = validateGatewayNonce(await getSolanaNonceAccount(slot.address), authority);
      const now = Date.now();
      slot.lamports = assertUnsignedLamports(remote.lamports, 'Solana nonce balance');
      slot.lamportsPerSignature = assertUnsignedLamports(remote.lamportsPerSignature, 'Solana nonce fee');
      slot.updatedAt = now;

      if (slot.state === 'reserved') {
        if (remote.nonce !== slot.nonce) {
          slot.state = 'advanced';
          slot.observedNonce = assertNonce(remote.nonce);
        }
        continue;
      }
      if (slot.state === 'advanced') {
        slot.observedNonce = assertNonce(remote.nonce);
        continue;
      }

      slot.nonce = assertNonce(remote.nonce);
      slot.state = 'ready';
      delete slot.observedNonce;
      delete slot.lastError;
    }
    await persistPool(pool);
    return pool.slots.map((slot) => ({ ...slot, signedTransactionBase64: undefined }));
  });
}

/**
 * Rearm only after the owning payment has reached a terminal, independently
 * verified state. This function re-reads the current on-chain nonce before the
 * slot can become available to another offline payment.
 */
export async function rearmAdvancedSolanaNonceSlot(input: {
  authority: string;
  slotId: string;
  paymentId: string;
}): Promise<SolanaNonceSlot> {
  const authority = assertPublicKey(input.authority, 'Solana wallet');
  const paymentId = assertPaymentId(input.paymentId);

  return withPoolLock(async () => {
    const pool = await readPool(authority);
    const slot = pool.slots.find((candidate) => candidate.id === input.slotId);
    if (!slot || slot.state !== 'advanced' || slot.paymentId !== paymentId) {
      throw new Error('Solana nonce slot is not ready to be rearmed');
    }

    const remote = validateGatewayNonce(await getSolanaNonceAccount(slot.address), authority);
    const now = Date.now();
    slot.nonce = assertNonce(remote.nonce);
    slot.lamports = assertUnsignedLamports(remote.lamports, 'Solana nonce balance');
    slot.lamportsPerSignature = assertUnsignedLamports(remote.lamportsPerSignature, 'Solana nonce fee');
    slot.state = 'ready';
    slot.updatedAt = now;
    delete slot.paymentId;
    delete slot.recipient;
    delete slot.amountLamports;
    delete slot.reservedAt;
    delete slot.signedAt;
    delete slot.signedTransactionBase64;
    delete slot.signedTransactionSha256;
    delete slot.observedNonce;
    delete slot.lastError;
    await persistPool(pool);
    return { ...slot };
  });
}

export async function listSolanaNonceSlots(authorityInput: string): Promise<SolanaNonceSlot[]> {
  const pool = await readPool(authorityInput);
  return pool.slots.map((slot) => ({ ...slot, signedTransactionBase64: undefined }));
}
