import { BleeStore } from './bleeStore';
import { recoverPendingWalletRestore } from './walletRestore';

export const SOLANA_VAULT_KEY = 'wallet.solana.v1';
const SOLANA_VAULT_VERSION = 1;
const SOLANA_KDF_ITERATIONS = 600_000;
const MIN_PASSPHRASE_LENGTH = 8;
const BASE58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';

export type StoredSolanaVault = {
  version: 1;
  algorithm: 'Ed25519';
  address: string;
  salt: string;
  iv: string;
  ciphertext: string;
  iterations: number;
  createdAt: number;
};

export type SolanaLocalSigner = {
  address: string;
  keyPair: CryptoKeyPair;
};

const encoder = new TextEncoder();

function cloneBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}

function toBase64(bytes: Uint8Array): string {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function fromBase64(value: string, field: string): Uint8Array {
  if (!value || value.length > 8192) throw new Error(`Solana wallet ${field} is invalid`);
  try {
    const binary = atob(value);
    return Uint8Array.from(binary, (char) => char.charCodeAt(0));
  } catch {
    throw new Error(`Solana wallet ${field} is invalid`);
  }
}

function base58Encode(bytes: Uint8Array): string {
  let leadingZeroes = 0;
  while (leadingZeroes < bytes.length && bytes[leadingZeroes] === 0) leadingZeroes += 1;

  let value = 0n;
  for (const byte of bytes) value = (value << 8n) | BigInt(byte);

  let encoded = '';
  while (value > 0n) {
    const remainder = Number(value % 58n);
    encoded = BASE58_ALPHABET[remainder] + encoded;
    value /= 58n;
  }

  return '1'.repeat(leadingZeroes) + encoded;
}

function base58Decode(value: string): Uint8Array {
  if (!value || value.length > 64) throw new Error('Solana wallet address is invalid');
  let number = 0n;
  for (const char of value) {
    const index = BASE58_ALPHABET.indexOf(char);
    if (index < 0) throw new Error('Solana wallet address is invalid');
    number = number * 58n + BigInt(index);
  }

  const body: number[] = [];
  while (number > 0n) {
    body.push(Number(number & 0xffn));
    number >>= 8n;
  }
  body.reverse();

  let leadingZeroes = 0;
  while (leadingZeroes < value.length && value[leadingZeroes] === '1') leadingZeroes += 1;
  return Uint8Array.from([...new Array(leadingZeroes).fill(0), ...body]);
}

async function ensureStore(): Promise<void> {
  const result = await BleeStore.init();
  if (!result.ready) throw new Error('Blee payment storage is unavailable');
}

async function deriveVaultKey(passphrase: string, salt: Uint8Array, iterations: number): Promise<CryptoKey> {
  const material = await crypto.subtle.importKey(
    'raw',
    cloneBuffer(encoder.encode(passphrase)),
    'PBKDF2',
    false,
    ['deriveKey'],
  );
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', hash: 'SHA-256', salt: cloneBuffer(salt), iterations },
    material,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
}

export function validateSolanaVaultSnapshot(input: unknown): StoredSolanaVault {
  const vault = input as Partial<StoredSolanaVault> | null | undefined;
  if (!vault || vault.version !== SOLANA_VAULT_VERSION || vault.algorithm !== 'Ed25519') {
    throw new Error('Unsupported Solana wallet version');
  }
  if (typeof vault.address !== 'string' || base58Decode(vault.address).byteLength !== 32) {
    throw new Error('Solana wallet address is invalid');
  }
  if (!Number.isInteger(vault.iterations) || (vault.iterations as number) < 100_000 || (vault.iterations as number) > 2_000_000) {
    throw new Error('Solana wallet key-derivation parameters are invalid');
  }
  if (!Number.isFinite(vault.createdAt) || (vault.createdAt as number) <= 0) {
    throw new Error('Solana wallet timestamp is invalid');
  }
  if (typeof vault.salt !== 'string' || typeof vault.iv !== 'string' || typeof vault.ciphertext !== 'string') {
    throw new Error('Solana wallet data is incomplete');
  }

  const salt = fromBase64(vault.salt, 'salt');
  const iv = fromBase64(vault.iv, 'IV');
  const ciphertext = fromBase64(vault.ciphertext, 'ciphertext');
  if (salt.byteLength !== 16) throw new Error('Solana wallet salt has an invalid length');
  if (iv.byteLength !== 12) throw new Error('Solana wallet IV has an invalid length');
  if (ciphertext.byteLength < 48 || ciphertext.byteLength > 512) {
    throw new Error('Solana wallet ciphertext has an invalid length');
  }

  return {
    version: SOLANA_VAULT_VERSION,
    algorithm: 'Ed25519',
    address: vault.address,
    salt: vault.salt,
    iv: vault.iv,
    ciphertext: vault.ciphertext,
    iterations: vault.iterations as number,
    createdAt: vault.createdAt as number,
  };
}

async function readStoredVault(): Promise<StoredSolanaVault | null> {
  // Keep the secondary identity consistent with the primary Arc identity after
  // a crash during Backup v2 restore.
  await recoverPendingWalletRestore();
  await ensureStore();
  const { value } = await BleeStore.getValue({ key: SOLANA_VAULT_KEY });
  if (!value) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(value) as unknown;
  } catch {
    throw new Error('Solana wallet data is damaged');
  }
  return validateSolanaVaultSnapshot(parsed);
}

