'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { formatUnits } from 'viem';
import { useBlee } from './useBlee';
import { loadPayments } from '../lib/persistence';
import { notifyPaymentReceived } from '../lib/nativeNotifications';
import type { PaymentRecord } from '../types/domain';
import { ARC_USDC_DECIMALS } from '../lib/networkConfig';

function mergePayments(...groups: PaymentRecord[][]): PaymentRecord[] {
  const byKey = new Map<string, PaymentRecord>();
  for (const rows of groups) {
    for (const row of rows) {
      const key = `${row.direction}:${row.id}`;
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
    .filter((row) => row.direction === 'in' && row.authorization && row.state !== 'settled' && row.state !== 'failed')
    .reduce((total, row) => total + BigInt(row.authorization!.value), 0n);
  return Number(formatUnits(units, ARC_USDC_DECIMALS));
}

/**
 * UI projection for the durable Blee ledger.
 *
 * Native background mesh and the foreground wallet intentionally write to the
 * same SQLite database. This hook listens for native ledger changes and merges
 * those durable rows with the wallet engine's live state without changing the
 * signing/settlement engine itself.
 */
export function useBleeView() {
  const core = useBlee();
  const [durablePayments, setDurablePayments] = useState<PaymentRecord[]>([]);
  const coreIncomingSeen = useRef<Set<string> | null>(null);

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

  useEffect(() => {
    const currentIds = new Set(
      core.payments.filter((row) => row.direction === 'in').map((row) => row.id),
    );
    if (coreIncomingSeen.current === null) {
      coreIncomingSeen.current = currentIds;
      return;
    }

    for (const row of core.payments) {
      if (row.direction !== 'in' || row.state === 'failed' || row.state === 'settled') continue;
      if (coreIncomingSeen.current.has(row.id)) continue;
      const sender = row.counterpartyAlias || `${row.counterparty.slice(0, 6)}…${row.counterparty.slice(-4)}`;
      void notifyPaymentReceived(row.id, row.amount, sender).catch(() => undefined);
    }
    coreIncomingSeen.current = currentIds;
  }, [core.payments]);

  const payments = useMemo(
    () => mergePayments(core.payments, durablePayments),
    [core.payments, durablePayments],
  );
  const pendingIncoming = useMemo(() => pendingIncomingAmount(payments), [payments]);

  return {
    ...core,
    payments,
    pendingIncoming,
  };
}
