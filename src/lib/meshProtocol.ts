import { isAddress, recoverMessageAddress, type Address, type Hex } from 'viem';
import type { PrivateKeyAccount } from 'viem/accounts';
import type {
  MeshCapabilitiesV1,
  MeshPacket,
  MeshPacketType,
  SolanaMeshDeliveryAckV1,
} from '../types/domain';
import { createMeshCapabilitiesV1, verifyMeshCapabilitiesV1 } from './meshCapabilities';
import { saveVerifiedPeerMeshCapabilities } from './meshCapabilityStore';
import { BleeNearby, nativeNearbyAvailable } from './nativeNearby';
import { looksLikeSolanaPublicKey } from './solanaGateway';
import { getSolanaSignerForPrimarySession } from './solanaSession';
import { getSolanaVaultAddress } from './solanaVault';
import { getVaultAddress } from './vault';

const FRAME_PREFIX = 'AD1';
const MAX_FRAME_DATA = 135;
const SOLANA_CAPABILITY_WAIT_MS = 250;
const ACTIVE_MESH_SIGNER_FRESH_MS = 15_000;
const SOLANA_ACK_DIGEST_RE = /^[0-9a-f]{64}$/;
const MAX_PAYMENT_ID_LENGTH = 160;

let activeMeshAccountRef: WeakRef<PrivateKeyAccount> | null = null;
let activeMeshAccountSeenAt = 0;

function rememberActiveMeshAccount(account: PrivateKeyAccount): void {
  activeMeshAccountRef = new WeakRef(account);
  activeMeshAccountSeenAt = Date.now();
}

function currentActiveMeshAccount(): PrivateKeyAccount | null {
  if (!activeMeshAccountRef || Date.now() - activeMeshAccountSeenAt > ACTIVE_MESH_SIGNER_FRESH_MS) return null;
  const account = activeMeshAccountRef.deref() || null;
  if (!account) {
    activeMeshAccountRef = null;
    activeMeshAccountSeenAt = 0;
  }
  return account;
}

function id(): string {
  const b = crypto.getRandomValues(new Uint8Array(12));
  return Array.from(b).map((v) => v.toString(16).padStart(2, '0')).join('');
}

function body(packet: Omit<MeshPacket, 'signature' | 'ttl' | 'hops'>) {
  return JSON.stringify({ version: packet.version, id: packet.id, type: packet.type, origin: packet.origin, createdAt: packet.createdAt, payload: packet.payload });
}

async function localHelloCapabilities(account: PrivateKeyAccount): Promise<MeshCapabilitiesV1> {
  // Capability discovery must never delay or break the established Arc hello.
  // If the secondary signer is still warming, advertise Arc only; the next
  // periodic hello can upgrade the same peer once the Solana signer is ready.
  let signer = null;
  try {
    signer = await Promise.race([
      getSolanaSignerForPrimarySession(account),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), SOLANA_CAPABILITY_WAIT_MS)),
    ]);
  } catch {}
  try {
    return await createMeshCapabilitiesV1({ evmOrigin: account.address, solanaSigner: signer });
  } catch {
    return { version: 1, rails: ['arc-usdc'] };
  }
}

async function helloPayloadWithCapabilities(
  account: PrivateKeyAccount,
  payload: unknown,
): Promise<unknown> {
  const capabilities = await localHelloCapabilities(account);
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return { capabilities };
  }
  return { ...(payload as Record<string, unknown>), capabilities };
}

export async function createMeshPacket(account: PrivateKeyAccount, type: MeshPacketType, payload: unknown, ttl = 7): Promise<MeshPacket> {
  // BLEE_MESH_CAPABILITY_HELLO_V1
  // Solana capability proof rides inside the already framed/signed hello packet.
  // The native 20-byte identity/profile characteristic is deliberately untouched.
  rememberActiveMeshAccount(account);
  const packetPayload = type === 'hello'
    ? await helloPayloadWithCapabilities(account, payload)
    : payload;
  const unsigned = { version: 1 as const, id: id(), type, origin: account.address, createdAt: Date.now(), payload: packetPayload };
  const signature = await account.signMessage({ message: body(unsigned) });
  return { ...unsigned, ttl, hops: 0, signature };
}

