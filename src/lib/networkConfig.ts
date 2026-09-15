import type { BleeEnvironment, BleeNetworkId } from '../types/domain';

export type ArcNetworkId = Extract<BleeNetworkId, 'arc-testnet' | 'arc-mainnet'>;

export type BleeNetwork = {
  id: ArcNetworkId;
  name: string;
  chainFamily: 'evm';
  environment: BleeEnvironment;
  chainId: number | null;
  rpcUrl: string | null;
  explorerUrl: string | null;
  nativeSymbol: 'USDC';
  nativeDecimals: number | null;
  tokenSymbol: 'USDC';
  tokenAddress: `0x${string}` | null;
  tokenDecimals: number | null;
  eip712Name: string | null;
  eip712Version: string | null;
  testnet: boolean;
  operational: boolean;
  locked: true;
};

export type OperationalBleeNetwork = BleeNetwork & {
  chainId: number;
  rpcUrl: string;
  explorerUrl: string;
  nativeDecimals: number;
  tokenAddress: `0x${string}`;
  tokenDecimals: number;
  eip712Name: string;
  eip712Version: string;
  operational: true;
};

export const ARC_TESTNET: OperationalBleeNetwork = Object.freeze({
  id: 'arc-testnet',
  name: 'Arc Testnet',
  chainFamily: 'evm',
  environment: 'testnet',
  chainId: 5_042_002,
  rpcUrl: 'https://rpc.testnet.arc.network',
  explorerUrl: 'https://testnet.arcscan.app',
  nativeSymbol: 'USDC',
  nativeDecimals: 18,
  tokenSymbol: 'USDC',
  tokenAddress: '0x3600000000000000000000000000000000000000',
  tokenDecimals: 6,
  eip712Name: 'USDC',
  eip712Version: '2',
  testnet: true,
  operational: true,
  locked: true,
});

/**
 * Mainnet is intentionally pre-registered but non-operational.
 *
 * We do not guess launch parameters. Chain ID, RPC, explorer, USDC contract,
 * decimal/domain details must be filled only from Circle/Arc's official source
 * of record. Until then no application path can select or sign for Mainnet.
 */
export const ARC_MAINNET: BleeNetwork = Object.freeze({
  id: 'arc-mainnet',
  name: 'Arc Mainnet',
  chainFamily: 'evm',
  environment: 'mainnet',
  chainId: null,
  rpcUrl: null,
  explorerUrl: null,
  nativeSymbol: 'USDC',
  nativeDecimals: null,
  tokenSymbol: 'USDC',
  tokenAddress: null,
  tokenDecimals: null,
  eip712Name: null,
  eip712Version: null,
  testnet: false,
  operational: false,
  locked: true,
});

const APPROVED_ARC_NETWORKS: Readonly<Record<ArcNetworkId, BleeNetwork>> = Object.freeze({
  'arc-testnet': ARC_TESTNET,
  'arc-mainnet': ARC_MAINNET,
});

/**
 * Release-controlled selection. This is deliberately not sourced from arbitrary
 * local/remote JSON. A release may switch this to arc-mainnet only after the
 * bundled ARC_MAINNET profile has been populated from verified official data.
 */
export const ACTIVE_ARC_NETWORK_ID: ArcNetworkId = 'arc-testnet';

export function getNetwork(id: ArcNetworkId): BleeNetwork {
  return APPROVED_ARC_NETWORKS[id];
}

export function listApprovedNetworks(): BleeNetwork[] {
  return Object.values(APPROVED_ARC_NETWORKS);
}

export function listNetworks(): OperationalBleeNetwork[] {
  return listApprovedNetworks().filter((network): network is OperationalBleeNetwork => network.operational);
}

export function isOperationalNetwork(network: BleeNetwork): network is OperationalBleeNetwork {
  return Boolean(
    network.operational
    && Number.isInteger(network.chainId)
    && network.chainId! > 0
    && network.rpcUrl
    && network.explorerUrl
    && Number.isInteger(network.nativeDecimals)
    && network.nativeDecimals! >= 0
    && network.tokenAddress
    && Number.isInteger(network.tokenDecimals)
    && network.tokenDecimals! >= 0
    && network.eip712Name
    && network.eip712Version,
  );
}

export function requireOperationalNetwork(network: BleeNetwork): OperationalBleeNetwork {
  if (!isOperationalNetwork(network)) {
    throw new Error(`${network.name} is registered but not enabled in this Blee release`);
  }
  return network;
}

export function getActiveNetwork(): OperationalBleeNetwork {
  return requireOperationalNetwork(getNetwork(ACTIVE_ARC_NETWORK_ID));
}

/**
 * Only an exact bundled profile is valid. This prevents Settings, cached data,
 * or a remote response from substituting arbitrary RPC/contract parameters.
 */
export function validateNetwork(input: BleeNetwork): OperationalBleeNetwork {
  const approved = requireOperationalNetwork(getNetwork(input.id));
  const same = input.chainId === approved.chainId
    && input.rpcUrl === approved.rpcUrl
    && input.explorerUrl === approved.explorerUrl
    && input.tokenAddress?.toLowerCase() === approved.tokenAddress.toLowerCase()
    && input.tokenDecimals === approved.tokenDecimals
    && input.eip712Name === approved.eip712Name
    && input.eip712Version === approved.eip712Version;
  if (!same) throw new Error('Settlement network parameters are not an approved Blee profile');
  return approved;
}

export function saveNetwork(_network: BleeNetwork): never {
  throw new Error('Custom settlement networks are not available in Blee');
}

export function deleteNetwork(_id: string): void {
  // Bundled approved profiles cannot be removed.
}

export function setActiveNetwork(id: string): OperationalBleeNetwork {
  if (id !== ACTIVE_ARC_NETWORK_ID) {
    throw new Error('Settlement network selection is release-controlled in this Blee build');
  }
  return getActiveNetwork();
}

export async function testNetwork(network: BleeNetwork): Promise<{ chainId: number; ok: true }> {
  const clean = validateNetwork(network);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 7000);
  try {
    const response = await fetch(clean.rpcUrl, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'eth_chainId', params: [] }),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`Arc RPC returned HTTP ${response.status}`);
    const body = await response.json() as { result?: string; error?: { message?: string } };
    if (!body.result) throw new Error(body.error?.message || 'Arc RPC did not return a chain ID');
    const actual = Number.parseInt(body.result, 16);
    if (actual !== clean.chainId) throw new Error(`Arc RPC reports chain ID ${actual}`);
    return { chainId: actual, ok: true };
  } finally {
    clearTimeout(timeout);
  }
}
