export type BleeRailId = 'arc-usdc' | 'solana-sol';
export type BleeNetworkId = 'arc-testnet' | 'arc-mainnet' | 'solana-mainnet';
export type BleeAssetId = 'usdc' | 'sol';
export type BleeChainFamily = 'evm' | 'solana';
export type BleeEnvironment = 'testnet' | 'mainnet';

export type BleeRail = {
  id: BleeRailId;
  assetId: BleeAssetId;
  assetSymbol: 'USDC' | 'SOL';
  chainFamily: BleeChainFamily;
  networkId: BleeNetworkId;
  networkLabel: string;
  environment: BleeEnvironment;
  decimals: number;
  settlementModel: 'eip3009' | 'solana-durable-nonce';
  transport: 'blee-mesh';
  senderFunded: true;
};

export const ARC_USDC_RAIL: BleeRail = Object.freeze({
  id: 'arc-usdc',
  assetId: 'usdc',
  assetSymbol: 'USDC',
  chainFamily: 'evm',
  networkId: 'arc-testnet',
  networkLabel: 'Arc Testnet',
  environment: 'testnet',
  decimals: 6,
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
