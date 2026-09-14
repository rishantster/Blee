import { Capacitor } from '@capacitor/core';
import type { PaymentRecord, PaymentState } from '../types/domain';
import { BleeStore } from './bleeStore';
import { ARC_TESTNET, getActiveNetwork } from './networkConfig';
import { ARC_USDC_RAIL } from './rails';

let ready = false;

type StoredPayment = Record<string, unknown>;
type MissingNetworkMode = 'legacy-testnet' | 'active-release';

function wallet(value: unknown): string | undefined {
  const clean = String(value || '').trim();
  return /^0x[0-9a-fA-F]{40}$/.test(clean) ? clean.toLowerCase() : undefined;
}

function canonicalDirection(value: unknown): PaymentRecord['direction'] | null {
  const direction = String(value || '').trim().toLowerCase();
  if (direction === 'out' || direction === 'outgoing' || direction === 'sent') return 'out';
  if (direction === 'in' || direction === 'incoming' || direction === 'received') return 'in';
  if (direction === 'relay' || direction === 'courier') return 'relay';
  return null;
}

function canonicalState(value: unknown): PaymentState {
  const state = String(value || '').trim().toLowerCase();
  if (state === 'verification-pending' || state.includes('verification_pending') || state.includes('verification-pending')) return 'verification-pending';
  if (state === 'settled' || state.includes('chain_confirmed') || state.includes('chain-confirmed')) return 'settled';
  if (state === 'failed' || state.includes('expired') || state.includes('revert') || state.includes('cancel')) return 'failed';
  if (state === 'submitted' || state.includes('settlement_submitted') || state.includes('settlement-submitted')) return 'submitted';
  if (state === 'mesh-delivered' || state.includes('delivered_offline') || state.includes('acknowledged') || state.includes('delivered')) return 'mesh-delivered';
  if (state === 'mesh-broadcast' || state.includes('broadcast')) return 'mesh-broadcast';
  return 'queued-local';
}

function canonicalRoute(value: unknown, state: PaymentState, originalState: unknown): PaymentRecord['route'] {
  const route = String(value || '').trim();
  if (state === 'verification-pending') return 'ble-mesh';
  if (state === 'mesh-delivered' || String(originalState || '').toLowerCase().includes('delivered_offline')) return 'ble-mesh';
  if (route === 'arc-direct' || route === 'ble-mesh' || route === 'local-queue') return route;
  if (state === 'submitted' || state === 'settled') return 'arc-direct';
  return 'local-queue';
}

function canonicalNetworkMetadata(
  input: StoredPayment,
  missingNetworkMode: MissingNetworkMode,
): Pick<PaymentRecord, 'railId' | 'networkId' | 'assetId' | 'assetSymbol' | 'environment' | 'chainFamily'> {
  const railId = input.railId === 'solana-sol' ? 'solana-sol' : 'arc-usdc';
  if (railId === 'solana-sol') {
    return {
      railId,
      networkId: 'solana-mainnet',
      assetId: 'sol',
      assetSymbol: 'SOL',
      environment: 'mainnet',
      chainFamily: 'solana',
    };
  }

  // BLEE_LEGACY_NETWORK_IDENTITY_V1
  // Persisted rows written before Sprint 3 carried no network metadata. They
  // were created when Blee was Arc-Testnet-only, so load-time missing metadata
  // ALWAYS means arc-testnet. New in-memory rows, however, inherit the release-
  // selected Arc profile before their first durable write.
  const activeArc = getActiveNetwork();
  const fallbackNetworkId = missingNetworkMode === 'legacy-testnet' ? ARC_TESTNET.id : activeArc.id;
  const networkId = input.networkId === 'arc-mainnet'
    ? 'arc-mainnet'
    : input.networkId === 'arc-testnet'
      ? 'arc-testnet'
      : fallbackNetworkId;
  return {
    railId: 'arc-usdc',
    networkId,
    assetId: 'usdc',
    assetSymbol: 'USDC',
    environment: networkId === 'arc-mainnet' ? 'mainnet' : 'testnet',
    chainFamily: 'evm',
  };
}

/**
 * SQLite is shared by the WebView journal and the native background mesh.
 * The native mesh historically used `outgoing` / `incoming`, while the React
 * domain uses `out` / `in`. Normalize that difference at this single storage
 * boundary so UI, notifications and background transport all describe the same
 * payment without leaking legacy names into application code.
 */
