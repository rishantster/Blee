import { getAddress, isAddress } from 'viem';
import type { PrivateKeyAccount } from 'viem/accounts';
import { loadVerifiedPeerMeshCapabilities } from './meshCapabilityStore';
import {
  retryPendingOutboundSolanaMeshPayments,
  sendPreparedOfflineSolOverMesh,
} from './solanaMeshDelivery';
import type { StoredOutboundSolanaMeshPayment } from './solanaMeshOutbox';
import { getSolanaSignerForPrimarySession } from './solanaSession';
import {
  prepareSignedOfflineSolTransfer,
  type PreparedOfflineSolTransfer,
} from './solanaTransaction';

const U64_MAX = 18_446_744_073_709_551_615n;
const PAYMENT_ID_RANDOM_BYTES = 16;

function assertLamports(value: string): string {
  const clean = value.trim();
  let amount: bigint;
  try { amount = BigInt(clean); } catch { throw new Error('Enter a valid SOL amount'); }
  if (amount <= 0n || amount > U64_MAX) throw new Error('SOL amount is outside the supported range');
  return amount.toString();
}

function newPaymentId(senderEvm: string): string {
  const random = crypto.getRandomValues(new Uint8Array(PAYMENT_ID_RANDOM_BYTES));
  const suffix = Array.from(random, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `sol:${senderEvm.toLowerCase()}:${suffix}`;
}

export type OfflineSolMeshSendResult = Readonly<{
  paymentId: string;
  senderSolana: string;
  recipientEvm: string;
  recipientSolana: string;
  amountLamports: string;
  prepared: PreparedOfflineSolTransfer;
  delivery: StoredOutboundSolanaMeshPayment;
  recipients: number;
}>;

/**
 * BLEE_SOLANA_OFFLINE_PAYMENT_COORDINATOR_V1
 *
 * High-level, UI-neutral entry point for one nearby native-SOL payment.
 *
 * Security/order invariants:
 * 1. recipient Solana address comes only from the cryptographically verified
 *    nearby capability cache; callers never supply an arbitrary SOL address;
 * 2. the already-authenticated primary Blee account is the only route to the
 *    in-memory Solana signer;
 * 3. durable nonce reservation and exact transaction signing happen before BLE;
 * 4. the exact signed transaction is durably persisted by the outbox before the
 *    first mesh frame leaves the phone;
 * 5. this coordinator never submits on-chain and never talks to a provider RPC.
 *
 * Balance/readiness presentation is intentionally a separate UI concern. If no
 * prepared nonce exists, transaction preparation fails closed rather than
 * falling back to a recent blockhash or an online-only transaction shape.
 */
export async function createAndDeliverOfflineSolPayment(input: {
  primaryAccount: PrivateKeyAccount;
  recipientEvm: string;
  amountLamports: string;
  paymentId?: string;
}): Promise<OfflineSolMeshSendResult> {
  if (!isAddress(input.recipientEvm)) throw new Error('Nearby recipient Blee identity is invalid');
  const recipientEvm = getAddress(input.recipientEvm);
  if (recipientEvm.toLowerCase() === input.primaryAccount.address.toLowerCase()) {
    throw new Error('Cannot send SOL to your own Blee identity');
  }

  const amountLamports = assertLamports(input.amountLamports);
  const capabilities = await loadVerifiedPeerMeshCapabilities(recipientEvm);
  if (
    !capabilities
    || !capabilities.rails.includes('solana-sol')
    || !capabilities.solana
    || capabilities.solana.networkId !== 'solana-mainnet'
  ) {
    throw new Error('Nearby recipient has not advertised verified SOL support');
  }

  const signer = await getSolanaSignerForPrimarySession(input.primaryAccount);
  if (!signer) throw new Error('Solana wallet is not ready for this authenticated Blee session');

  const paymentId = input.paymentId?.trim() || newPaymentId(input.primaryAccount.address);
  if (!paymentId || paymentId.length > 160) throw new Error('Invalid Blee SOL payment ID');

  const prepared = await prepareSignedOfflineSolTransfer({
    signer,
    paymentId,
    recipient: capabilities.solana.address,
    amountLamports,
  });

  const { payment, recipients } = await sendPreparedOfflineSolOverMesh({
    primaryAccount: input.primaryAccount,
    solanaSigner: signer,
    prepared,
    recipientEvm,
  });

  return {
    paymentId,
    senderSolana: signer.address,
    recipientEvm,
    recipientSolana: capabilities.solana.address,
    amountLamports,
    prepared,
    delivery: payment,
    recipients,
  };
}

/**
 * Retries only durable pending outbox rows for the authenticated Blee identity.
 * The underlying delivery layer reuses the exact signed Solana bytes and merely
 * refreshes the outer EVM-signed transport packet.
 */
export async function retryPendingOfflineSolPayments(input: {
  primaryAccount: PrivateKeyAccount;
  limit?: number;
  minRetryAgeMs?: number;
}): Promise<Array<{ payment: StoredOutboundSolanaMeshPayment; recipients: number }>> {
  return retryPendingOutboundSolanaMeshPayments(input);
}
