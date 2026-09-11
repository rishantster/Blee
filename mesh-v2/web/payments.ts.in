import { Capacitor, registerPlugin } from '@capacitor/core';
import {
  createPublicClient,
  createWalletClient,
  decodeEventLog,
  encodeFunctionData,
  formatUnits,
  http,
  keccak256,
  parseUnits,
  recoverTypedDataAddress,
  type Address,
  type Hex,
} from 'viem';
import type { PrivateKeyAccount } from 'viem/accounts';
import {
  ARC_RPC,
  ARC_USDC,
  ARC_USDC_DECIMALS,
  USDC_EIP712_NAME,
  USDC_EIP712_VERSION,
  arcTestnet,
  transferAuthorizationTypes,
  usdcAbi,
} from './arc';
import { getActiveNetwork } from './networkConfig';
import type { TransferAuthorization } from '../types/domain';

export const AUTH_TTL_SECONDS = 24 * 60 * 60;
const CLOCK_SKEW_SECONDS = 60;
const EVM_NATIVE_DECIMALS = 18;
const GAS_BUFFER_BPS = 15_000n;
const BPS = 10_000n;
const OFFLINE_GAS_LIMIT = 250_000n;
const PROFILE_VERSION = 1;
const FRESH_FEE_WINDOW_MS = 6 * 60 * 60 * 1000;

type StorePlugin = {
  init(): Promise<{ ready: boolean }>;
  getValue(options: { key: string }): Promise<{ value?: string | null }>;
  setValue(options: { key: string; value: string }): Promise<void>;
  loadPayments(): Promise<{ payments?: string[] }>;
};

type SettlementProfile = {
  version: number;
  chainId: number;
  address: string;
  chainNonce: number;
  nextNonce: number;
  maxFeePerGas: string;
  maxPriorityFeePerGas: string;
  syncedAt: number;
};

export type SenderFundedBroadcast = {
  mode: 'SENDER_FUNDED_RAW_TX';
  chainId: number;
  txNonce: number;
  rawTransaction: Hex;
  txHash: Hex;
  gasLimit: string;
  maxFeePerGas: string;
  maxPriorityFeePerGas: string;
  maxGasCostNative: string;
  profileSyncedAt: number;
};

type AuthorizationWithBroadcast = TransferAuthorization & {
  broadcast?: SenderFundedBroadcast | { mode: 'AUTH_ONLY'; reason: string };
};

const BleeStore = registerPlugin<StorePlugin>('BleeStore');
const inMemoryReservations = new Map<string, Set<number>>();
let reservationQueue: Promise<unknown> = Promise.resolve();

export const publicClient = createPublicClient({ chain: arcTestnet, transport: http(ARC_RPC) });

function randomNonce(): Hex {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return (`0x${Array.from(bytes).map((value) => value.toString(16).padStart(2, '0')).join('')}`) as Hex;
}

function domain() {
  return {
    name: USDC_EIP712_NAME,
    version: USDC_EIP712_VERSION,
    chainId: arcTestnet.id,
    verifyingContract: ARC_USDC,
  } as const;
}

function ceilDiv(value: bigint, divisor: bigint): bigint {
  return value === 0n ? 0n : (value + divisor - 1n) / divisor;
}

function sameAssetPaysGas(): boolean {
  const network = getActiveNetwork();
  return network.nativeSymbol.trim().toLowerCase() === network.tokenSymbol.trim().toLowerCase();
}

function nativeFeeToPaymentTokenRaw(nativeFee: bigint): bigint {
  const network = getActiveNetwork();
  const tokenScale = 10n ** BigInt(network.tokenDecimals);
  const nativeScale = 10n ** BigInt(EVM_NATIVE_DECIMALS);
  return ceilDiv(nativeFee * tokenScale, nativeScale);
}

function friendlySettlementError(error: unknown): Error {
  const raw = error instanceof Error ? error.message : String(error);
  const lower = raw.toLowerCase();
  if (lower.includes('transfer amount exceeds balance')) {
    return new Error('Payment could not settle because the authorizer no longer has enough spendable balance.');
  }
  if (lower.includes('insufficient funds') || lower.includes('insufficient balance')) {
    return new Error('Not enough balance to cover the payment and network fee.');
  }
  if (lower.includes('authorization is used') || lower.includes('authorizationused')) {
    return new Error('This payment authorization has already been settled.');
  }
  return error instanceof Error ? error : new Error('Settlement failed');
}

