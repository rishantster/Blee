import { Capacitor, registerPlugin } from '@capacitor/core';
import type { PaymentRecord } from '../types/domain';

interface BleeStorePlugin {
  init(): Promise<{ ready: boolean; journalMode: string }>;
  loadPayments(): Promise<{ payments: string[] }>;
  replacePayments(options: { payments: string[] }): Promise<{ count: number }>;
  getValue(options: { key: string }): Promise<{ value: string | null }>;
  setValue(options: { key: string; value: string }): Promise<void>;
  removeValue(options: { key: string }): Promise<void>;
}

const BleeStore = registerPlugin<BleeStorePlugin>('BleeStore');
let ready = false;

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
    throw new Error(detail.startsWith("Blee SQLite") ? detail : `Blee SQLite initialization failed: ${detail}`);
  }
}

function normalizePayments(rows: PaymentRecord[]): PaymentRecord[] {
  const map = new Map<string, PaymentRecord>();
  for (const row of rows) {
    if (!row?.id || !row?.direction || !row?.state || !row?.route) continue;
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
  const rows: PaymentRecord[] = [];
  for (const raw of payments) {
    try { rows.push(JSON.parse(raw) as PaymentRecord); } catch {}
  }
  return normalizePayments(rows);
}

/** Persist the entire bounded payment journal in one native SQLite transaction. */
export async function savePayments(rows: PaymentRecord[]): Promise<PaymentRecord[]> {
  await initPersistence();
  const now = Date.now();
  const safe = normalizePayments(rows).map((row) => ({ ...row, updatedAt: row.updatedAt || now }));
  await BleeStore.replacePayments({ payments: safe.map((row) => JSON.stringify(row)) });
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
