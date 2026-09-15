import { isAddress } from 'viem';
import type { MeshCapabilitiesV1 } from '../types/domain';
import type { SolanaLocalSigner } from './solanaVault';

const CAPABILITY_DOMAIN = 'BLEE_SOLANA_CAPABILITY_V1';
const BASE58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
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

function fromBase64(value: string): Uint8Array | null {
  if (!value || value.length > 512) return null;
  try {
    const binary = atob(value);
    return Uint8Array.from(binary, (char) => char.charCodeAt(0));
  } catch {
    return null;
  }
}

function base58Decode32(value: string): Uint8Array | null {
  if (!value || value.length < 32 || value.length > 44) return null;
  let number = 0n;
  for (const char of value) {
    const index = BASE58_ALPHABET.indexOf(char);
    if (index < 0) return null;
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
  const decoded = Uint8Array.from([...new Array(leadingZeroes).fill(0), ...body]);
  return decoded.byteLength === 32 ? decoded : null;
}

function capabilityMessage(evmOrigin: string, solanaAddress: string): string {
  return [
    CAPABILITY_DOMAIN,
    `evm=${evmOrigin.toLowerCase()}`,
    'rail=solana-sol',
    'network=solana-mainnet',
    `solana=${solanaAddress}`,
  ].join('\n');
}

/**
 * BLEE_MESH_CAPABILITY_PROOF_V1
 *
 * The existing EVM-signed mesh packet authenticates the Blee identity. This
 * second signature proves that the same peer also controls the advertised
 * Solana address. We never trust a Solana address based only on an EVM hello.
 */
export async function createMeshCapabilitiesV1(input: {
  evmOrigin: string;
  solanaSigner?: SolanaLocalSigner | null;
}): Promise<MeshCapabilitiesV1> {
  if (!isAddress(input.evmOrigin)) throw new Error('Blee mesh EVM identity is invalid');
  if (!input.solanaSigner) return { version: 1, rails: ['arc-usdc'] };

  const solanaAddress = input.solanaSigner.address;
  if (!base58Decode32(solanaAddress)) throw new Error('Blee mesh Solana identity is invalid');
  const messageBytes = encoder.encode(capabilityMessage(input.evmOrigin, solanaAddress));
  const signature = new Uint8Array(await crypto.subtle.sign(
    { name: 'Ed25519' },
    input.solanaSigner.keyPair.privateKey,
    cloneBuffer(messageBytes),
  ));
  if (signature.byteLength !== 64) throw new Error('Blee mesh Solana capability proof is invalid');

  return {
    version: 1,
    rails: ['arc-usdc', 'solana-sol'],
    solana: {
      networkId: 'solana-mainnet',
      address: solanaAddress,
      proofBase64: toBase64(signature),
    },
  };
}

/**
 * Verifies the dual-key binding advertised above the stable BLE transport.
 * Invalid or forged capability data is ignored by callers; it must never make
 * a peer eligible for SOL payments.
 */
export async function verifyMeshCapabilitiesV1(
  evmOrigin: string,
  input: unknown,
): Promise<MeshCapabilitiesV1 | null> {
  if (!isAddress(evmOrigin) || !input || typeof input !== 'object') return null;
  const raw = input as Partial<MeshCapabilitiesV1>;
  if (raw.version !== 1 || !Array.isArray(raw.rails)) return null;

  const rails = raw.rails.filter((rail): rail is 'arc-usdc' | 'solana-sol' =>
    rail === 'arc-usdc' || rail === 'solana-sol');
  if (rails.length !== raw.rails.length || new Set(rails).size !== rails.length || !rails.includes('arc-usdc')) {
    return null;
  }

  const advertisesSol = rails.includes('solana-sol');
  if (!advertisesSol) {
    if (raw.solana !== undefined) return null;
    return { version: 1, rails: ['arc-usdc'] };
  }

  const solana = raw.solana;
  if (!solana || solana.networkId !== 'solana-mainnet') return null;
  const publicKeyRaw = base58Decode32(String(solana.address || ''));
  const signature = fromBase64(String(solana.proofBase64 || ''));
  if (!publicKeyRaw || !signature || signature.byteLength !== 64) return null;

  try {
    const publicKey = await crypto.subtle.importKey(
      'raw',
      cloneBuffer(publicKeyRaw),
      { name: 'Ed25519' },
      false,
      ['verify'],
    );
    const messageBytes = encoder.encode(capabilityMessage(evmOrigin, solana.address));
    const valid = await crypto.subtle.verify(
      { name: 'Ed25519' },
      publicKey,
      cloneBuffer(signature),
      cloneBuffer(messageBytes),
    );
    if (!valid) return null;
    return {
      version: 1,
      rails: ['arc-usdc', 'solana-sol'],
      solana: {
        networkId: 'solana-mainnet',
        address: solana.address,
        proofBase64: solana.proofBase64,
      },
    };
  } catch {
    return null;
  }
}
