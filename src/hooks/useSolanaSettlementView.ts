'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Address } from 'viem';
import {
  loadSolanaSettlementRecords,
  runSolanaSettlementCycle,
  type SolanaSettlementRecord,
} from '../lib/solanaSettlement';

const SETTLEMENT_TICK_MS = 30_000;

export type SolanaSettlementView = Readonly<{
  records: SolanaSettlementRecord[];
  pendingCount: number;
  submittedCount: number;
  confirmedCount: number;
  finalizedCount: number;
  running: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}>;

/**
 * BLEE_SOLANA_SETTLEMENT_WORKER_V1
 *
 * Foreground/unlocked settlement worker. It never signs and never owns payment
 * notifications. Any authenticated device holding exact durable SOL bytes may
 * submit them through the public Blee gateway when internet is available.
 */
export function useSolanaSettlementView(input: {
  localEvmAddress: Address | null;
  localSolanaAddress: string | null;
}): SolanaSettlementView {
  const generationRef = useRef(0);
  const runningRef = useRef(false);
  const [records, setRecords] = useState<SolanaSettlementRecord[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadOnly = useCallback(async () => {
    const rows = await loadSolanaSettlementRecords();
    setRecords(rows);
  }, []);

  const refresh = useCallback(async () => {
    if (!input.localEvmAddress || runningRef.current) return;
    const generation = ++generationRef.current;
    runningRef.current = true;
    setRunning(true);
    setError(null);
    try {
      if (typeof navigator !== 'undefined' && navigator.onLine === false) {
        const rows = await loadSolanaSettlementRecords();
        if (generation === generationRef.current) setRecords(rows);
        return;
      }
      const rows = await runSolanaSettlementCycle({
        localEvmAddress: input.localEvmAddress,
        localSolanaAddress: input.localSolanaAddress,
      });
      if (generation === generationRef.current) setRecords(rows);
    } catch (refreshError) {
      if (generation === generationRef.current) {
        setError(refreshError instanceof Error ? refreshError.message : 'SOL settlement is unavailable');
        try { await loadOnly(); } catch {}
      }
    } finally {
      runningRef.current = false;
      if (generation === generationRef.current) setRunning(false);
    }
  }, [input.localEvmAddress, input.localSolanaAddress, loadOnly]);

  useEffect(() => {
    if (!input.localEvmAddress) {
      generationRef.current += 1;
      runningRef.current = false;
      setRecords([]);
      setRunning(false);
      setError(null);
      return;
    }

    void refresh();
    const onWake = () => { void refresh(); };
    const onVisible = () => {
      if (document.visibilityState === 'visible') void refresh();
    };
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refresh();
    }, SETTLEMENT_TICK_MS);
    window.addEventListener('online', onWake);
    window.addEventListener('focus', onWake);
    window.addEventListener('blee:refresh-all', onWake);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      generationRef.current += 1;
      runningRef.current = false;
      window.clearInterval(timer);
      window.removeEventListener('online', onWake);
      window.removeEventListener('focus', onWake);
      window.removeEventListener('blee:refresh-all', onWake);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [input.localEvmAddress, refresh]);

  const counts = useMemo(() => ({
    pendingCount: records.filter((row) => row.state === 'pending').length,
    submittedCount: records.filter((row) => row.state === 'submitted').length,
    confirmedCount: records.filter((row) => row.state === 'confirmed').length,
    finalizedCount: records.filter((row) => row.state === 'finalized').length,
  }), [records]);

  return { records, ...counts, running, error, refresh };
}
