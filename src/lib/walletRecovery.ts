import { privateKeyToAccount } from "viem/accounts";
import type { Hex } from "viem";
import { BleeStore } from './bleeStore';
import {
  getEncryptedSolanaVaultSnapshot,
  validateSolanaVaultSnapshot,
  type StoredSolanaVault,
} from './solanaVault';
import { commitWalletRestoreCrashSafe, recoverPendingWalletRestore } from './walletRestore';

type StoredVault = {
  version: 1 | 2;
  address: string;
  salt: string;
  iv: string;
  ciphertext: string;
  iterations?: number;
  createdAt?: number;
};

type BackupV1 = {
  format?: string;
  formatVersion?: number;
  vault?: unknown;
};

type BackupV2 = {
  format?: string;
  formatVersion?: number;
  wallets?: {
    arc?: unknown;
    solana?: unknown;
  };
};

const VAULT_KEY = "wallet.vault.v2";
const encoder = new TextEncoder();
const decoder = new TextDecoder();

// BLEE_BACKUP_VALIDATION_V1
const MAX_BACKUP_CHARS = 200_000;
const MIN_PBKDF2_ITERATIONS = 100_000;
const MAX_PBKDF2_ITERATIONS = 2_000_000;

function decodeBackupBase64(value: string, field: string): Uint8Array {
  if (!value || value.length > 4096) throw new Error(`Wallet backup ${field} is invalid`);
  try {
    return fromBase64(value);
  } catch {
    throw new Error(`Wallet backup ${field} is invalid`);
  }
}

function validateImportedVault(input: unknown): StoredVault {
  const vault = input as Partial<StoredVault> | null | undefined;
  if (!vault || (vault.version !== 1 && vault.version !== 2)) throw new Error("Unsupported Blee wallet backup version");
  if (typeof vault.address !== 'string' || !/^0x[0-9a-fA-F]{40}$/.test(vault.address)) {
    throw new Error("Wallet backup address is invalid");
  }
  if (typeof vault.salt !== 'string' || typeof vault.iv !== 'string' || typeof vault.ciphertext !== 'string') {
    throw new Error("Wallet backup is incomplete");
  }

  // BLEE_BACKUP_V1_COMPAT_V1
  const iterations = vault.version === 2 ? vault.iterations : (vault.iterations || 210_000);
  if (!Number.isInteger(iterations) || (iterations as number) < MIN_PBKDF2_ITERATIONS || (iterations as number) > MAX_PBKDF2_ITERATIONS) {
    throw new Error("Wallet backup key-derivation parameters are invalid");
  }

  const salt = decodeBackupBase64(vault.salt, "salt");
  const iv = decodeBackupBase64(vault.iv, "IV");
  const ciphertext = decodeBackupBase64(vault.ciphertext, "ciphertext");
  if (salt.byteLength !== 16) throw new Error("Wallet backup salt has an invalid length");
  if (iv.byteLength !== 12) throw new Error("Wallet backup IV has an invalid length");
  if (ciphertext.byteLength < 32 || ciphertext.byteLength > 512) throw new Error("Wallet backup ciphertext has an invalid length");
  if (vault.createdAt !== undefined && (!Number.isFinite(vault.createdAt) || vault.createdAt <= 0)) {
    throw new Error("Wallet backup timestamp is invalid");
  }

  return {
    version: vault.version,
    address: vault.address,
    salt: vault.salt,
    iv: vault.iv,
    ciphertext: vault.ciphertext,
    iterations: iterations as number,
    ...(vault.createdAt !== undefined ? { createdAt: vault.createdAt } : {}),
  };
}

function cloneBuffer(bytes: Uint8Array): ArrayBuffer {
  const out = new Uint8Array(bytes.byteLength);
  out.set(bytes);
  return out.buffer;
}

