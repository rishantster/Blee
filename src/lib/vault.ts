import { type Hex } from 'viem';
import { generatePrivateKey, privateKeyToAccount, type PrivateKeyAccount } from 'viem/accounts';
import { getPersistentValue, setPersistentValue } from './persistence';

const VAULT_KEY = 'wallet.vault.v2';
const ITERATIONS_V1 = 210_000;
const ITERATIONS_V2 = 600_000;
export const MIN_PASSPHRASE_LENGTH = 8;

type StoredVault = {
  version: 1 | 2;
  address: string;
  salt: string;
  iv: string;
  ciphertext: string;
  iterations?: number;
  createdAt?: number;
};

const enc = new TextEncoder();
const dec = new TextDecoder();

function asArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}
function b64(bytes: Uint8Array): string {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}
function fromB64(value: string): Uint8Array {
  const s = atob(value);
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
}
async function derive(passphrase: string, salt: Uint8Array, iterations: number): Promise<CryptoKey> {
  const material = await crypto.subtle.importKey('raw', asArrayBuffer(enc.encode(passphrase)), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', hash: 'SHA-256', salt: asArrayBuffer(salt), iterations },
    material,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
}

async function readVault(): Promise<StoredVault | null> {
  const raw = await getPersistentValue(VAULT_KEY);
  if (raw) {
    try { return JSON.parse(raw) as StoredVault; } catch {}
  }
  return null;
}

async function persistPrivateKey(privateKey: Hex, passphrase: string, address: string): Promise<void> {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await derive(passphrase, salt, ITERATIONS_V2);
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv: asArrayBuffer(iv) }, key, asArrayBuffer(enc.encode(privateKey))));
  const vault: StoredVault = {
    version: 2,
    address,
    salt: b64(salt),
    iv: b64(iv),
    ciphertext: b64(ciphertext),
    iterations: ITERATIONS_V2,
    createdAt: Date.now(),
  };
  await setPersistentValue(VAULT_KEY, JSON.stringify(vault));
}

export async function hasVault(): Promise<boolean> {
  return Boolean(await readVault());
}

export async function getVaultAddress(): Promise<string | null> {
  return (await readVault())?.address || null;
}

export async function createVault(passphrase: string): Promise<PrivateKeyAccount> {
  if (passphrase.length < 8) throw new Error("Use a passphrase of at least 8 characters");
  if (await hasVault()) throw new Error('A wallet already exists on this device');
  if (passphrase.length < MIN_PASSPHRASE_LENGTH) throw new Error(`Use at least ${MIN_PASSPHRASE_LENGTH} characters`);
  const privateKey = generatePrivateKey();
  const account = privateKeyToAccount(privateKey);
  await persistPrivateKey(privateKey, passphrase, account.address);
  return account;
}

export async function unlockVault(passphrase: string): Promise<PrivateKeyAccount> {
  const vault = await readVault();
  if (!vault) throw new Error('No wallet exists on this device');
  const iterations = vault.version === 2 ? (vault.iterations || ITERATIONS_V2) : ITERATIONS_V1;
  const key = await derive(passphrase, fromB64(vault.salt), iterations);
  try {
    const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: asArrayBuffer(fromB64(vault.iv)) }, key, asArrayBuffer(fromB64(vault.ciphertext)));
    const privateKey = dec.decode(plain) as Hex;
    const account = privateKeyToAccount(privateKey);
    if (account.address.toLowerCase() !== vault.address.toLowerCase()) throw new Error('Wallet integrity check failed');
    if (vault.version === 1 || iterations < ITERATIONS_V2) await persistPrivateKey(privateKey, passphrase, account.address);
    return account;
  } catch (error) {
    if (error instanceof Error && error.message === 'Wallet integrity check failed') throw error;
    throw new Error('Incorrect passphrase');
  }
}
