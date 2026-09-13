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

export const ARC_TESTNET: BleeNetwork = {
  id: "arc-testnet",
  name: "Arc Testnet",
  chainId: 5042002,
  rpcUrl: "https://rpc.testnet.arc.network",
  explorerUrl: "https://testnet.arcscan.app",
  nativeSymbol: "USDC",
  tokenSymbol: "USDC",
  tokenAddress: "0x3600000000000000000000000000000000000000",
  tokenDecimals: 6,
  eip712Name: "USDC",
  eip712Version: "2",
  testnet: true,
  locked: true,
};

const NETWORKS_KEY = "blee.networks.v1";
const ACTIVE_KEY = "blee.active-network.v1";

function browserStorage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

function isAddress(value: string): value is `0x${string}` {
  return /^0x[0-9a-fA-F]{40}$/.test(value);
}

export function validateNetwork(input: BleeNetwork): BleeNetwork {
  const network: BleeNetwork = {
    ...input,
    id: input.id.trim() || `custom-${input.chainId}`,
    name: input.name.trim(),
    rpcUrl: input.rpcUrl.trim().replace(/\/$/, ""),
    explorerUrl: input.explorerUrl.trim().replace(/\/$/, ""),
    nativeSymbol: input.nativeSymbol.trim().toUpperCase(),
    tokenSymbol: input.tokenSymbol.trim().toUpperCase(),
    tokenAddress: input.tokenAddress.trim() as `0x${string}`,
    eip712Name: input.eip712Name.trim(),
    eip712Version: input.eip712Version.trim(),
  };

  if (!network.name) throw new Error("Network name is required");
  if (!Number.isInteger(network.chainId) || network.chainId <= 0) throw new Error("Chain ID must be a positive integer");
  if (!/^https:\/\//i.test(network.rpcUrl)) throw new Error("RPC URL must use HTTPS");
  if (network.explorerUrl && !/^https:\/\//i.test(network.explorerUrl)) throw new Error("Explorer URL must use HTTPS");
  if (!isAddress(network.tokenAddress)) throw new Error("Enter a valid payment token contract address");
  if (!Number.isInteger(network.tokenDecimals) || network.tokenDecimals < 0 || network.tokenDecimals > 36) throw new Error("Token decimals must be between 0 and 36");
  if (!network.tokenSymbol) throw new Error("Token symbol is required");
  if (!network.eip712Name || !network.eip712Version) throw new Error("EIP-712 name and version are required");
  return network;
}

export function listNetworks(): BleeNetwork[] {
  const storage = browserStorage();
  if (!storage) return [ARC_TESTNET];
  try {
    const parsed = JSON.parse(storage.getItem(NETWORKS_KEY) || "[]") as BleeNetwork[];
    const custom = Array.isArray(parsed) ? parsed.filter((item) => item?.id !== ARC_TESTNET.id) : [];
    return [ARC_TESTNET, ...custom.map(validateNetwork)];
  } catch {
    return [ARC_TESTNET];
  }
}

export function getActiveNetwork(): BleeNetwork {
  const storage = browserStorage();
  if (!storage) return ARC_TESTNET;
  const activeId = storage.getItem(ACTIVE_KEY) || ARC_TESTNET.id;
  return listNetworks().find((network) => network.id === activeId) || ARC_TESTNET;
}

export function saveNetwork(network: BleeNetwork): BleeNetwork {
  const storage = browserStorage();
  if (!storage) throw new Error("Network settings are available in the Android app");
  const clean = validateNetwork(network);
  if (clean.id === ARC_TESTNET.id) throw new Error("The bundled Arc Testnet profile cannot be replaced");
  const custom = listNetworks().filter((item) => !item.locked && item.id !== clean.id);
  storage.setItem(NETWORKS_KEY, JSON.stringify([...custom, clean]));
  return clean;
}

export function deleteNetwork(id: string) {
  if (id === ARC_TESTNET.id) return;
  const storage = browserStorage();
  if (!storage) return;
  const remaining = listNetworks().filter((item) => !item.locked && item.id !== id);
  storage.setItem(NETWORKS_KEY, JSON.stringify(remaining));
  if (storage.getItem(ACTIVE_KEY) === id) storage.setItem(ACTIVE_KEY, ARC_TESTNET.id);
}

export function setActiveNetwork(id: string): BleeNetwork {
  const storage = browserStorage();
  if (!storage) return ARC_TESTNET;
  const network = listNetworks().find((item) => item.id === id);
  if (!network) throw new Error("Network not found");
  storage.setItem(ACTIVE_KEY, network.id);
  return network;
}

export async function testNetwork(network: BleeNetwork): Promise<{ chainId: number; ok: true }> {
  const clean = validateNetwork(network);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 7000);
  try {
    const response = await fetch(clean.rpcUrl, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_chainId", params: [] }),
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`RPC returned HTTP ${response.status}`);
    const body = await response.json() as { result?: string; error?: { message?: string } };
    if (!body.result) throw new Error(body.error?.message || "RPC did not return a chain ID");
    const actual = Number.parseInt(body.result, 16);
    if (actual !== clean.chainId) throw new Error(`RPC reports chain ID ${actual}, not ${clean.chainId}`);
    return { chainId: actual, ok: true };
  } finally {
    clearTimeout(timeout);
  }
}
