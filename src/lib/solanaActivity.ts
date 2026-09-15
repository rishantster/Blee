import { formatUnits, getAddress, isAddress } from 'viem';
import type { PaymentRecord } from '../types/domain';
import { validateSolanaMeshPaymentEnvelope } from './solanaMeshEnvelope';
import { loadOutboundSolanaMeshPayments } from './solanaMeshOutbox';
import { loadStoredSolanaMeshPayments } from './solanaMeshStore';
import { loadSolanaSettlementRecords, type SolanaSettlementRecord } from './solanaSettlement';

const SOL_DECIMALS = 9;

function outboundState(state: 'prepared' | 'broadcast' | 'delivered'): PaymentRecord['state'] {
  switch (state) {
    case 'prepared': return 'queued-local';
    case 'broadcast': return 'mesh-broadcast';
    case 'delivered': return 'mesh-delivered';
  }
}

function baseSolPayment(input: {
  id: string;
  direction: 'out' | 'in';
  counterparty: string;
  amountLamports: string;
  createdAt: number;
  updatedAt: number;
  state: PaymentRecord['state'];
  durablyReceivedAt?: number;
  attempts?: number;
}): PaymentRecord {
  if (!isAddress(input.counterparty)) throw new Error('SOL activity counterparty Blee identity is invalid');
  const amountLamports = BigInt(input.amountLamports);
  if (amountLamports <= 0n) throw new Error('SOL activity amount is invalid');
  return {
    id: input.id,
    direction: input.direction,
    counterparty: getAddress(input.counterparty),
    amount: formatUnits(amountLamports, SOL_DECIMALS),
    createdAt: input.createdAt,
    updatedAt: input.updatedAt,
    state: input.state,
    route: 'ble-mesh',
    railId: 'solana-sol',
    networkId: 'solana-mainnet',
    assetId: 'sol',
    assetSymbol: 'SOL',
    environment: 'mainnet',
    chainFamily: 'solana',
    durablyReceivedAt: input.durablyReceivedAt,
    attempts: input.attempts,
  };
}

function applySettlement(row: PaymentRecord, settlement?: SolanaSettlementRecord): PaymentRecord {
  if (!settlement || settlement.paymentId !== row.id) return row;
  const next: PaymentRecord = {
    ...row,
    updatedAt: Math.max(row.updatedAt || row.createdAt, settlement.updatedAt),
    attempts: Math.max(row.attempts || 0, settlement.attempts),
  };

  if (settlement.signature) next.solanaSignature = settlement.signature;
  if (settlement.submittedAt) next.submittedAt = settlement.submittedAt;
  if (settlement.confirmedAt) next.confirmedAt = settlement.confirmedAt;

  switch (settlement.state) {
    case 'pending':
      return next;
    case 'submitted':
      return { ...next, state: 'submitted', solanaConfirmationStatus: 'processed' };
    case 'confirmed':
      return { ...next, state: 'submitted', solanaConfirmationStatus: 'confirmed' };
    case 'finalized':
      return {
        ...next,
        state: 'settled',
        solanaConfirmationStatus: 'finalized',
        settledAt: settlement.finalizedAt || settlement.updatedAt,
      };
    case 'failed':
      return { ...next, state: 'failed', error: settlement.lastError || 'Solana settlement failed' };
  }
}

/**
 * BLEE_SOLANA_ACTIVITY_PROJECTION_V2
 *
 * Builds user-visible SOL Activity from durable mesh custody first, then overlays
 * only the separately persisted settlement journal. Outbox rows describe this
 * identity's sends. Inbox rows are shown only when this identity is the intended
 * recipient; courier custody is deliberately excluded. On-chain submitted,
 * confirmed and finalized states can therefore appear only after the settlement
 * worker has persisted a gateway signature/status for the exact transaction.
 */
export async function loadSolanaActivityPayments(localEvmAddress: string): Promise<PaymentRecord[]> {
  if (!isAddress(localEvmAddress)) return [];
  const localEvm = getAddress(localEvmAddress);
  const [outbox, inbox, settlements] = await Promise.all([
    loadOutboundSolanaMeshPayments(),
    loadStoredSolanaMeshPayments(),
    loadSolanaSettlementRecords(),
  ]);
  const settlementByPaymentId = new Map(settlements.map((row) => [row.paymentId, row]));

  const rows: PaymentRecord[] = [];
  for (const row of outbox) {
    if (row.senderEvm.toLowerCase() !== localEvm.toLowerCase()) continue;
    const payment = baseSolPayment({
      id: row.envelope.paymentId,
      direction: 'out',
      counterparty: row.envelope.recipientEvm,
      amountLamports: row.envelope.amountLamports,
      createdAt: row.createdAt,
      updatedAt: row.updatedAt,
      state: outboundState(row.state),
      durablyReceivedAt: row.deliveredAt,
      attempts: row.attempts,
    });
    rows.push(applySettlement(payment, settlementByPaymentId.get(payment.id)));
  }

  for (const row of inbox) {
    if (row.role !== 'recipient') continue;
    const envelope = await validateSolanaMeshPaymentEnvelope(row.packet);
    if (envelope.recipientEvm.toLowerCase() !== localEvm.toLowerCase()) continue;
    const payment = baseSolPayment({
      id: envelope.paymentId,
      direction: 'in',
      counterparty: row.packet.origin,
      amountLamports: envelope.amountLamports,
      createdAt: row.firstReceivedAt,
      updatedAt: row.lastReceivedAt,
      state: 'mesh-delivered',
      durablyReceivedAt: row.firstReceivedAt,
    });
    rows.push(applySettlement(payment, settlementByPaymentId.get(payment.id)));
  }

  return rows.sort((a, b) => b.createdAt - a.createdAt);
}
