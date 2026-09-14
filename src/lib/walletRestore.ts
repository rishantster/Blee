import { BleeStore } from './bleeStore';

export const WALLET_RESTORE_JOURNAL_KEY = 'wallet.restore.v2.pending';
export const ARC_VAULT_STORAGE_KEY = 'wallet.vault.v2';
export const SOLANA_VAULT_STORAGE_KEY = 'wallet.solana.v1';

const JOURNAL_VERSION = 1;
const MAX_VAULT_JSON_CHARS = 16_384;

type WalletRestoreJournal = {
  version: 1;
  targetArcVault: string;
  targetSolanaVault?: string;
  createdAt: number;
};

let recoveryInFlight: Promise<void> | null = null;

async function ensureStore(): Promise<void> {
  const result = await BleeStore.init();
  if (!result.ready) throw new Error('Blee payment storage is unavailable');
}

function validateEncryptedVaultJson(raw: string, family: 'arc' | 'solana'): void {
  if (!raw || raw.length > MAX_VAULT_JSON_CHARS) throw new Error('Wallet restore payload is invalid');

  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(raw) as Record<string, unknown>;
  } catch {
    throw new Error('Wallet restore payload is invalid');
  }

  if (!parsed || typeof parsed !== 'object') throw new Error('Wallet restore payload is invalid');
  if (typeof parsed.salt !== 'string' || typeof parsed.iv !== 'string' || typeof parsed.ciphertext !== 'string') {
    throw new Error('Wallet restore payload is incomplete');
  }

  if (family === 'arc') {
    if (parsed.version !== 1 && parsed.version !== 2) throw new Error('Unsupported Arc wallet restore payload');
    if (typeof parsed.address !== 'string' || !/^0x[0-9a-fA-F]{40}$/.test(parsed.address)) {
      throw new Error('Arc wallet restore address is invalid');
    }
    return;
  }

  if (parsed.version !== 1 || parsed.algorithm !== 'Ed25519') {
    throw new Error('Unsupported Solana wallet restore payload');
  }
  if (typeof parsed.address !== 'string' || !/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(parsed.address)) {
    throw new Error('Solana wallet restore address is invalid');
  }
}

function parseJournal(raw: string): WalletRestoreJournal {
  let parsed: WalletRestoreJournal;
  try {
    parsed = JSON.parse(raw) as WalletRestoreJournal;
  } catch {
    throw new Error('Pending wallet restore journal is damaged');
  }

  if (!parsed || parsed.version !== JOURNAL_VERSION || !Number.isFinite(parsed.createdAt) || parsed.createdAt <= 0) {
    throw new Error('Pending wallet restore journal is invalid');
  }
  validateEncryptedVaultJson(parsed.targetArcVault, 'arc');
  if (parsed.targetSolanaVault !== undefined) validateEncryptedVaultJson(parsed.targetSolanaVault, 'solana');
  return parsed;
}

async function applyPendingRestore(): Promise<void> {
  await ensureStore();
  const { value } = await BleeStore.getValue({ key: WALLET_RESTORE_JOURNAL_KEY });
  if (!value) return;

  const journal = parseJournal(value);

  // Secondary wallet first, primary wallet last. If the process dies between
  // writes the journal remains durable, and every wallet read completes this
  // exact target state before exposing either identity to the app.
  if (journal.targetSolanaVault !== undefined) {
    await BleeStore.setValue({ key: SOLANA_VAULT_STORAGE_KEY, value: journal.targetSolanaVault });
  }
  await BleeStore.setValue({ key: ARC_VAULT_STORAGE_KEY, value: journal.targetArcVault });
  await BleeStore.removeValue({ key: WALLET_RESTORE_JOURNAL_KEY });
}

/**
 * Completes a previously interrupted dual-wallet restore before any wallet is
 * read. Replaying the same encrypted values is idempotent.
 */
export async function recoverPendingWalletRestore(): Promise<void> {
  if (recoveryInFlight) return recoveryInFlight;
  const task = applyPendingRestore();
  recoveryInFlight = task;
  try {
    await task;
  } finally {
    if (recoveryInFlight === task) recoveryInFlight = null;
  }
}

/**
 * Crash-safe multi-wallet restore without changing the native SQLite schema.
 * The durable journal is committed first; a crash at any later point rolls
 * forward to the same validated encrypted wallet pair on the next wallet read.
 *
 * An omitted Solana vault is intentionally non-destructive: legacy Arc-only
 * backups never erase an already-backed-up Solana identity on the device.
 */
export async function commitWalletRestoreCrashSafe(
  targetArcVault: string,
  targetSolanaVault?: string,
): Promise<void> {
  validateEncryptedVaultJson(targetArcVault, 'arc');
  if (targetSolanaVault !== undefined) validateEncryptedVaultJson(targetSolanaVault, 'solana');

  await recoverPendingWalletRestore();
  await ensureStore();

  const journal: WalletRestoreJournal = {
    version: JOURNAL_VERSION,
    targetArcVault,
    ...(targetSolanaVault !== undefined ? { targetSolanaVault } : {}),
    createdAt: Date.now(),
  };

  await BleeStore.setValue({ key: WALLET_RESTORE_JOURNAL_KEY, value: JSON.stringify(journal) });
  await recoverPendingWalletRestore();
}