function profileKey(address: Address) {
  return `settlement.profile.v1:${arcTestnet.id}:${address.toLowerCase()}`;
}

function isFinalPaymentState(state: unknown) {
  const value = String(state ?? '').toLowerCase();
  return value.includes('confirm') || value.includes('settled') || value.includes('expired') || value.includes('fail') || value.includes('revert');
}

async function ensureNativeStore() {
  if (!Capacitor.isNativePlatform()) return false;
  try {
    const result = await BleeStore.init();
    return Boolean(result.ready);
  } catch {
    return false;
  }
}

async function loadProfile(address: Address): Promise<SettlementProfile | null> {
  if (!(await ensureNativeStore())) return null;
  try {
    const { value } = await BleeStore.getValue({ key: profileKey(address) });
    if (!value) return null;
    const parsed = JSON.parse(value) as SettlementProfile;
    if (
      parsed.version !== PROFILE_VERSION
      || parsed.chainId !== arcTestnet.id
      || parsed.address.toLowerCase() !== address.toLowerCase()
      || !Number.isSafeInteger(parsed.chainNonce)
      || !parsed.maxFeePerGas
    ) return null;
    return parsed;
  } catch {
    return null;
  }
}

async function saveProfile(profile: SettlementProfile) {
  if (!(await ensureNativeStore())) return;
  await BleeStore.setValue({ key: profileKey(profile.address as Address), value: JSON.stringify(profile) });
}

async function localActiveTransactionNonces(address: Address): Promise<number[]> {
  if (!(await ensureNativeStore())) return [];
  try {
    const { payments = [] } = await BleeStore.loadPayments();
    const rows: number[] = [];
    for (const raw of payments) {
      try {
        const payment = JSON.parse(raw) as Record<string, any>;
        if (String(payment.direction).toLowerCase() !== 'outgoing' || isFinalPaymentState(payment.state)) continue;
        const auth = (payment.authorization ?? payment.auth) as AuthorizationWithBroadcast | undefined;
        const broadcast = auth?.broadcast;
        if (!broadcast || broadcast.mode !== 'SENDER_FUNDED_RAW_TX') continue;
        if (String(auth.from).toLowerCase() !== address.toLowerCase()) continue;
        if (broadcast.chainId !== arcTestnet.id || !Number.isSafeInteger(broadcast.txNonce)) continue;
        rows.push(broadcast.txNonce);
      } catch {}
    }
    return rows;
  } catch {
    return [];
  }
}

function memoryNonces(address: Address) {
  const key = `${arcTestnet.id}:${address.toLowerCase()}`;
  let set = inMemoryReservations.get(key);
  if (!set) {
    set = new Set<number>();
    inMemoryReservations.set(key, set);
  }
  return set;
}

export async function refreshSenderFundedSettlementProfile(address: Address): Promise<boolean> {
  if (!(await ensureNativeStore())) return false;
  try {
    const [chainNonce, feeEstimate] = await Promise.all([
      publicClient.getTransactionCount({ address, blockTag: 'pending' }),
      publicClient.estimateFeesPerGas().catch(async () => {
        const gasPrice = await publicClient.getGasPrice();
        return { maxFeePerGas: gasPrice, maxPriorityFeePerGas: 1n };
      }),
    ]);
    const active = await localActiveTransactionNonces(address);
    const maxActive = active.length ? Math.max(...active) : chainNonce - 1;
    const maxFeePerGas = feeEstimate.maxFeePerGas ?? await publicClient.getGasPrice();
    const maxPriorityFeePerGas = feeEstimate.maxPriorityFeePerGas ?? 1n;
    const profile: SettlementProfile = {
      version: PROFILE_VERSION,
      chainId: arcTestnet.id,
      address: address.toLowerCase(),
      chainNonce,
      nextNonce: Math.max(chainNonce, maxActive + 1),
      maxFeePerGas: maxFeePerGas.toString(),
      maxPriorityFeePerGas: maxPriorityFeePerGas.toString(),
      syncedAt: Date.now(),
    };
    await saveProfile(profile);
    const memory = memoryNonces(address);
    for (const nonce of [...memory]) if (nonce < chainNonce) memory.delete(nonce);
    return true;
  } catch {
    return false;
  }
}

