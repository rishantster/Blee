import type {
  BleeAssetId,
  BleeChainFamily,
  BleeEnvironment,
  BleeNetworkId,
  BleeRailId,
} from '../types/domain';
import { getActiveNetwork } from './networkConfig';

export type BleeRail = {
  id: BleeRailId;
  assetId: BleeAssetId;
  assetSymbol: 'USDC' | 'SOL';
  chainFamily: BleeChainFamily;
  networkId: BleeNetworkId;
  supportedNetworkIds: readonly BleeNetworkId[];
  networkLabel: string;
  environment: BleeEnvironment;
  decimals: number;
  settlementModel: 'eip3009' | 'solana-durable-nonce';
  transport: 'blee-mesh';
  senderFunded: true;
};

const activeArc = getActiveNetwork();

export const ARC_USDC_RAIL: BleeRail = Object.freeze({
  id: 'arc-usdc',
  assetId: 'usdc',
  assetSymbol: 'USDC',
  chainFamily: 'evm',
  networkId: activeArc.id,
  supportedNetworkIds: Object.freeze(['arc-testnet', 'arc-mainnet'] as const),
  networkLabel: activeArc.name,
  environment: activeArc.environment,
  decimals: activeArc.tokenDecimals,
  settlementModel: 'eip3009',
  transport: 'blee-mesh',
  senderFunded: true,
});

export const SOLANA_SOL_RAIL: BleeRail = Object.freeze({
  id: 'solana-sol',
  assetId: 'sol',
  assetSymbol: 'SOL',
  chainFamily: 'solana',
  networkId: 'solana-mainnet',
  supportedNetworkIds: Object.freeze(['solana-mainnet'] as const),
  networkLabel: 'Solana Mainnet',
  environment: 'mainnet',
  decimals: 9,
  settlementModel: 'solana-durable-nonce',
  transport: 'blee-mesh',
  senderFunded: true,
});

const RAILS: Readonly<Record<BleeRailId, BleeRail>> = Object.freeze({
  'arc-usdc': ARC_USDC_RAIL,
  'solana-sol': SOLANA_SOL_RAIL,
});

export function getRail(id: BleeRailId): BleeRail {
  return RAILS[id];
}

export function listRails(): BleeRail[] {
  return Object.values(RAILS);
}

export function isMainnetRail(id: BleeRailId): boolean {
  return getRail(id).environment === 'mainnet';
}
