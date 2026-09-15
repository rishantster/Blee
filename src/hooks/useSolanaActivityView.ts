'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { Address } from 'viem';
import type { PaymentRecord } from '../types/domain';
import { loadSolanaActivityPayments } from '../lib/solanaActivity';
import { SOLANA_ACTIVITY_CHANGED_EVENT } from '../lib/solanaActivitySignal';

export type SolanaActivityView = Readonly<{
  payments: PaymentRecord[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}>;

/** Read-only live projection over durable SOL inbox/outbox custody state. */
export function useSolanaActivityView(localEvmAddress: Address | null): SolanaActivityView {
  const generationRef = useRef(0);
  const [payments, setPayments] = useState<PaymentRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const address = localEvmAddress;
    if (!address) {
      generationRef.current += 1;
      setPayments([]);
      setError(null);
      setLoading(false);
      return;
    }
    const generation = ++generationRef.current;
    setLoading(true);
    setError(null);
    try {
      const rows = await loadSolanaActivityPayments(address);
      if (generation === generationRef.current) setPayments(rows);
    } catch (refreshError) {
      if (generation === generationRef.current) {
        setError(refreshError instanceof Error ? refreshError.message : 'SOL activity is unavailable');
      }
    } finally {
      if (generation === generationRef.current) setLoading(false);
    }
  }, [localEvmAddress]);

  useEffect(() => {
    if (!localEvmAddress) {
      generationRef.current += 1;
      setPayments([]);
      setError(null);
      setLoading(false);
      return;
    }
    void refresh();
    const onRefresh = () => { void refresh(); };
    const onVisible = () => {
      if (document.visibilityState === 'visible') void refresh();
    };
    window.addEventListener('blee:ledger-changed', onRefresh);
    window.addEventListener(SOLANA_ACTIVITY_CHANGED_EVENT, onRefresh);
    window.addEventListener('blee:refresh-all', onRefresh);
    window.addEventListener('focus', onRefresh);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      generationRef.current += 1;
      window.removeEventListener('blee:ledger-changed', onRefresh);
      window.removeEventListener(SOLANA_ACTIVITY_CHANGED_EVENT, onRefresh);
      window.removeEventListener('blee:refresh-all', onRefresh);
      window.removeEventListener('focus', onRefresh);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [localEvmAddress, refresh]);

  return { payments, loading, error, refresh };
}