async function prepareSenderFundedBroadcast(
  account: PrivateKeyAccount,
  auth: TransferAuthorization,
): Promise<AuthorizationWithBroadcast> {
  if (!(await ensureNativeStore())) return { ...auth, broadcast: { mode: 'AUTH_ONLY', reason: 'NATIVE_STORE_UNAVAILABLE' } };

  let profile = await loadProfile(account.address);
  if (!profile) {
    await refreshSenderFundedSettlementProfile(account.address);
    profile = await loadProfile(account.address);
  }
  if (!profile) return { ...auth, broadcast: { mode: 'AUTH_ONLY', reason: 'NO_SYNCED_NONCE_OR_FEE_PROFILE' } };

  const active = await localActiveTransactionNonces(account.address);
  const memory = memoryNonces(account.address);
  const maxActive = active.length ? Math.max(...active) : profile.chainNonce - 1;
  const maxMemory = memory.size ? Math.max(...memory) : profile.chainNonce - 1;
  const txNonce = Math.max(profile.chainNonce, maxActive + 1, maxMemory + 1);

  const age = Math.max(0, Date.now() - profile.syncedAt);
  const feeMultiplier = age <= FRESH_FEE_WINDOW_MS ? 2n : 4n;
  const baseMaxFee = BigInt(profile.maxFeePerGas);
  const basePriority = BigInt(profile.maxPriorityFeePerGas || '1');
  const maxFeePerGas = baseMaxFee * feeMultiplier;
  const maxPriorityFeePerGas = basePriority * 2n;

  const data = encodeFunctionData({
    abi: usdcAbi,
    functionName: 'transferWithAuthorization',
    args: [
      auth.from,
      auth.to,
      BigInt(auth.value),
      BigInt(auth.validAfter),
      BigInt(auth.validBefore),
      auth.nonce,
      auth.signature,
    ],
  });

  const rawTransaction = await account.signTransaction({
    type: 'eip1559',
    chainId: arcTestnet.id,
    nonce: txNonce,
    to: ARC_USDC,
    value: 0n,
    data,
    gas: OFFLINE_GAS_LIMIT,
    maxFeePerGas,
    maxPriorityFeePerGas,
  });
  const txHash = keccak256(rawTransaction);
  memory.add(txNonce);
  profile.nextNonce = txNonce + 1;
  await saveProfile(profile);

  return {
    ...auth,
    broadcast: {
      mode: 'SENDER_FUNDED_RAW_TX',
      chainId: arcTestnet.id,
      txNonce,
      rawTransaction,
      txHash,
      gasLimit: OFFLINE_GAS_LIMIT.toString(),
      maxFeePerGas: maxFeePerGas.toString(),
      maxPriorityFeePerGas: maxPriorityFeePerGas.toString(),
      maxGasCostNative: (OFFLINE_GAS_LIMIT * maxFeePerGas).toString(),
      profileSyncedAt: profile.syncedAt,
    },
  };
}

function withNonceReservation<T>(work: () => Promise<T>): Promise<T> {
  const next = reservationQueue.then(work, work);
  reservationQueue = next.then(() => undefined, () => undefined);
  return next;
}

function senderBroadcast(auth: TransferAuthorization): SenderFundedBroadcast | null {
  const candidate = (auth as AuthorizationWithBroadcast).broadcast;
  return candidate?.mode === 'SENDER_FUNDED_RAW_TX' ? candidate : null;
}

export async function checkArc(timeoutMs = 3200): Promise<boolean> {
  try {
    await Promise.race([
      publicClient.getBlockNumber(),
      new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), timeoutMs)),
    ]);
    return true;
  } catch {
    return false;
  }
}

export async function getBalance(address: Address): Promise<string> {
  const raw = await publicClient.readContract({
    address: ARC_USDC,
    abi: usdcAbi,
    functionName: 'balanceOf',
    args: [address],
  });
  try { await refreshSenderFundedSettlementProfile(address); } catch {}
  return formatUnits(raw, ARC_USDC_DECIMALS);
}

