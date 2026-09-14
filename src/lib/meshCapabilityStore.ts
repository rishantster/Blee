import { isAddress } from 'viem';
import type { MeshCapabilitiesV1 } from '../types/domain';
import { BleeStore } from './bleeStore';
import { verifyMeshCapabilitiesV1 } from './meshCapabilities';

export const MESH_CAPABILITY_STORE_PREFIX = 'mesh.peer-capabilities.v1';
const MAX_CACHE_AGE_MS = 24 * 60 * 60 * 1000;

type StoredPeerCapabilities = {
  version: 1;
  evmOrigin: string;
  capabilities: MeshCapabilitiesV1;
  verifiedAt: number;
};

async function ensureStore(): Promise<void> {
  const result = await BleeStore.init();
  if (!result.ready) throw new Error('Blee payment storage is unavailable');
}

function keyFor(evmOrigin: string): string {
  if (!isAddress(evmOrigin)) throw new Error('Peer EVM identity is invalid');
  return `${MESH_CAPABILITY_STORE_PREFIX}.${evmOrigin.toLowerCase()}`;
}

export async function saveVerifiedPeerMeshCapabilities(
  evmOrigin: string,
  input: MeshCapabilitiesV1,
): Promise<MeshCapabilitiesV1> {
  const verified = await verifyMeshCapabilitiesV1(evmOrigin, input);
  if (!verified) throw new Error('Peer mesh capabilities failed verification');
  await ensureStore();
  const row: StoredPeerCapabilities = {
    version: 1,
    evmOrigin: evmOrigin.toLowerCase(),
    capabilities: verified,
    verifiedAt: Date.now(),
  };
  await BleeStore.setValue({ key: keyFor(evmOrigin), value: JSON.stringify(row) });
  return verified;
}

export async function loadVerifiedPeerMeshCapabilities(
  evmOrigin: string,
): Promise<MeshCapabilitiesV1 | null> {
  await ensureStore();
  const { value } = await BleeStore.getValue({ key: keyFor(evmOrigin) });
  if (!value) return null;

  let parsed: StoredPeerCapabilities;
  try { parsed = JSON.parse(value) as StoredPeerCapabilities; } catch { return null; }
  if (
    parsed?.version !== 1
    || parsed.evmOrigin !== evmOrigin.toLowerCase()
    || !Number.isFinite(parsed.verifiedAt)
    || parsed.verifiedAt <= 0
    || Date.now() - parsed.verifiedAt > MAX_CACHE_AGE_MS
  ) {
    return null;
  }

  return verifyMeshCapabilitiesV1(evmOrigin, parsed.capabilities);
}