function canonicalPayment(input: StoredPayment, missingNetworkMode: MissingNetworkMode): PaymentRecord | null {
  const id = String(input.id || input.paymentId || '').trim();
  const direction = canonicalDirection(input.direction);
  if (!id || !direction) return null;

  const network = canonicalNetworkMetadata(input, missingNetworkMode);
  const storedAuthorization = (input.authorization || input.auth || input.archivedAuthorization) as PaymentRecord['authorization'] | undefined;

  // BLEE_INACTIVE_NETWORK_AUTH_ARCHIVE_V1
  // A payment from another Arc environment remains in durable history, but its
  // EIP-3009 authorization is moved out of the runtime settlement field. This
  // prevents a future Mainnet release from reserving, retrying, relaying or
  // reconciling an old Testnet authorization while preserving the exact signed
  // payload for audit and for durable rewrite.
  const activeArc = getActiveNetwork();
  const settlementEligible = network.railId === 'arc-usdc'
    && network.networkId === activeArc.id
    && network.assetId === 'usdc'
    && network.chainFamily === 'evm';
  const authorization = settlementEligible ? storedAuthorization : undefined;
  const archivedAuthorization = storedAuthorization && !settlementEligible ? storedAuthorization : undefined;

  const state = canonicalState(input.state);
  const authFrom = wallet(storedAuthorization?.from);
  const authTo = wallet(storedAuthorization?.to);
  const rawCounterparty = wallet(input.counterparty || input.counterpartyWallet);
  const counterparty = direction === 'out'
    ? (authTo || rawCounterparty)
    : direction === 'in'
      ? (authFrom || rawCounterparty)
      : (rawCounterparty || authTo || authFrom);
  if (!counterparty) return null;

  const incomingAlias = String(
    input.senderName || input.contactName || input.peerName || input.counterpartyName || '',
  ).trim();
  const outgoingAlias = String(
    input.counterpartyAlias || input.recipientName || input.receiverName || input.contactName || input.peerName || input.counterpartyName || '',
  ).trim();
  const counterpartyAlias = direction === 'in' ? incomingAlias : outgoingAlias;
  const incomingAvatar = String(
    input.senderAvatar || input.counterpartyAvatar || input.peerAvatar || input.contactAvatar || '',
  ).trim();
  const outgoingAvatar = String(
    input.counterpartyAvatar || input.receiverAvatar || input.peerAvatar || input.contactAvatar || '',
  ).trim();
  const counterpartyAvatar = direction === 'in' ? incomingAvatar : outgoingAvatar;

  const createdAt = Number(input.createdAt || Date.now());
  const updatedAt = Number(input.updatedAt || createdAt);
  const amount = String(input.amount || input.displayAmount || input.tokenAmount || '0');
  const route = canonicalRoute(input.route, state, input.state);

  return {
    ...(input as unknown as PaymentRecord),
    id,
    direction,
    counterparty: counterparty as PaymentRecord['counterparty'],
    counterpartyAlias: counterpartyAlias || undefined,
    counterpartyAvatar: counterpartyAvatar || undefined,
    amount,
    createdAt: Number.isFinite(createdAt) ? createdAt : Date.now(),
    updatedAt: Number.isFinite(updatedAt) ? updatedAt : undefined,
    state,
    route,
    ...network,
    authorization,
    archivedAuthorization,
  };
}

/** Native mesh storage keys remain outgoing/incoming for compatibility. */
function storagePayment(row: PaymentRecord): StoredPayment {
  const { archivedAuthorization, ...durable } = row;
  return {
    ...durable,
    authorization: row.authorization ?? archivedAuthorization,
    direction: row.direction === 'out' ? 'outgoing' : row.direction === 'in' ? 'incoming' : 'relay',
  };
}

export function nativePersistenceAvailable() {
  return Capacitor.isNativePlatform();
}

export async function initPersistence(): Promise<{ native: true; journalMode: string }> {
  if (ready) return { native: true, journalMode: 'wal' };
  if (!Capacitor.isNativePlatform()) throw new Error('Blee payment storage requires the Android app.');
  try {
    const result = await BleeStore.init();
    if (!result.ready) throw new Error('native store returned not-ready');
    ready = true;
    return { native: true, journalMode: result.journalMode || 'unknown' };
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(detail.startsWith('Blee SQLite') ? detail : `Blee SQLite initialization failed: ${detail}`);
  }
}

function normalizePayments(
  rows: Array<PaymentRecord | StoredPayment>,
  missingNetworkMode: MissingNetworkMode,
): PaymentRecord[] {
  const map = new Map<string, PaymentRecord>();
  for (const source of rows) {
    const row = canonicalPayment(source as StoredPayment, missingNetworkMode);
    if (!row) continue;
    const key = `${row.direction}:${row.id}`;
    const existing = map.get(key);
    if (!existing || (row.updatedAt || 0) >= (existing.updatedAt || 0)) map.set(key, row);
  }
  const all = [...map.values()].sort((a, b) => b.createdAt - a.createdAt);
  const live = all.filter((r) => r.state !== 'settled' && r.state !== 'failed');
  const final = all.filter((r) => r.state === 'settled' || r.state === 'failed').slice(0, 400);
  return [...live, ...final].sort((a, b) => b.createdAt - a.createdAt).slice(0, 600);
}

