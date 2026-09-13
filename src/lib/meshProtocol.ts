import { recoverMessageAddress, type Address, type Hex } from 'viem';
import type { PrivateKeyAccount } from 'viem/accounts';
import type { MeshPacket, MeshPacketType } from '../types/domain';

const FRAME_PREFIX = 'AD1';
const MAX_FRAME_DATA = 135;

function id(): string {
  const b = crypto.getRandomValues(new Uint8Array(12));
  return Array.from(b).map((v) => v.toString(16).padStart(2, '0')).join('');
}

function body(packet: Omit<MeshPacket, 'signature' | 'ttl' | 'hops'>) {
  return JSON.stringify({ version: packet.version, id: packet.id, type: packet.type, origin: packet.origin, createdAt: packet.createdAt, payload: packet.payload });
}

export async function createMeshPacket(account: PrivateKeyAccount, type: MeshPacketType, payload: unknown, ttl = 7): Promise<MeshPacket> {
  const unsigned = { version: 1 as const, id: id(), type, origin: account.address, createdAt: Date.now(), payload };
  const signature = await account.signMessage({ message: body(unsigned) });
  return { ...unsigned, ttl, hops: 0, signature };
}

export async function verifyMeshPacket(packet: MeshPacket): Promise<boolean> {
  try {
    if (packet.version !== 1 || packet.ttl < 0 || Date.now() - packet.createdAt > 48 * 60 * 60 * 1000) return false;
    const recovered = await recoverMessageAddress({
      message: body({ version: packet.version, id: packet.id, type: packet.type, origin: packet.origin, createdAt: packet.createdAt, payload: packet.payload }),
      signature: packet.signature,
    });
    return recovered.toLowerCase() === packet.origin.toLowerCase();
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
