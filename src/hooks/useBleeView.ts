'use client';

import { useEffect, useMemo, useState } from 'react';
import { formatUnits } from 'viem';
import { useBlee } from './useBlee';
import { loadPayments } from '../lib/persistence';
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
 */
export function useBleeView() {
  const core = useBlee();
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

  const payments = useMemo(
    () => mergePayments(core.payments, durablePayments),
    [core.payments, durablePayments],
  );
  const pendingIncoming = useMemo(() => pendingIncomingAmount(payments), [payments]);
  const verifyingIncoming = useMemo(() => verifyingIncomingCount(payments), [payments]);

  return {
    ...core,
    payments,
    pendingIncoming,
    verifyingIncoming,
  };
}
