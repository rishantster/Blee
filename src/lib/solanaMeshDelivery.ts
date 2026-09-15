import type { PrivateKeyAccount } from 'viem/accounts';
import type { MeshPacket } from '../types/domain';
import { BleeNearby, nativeNearbyAvailable } from './nativeNearby';
import { createMeshPacket, packetFrames } from './meshProtocol';
import {
  prepareSolanaMeshPaymentPacket,
  validateSolanaMeshPaymentEnvelope,
} from './solanaMeshEnvelope';
import {
  loadOutboundSolanaMeshPayments,
  persistOutboundSolanaMeshPayment,
  recordOutboundSolanaMeshBroadcast,
  type StoredOutboundSolanaMeshPayment,
} from './solanaMeshOutbox';
import type { PreparedOfflineSolTransfer } from './solanaTransaction';
import type { SolanaLocalSigner } from './solanaVault';

async function transmitPacket(packet: MeshPacket): Promise<number> {
  if (!nativeNearbyAvailable()) return 0;
  const frames = packetFrames(packet);
  if (!frames.length) return 0;
  let recipients = Number.POSITIVE_INFINITY;
  for (const frame of frames) {
    const result = await BleeNearby.send({ data: frame });
    recipients = Math.min(recipients, Math.max(0, Number(result.recipients || 0)));
  }
  return Number.isFinite(recipients) ? recipients : 0;
}

/**
 * BLEE_SOLANA_MESH_OUTBOUND_DELIVERY_V1
 *
 * The signed durable-nonce transaction is already fixed before this layer.
 * Blee persists the authenticated SOL envelope to the SQLite-backed outbox
 * before emitting the first BLE frame. Delivery is complete only after a
 * matching cryptographic recipient ACK updates that durable outbox entry.
 */
export async function sendPreparedOfflineSolOverMesh(input: {
  primaryAccount: PrivateKeyAccount;
  solanaSigner: SolanaLocalSigner;
  prepared: PreparedOfflineSolTransfer;
  recipientEvm: string;
}): Promise<{ payment: StoredOutboundSolanaMeshPayment; recipients: number }> {
  const packet = await prepareSolanaMeshPaymentPacket(input);
  const envelope = await validateSolanaMeshPaymentEnvelope(packet);

  // BLEE_SOLANA_OUTBOX_BEFORE_TRANSPORT_V1
  // No frame may leave this device until the exact signed transaction envelope
  // is committed durably. A crash after this line can safely retry later.
  await persistOutboundSolanaMeshPayment({
    senderEvm: input.primaryAccount.address,
    envelope,
  });

  const recipients = await transmitPacket(packet);
  const payment = await recordOutboundSolanaMeshBroadcast({
    paymentId: envelope.paymentId,
    signedTransactionSha256: envelope.signedTransactionSha256,
    recipients,
  });
  return { payment, recipients };
}

/**
 * Retries an existing outbound payment without rebuilding or re-signing the
 * Solana transaction. A fresh outer EVM-signed mesh packet id is intentional:
 * it allows a recipient that durably stored an earlier attempt to emit the ACK
 * again if the first acknowledgement was lost.
 */
export async function retryOutboundSolanaMeshPayment(input: {
  primaryAccount: PrivateKeyAccount;
  paymentId: string;
}): Promise<{ payment: StoredOutboundSolanaMeshPayment; recipients: number }> {
  const entries = await loadOutboundSolanaMeshPayments();
  const existing = entries.find((row) => row.envelope.paymentId === input.paymentId);
  if (!existing) throw new Error('Outbound SOL payment was not found');
  if (existing.senderEvm.toLowerCase() !== input.primaryAccount.address.toLowerCase()) {
    throw new Error('Outbound SOL payment belongs to a different Blee identity');
  }
  if (existing.state === 'delivered') return { payment: existing, recipients: 0 };

  // The inner envelope contains the same exact signed Solana wire bytes and
  // digest. Only the transport packet id/signature are refreshed for retry.
  const packet = await createMeshPacket(input.primaryAccount, 'sol-payment', existing.envelope);
  const validated = await validateSolanaMeshPaymentEnvelope(packet);
  if (validated.signedTransactionSha256 !== existing.envelope.signedTransactionSha256) {
    throw new Error('Outbound SOL retry changed the signed transaction digest');
  }

  const recipients = await transmitPacket(packet);
  const payment = await recordOutboundSolanaMeshBroadcast({
    paymentId: existing.envelope.paymentId,
    signedTransactionSha256: existing.envelope.signedTransactionSha256,
    recipients,
  });
  return { payment, recipients };
}

export async function retryPendingOutboundSolanaMeshPayments(input: {
  primaryAccount: PrivateKeyAccount;
  limit?: number;
  minRetryAgeMs?: number;
}): Promise<Array<{ payment: StoredOutboundSolanaMeshPayment; recipients: number }>> {
  const limit = Math.max(1, Math.min(4, Math.trunc(input.limit || 2)));
  const minRetryAgeMs = Math.max(1000, Math.trunc(input.minRetryAgeMs || 6000));
  const now = Date.now();
  const entries = (await loadOutboundSolanaMeshPayments())
    .filter((row) =>
      row.senderEvm.toLowerCase() === input.primaryAccount.address.toLowerCase()
      && row.state !== 'delivered'
      && (!row.lastBroadcastAt || now - row.lastBroadcastAt >= minRetryAgeMs))
    .sort((a, b) => a.updatedAt - b.updatedAt)
    .slice(0, limit);

  const results: Array<{ payment: StoredOutboundSolanaMeshPayment; recipients: number }> = [];
  for (const row of entries) {
    results.push(await retryOutboundSolanaMeshPayment({
      primaryAccount: input.primaryAccount,
      paymentId: row.envelope.paymentId,
    }));
  }
  return results;
}