function toBase64(bytes: Uint8Array) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function fromBase64(value: string) {
  const binary = atob(value);
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

async function ensureStore() {
  const result = await BleeStore.init();
  if (!result.ready) throw new Error("Blee payment storage is unavailable");
  await recoverPendingWalletRestore();
}

async function readVault(): Promise<StoredVault> {
  await ensureStore();
  const { value } = await BleeStore.getValue({ key: VAULT_KEY });
  if (!value) throw new Error("No wallet exists on this device");
  let parsed: unknown;
  try {
    parsed = JSON.parse(value) as unknown;
  } catch {
    throw new Error("Wallet backup data is damaged");
  }
  return validateImportedVault(parsed);
}

async function deriveKey(passphrase: string, salt: Uint8Array, iterations: number) {
  const base = await crypto.subtle.importKey("raw", cloneBuffer(encoder.encode(passphrase)), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt: cloneBuffer(salt), iterations },
    base,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

function normalizePrivateKey(value: string): Hex {
  const clean = value.trim();
  const normalized = (clean.startsWith("0x") ? clean : `0x${clean}`) as Hex;
  if (!/^0x[0-9a-fA-F]{64}$/.test(normalized)) throw new Error("Private key must be 32 bytes (64 hex characters)");
  return normalized;
}

async function encryptAndStore(privateKey: Hex, passphrase: string) {
  if (passphrase.length < 8) throw new Error("Use a passphrase of at least 8 characters");
  const account = privateKeyToAccount(privateKey);
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const iterations = 600_000;
  const key = await deriveKey(passphrase, salt, iterations);
  const encrypted = new Uint8Array(
    await crypto.subtle.encrypt({ name: "AES-GCM", iv: cloneBuffer(iv) }, key, cloneBuffer(encoder.encode(privateKey))),
  );
  const vault: StoredVault = {
    version: 2,
    address: account.address,
    salt: toBase64(salt),
    iv: toBase64(iv),
    ciphertext: toBase64(encrypted),
    iterations,
    createdAt: Date.now(),
  };
  await ensureStore();
  await BleeStore.setValue({ key: VAULT_KEY, value: JSON.stringify(vault) });
  return account.address;
}

export async function revealPrivateKey(passphrase: string): Promise<Hex> {
  if (!passphrase) throw new Error("Enter your wallet passphrase");
  const vault = await readVault();
  const iterations = vault.version === 2 ? vault.iterations || 600_000 : 210_000;
  const key = await deriveKey(passphrase, fromBase64(vault.salt), iterations);
  try {
    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: cloneBuffer(fromBase64(vault.iv)) },
      key,
      cloneBuffer(fromBase64(vault.ciphertext)),
    );
    const privateKey = normalizePrivateKey(decoder.decode(decrypted));
    const account = privateKeyToAccount(privateKey);
    if (account.address.toLowerCase() !== vault.address.toLowerCase()) throw new Error("Wallet integrity check failed");
    return privateKey;
  } catch (error) {
    if (error instanceof Error && error.message === "Wallet integrity check failed") throw error;
    throw new Error("Incorrect passphrase");
  }
}

/**
 * Backup v2 contains the two independently encrypted wallet vaults. The export
 * never decrypts either private key and remains a normal JSON file.
 */
export async function exportEncryptedWalletBackup(): Promise<string> {
  const arc = await readVault();
  const solana = await getEncryptedSolanaVaultSnapshot();
  return JSON.stringify({
    format: "blee-wallet-backup",
    formatVersion: 2,
    exportedAt: new Date().toISOString(),
    wallets: {
      arc,
      solana: solana || null,
    },
  }, null, 2);
}

export async function importPrivateKey(privateKeyInput: string, newPassphrase: string): Promise<string> {
  const privateKey = normalizePrivateKey(privateKeyInput);
  return encryptAndStore(privateKey, newPassphrase);
}

export async function importEncryptedWalletBackup(backupInput: string): Promise<string> {
  if (!backupInput || backupInput.length > MAX_BACKUP_CHARS) throw new Error("Wallet backup is empty or too large");
  await ensureStore();

  let parsed: BackupV1 & BackupV2;
  try {
    parsed = JSON.parse(backupInput) as BackupV1 & BackupV2;
  } catch {
    throw new Error("Backup must be valid JSON");
  }
  if (parsed.format !== "blee-wallet-backup") throw new Error("This is not a Blee wallet backup");

  if (parsed.formatVersion === 2) {
    if (!parsed.wallets || parsed.wallets.arc === undefined) throw new Error("Blee Backup v2 is incomplete");
    const arc = validateImportedVault(parsed.wallets.arc);

    let solana: StoredSolanaVault | undefined;
    if (parsed.wallets.solana !== undefined && parsed.wallets.solana !== null) {
      solana = validateSolanaVaultSnapshot(parsed.wallets.solana);
    }

    // Both encrypted vaults are validated before the durable restore journal is
    // written. Interrupted two-wallet restores roll forward before either vault
    // is exposed to the application again.
    await commitWalletRestoreCrashSafe(
      JSON.stringify(arc),
      solana ? JSON.stringify(solana) : undefined,
    );
    return arc.address;
  }

  // Exact legacy shape remains supported for backups produced by Blee <=2.7.1.
  // A v1 backup contains no Solana identity, so restoring it only replaces the
  // Arc vault and deliberately does not destroy any existing Solana vault.
  if (parsed.formatVersion !== undefined && parsed.formatVersion !== 1) {
    throw new Error("Unsupported Blee wallet backup format version");
  }
  if (parsed.vault === undefined) throw new Error("This is not a Blee wallet backup");
  const vault = validateImportedVault(parsed.vault);
  await BleeStore.setValue({ key: VAULT_KEY, value: JSON.stringify(vault) });
  return vault.address;
}