export async function loadPayments(): Promise<PaymentRecord[]> {
  await initPersistence();
  const { payments } = await BleeStore.loadPayments();
  const rows: StoredPayment[] = [];
  for (const raw of payments) {
    try { rows.push(JSON.parse(raw) as StoredPayment); } catch {}
  }
  return normalizePayments(rows, 'legacy-testnet');
}

/** Persist the entire bounded payment journal in one native SQLite transaction. */
export async function savePayments(rows: PaymentRecord[]): Promise<PaymentRecord[]> {
  await initPersistence();
  const now = Date.now();
  const safe = normalizePayments(rows, 'active-release').map((row) => ({ ...row, updatedAt: row.updatedAt || now }));
  await BleeStore.replacePayments({
    payments: safe.map((row) => JSON.stringify(storagePayment(row))),
  });
  return safe;
}

export async function getPersistentValue(key: string): Promise<string | null> {
  await initPersistence();
  return (await BleeStore.getValue({ key })).value ?? null;
}

export async function setPersistentValue(key: string, value: string): Promise<void> {
  await initPersistence();
  await BleeStore.setValue({ key, value });
}

export async function removePersistentValue(key: string): Promise<void> {
  await initPersistence();
  await BleeStore.removeValue({ key });
}

export async function getAlias(): Promise<string> {
  return (await getPersistentValue('profile.alias')) || 'blee_user';
}

export async function setAlias(alias: string): Promise<string> {
  const safe = alias.trim().replace(/\s+/g, ' ').slice(0, 24) || 'blee_user';
  await setPersistentValue('profile.alias', safe);
  return safe;
}

// BLEE_NETWORK_SCOPED_CACHE_V1
// Balance snapshots and scan cursors are settlement-network state. They must be
// isolated by network ID so a Mainnet release can never display a cached Testnet
// balance or start scanning Mainnet from a Testnet block cursor.
function stateKey(kind: 'balance' | 'chainCursor', networkId: string, address: string): string {
  return `${kind}.${networkId}.${address.toLowerCase()}`;
}

function parseBalanceSnapshot(raw: string | null): { value: string; at: number } | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { value?: unknown; at?: unknown };
    return typeof parsed.value === 'string' && Number.isFinite(parsed.at)
      ? { value: parsed.value, at: Number(parsed.at) }
      : null;
  } catch { return null; }
}

export async function loadLastBalance(address: string): Promise<{ value: string; at: number } | null> {
  const active = getActiveNetwork();
  const scopedKey = stateKey('balance', active.id, address);
  const scoped = parseBalanceSnapshot(await getPersistentValue(scopedKey));
  if (scoped) return scoped;

  // Blee <=2.7.1 stored an unscoped balance, and that app only supported Arc
  // Testnet. Migrate it only when Testnet is still the active release network.
  if (active.id !== ARC_TESTNET.id) return null;
  const legacy = parseBalanceSnapshot(await getPersistentValue(`balance.${address.toLowerCase()}`));
  if (!legacy) return null;
  await setPersistentValue(scopedKey, JSON.stringify(legacy)).catch(() => undefined);
  return legacy;
}

export async function saveLastBalance(address: string, value: string, at = Date.now()): Promise<void> {
  const active = getActiveNetwork();
  await setPersistentValue(stateKey('balance', active.id, address), JSON.stringify({ value, at }));
}

function parseCursor(raw: string | null): bigint | null {
  if (!raw) return null;
  try { return BigInt(raw); } catch { return null; }
}

export async function loadChainCursor(address: string): Promise<bigint | null> {
  const active = getActiveNetwork();
  const scopedKey = stateKey('chainCursor', active.id, address);
  const scoped = parseCursor(await getPersistentValue(scopedKey));
  if (scoped !== null) return scoped;

  // Legacy cursors can only describe Arc Testnet because no other Arc network
  // was selectable when the unscoped key existed.
  if (active.id !== ARC_TESTNET.id) return null;
  const legacy = parseCursor(await getPersistentValue(`chainCursor.${address.toLowerCase()}`));
  if (legacy === null) return null;
  await setPersistentValue(scopedKey, legacy.toString()).catch(() => undefined);
  return legacy;
}

export async function saveChainCursor(address: string, block: bigint): Promise<void> {
  const active = getActiveNetwork();
  await setPersistentValue(stateKey('chainCursor', active.id, address), block.toString());
}
