export type BleeNetwork = {
  id: string;
  name: string;
  chainId: number;
  rpcUrl: string;
  explorerUrl: string;
  nativeSymbol: string;
  tokenSymbol: string;
  tokenAddress: `0x${string}`;
  tokenDecimals: number;
  eip712Name: string;
  eip712Version: string;
  testnet: boolean;
  locked?: boolean;
};

export const ARC_TESTNET: BleeNetwork = Object.freeze({
  id: 'arc-testnet',
  name: 'Arc Testnet',
  chainId: 5042002,
  rpcUrl: 'https://rpc.testnet.arc.network',
  explorerUrl: 'https://testnet.arcscan.app',
  nativeSymbol: 'USDC',
  tokenSymbol: 'USDC',
  tokenAddress: '0x3600000000000000000000000000000000000000',
  tokenDecimals: 6,
  eip712Name: 'USDC',
  eip712Version: '2',
  testnet: true,
  locked: true,
});

// Blee 2.4 intentionally has one settlement network and one payment asset.
// Keep the legacy API surface so older generated modules still typecheck, but
// never persist, activate, or expose custom network profiles.
export function listNetworks(): BleeNetwork[] {
  return [ARC_TESTNET];
}

export function getActiveNetwork(): BleeNetwork {
  return ARC_TESTNET;
}

export function validateNetwork(input: BleeNetwork): BleeNetwork {
  if (input.id !== ARC_TESTNET.id || input.chainId !== ARC_TESTNET.chainId) {
    throw new Error('Blee supports Arc Testnet only in this build');
  }
  return ARC_TESTNET;
}

export function saveNetwork(_network: BleeNetwork): never {
  throw new Error('Custom settlement networks are not available in Blee');
}

export function deleteNetwork(_id: string): void {
  // Intentionally no-op: the bundled Arc Testnet profile cannot be removed.
}

export function setActiveNetwork(id: string): BleeNetwork {
  if (id !== ARC_TESTNET.id) throw new Error('Blee supports Arc Testnet only in this build');
  return ARC_TESTNET;
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
    if (actual !== ARC_TESTNET.chainId) throw new Error(`Arc RPC reports chain ID ${actual}`);
    return { chainId: actual, ok: true };
  } finally {
    clearTimeout(timeout);
  }
}
