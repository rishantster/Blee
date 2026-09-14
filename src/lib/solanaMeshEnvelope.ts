import { getAddress, isAddress } from 'viem';
import type { PrivateKeyAccount } from 'viem/accounts';
import type {
  MeshPacket,
  SolanaMeshPaymentEnvelopeV1,
} from '../types/domain';
import { createMeshCapabilitiesV1, verifyMeshCapabilitiesV1 } from './meshCapabilities';
import { loadVerifiedPeerMeshCapabilities } from './meshCapabilityStore';
import { createMeshPacket, verifyMeshPacket } from './meshProtocol';
import { looksLikeSolanaPublicKey } from './solanaGateway';
import type { PreparedOfflineSolTransfer } from './solanaTransaction';
import type { SolanaLocalSigner } from './solanaVault';

const U64_MAX = 18_446_744_073_709_551_615n;
const MAX_PAYMENT_ID_LENGTH = 160;
const MAX_WIRE_TRANSACTION_BYTES = 1232;
const MAX_WIRE_TRANSACTION_B64_CHARS = 4096;
const SHA256_HEX_RE = /^[0-9a-f]{64}$/;
const BASE64_RE = /^[A-Za-z0-9+/]+={0,2}$/;

function cloneBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}

function assertPaymentId(value: string): string {
  const clean = value.trim();
  if (!clean || clean.length > MAX_PAYMENT_ID_LENGTH) throw new Error('Invalid Blee SOL payment ID');
  return clean;
}

function assertLamports(value: string): string {
  const clean = value.trim();
  let amount: bigint;
  try { amount = BigInt(clean); } catch { throw new Error('Invalid SOL amount'); }
  if (amount <= 0n || amount > U64_MAX) throw new Error('SOL amount is outside the supported range');
  return amount.toString();
}

function decodeWireTransaction(value: string): Uint8Array {
  const clean = value.trim();
  if (
    !clean
    || clean.length > MAX_WIRE_TRANSACTION_B64_CHARS
    || clean.length % 4 !== 0
    || !BASE64_RE.test(clean)
  ) {
    throw new Error('Signed Solana transaction is not canonical base64');
  }
  let bytes: Uint8Array;
  try {
    const binary = atob(clean);
    bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  } catch {
    throw new Error('Signed Solana transaction is not valid base64');
  }
  if (bytes.byteLength <= 64 || bytes.byteLength > MAX_WIRE_TRANSACTION_BYTES) {
    throw new Error('Signed Solana transaction has an invalid wire size');
  }
  return bytes;
}