export function isAuthorizationExpired(auth: TransferAuthorization, nowSeconds = Math.floor(Date.now() / 1000)): boolean {
  try {
    return BigInt(auth.validBefore) <= BigInt(nowSeconds);
  } catch {
    return true;
  }
}

export const authorizationExpired = isAuthorizationExpired;

async function signProbeAuthorization(
  account: PrivateKeyAccount,
  to: Address,
  value: bigint,
): Promise<TransferAuthorization> {
  const now = BigInt(Math.floor(Date.now() / 1000));
  const validAfter = now - BigInt(CLOCK_SKEW_SECONDS);
  const validBefore = now + BigInt(AUTH_TTL_SECONDS);
  const nonce = randomNonce();
  const signature = await account.signTypedData({
    domain: domain(),
    types: transferAuthorizationTypes,
    primaryType: 'TransferWithAuthorization',
    message: { from: account.address, to, value, validAfter, validBefore, nonce },
  });
  return {
    from: account.address,
    to,
    value: value.toString(),
    validAfter: validAfter.toString(),
    validBefore: validBefore.toString(),
    nonce,
    signature,
  };
}

export async function estimateSelfRelayGasReserve(
  account: PrivateKeyAccount,
  to: Address,
): Promise<bigint> {
  if (!sameAssetPaysGas()) return 0n;

  const rawBalance = await publicClient.readContract({
    address: ARC_USDC,
    abi: usdcAbi,
    functionName: 'balanceOf',
    args: [account.address],
  });
  if (rawBalance <= 1n) return rawBalance;

  const probe = await signProbeAuthorization(account, to, 1n);
  const estimatedGas = await publicClient.estimateContractGas({
    account: account.address,
    address: ARC_USDC,
    abi: usdcAbi,
    functionName: 'transferWithAuthorization',
    args: [
      probe.from,
      probe.to,
      BigInt(probe.value),
      BigInt(probe.validAfter),
      BigInt(probe.validBefore),
      probe.nonce,
      probe.signature,
    ],
  });
  const gasPrice = await publicClient.getGasPrice();
  const bufferedNativeFee = ceilDiv(estimatedGas * gasPrice * GAS_BUFFER_BPS, BPS);
  const tokenReserve = nativeFeeToPaymentTokenRaw(bufferedNativeFee);
  return tokenReserve > 0n ? tokenReserve + 1n : 1n;
}

export async function getSelfRelaySpendable(
  account: PrivateKeyAccount,
  to: Address,
): Promise<{ balance: string; reserve: string; spendable: string }> {
  const network = getActiveNetwork();
  const balanceRaw = await publicClient.readContract({
    address: ARC_USDC,
    abi: usdcAbi,
    functionName: 'balanceOf',
    args: [account.address],
  });
  const reserveRaw = sameAssetPaysGas() ? await estimateSelfRelayGasReserve(account, to) : 0n;
  const spendableRaw = balanceRaw > reserveRaw ? balanceRaw - reserveRaw : 0n;
  return {
    balance: formatUnits(balanceRaw, network.tokenDecimals),
    reserve: formatUnits(reserveRaw, network.tokenDecimals),
    spendable: formatUnits(spendableRaw, network.tokenDecimals),
  };
}

export async function createAuthorization(
  account: PrivateKeyAccount,
  to: Address,
  amount: string,
): Promise<TransferAuthorization> {
  const now = BigInt(Math.floor(Date.now() / 1000));
  const validAfter = now - BigInt(CLOCK_SKEW_SECONDS);
  const validBefore = now + BigInt(AUTH_TTL_SECONDS);
  const nonce = randomNonce();
  const value = parseUnits(amount, ARC_USDC_DECIMALS);
  if (value <= 0n) throw new Error('Amount must be greater than zero');

  const signature = await account.signTypedData({
    domain: domain(),
    types: transferAuthorizationTypes,
    primaryType: 'TransferWithAuthorization',
    message: { from: account.address, to, value, validAfter, validBefore, nonce },
  });

  const authorization: TransferAuthorization = {
    from: account.address,
    to,
    value: value.toString(),
    validAfter: validAfter.toString(),
    validBefore: validBefore.toString(),
    nonce,
    signature,
  };

  return withNonceReservation(() => prepareSenderFundedBroadcast(account, authorization));
}