function packKeyMaterial(privateKeyPkcs8: Uint8Array, publicKeyRaw: Uint8Array): Uint8Array {
  if (publicKeyRaw.byteLength !== 32) throw new Error('Solana public key has an invalid length');
  if (privateKeyPkcs8.byteLength < 32 || privateKeyPkcs8.byteLength > 256) {
    throw new Error('Solana private key has an invalid length');
  }
  const packed = new Uint8Array(2 + privateKeyPkcs8.byteLength + publicKeyRaw.byteLength);
  packed[0] = (privateKeyPkcs8.byteLength >> 8) & 0xff;
  packed[1] = privateKeyPkcs8.byteLength & 0xff;
  packed.set(privateKeyPkcs8, 2);
  packed.set(publicKeyRaw, 2 + privateKeyPkcs8.byteLength);
  return packed;
}

function unpackKeyMaterial(packed: Uint8Array): { privateKeyPkcs8: Uint8Array; publicKeyRaw: Uint8Array } {
  if (packed.byteLength < 66) throw new Error('Solana wallet key material is incomplete');
  const privateLength = (packed[0] << 8) | packed[1];
  const publicOffset = 2 + privateLength;
  if (privateLength < 32 || privateLength > 256 || packed.byteLength !== publicOffset + 32) {
    throw new Error('Solana wallet key material is invalid');
  }
  return {
    privateKeyPkcs8: packed.slice(2, publicOffset),
    publicKeyRaw: packed.slice(publicOffset),
  };
}

async function importSigner(address: string, privateKeyPkcs8: Uint8Array, publicKeyRaw: Uint8Array): Promise<SolanaLocalSigner> {
  const derivedAddress = base58Encode(publicKeyRaw);
  if (derivedAddress !== address) throw new Error('Solana wallet integrity check failed');

  const privateKey = await crypto.subtle.importKey(
    'pkcs8',
    cloneBuffer(privateKeyPkcs8),
    { name: 'Ed25519' },
    false,
    ['sign'],
  );
  const publicKey = await crypto.subtle.importKey(
    'raw',
    cloneBuffer(publicKeyRaw),
    { name: 'Ed25519' },
    false,
    ['verify'],
  );

  return { address, keyPair: { privateKey, publicKey } };
}

/**
 * Returns whether a dedicated Solana wallet has already been provisioned.
 * This does not mutate the existing Arc/EVM vault.
 */
export async function hasSolanaVault(): Promise<boolean> {
  return Boolean(await readStoredVault());
}

