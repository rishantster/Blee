import type {
  BleeEnvironment,
  BleeNetworkId,
  PaymentRecord,
} from '../types/domain';
import { getActiveNetwork, getNetwork } from './networkConfig';

export type PaymentNetworkPresentation = {
  networkId: BleeNetworkId;
  networkLabel: string;
  assetSymbol: 'USDC' | 'SOL';
  environment: BleeEnvironment;
  explorerUrl: string | null;
  activeSettlementNetwork: boolean;
};

const SOLANA_MAINNET_EXPLORER = 'https://explorer.solana.com';

/**
 * Persisted Blee <=2.7.1 rows had no network metadata and could only have been
 * created on Arc Testnet. Never reinterpret a missing historical network as the
 * currently selected release network.
 */
export function paymentNetworkId(row: PaymentRecord): BleeNetworkId {
  if (row.networkId) return row.networkId;
  return row.railId === 'solana-sol' ? 'solana-mainnet' : 'arc-testnet';
}

export function paymentAssetSymbol(row: PaymentRecord): 'USDC' | 'SOL' {
  if (row.assetSymbol) return row.assetSymbol;
  return row.railId === 'solana-sol' ? 'SOL' : 'USDC';
}

export function paymentNetworkLabel(row: PaymentRecord): string {
  switch (paymentNetworkId(row)) {
    case 'arc-testnet': return getNetwork('arc-testnet').name;
    case 'arc-mainnet': return getNetwork('arc-mainnet').name;
    case 'solana-mainnet': return 'Solana Mainnet';
  }
}

export function paymentEnvironment(row: PaymentRecord): BleeEnvironment {
  if (row.environment) return row.environment;
  return paymentNetworkId(row) === 'arc-testnet' ? 'testnet' : 'mainnet';
}

/** Explorer lookup always follows the immutable network identity of the row. */
export function paymentExplorerUrl(row: PaymentRecord): string | null {
  switch (paymentNetworkId(row)) {
    case 'arc-testnet': return getNetwork('arc-testnet').explorerUrl;
    case 'arc-mainnet': return getNetwork('arc-mainnet').explorerUrl;
    case 'solana-mainnet': return SOLANA_MAINNET_EXPLORER;
  }
}

export function paymentTransactionUrl(row: PaymentRecord): string | null {
  const explorer = paymentExplorerUrl(row);
  if (!explorer) return null;
  if (paymentNetworkId(row) === 'solana-mainnet') {
    return row.solanaSignature ? `${explorer}/tx/${encodeURIComponent(row.solanaSignature)}` : null;
  }
  return row.txHash ? `${explorer}/tx/${row.txHash}` : null;
}

/** Active Arc balances/projections may include only the release-selected rail. */
export function isActiveArcPayment(row: PaymentRecord): boolean {
  const active = getActiveNetwork();
  return (row.railId ?? 'arc-usdc') === 'arc-usdc'
    && paymentNetworkId(row) === active.id
    && (row.assetId ?? 'usdc') === 'usdc'
    && (row.chainFamily ?? 'evm') === 'evm';
}

/**
 * React projection keys include immutable network/rail identity so the same
 * logical payment id on two networks can never overwrite the other in Activity.
 */
export function paymentProjectionKey(row: PaymentRecord): string {
  return `${row.direction}:${row.railId ?? 'arc-usdc'}:${paymentNetworkId(row)}:${row.id}`;
}

export function describePaymentNetwork(row: PaymentRecord): PaymentNetworkPresentation {
  return {
    networkId: paymentNetworkId(row),
    networkLabel: paymentNetworkLabel(row),
    assetSymbol: paymentAssetSymbol(row),
    environment: paymentEnvironment(row),
    explorerUrl: paymentExplorerUrl(row),
    activeSettlementNetwork: isActiveArcPayment(row),
  };
}