export async function verifyAuthorization(auth: TransferAuthorization): Promise<boolean> {
  try {
    if (isAuthorizationExpired(auth)) return false;
    const recovered = await recoverTypedDataAddress({
      domain: domain(),
      types: transferAuthorizationTypes,
      primaryType: 'TransferWithAuthorization',
      message: {
        from: auth.from,
        to: auth.to,
        value: BigInt(auth.value),
        validAfter: BigInt(auth.validAfter),
        validBefore: BigInt(auth.validBefore),
        nonce: auth.nonce,
      },
      signature: auth.signature,
    });
    return recovered.toLowerCase() === auth.from.toLowerCase();
  } catch {
    return false;
  }
}

export async function submitAuthorization(
  relayer: PrivateKeyAccount,
  auth: TransferAuthorization,
  onBroadcast?: (hash: Hex) => Promise<void> | void,
): Promise<Hex> {
  if (!(await verifyAuthorization(auth))) throw new Error('Invalid or expired authorization');

  if (sameAssetPaysGas() && relayer.address.toLowerCase() === auth.from.toLowerCase()) {
    const balanceRaw = await publicClient.readContract({
      address: ARC_USDC,
      abi: usdcAbi,
      functionName: 'balanceOf',
      args: [auth.from],
    });
    const reserveRaw = await estimateSelfRelayGasReserve(relayer, auth.to);
    const principalRaw = BigInt(auth.value);
    if (principalRaw + reserveRaw > balanceRaw) {
      const network = getActiveNetwork();
      const spendableRaw = balanceRaw > reserveRaw ? balanceRaw - reserveRaw : 0n;
      throw new Error(
        `BLEE_RELAY_REQUIRED: payment is ${formatUnits(principalRaw, network.tokenDecimals)} ${network.tokenSymbol}; sender-funded settlement can spend ${formatUnits(spendableRaw, network.tokenDecimals)} after reserving the network fee. No transaction was broadcast.`,
      );
    }
  }

  const prepared = senderBroadcast(auth);
  if (prepared && prepared.chainId === arcTestnet.id && /^0x[0-9a-fA-F]+$/.test(prepared.rawTransaction)) {
    let hash = prepared.txHash;
    try {
      hash = await publicClient.sendRawTransaction({ serializedTransaction: prepared.rawTransaction });
      await onBroadcast?.(hash);
      const receipt = await publicClient.waitForTransactionReceipt({ hash, timeout: 90_000, confirmations: 1 });
      if (receipt.status !== 'success') throw new Error('Network transaction reverted');
      return hash;
    } catch (error) {
      const message = error instanceof Error ? error.message.toLowerCase() : String(error).toLowerCase();
      const known = message.includes('already known') || message.includes('known transaction') || message.includes('already imported');
      if (known) {
        await onBroadcast?.(hash);
        const receipt = await publicClient.waitForTransactionReceipt({ hash, timeout: 90_000, confirmations: 1 });
        if (receipt.status !== 'success') throw new Error('Network transaction reverted');
        return hash;
      }
      if (!message.includes('nonce too low')) throw friendlySettlementError(error);
      try {
        const receipt = await publicClient.getTransactionReceipt({ hash });
        if (receipt.status === 'success') return hash;
      } catch {}
      // The sender is online and unlocked here, so a stale cached raw transaction
      // may safely fall through to a fresh sender-signed transaction below.
    }
  }

  const walletClient = createWalletClient({ account: relayer, chain: arcTestnet, transport: http(ARC_RPC) });
  let hash: Hex;
  try {
    hash = await walletClient.writeContract({
      address: ARC_USDC,
      abi: usdcAbi,
      functionName: 'transferWithAuthorization',
      args: [
        auth.from,
        auth.to,
        BigInt(auth.value),
        BigInt(auth.validAfter),
        BigInt(auth.validBefore),
        auth.nonce,
        auth.signature,
      ],
    });
  } catch (error) {
    throw friendlySettlementError(error);
  }

  await onBroadcast?.(hash);
  const receipt = await publicClient.waitForTransactionReceipt({ hash, timeout: 90_000, confirmations: 1 });
  if (receipt.status !== 'success') throw new Error('Network transaction reverted');
  return hash;
}