/**
 * Returns the public Solana address without decrypting private key material.
 */
export async function getSolanaVaultAddress(): Promise<string | null> {
  return (await readStoredVault())?.address || null;
}

/**
 * Returns only the already-encrypted persisted vault representation for Backup
 * v2. No private key plaintext or extractable CryptoKey is exposed.
 */
export async function getEncryptedSolanaVaultSnapshot(): Promise<StoredSolanaVault | null> {
  const vault = await readStoredVault();
  return vault ? { ...vault } : null;
}

/**
 * Creates a new Ed25519 Solana identity in a parallel encrypted vault.
 *
 * IMPORTANT: call this only after the primary Arc/EVM vault has successfully
 * authenticated the same passphrase. Keeping provisioning behind the existing
 * primary unlock prevents a mistyped passphrase from creating an inaccessible
 * second wallet.
 */
export async function provisionSolanaVaultAfterPrimaryUnlock(passphrase: string): Promise<string> {
  if (passphrase.length < MIN_PASSPHRASE_LENGTH) {
    throw new Error(`Use a passphrase of at least ${MIN_PASSPHRASE_LENGTH} characters`);
  }
  const existing = await readStoredVault();
  if (existing) return existing.address;

  let generated: CryptoKeyPair;
  try {
    generated = await crypto.subtle.generateKey(
      { name: 'Ed25519' },
      true,
      ['sign', 'verify'],
    ) as CryptoKeyPair;
  } catch {
    throw new Error('This device does not support the cryptography required for Solana');
  }

  const privateKeyPkcs8 = new Uint8Array(await crypto.subtle.exportKey('pkcs8', generated.privateKey));
  const publicKeyRaw = new Uint8Array(await crypto.subtle.exportKey('raw', generated.publicKey));
  const address = base58Encode(publicKeyRaw);
  const packed = packKeyMaterial(privateKeyPkcs8, publicKeyRaw);

  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await deriveVaultKey(passphrase, salt, SOLANA_KDF_ITERATIONS);

  try {
    const encrypted = new Uint8Array(await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv: cloneBuffer(iv) },
      key,
      cloneBuffer(packed),
    ));
    const vault: StoredSolanaVault = {
      version: SOLANA_VAULT_VERSION,
      algorithm: 'Ed25519',
      address,
      salt: toBase64(salt),
      iv: toBase64(iv),
      ciphertext: toBase64(encrypted),
      iterations: SOLANA_KDF_ITERATIONS,
      createdAt: Date.now(),
    };
    await BleeStore.setValue({ key: SOLANA_VAULT_KEY, value: JSON.stringify(vault) });
    return address;
  } finally {
    privateKeyPkcs8.fill(0);
    packed.fill(0);
  }
}

/**
 * Decrypts the Solana vault into non-extractable Web Crypto keys for the
 * current in-memory session. Private key bytes are never returned to callers.
 */
export async function unlockSolanaVault(passphrase: string): Promise<SolanaLocalSigner> {
  const vault = await readStoredVault();
  if (!vault) throw new Error('No Solana wallet exists on this device');

  const salt = fromBase64(vault.salt, 'salt');
  const iv = fromBase64(vault.iv, 'IV');
  const ciphertext = fromBase64(vault.ciphertext, 'ciphertext');
  const key = await deriveVaultKey(passphrase, salt, vault.iterations);

  let plaintext: Uint8Array;
  try {
    plaintext = new Uint8Array(await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: cloneBuffer(iv) },
      key,
      cloneBuffer(ciphertext),
    ));
  } catch {
    throw new Error('Incorrect passphrase');
  }

  try {
    const { privateKeyPkcs8, publicKeyRaw } = unpackKeyMaterial(plaintext);
    try {
      return await importSigner(vault.address, privateKeyPkcs8, publicKeyRaw);
    } finally {
      privateKeyPkcs8.fill(0);
    }
  } finally {
    plaintext.fill(0);
  }
}