async function sendRuntimeMeshPacket(packet: MeshPacket): Promise<void> {
  if (!nativeNearbyAvailable()) return;
  for (const frame of packetFrames(packet)) await BleeNearby.send({ data: frame });
}

async function validateSolanaDeliveryAck(packet: MeshPacket): Promise<boolean> {
  if (!packet.payload || typeof packet.payload !== 'object' || Array.isArray(packet.payload)) return false;
  const raw = packet.payload as Partial<SolanaMeshDeliveryAckV1>;
  if (
    raw.version !== 1
    || raw.railId !== 'solana-sol'
    || raw.networkId !== 'solana-mainnet'
    || raw.durable !== true
    || typeof raw.paymentId !== 'string'
    || !raw.paymentId.trim()
    || raw.paymentId.trim().length > MAX_PAYMENT_ID_LENGTH
    || typeof raw.signedTransactionSha256 !== 'string'
    || !SOLANA_ACK_DIGEST_RE.test(raw.signedTransactionSha256.toLowerCase())
    || !isAddress(String(raw.recipientEvm || ''))
    || String(raw.recipientEvm).toLowerCase() !== packet.origin.toLowerCase()
    || !looksLikeSolanaPublicKey(String(raw.recipientSolana || ''))
  ) {
    return false;
  }

  const capabilities = await verifyMeshCapabilitiesV1(packet.origin, raw.recipientCapabilities);
  return Boolean(
    capabilities
    && capabilities.rails.includes('solana-sol')
    && capabilities.solana
    && capabilities.solana.networkId === 'solana-mainnet'
    && capabilities.solana.address === raw.recipientSolana,
  );
}

async function emitSolanaDurableAck(input: {
  account: PrivateKeyAccount;
  paymentId: string;
  signedTransactionSha256: string;
  recipientSolana: string;
}): Promise<void> {
  const signer = await getSolanaSignerForPrimarySession(input.account);
  if (!signer || signer.address !== input.recipientSolana) return;
  const recipientCapabilities = await createMeshCapabilitiesV1({
    evmOrigin: input.account.address,
    solanaSigner: signer,
  });
  if (!recipientCapabilities.solana || recipientCapabilities.solana.address !== input.recipientSolana) return;

  const ackPayload: SolanaMeshDeliveryAckV1 = {
    version: 1,
    railId: 'solana-sol',
    networkId: 'solana-mainnet',
    paymentId: input.paymentId,
    signedTransactionSha256: input.signedTransactionSha256,
    recipientEvm: input.account.address,
    recipientSolana: input.recipientSolana,
    durable: true,
    recipientCapabilities,
  };
  const ack = await createMeshPacket(input.account, 'sol-ack', ackPayload);
  await sendRuntimeMeshPacket(ack);
}

async function processLiveSolanaPayment(packet: MeshPacket): Promise<void> {
  // BLEE_SOLANA_MESH_LIVE_RECEIVE_V1
  // Outer EVM authentication has already passed. Validate the SOL envelope,
  // COMMIT exact signed bytes to SQLite, and only then allow normal forwarding
  // and (for the addressed recipient) emit a durable delivery ACK.
  const { validateAuthenticatedSolanaMeshPaymentEnvelope } = await import('./solanaMeshEnvelope');
  const { storeVerifiedInboundSolanaMeshPayment } = await import('./solanaMeshStore');
  const envelope = await validateAuthenticatedSolanaMeshPaymentEnvelope(packet);

  const activeAccount = currentActiveMeshAccount();
  const localEvmAddress = activeAccount?.address || await getVaultAddress();
  if (!localEvmAddress || !isAddress(localEvmAddress)) {
    throw new Error('Local Blee identity is unavailable for SOL mesh custody');
  }
  const localSolanaAddress = await getSolanaVaultAddress().catch(() => null);

  const custody = await storeVerifiedInboundSolanaMeshPayment({
    packet,
    envelope,
    localEvmAddress,
    localSolanaAddress,
    allowCourier: true,
  });
  if (!custody) return;

  if (custody.stored.role === 'recipient' && activeAccount) {
    // BLEE_SOLANA_ACK_AFTER_DURABLE_STORE_V1
    // storeVerifiedInboundSolanaMeshPayment has completed its SQLite write before
    // this ACK can be constructed or transmitted.
    await emitSolanaDurableAck({
      account: activeAccount,
      paymentId: envelope.paymentId,
      signedTransactionSha256: envelope.signedTransactionSha256,
      recipientSolana: envelope.recipientSolana,
    });
  }
}