export async function digestSolanaWireTransactionBase64(value: string): Promise<string> {
  const bytes = decodeWireTransaction(value);
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', cloneBuffer(bytes)));
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

/**
 * BLEE_SOLANA_MESH_PAYMENT_ENVELOPE_V1
 *
 * Builds a self-authenticating transport envelope around the exact signed
 * durable-nonce transaction. The outer mesh packet is authenticated by the
 * existing Blee/EVM identity. A second Ed25519 capability proof binds the
 * advertised Solana sender address to that same Blee identity.
 *
 * Recipient SOL eligibility comes only from the previously verified nearby
 * capability cache. This layer never rebuilds, re-signs, submits or mutates the
 * transaction bytes created by solanaTransaction.ts.
 */
export async function prepareSolanaMeshPaymentPacket(input: {
  primaryAccount: PrivateKeyAccount;
  solanaSigner: SolanaLocalSigner;
  prepared: PreparedOfflineSolTransfer;
  recipientEvm: string;
}): Promise<MeshPacket> {
  if (!isAddress(input.recipientEvm)) throw new Error('Nearby recipient EVM identity is invalid');
  const recipientEvm = getAddress(input.recipientEvm);
  if (recipientEvm.toLowerCase() === input.primaryAccount.address.toLowerCase()) {
    throw new Error('Cannot send SOL to your own Blee identity');
  }
  if (input.prepared.railId !== 'solana-sol' || input.prepared.networkId !== 'solana-mainnet') {
    throw new Error('Prepared transaction is not a Solana Mainnet SOL payment');
  }
  if (input.prepared.sender !== input.solanaSigner.address) {
    throw new Error('Prepared SOL transaction belongs to a different Solana signer');
  }

  const recipientCapabilities = await loadVerifiedPeerMeshCapabilities(recipientEvm);
  if (
    !recipientCapabilities
    || !recipientCapabilities.rails.includes('solana-sol')
    || !recipientCapabilities.solana
    || recipientCapabilities.solana.networkId !== 'solana-mainnet'
  ) {
    throw new Error('Nearby recipient has not advertised verified SOL support');
  }
  if (recipientCapabilities.solana.address !== input.prepared.recipient) {
    throw new Error('Prepared SOL recipient does not match the verified nearby identity');
  }

  const senderCapabilities = await createMeshCapabilitiesV1({
    evmOrigin: input.primaryAccount.address,
    solanaSigner: input.solanaSigner,
  });
  if (!senderCapabilities.solana || senderCapabilities.solana.address !== input.prepared.sender) {
    throw new Error('Local Solana capability proof does not match the prepared transaction');
  }

  const signedTransactionSha256 = await digestSolanaWireTransactionBase64(input.prepared.signedTransactionBase64);
  if (signedTransactionSha256 !== input.prepared.signedTransactionSha256.toLowerCase()) {
    throw new Error('Prepared SOL transaction digest does not match its exact wire bytes');
  }

  const envelope: SolanaMeshPaymentEnvelopeV1 = {
    version: 1,
    railId: 'solana-sol',
    networkId: 'solana-mainnet',
    paymentId: assertPaymentId(input.prepared.paymentId),
    senderSolana: input.prepared.sender,
    recipientEvm,
    recipientSolana: input.prepared.recipient,
    amountLamports: assertLamports(input.prepared.amountLamports),
    nonceAccountAddress: input.prepared.nonceAccountAddress,
    nonce: input.prepared.nonce,
    signedTransactionBase64: input.prepared.signedTransactionBase64,
    signedTransactionSha256,
    senderCapabilities,
  };

  if (!looksLikeSolanaPublicKey(envelope.senderSolana)) throw new Error('SOL sender address is invalid');
  if (!looksLikeSolanaPublicKey(envelope.recipientSolana)) throw new Error('SOL recipient address is invalid');
  if (!looksLikeSolanaPublicKey(envelope.nonceAccountAddress)) throw new Error('SOL nonce account is invalid');
  if (!looksLikeSolanaPublicKey(envelope.nonce)) throw new Error('SOL durable nonce is invalid');

  return createMeshPacket(input.primaryAccount, 'sol-payment', envelope);
}

/**
 * Revalidates a received SOL envelope from first principles before any durable
 * receiver/courier storage. This confirms:
 * - the existing EVM mesh signature,
 * - the Solana capability proof bound to packet.origin,
 * - exact rail/network/address metadata,
 * - exact signed wire-byte SHA-256 and Solana wire-size limit.
 *
 * Full on-chain transaction-shape validation remains a gateway responsibility
 * before broadcast. Offline recipients treat this as authenticated custody of
 * exact signed bytes, not as chain confirmation.
 */
export async function validateSolanaMeshPaymentEnvelope(
  packet: MeshPacket,
): Promise<SolanaMeshPaymentEnvelopeV1> {
  if (packet.type !== 'sol-payment') throw new Error('Mesh packet is not a SOL payment');
  if (!(await verifyMeshPacket(packet))) throw new Error('SOL mesh packet failed Blee identity verification');
  if (!packet.payload || typeof packet.payload !== 'object' || Array.isArray(packet.payload)) {
    throw new Error('SOL mesh payment envelope is missing');
  }

  const raw = packet.payload as Partial<SolanaMeshPaymentEnvelopeV1>;
  if (raw.version !== 1 || raw.railId !== 'solana-sol' || raw.networkId !== 'solana-mainnet') {
    throw new Error('Unsupported SOL mesh payment envelope');
  }
  if (!isAddress(String(raw.recipientEvm || ''))) throw new Error('SOL mesh recipient Blee identity is invalid');

  const senderSolana = String(raw.senderSolana || '').trim();
  const recipientSolana = String(raw.recipientSolana || '').trim();
  const nonceAccountAddress = String(raw.nonceAccountAddress || '').trim();
  const nonce = String(raw.nonce || '').trim();
  if (!looksLikeSolanaPublicKey(senderSolana)) throw new Error('SOL mesh sender address is invalid');
  if (!looksLikeSolanaPublicKey(recipientSolana)) throw new Error('SOL mesh recipient address is invalid');
  if (!looksLikeSolanaPublicKey(nonceAccountAddress)) throw new Error('SOL mesh nonce account is invalid');
  if (!looksLikeSolanaPublicKey(nonce)) throw new Error('SOL mesh durable nonce is invalid');

  const senderCapabilities = await verifyMeshCapabilitiesV1(packet.origin, raw.senderCapabilities);
  if (
    !senderCapabilities
    || !senderCapabilities.rails.includes('solana-sol')
    || !senderCapabilities.solana
    || senderCapabilities.solana.address !== senderSolana
    || senderCapabilities.solana.networkId !== 'solana-mainnet'
  ) {
    throw new Error('SOL mesh sender capability proof is invalid');
  }

  const signedTransactionBase64 = String(raw.signedTransactionBase64 || '').trim();
  const signedTransactionSha256 = String(raw.signedTransactionSha256 || '').trim().toLowerCase();
  if (!SHA256_HEX_RE.test(signedTransactionSha256)) throw new Error('SOL mesh transaction digest is invalid');
  const digest = await digestSolanaWireTransactionBase64(signedTransactionBase64);
  if (digest !== signedTransactionSha256) throw new Error('SOL mesh transaction bytes do not match their digest');

  return {
    version: 1,
    railId: 'solana-sol',
    networkId: 'solana-mainnet',
    paymentId: assertPaymentId(String(raw.paymentId || '')),
    senderSolana,
    recipientEvm: getAddress(String(raw.recipientEvm)),
    recipientSolana,
    amountLamports: assertLamports(String(raw.amountLamports || '')),
    nonceAccountAddress,
    nonce,
    signedTransactionBase64,
    signedTransactionSha256,
    senderCapabilities,
  };
}
