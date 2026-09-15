'use client';

import { useEffect, useMemo, useState } from 'react';
import { formatUnits } from 'viem';
import { useBlee } from './useBlee';
import { useSolanaWalletView } from './useSolanaWalletView';
import { useSolanaActivityView } from './useSolanaActivityView';
import { useSolanaSettlementView } from './useSolanaSettlementView';
import { loadPayments, setPersistentValue } from '../lib/persistence';
import { getSolUsdPrice } from '../lib/marketData';
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
 * BLEE_MULTI_ASSET_PRESENTATION_BOUNDARY_V2
 * Arc/USDC and SOL/Solana remain independent operational balances. A separate,
 * read-only portfolio projection may value SOL in USD and add that valuation to
 * USDC for Home display only. That valuation is never used for spend checks,
 * signing, settlement, nonce ownership or payment routing. SOL Activity is also
 * a separate durable projection and is merged only at presentation.
 */
export function useBleeView() {
  const core = useBlee();
  const solana = useSolanaWalletView(core.account);
  const solanaActivity = useSolanaActivityView(core.account?.address ?? null);
  const solanaSettlement = useSolanaSettlementView({
    localEvmAddress: core.account?.address ?? null,
    localSolanaAddress: solana.address,
  });
  const [durablePayments, setDurablePayments] = useState<PaymentRecord[]>([]);
  const [solUsdPrice, setSolUsdPrice] = useState<number | null>(null);
  const [solUsdPriceAt, setSolUsdPriceAt] = useState<number | null>(null);
  const [solUsdPriceError, setSolUsdPriceError] = useState<string | null>(null);

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
  // BLEE_UNIFIED_ACTIVITY_PRESENTATION_V1
  // SOL rows join Arc rows only here, after both rails have independently
  // produced durable read models. The operational Arc ledger remains `payments`.
  const activityPayments = useMemo(
    () => mergePayments(payments, solanaActivity.payments),
    [payments, solanaActivity.payments],
  );
  const pendingIncoming = useMemo(() => pendingIncomingAmount(payments), [payments]);
  const verifyingIncoming = useMemo(() => verifyingIncomingCount(payments), [payments]);

  // BLEE_PORTFOLIO_VALUATION_V1
  // SOL/USD is presentation-only market data fetched directly from DIA's public,
  // keyless endpoint. Operational SOL chain state still comes solely through the
  // isolated Solana wallet view/Blee gateway and remains the only SOL spend source.
  useEffect(() => {
    if (!core.account || !solana.address) {
      setSolUsdPrice(null);
      setSolUsdPriceAt(null);
      setSolUsdPriceError(null);
      return;
    }

    let active = true;
    const refreshPrice = async () => {
      try {
        const value = await getSolUsdPrice();
        if (!active) return;
        setSolUsdPrice(value);
        setSolUsdPriceAt(Date.now());
        setSolUsdPriceError(null);
      } catch (error) {
        if (!active) return;
        setSolUsdPriceError(error instanceof Error ? error.message : 'SOL USD price is unavailable');
      }
    };

    void refreshPrice();
    const timer = window.setInterval(() => { void refreshPrice(); }, 120_000);
    const onOnline = () => { void refreshPrice(); };
    const onFocus = () => { void refreshPrice(); };
    window.addEventListener('online', onOnline);
    window.addEventListener('focus', onFocus);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener('online', onOnline);
      window.removeEventListener('focus', onFocus);
    };
  }, [core.account, solana.address]);

  const usdcQuantity = useMemo(
    () => Number(core.available || 0) + pendingIncoming,
    [core.available, pendingIncoming],
  );
  const solQuantity = useMemo(() => {
    if (solana.balance === null) return null;
    const value = Number(solana.balance);
    return Number.isFinite(value) && value >= 0 ? value : null;
  }, [solana.balance]);
  const solUsdValue = useMemo(() => {
    if (solQuantity === null) return null;
    if (solQuantity === 0) return 0;
    if (solUsdPrice === null) return null;
    return solQuantity * solUsdPrice;
  }, [solQuantity, solUsdPrice]);
  const totalUsdcEquivalent = useMemo(
    () => usdcQuantity + (solUsdValue ?? 0),
    [usdcQuantity, solUsdValue],
  );
  const valuationComplete = solQuantity !== null && (solQuantity === 0 || solUsdValue !== null);

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
    activityPayments,
    pendingIncoming,
    verifyingIncoming,
    identityFor,
    solana,
    solanaActivity,
    solanaSettlement,
    portfolio: {
      usdcQuantity,
      solQuantity,
      solUsdPrice,
      solUsdValue,
      totalUsdcEquivalent,
      valuationComplete,
      priceAt: solUsdPriceAt,
      priceError: solUsdPriceError,
      pricingSource: 'dia-direct' as const,
    },
  };
}
