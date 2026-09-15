import { formatUnits, getAddress, isAddress } from 'viem';
import type { PaymentRecord } from '../types/domain';
import { validateSolanaMeshPaymentEnvelope } from './solanaMeshEnvelope';
import { loadOutboundSolanaMeshPayments } from './solanaMeshOutbox';
import { loadStoredSolanaMeshPayments } from './solanaMeshStore';

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

/**
 * BLEE_SOLANA_ACTIVITY_PROJECTION_V1
 *
 * Builds read-only Activity rows from the two durable SOL custody journals.
 * Outbox rows describe this identity's sends. Inbox rows are shown only when
 * this identity is the intended recipient; courier custody is deliberately
 * excluded from user Activity. These rows are transport state only and never
 * claim on-chain submission or settlement.
 */
export async function loadSolanaActivityPayments(localEvmAddress: string): Promise<PaymentRecord[]> {
  if (!isAddress(localEvmAddress)) return [];
  const localEvm = getAddress(localEvmAddress);
  const [outbox, inbox] = await Promise.all([
    loadOutboundSolanaMeshPayments(),
    loadStoredSolanaMeshPayments(),
  ]);

  const rows: PaymentRecord[] = [];
  for (const row of outbox) {
    if (row.senderEvm.toLowerCase() !== localEvm.toLowerCase()) continue;
    rows.push(baseSolPayment({
      id: row.envelope.paymentId,
      direction: 'out',
      counterparty: row.envelope.recipientEvm,
      amountLamports: row.envelope.amountLamports,
      createdAt: row.createdAt,
      updatedAt: row.updatedAt,
      state: outboundState(row.state),
      durablyReceivedAt: row.deliveredAt,
      attempts: row.attempts,
    }));
  }

  for (const row of inbox) {
    if (row.role !== 'recipient') continue;
    const envelope = await validateSolanaMeshPaymentEnvelope(row.packet);
    if (envelope.recipientEvm.toLowerCase() !== localEvm.toLowerCase()) continue;
    rows.push(baseSolPayment({
      id: envelope.paymentId,
      direction: 'in',
      counterparty: row.packet.origin,
      amountLamports: envelope.amountLamports,
      createdAt: row.firstReceivedAt,
      updatedAt: row.lastReceivedAt,
      state: 'mesh-delivered',
      durablyReceivedAt: row.firstReceivedAt,
    }));
  }

  return rows.sort((a, b) => b.createdAt - a.createdAt);
}
