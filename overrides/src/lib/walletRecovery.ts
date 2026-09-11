import { registerPlugin } from "@capacitor/core";
import { privateKeyToAccount } from "viem/accounts";
import type { Hex } from "viem";

type StoredVault = {
  version: number;
  address: string;
  salt: string;
  iv: string;
  ciphertext: string;
  iterations: number;
  createdAt: number;
};

type StorePlugin = {
  init(): Promise<{ ready: boolean }>;
  getValue(options: { key: string }): Promise<{ value?: string | null }>;
  setValue(options: { key: string; value: string }): Promise<void>;
};

const BleeStore = registerPlugin<StorePlugin>("BleeStore");
const VAULT_KEY = "wallet.vault.v2";
const encoder = new TextEncoder();
const decoder = new TextDecoder();

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
}

async function readVault(): Promise<StoredVault> {
  await ensureStore();
  const { value } = await BleeStore.getValue({ key: VAULT_KEY });
  if (!value) throw new Error("No wallet exists on this device");
  let vault: StoredVault;
  try {
    vault = JSON.parse(value) as StoredVault;
  } catch {
    throw new Error("Wallet backup data is damaged");
  }
  if (!vault.address || !vault.salt || !vault.iv || !vault.ciphertext) throw new Error("Wallet backup is incomplete");
  return vault;
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

export async function exportEncryptedWalletBackup(): Promise<string> {
  const vault = await readVault();
  return JSON.stringify({
    format: "blee-wallet-backup",
    formatVersion: 1,
    exportedAt: new Date().toISOString(),
    vault,
  }, null, 2);
}

export async function importPrivateKey(privateKeyInput: string, newPassphrase: string): Promise<string> {
  const privateKey = normalizePrivateKey(privateKeyInput);
  return encryptAndStore(privateKey, newPassphrase);
}

export async function importEncryptedWalletBackup(backupInput: string): Promise<string> {
  await ensureStore();
  let parsed: { format?: string; vault?: StoredVault };
  try {
    parsed = JSON.parse(backupInput) as { format?: string; vault?: StoredVault };
  } catch {
    throw new Error("Backup must be valid JSON");
  }
  if (parsed.format !== "blee-wallet-backup" || !parsed.vault) throw new Error("This is not a Blee wallet backup");
  const vault = parsed.vault;
  if (!/^0x[0-9a-fA-F]{40}$/.test(vault.address) || !vault.salt || !vault.iv || !vault.ciphertext) {
    throw new Error("Wallet backup is incomplete");
  }
  await BleeStore.setValue({ key: VAULT_KEY, value: JSON.stringify(vault) });
  return vault.address;
}