export async function transactionStatus(hash: Hex): Promise<'success' | 'reverted' | 'pending'> {
  try {
    const receipt = await publicClient.getTransactionReceipt({ hash });
    return receipt.status === 'success' ? 'success' : 'reverted';
  } catch {
    return 'pending';
  }
}

export const getTransactionStatus = transactionStatus;

export async function authorizationUsed(from: Address, nonce: Hex): Promise<boolean> {
  try {
    return Boolean(await publicClient.readContract({
      address: ARC_USDC,
      abi: usdcAbi,
      functionName: 'authorizationState',
      args: [from, nonce],
    }));
  } catch {
    return false;
  }
}

export async function verifyReceipt(auth: TransferAuthorization, txHash: Hex): Promise<boolean> {
  try {
    const receipt = await publicClient.getTransactionReceipt({ hash: txHash });
    if (receipt.status !== 'success') return false;
    for (const log of receipt.logs) {
      if (log.address.toLowerCase() !== ARC_USDC.toLowerCase()) continue;
      try {
        const decoded = decodeEventLog({ abi: usdcAbi, data: log.data, topics: log.topics });
        if (decoded.eventName !== 'AuthorizationUsed') continue;
        const args = decoded.args as { authorizer: Address; nonce: Hex };
        if (
          args.authorizer.toLowerCase() === auth.from.toLowerCase()
          && args.nonce.toLowerCase() === auth.nonce.toLowerCase()
        ) return true;
      } catch {}
    }
    return false;
  } catch {
    return false;
  }
}

const transferEvent = {
  type: 'event',
  name: 'Transfer',
  anonymous: false,
  inputs: [
    { name: 'from', type: 'address', indexed: true },
    { name: 'to', type: 'address', indexed: true },
    { name: 'value', type: 'uint256', indexed: false },
  ],
} as const;

export async function scanIncomingTransfers(address: Address, fromBlock: bigint, toBlock: bigint) {
  if (fromBlock > toBlock) return [];
  const logs = await publicClient.getLogs({
    address: ARC_USDC,
    event: transferEvent,
    args: { to: address },
    fromBlock,
    toBlock,
  });
  const rows: Array<{
    id: string;
    from: Address;
    to: Address;
    amount: string;
    txHash: Hex;
    blockNumber: bigint;
    logIndex: number;
    nonce: Hex;
  }> = [];

  for (const log of logs.slice(0, 100)) {
    const args = log.args;
    if (!args.from || !args.to || args.value === undefined || !log.transactionHash || log.blockNumber === null || log.logIndex === null) continue;
    try {
      const receipt = await publicClient.getTransactionReceipt({ hash: log.transactionHash });
      let nonce: Hex | null = null;
      for (const receiptLog of receipt.logs) {
        if (receiptLog.address.toLowerCase() !== ARC_USDC.toLowerCase()) continue;
        try {
          const decoded = decodeEventLog({ abi: usdcAbi, data: receiptLog.data, topics: receiptLog.topics });
          if (decoded.eventName !== 'AuthorizationUsed') continue;
          const used = decoded.args as { authorizer: Address; nonce: Hex };
          if (used.authorizer.toLowerCase() === args.from.toLowerCase()) {
            nonce = used.nonce;
            break;
          }
        } catch {}
      }
      if (!nonce) continue;
      rows.push({
        id: `${args.from}:${nonce}`.toLowerCase(),
        from: args.from,
        to: args.to,
        amount: formatUnits(args.value, ARC_USDC_DECIMALS),
        txHash: log.transactionHash,
        blockNumber: log.blockNumber,
        logIndex: log.logIndex,
        nonce,
      });
    } catch {}
  }
  return rows;
}

export const scanIncomingPayments = scanIncomingTransfers;
export const scanIncomingSettlements = scanIncomingTransfers;
export const scanSettledIncomingTransfers = scanIncomingTransfers;

export function displayAuthAmount(auth: TransferAuthorization): string {
  return formatUnits(BigInt(auth.value), ARC_USDC_DECIMALS);
}
