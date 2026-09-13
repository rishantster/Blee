import { Capacitor } from '@capacitor/core';
import type { PaymentRecord, PaymentState } from '../types/domain';
import { BleeStore } from './bleeStore';

let ready = false;

type StoredPayment = Record<string, unknown>;

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

/**
 * SQLite is shared by the WebView journal and the native background mesh.
 * The native mesh historically used `outgoing` / `incoming`, while the React
 * domain uses `out` / `in`. Normalize that difference at this single storage
 * boundary so UI, notifications and background transport all describe the same
 * payment without leaking legacy names into application code.
 */
function canonicalPayment(input: StoredPayment): PaymentRecord | null {
  const id = String(input.id || input.paymentId || '').trim();
  const direction = canonicalDirection(input.direction);
  if (!id || !direction) return null;

  const authorization = (input.authorization || input.auth) as PaymentRecord['authorization'] | undefined;
  const state = canonicalState(input.state);
  const authFrom = wallet(authorization?.from);
  const authTo = wallet(authorization?.to);
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
    authorization,
  };
}

/** Native mesh storage keys remain outgoing/incoming for compatibility. */
function storagePayment(row: PaymentRecord): StoredPayment {
  return {
    ...row,
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

function normalizePayments(rows: Array<PaymentRecord | StoredPayment>): PaymentRecord[] {
  const map = new Map<string, PaymentRecord>();
  for (const source of rows) {
    const row = canonicalPayment(source as StoredPayment);
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
  return normalizePayments(rows);
}

/** Persist the entire bounded payment journal in one native SQLite transaction. */
export async function savePayments(rows: PaymentRecord[]): Promise<PaymentRecord[]> {
  await initPersistence();
  const now = Date.now();
  const safe = normalizePayments(rows).map((row) => ({ ...row, updatedAt: row.updatedAt || now }));
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

export async function loadLastBalance(address: string): Promise<{ value: string; at: number } | null> {
  const raw = await getPersistentValue(`balance.${address.toLowerCase()}`);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { value: string; at: number };
    return typeof parsed.value === 'string' && Number.isFinite(parsed.at) ? parsed : null;
  } catch { return null; }
}

export async function saveLastBalance(address: string, value: string, at = Date.now()): Promise<void> {
  await setPersistentValue(`balance.${address.toLowerCase()}`, JSON.stringify({ value, at }));
}

export async function loadChainCursor(address: string): Promise<bigint | null> {
  const raw = await getPersistentValue(`chainCursor.${address.toLowerCase()}`);
  if (!raw) return null;
  try { return BigInt(raw); } catch { return null; }
}

export async function saveChainCursor(address: string, block: bigint): Promise<void> {
  await setPersistentValue(`chainCursor.${address.toLowerCase()}`, block.toString());
}
