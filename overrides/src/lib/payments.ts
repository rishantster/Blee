import {
  createPublicClient,
  createWalletClient,
  decodeEventLog,
  formatUnits,
  http,
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
const GAS_BUFFER_BPS = 15_000n; // 50% headroom over the current estimate.
const BPS = 10_000n;

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
  return formatUnits(raw, ARC_USDC_DECIMALS);
}

export function isAuthorizationExpired(auth: TransferAuthorization, nowSeconds = Math.floor(Date.now() / 1000)): boolean {
  try {
    return BigInt(auth.validBefore) <= BigInt(nowSeconds);
  } catch {
    return true;
  }
}

// Compatibility name used by the existing Blee reconciliation hook.
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

/**
 * BLEE_GAS_ACCOUNTING_V2
 *
 * Arc uses USDC as the native gas asset while Blee transfers the ERC-20-facing
 * USDC balance. When the sender also submits the EIP-3009 authorization, gas
 * therefore comes out of the same economic balance as the payment.
 *
 * Blee estimates that cost BEFORE broadcasting a self-relayed transaction and
 * keeps a 50% safety buffer. An estimate is read-only and does not spend gas.
 */
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

  // Gas usage is effectively independent of payment size. A one-base-unit
  // authorization gives eth_estimateGas a valid transfer to simulate without
  // creating the full-balance failure we are protecting against.
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

  // Preserve the amount the user asked the recipient to receive. Gas is a
  // separate routing cost. If this wallet cannot self-relay payment + gas,
  // submitAuthorization stops BEFORE broadcast so the existing Blee send flow
  // can hand the unchanged authorization to a nearby relay instead.
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

  /** BLEE_GAS_SAFE_SUBMISSION_V2
   * If the payer is also the transaction relayer, principal + buffered gas
   * must fit before writeContract is called. This is the critical fix for the
   * Kumar -> Rishant failure: the old build broadcast a doomed transaction,
   * paid gas for the revert, and only then tried Nearby. This build never does.
   */
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
        `BLEE_RELAY_REQUIRED: payment is ${formatUnits(principalRaw, network.tokenDecimals)} ${network.tokenSymbol}; self-settlement can spend ${formatUnits(spendableRaw, network.tokenDecimals)} after reserving the network fee. No transaction was broadcast.`,
      );
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