export async function verifyMeshPacket(
  packet: MeshPacket,
  options?: { processSolanaRuntime?: boolean },
): Promise<boolean> {
  try {
    if (packet.version !== 1 || packet.ttl < 0 || Date.now() - packet.createdAt > 48 * 60 * 60 * 1000) return false;
    const recovered = await recoverMessageAddress({
      message: body({ version: packet.version, id: packet.id, type: packet.type, origin: packet.origin, createdAt: packet.createdAt, payload: packet.payload }),
      signature: packet.signature,
    });
    if (recovered.toLowerCase() !== packet.origin.toLowerCase()) return false;

    if (packet.type === 'hello' && packet.payload && typeof packet.payload === 'object' && !Array.isArray(packet.payload)) {
      const hello = packet.payload as { address?: unknown; capabilities?: unknown };
      // The display address inside hello must be the same identity that signed
      // the packet. Legacy hello packets without an address remain harmlessly
      // ignored by the UI, exactly as before.
      if (hello.address !== undefined) {
        if (!isAddress(String(hello.address)) || String(hello.address).toLowerCase() !== packet.origin.toLowerCase()) return false;
      }

      if (hello.capabilities !== undefined) {
        const verified = await verifyMeshCapabilitiesV1(packet.origin, hello.capabilities);
        if (verified) {
          // Normalize the in-memory payload only after the EVM packet signature
          // and the independent Solana proof both pass. Durable cache writes are
          // best-effort and never block ordinary Arc discovery.
          hello.capabilities = verified;
          await saveVerifiedPeerMeshCapabilities(packet.origin, verified).catch(() => undefined);
        } else {
          // A bad optional capability must never make a peer SOL-eligible, but it
          // also must not regress the established Arc/USDC nearby experience.
          delete hello.capabilities;
        }
      }
    }

    if (packet.type === 'sol-payment' && options?.processSolanaRuntime !== false) {
      await processLiveSolanaPayment(packet);
    }

    if (packet.type === 'sol-ack' && !(await validateSolanaDeliveryAck(packet))) return false;

    return true;
  } catch { return false; }
}

function utf8ToB64(s: string): string {
  const bytes = new TextEncoder().encode(s);
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}
function b64ToUtf8(s: string): string {
  const bin = atob(s);
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

export function packetFrames(packet: MeshPacket): string[] {
  const encoded = utf8ToB64(JSON.stringify(packet));
  const total = Math.ceil(encoded.length / MAX_FRAME_DATA);
  return Array.from({ length: total }, (_, i) => `${FRAME_PREFIX}|${packet.id}|${i}|${total}|${encoded.slice(i * MAX_FRAME_DATA, (i + 1) * MAX_FRAME_DATA)}`);
}

type Assembly = { total: number; chunks: Map<number, string>; seenAt: number };
export class FrameAssembler {
  private pending = new Map<string, Assembly>();
  push(frame: string): MeshPacket | null {
    const parts = frame.split('|');
    if (parts.length !== 5 || parts[0] !== FRAME_PREFIX) return null;
    const [, messageId, indexText, totalText, chunk] = parts;
    const index = Number(indexText); const total = Number(totalText);
    if (!Number.isInteger(index) || !Number.isInteger(total) || total < 1 || total > 128 || index < 0 || index >= total) return null;
    const now = Date.now();
    for (const [key, value] of this.pending) if (now - value.seenAt > 60_000) this.pending.delete(key);
    const row = this.pending.get(messageId) || { total, chunks: new Map<number, string>(), seenAt: now };
    if (row.total !== total) return null;
    row.chunks.set(index, chunk); row.seenAt = now; this.pending.set(messageId, row);
    if (row.chunks.size !== total) return null;
    const encoded = Array.from({ length: total }, (_, i) => row.chunks.get(i) || '').join('');
    this.pending.delete(messageId);
    try { return JSON.parse(b64ToUtf8(encoded)) as MeshPacket; } catch { return null; }
  }
}

export function forwarded(packet: MeshPacket): MeshPacket | null {
  if (packet.ttl <= 1) return null;
  return { ...packet, ttl: packet.ttl - 1, hops: packet.hops + 1 };
}
