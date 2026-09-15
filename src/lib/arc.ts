import { defineChain } from 'viem';

import { getActiveNetwork, type OperationalBleeNetwork } from './networkConfig';

const BLEE_ACTIVE_NETWORK: OperationalBleeNetwork = getActiveNetwork();

export const ARC_CHAIN_ID = BLEE_ACTIVE_NETWORK.chainId;
export const ARC_RPC = BLEE_ACTIVE_NETWORK.rpcUrl;
export const ARC_EXPLORER = BLEE_ACTIVE_NETWORK.explorerUrl;
export const ARC_USDC = BLEE_ACTIVE_NETWORK.tokenAddress;
export const ARC_USDC_DECIMALS = BLEE_ACTIVE_NETWORK.tokenDecimals;
export const USDC_EIP712_NAME = BLEE_ACTIVE_NETWORK.eip712Name;
export const USDC_EIP712_VERSION = BLEE_ACTIVE_NETWORK.eip712Version;

export const activeArcChain = defineChain({
  id: BLEE_ACTIVE_NETWORK.chainId,
  name: BLEE_ACTIVE_NETWORK.name,
  nativeCurrency: {
    name: BLEE_ACTIVE_NETWORK.nativeSymbol,
    symbol: BLEE_ACTIVE_NETWORK.nativeSymbol,
    decimals: BLEE_ACTIVE_NETWORK.nativeDecimals,
  },
  rpcUrls: {
    default: { http: [BLEE_ACTIVE_NETWORK.rpcUrl] },
  },
  blockExplorers: BLEE_ACTIVE_NETWORK.explorerUrl
    ? { default: { name: `${BLEE_ACTIVE_NETWORK.name} Explorer`, url: BLEE_ACTIVE_NETWORK.explorerUrl } }
    : undefined,
  testnet: BLEE_ACTIVE_NETWORK.testnet,
});

/**
 * Backwards-compatible export for the existing Arc payment engine. The value is
 * now the release-selected Arc chain rather than a permanently hardcoded
 * Testnet definition. Existing imports therefore keep working during cutover.
 */
export const arcTestnet = activeArcChain;

export const usdcAbi = [
  {
    type: 'event', name: 'Transfer', anonymous: false,
    inputs: [
      { name: 'from', type: 'address', indexed: true },
      { name: 'to', type: 'address', indexed: true },
      { name: 'value', type: 'uint256', indexed: false },
    ],
  },
  {
    type: 'event', name: 'AuthorizationUsed', anonymous: false,
    inputs: [
      { name: 'authorizer', type: 'address', indexed: true },
      { name: 'nonce', type: 'bytes32', indexed: true },
    ],
  },
  {
    type: 'function', name: 'balanceOf', stateMutability: 'view',
    inputs: [{ name: 'account', type: 'address' }], outputs: [{ name: '', type: 'uint256' }],
  },
  {
    type: 'function', name: 'transferWithAuthorization', stateMutability: 'nonpayable',
    inputs: [
      { name: 'from', type: 'address' }, { name: 'to', type: 'address' },
      { name: 'value', type: 'uint256' }, { name: 'validAfter', type: 'uint256' },
      { name: 'validBefore', type: 'uint256' }, { name: 'nonce', type: 'bytes32' },
      { name: 'signature', type: 'bytes' },
    ], outputs: [],
  },
  {
    type: 'function', name: 'authorizationState', stateMutability: 'view',
    inputs: [{ name: 'authorizer', type: 'address' }, { name: 'nonce', type: 'bytes32' }],
    outputs: [{ name: '', type: 'bool' }],
  },
] as const;

export const transferAuthorizationTypes = {
  TransferWithAuthorization: [
    { name: 'from', type: 'address' }, { name: 'to', type: 'address' },
    { name: 'value', type: 'uint256' }, { name: 'validAfter', type: 'uint256' },
    { name: 'validBefore', type: 'uint256' }, { name: 'nonce', type: 'bytes32' },
  ],
} as const;

// Network selection is resolved once at app startup. Historical payment rows
// persist their own networkId and are never reinterpreted when this release
// selector changes.
export function getBleeActiveNetwork() {
  return BLEE_ACTIVE_NETWORK;
}
