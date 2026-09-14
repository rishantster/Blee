'use client';

import { useEffect, useMemo, useState } from 'react';
import { formatUnits } from 'viem';
import { useBlee } from './useBlee';
import { useSolanaWalletView } from './useSolanaWalletView';
import { loadPayments, setPersistentValue } from '../lib/persistence';
import type { PaymentRecord } from '../types/domain';
import { ARC_USDC_DECIMALS } from '../lib/arc';
import { isActiveArcPayment, paymentProjectionKey } from '../lib/paymentNetwork';

function mergePayments(...groups: PaymentRecord[][]): PaymentRecord[] {
  const byKey = new Map<string, PaymentRecord>();
  for (const rows of groups) {
    for (const row of rows) {
      const key = paymentProjectionKey(row);
      const previous = byKey.get(key);
      if (!previous || (row.updatedAt || row.createdAt) >= (previous.updatedAt || previous.createdAt)) {
        byKey.set(key, row);
      }
    }
  }
  return [...byKey.values()].sort((a, b) => b.createdAt - a.createdAt);
}

function pendingIncomingAmount(payments: PaymentRecord[]): number {
  const units = payments
    .filter((row) =>
      isActiveArcPayment(row)
      && row.direction === 'in'
      && row.authorization
      && (row.state === 'mesh-delivered' || row.state === 'submitted'))
    .reduce((total, row) => total + BigInt(row.authorization!.value), 0n);
  return Number(formatUnits(units, ARC_USDC_DECIMALS));
}

function verifyingIncomingCount(payments: PaymentRecord[]): number {
  return payments.filter((row) =>
    isActiveArcPayment(row)
    && row.direction === 'in'
    && row.state === 'verification-pending').length;
}

/**
 * UI projection for the durable Blee ledger.
 *
 * Native background mesh and the foreground wallet intentionally write to the
 * same SQLite database. This hook listens for native ledger changes and merges
 * those durable rows with the wallet engine's live state without changing the
 * signing/settlement engine itself. Native Android owns payment notifications;
 * this projection owns presentation only.
 *
 * Network identity is part of the projection key and active-balance projection.
 * Historical Testnet rows therefore remain visible without ever contributing to
 * a later Mainnet balance, pending total or verification badge.
 *
 * BLEE_MULTI_ASSET_PRESENTATION_BOUNDARY_V1
 * Arc/USDC remains the existing primary projection. Solana/SOL is exposed as a
 * separate nested read model and is never summed into the Arc balance.
 */
export function useBleeView() {
  const core = useBlee();
  const solana = useSolanaWalletView(core.account);
  const [durablePayments, setDurablePayments] = useState<PaymentRecord[]>([]);

  useEffect(() => {
    let active = true;
    const reload = async () => {
      try {
        const rows = await loadPayments();
        if (active) setDurablePayments(rows);
      } catch {
        // The core hook exposes persistence errors. A projection refresh should
        // never make an otherwise usable wallet crash.
      }
    };

    void reload();
    const onLedgerChanged = () => { void reload(); };
    const onVisible = () => {
      if (document.visibilityState === 'visible') void reload();
    };
    window.addEventListener('blee:ledger-changed', onLedgerChanged);
    window.addEventListener('focus', onLedgerChanged);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      active = false;
      window.removeEventListener('blee:ledger-changed', onLedgerChanged);
      window.removeEventListener('focus', onLedgerChanged);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, []);

  // BLEE_NATIVE_PROFILE_IDENTITY_SYNC_V1
  // The foreground profile editor owns the canonical name/photo, while raw BLE
  // discovery runs in a native foreground service even when the WebView is idle.
  // Mirror only this non-financial presentation metadata into the same native
  // SQLite KV store so the transport can advertise it without internet access.
  // Keep an explicit empty avatar tombstone so photo removal changes the native
  // profile version and is propagated to peers rather than resurrecting a stale photo.
  useEffect(() => {
    if (!core.persistenceReady) return;
    void setPersistentValue('profile.alias', core.alias).catch(() => undefined);
    void setPersistentValue('profile.avatar', core.profilePhoto || '').catch(() => undefined);
  }, [core.persistenceReady, core.alias, core.profilePhoto]);

  const payments = useMemo(
    () => mergePayments(core.payments, durablePayments),
    [core.payments, durablePayments],
  );
  const pendingIncoming = useMemo(() => pendingIncomingAmount(payments), [payments]);
  const verifyingIncoming = useMemo(() => verifyingIncomingCount(payments), [payments]);

  // BLEE_LIVE_NEARBY_IDENTITY_PROJECTION_V1
  // A native BLE snapshot may carry fresher identity metadata than the browser
  // cache. Prefer the live peer avatar/name, while retaining the durable cached
  // identity as an offline fallback for Activity and previously-seen contacts.
  const liveIdentities = useMemo(() => {
    const map = new Map<string, { alias?: string; avatar?: string }>();
    for (const peer of core.peers as any[]) {
      const address = String(peer?.address || peer?.wallet || peer?.walletAddress || '').toLowerCase();
      if (!/^0x[0-9a-f]{40}$/.test(address)) continue;
      const alias = String(peer?.alias || peer?.displayName || peer?.name || '').trim() || undefined;
      const avatar = typeof peer?.avatar === 'string' && peer.avatar ? peer.avatar : undefined;
      map.set(address, { alias, avatar });
    }
    return map;
  }, [core.peers]);

  const identityFor = (address?: string | null) => {
    const stored = core.identityFor(address);
    if (!address) return stored;
    const live = liveIdentities.get(address.toLowerCase());
    if (!live) return stored;
    return {
      alias: live.alias || stored?.alias,
      avatar: live.avatar || stored?.avatar,
      updatedAt: stored?.updatedAt || Date.now(),
    };
  };

  return {
    ...core,
    payments,
    pendingIncoming,
    verifyingIncoming,
    identityFor,
    solana,
  };
}
