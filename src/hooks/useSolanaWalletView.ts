'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { formatUnits } from 'viem';
import type { PrivateKeyAccount } from 'viem/accounts';
import { getSolBalance } from '../lib/solanaGateway';
import { loadOutboundSolanaMeshPayments } from '../lib/solanaMeshOutbox';
import { listSolanaNonceSlots } from '../lib/solanaNoncePool';
import { getSolanaSignerForPrimarySession } from '../lib/solanaSession';
import { getSolanaVaultAddress } from '../lib/solanaVault';

const SOL_DECIMALS = 9;
const TARGET_READY_NONCES = 4;

export type SolanaWalletView = Readonly<{
  networkId: 'solana-mainnet';
  symbol: 'SOL';
  address: string | null;
  sessionReady: boolean;
  gatewayReachable: boolean | null;
  balanceLamports: bigint | null;
  balance: string | null;
  balanceAt: number | null;
  readyNonceCount: number;
  reservedNonceCount: number;
  advancedNonceCount: number;
  invalidNonceCount: number;
  nonceTarget: number;
  offlineReady: boolean;
  pendingOutboundCount: number;
  deliveredOutboundCount: number;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}>;

/**
 * BLEE_SOLANA_WALLET_VIEW_V1
 *
 * Read-only presentation boundary for the SOL rail. This keeps USDC/Arc and
 * SOL/Solana balances independent, derives offline readiness only from the
 * durable nonce pool, and uses the Blee gateway for public chain state.
 *
 * It never signs, sends, reserves a nonce, mutates the outbox, or falls back to
 * a public/provider RPC. A gateway outage therefore degrades SOL balance
 * freshness without affecting the existing Arc wallet or local SOL readiness.
 */
export function useSolanaWalletView(primaryAccount: PrivateKeyAccount | null): SolanaWalletView {
  const generationRef = useRef(0);
  const [address, setAddress] = useState<string | null>(null);
  const [sessionReady, setSessionReady] = useState(false);
  const [gatewayReachable, setGatewayReachable] = useState<boolean | null>(null);
  const [balanceLamports, setBalanceLamports] = useState<bigint | null>(null);
  const [balanceAt, setBalanceAt] = useState<number | null>(null);
  const [readyNonceCount, setReadyNonceCount] = useState(0);
  const [reservedNonceCount, setReservedNonceCount] = useState(0);
  const [advancedNonceCount, setAdvancedNonceCount] = useState(0);
  const [invalidNonceCount, setInvalidNonceCount] = useState(0);
  const [pendingOutboundCount, setPendingOutboundCount] = useState(0);
  const [deliveredOutboundCount, setDeliveredOutboundCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = useCallback(() => {
    generationRef.current += 1;
    setAddress(null);
    setSessionReady(false);
    setGatewayReachable(null);
    setBalanceLamports(null);
    setBalanceAt(null);
    setReadyNonceCount(0);
    setReservedNonceCount(0);
    setAdvancedNonceCount(0);
    setInvalidNonceCount(0);
    setPendingOutboundCount(0);
    setDeliveredOutboundCount(0);
    setLoading(false);
    setError(null);
  }, []);

  const refresh = useCallback(async () => {
    const account = primaryAccount;
    if (!account) {
      reset();
      return;
    }

    const generation = ++generationRef.current;
    setLoading(true);
    setError(null);

    try {
      // The session promise is created only after the primary Arc vault has
      // authenticated. Awaiting it here never exposes or duplicates key material.
      const signer = await getSolanaSignerForPrimarySession(account);
      if (generation !== generationRef.current) return;

      const publicAddress = signer?.address || await getSolanaVaultAddress().catch(() => null);
      if (generation !== generationRef.current) return;

      setAddress(publicAddress);
      setSessionReady(Boolean(signer));

      if (!publicAddress) {
        setGatewayReachable(null);
        setBalanceLamports(null);
        setBalanceAt(null);
        setReadyNonceCount(0);
        setReservedNonceCount(0);
        setAdvancedNonceCount(0);
        setInvalidNonceCount(0);
        setPendingOutboundCount(0);
        setDeliveredOutboundCount(0);
        return;
      }

      // Local durable state remains useful while internet/gateway is absent.
      const [slotsResult, outboxResult] = await Promise.allSettled([
        listSolanaNonceSlots(publicAddress),
        loadOutboundSolanaMeshPayments(),
      ]);
      if (generation !== generationRef.current) return;

      if (slotsResult.status === 'fulfilled') {
        const slots = slotsResult.value;
        setReadyNonceCount(slots.filter((slot) => slot.state === 'ready').length);
        setReservedNonceCount(slots.filter((slot) => slot.state === 'reserved').length);
        setAdvancedNonceCount(slots.filter((slot) => slot.state === 'advanced').length);
        setInvalidNonceCount(slots.filter((slot) => slot.state === 'invalid').length);
      }

      if (outboxResult.status === 'fulfilled') {
        const own = outboxResult.value.filter((row) =>
          row.senderEvm.toLowerCase() === account.address.toLowerCase());
        setPendingOutboundCount(own.filter((row) => row.state !== 'delivered').length);
        setDeliveredOutboundCount(own.filter((row) => row.state === 'delivered').length);
      }

      try {
        const fresh = await getSolBalance(publicAddress);
        if (generation !== generationRef.current) return;
        setBalanceLamports(fresh);
        setBalanceAt(Date.now());
        setGatewayReachable(true);
      } catch (gatewayError) {
        if (generation !== generationRef.current) return;
        setGatewayReachable(false);
        setError(gatewayError instanceof Error ? gatewayError.message : 'Solana balance is unavailable');
      }
    } finally {
      if (generation === generationRef.current) setLoading(false);
    }
  }, [primaryAccount, reset]);

  useEffect(() => {
    if (!primaryAccount) {
      reset();
      return;
    }

    void refresh();
    const onRefresh = () => { void refresh(); };
    const onVisible = () => {
      if (document.visibilityState === 'visible') void refresh();
    };
    window.addEventListener('focus', onRefresh);
    window.addEventListener('online', onRefresh);
    window.addEventListener('blee:ledger-changed', onRefresh);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      generationRef.current += 1;
      window.removeEventListener('focus', onRefresh);
      window.removeEventListener('online', onRefresh);
      window.removeEventListener('blee:ledger-changed', onRefresh);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [primaryAccount, refresh, reset]);

  const balance = useMemo(
    () => balanceLamports === null ? null : formatUnits(balanceLamports, SOL_DECIMALS),
    [balanceLamports],
  );

  return {
    networkId: 'solana-mainnet',
    symbol: 'SOL',
    address,
    sessionReady,
    gatewayReachable,
    balanceLamports,
    balance,
    balanceAt,
    readyNonceCount,
    reservedNonceCount,
    advancedNonceCount,
    invalidNonceCount,
    nonceTarget: TARGET_READY_NONCES,
    offlineReady: sessionReady && readyNonceCount > 0,
    pendingOutboundCount,
    deliveredOutboundCount,
    loading,
    error,
    refresh,
  };
}
