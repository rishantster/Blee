import type { Address, Hex } from 'viem';

export type TransferAuthorization = {
  from: Address;
  to: Address;
  value: string;
  validAfter: string;
  validBefore: string;
  nonce: Hex;
  signature: Hex;
};

export type PaymentState = 'verification-pending' | 'queued-local' | 'mesh-broadcast' | 'mesh-delivered' | 'submitted' | 'settled' | 'failed';

export type PaymentRecord = {
  id: string;
  direction: 'out' | 'in' | 'relay';
  counterparty: Address;
  counterpartyAlias?: string;
  counterpartyAvatar?: string;
  senderName?: string;
  senderAvatar?: string;
  amount: string;
  createdAt: number;
  updatedAt?: number;
  state: PaymentState;
  route: 'arc-direct' | 'ble-mesh' | 'local-queue';
  authorization?: TransferAuthorization;
  txHash?: Hex;
  error?: string;
  attempts?: number;
  lastAttemptAt?: number;
  nextRetryAt?: number;
  durablyReceivedAt?: number;
  submittedAt?: number;
  settledAt?: number;
};

export type MeshPeer = {
  transport?: 'lan' | 'ble';
  transportId: string;
  address: Address;
  alias: string;
  hops: number;
  rssi?: number;
  lastSeen: number;
  arcReachable?: boolean;
};

export type MeshPacketType = 'hello' | 'payment' | 'ack' | 'receipt';

export type MeshPacket = {
  version: 1;
  id: string;
  type: MeshPacketType;
  origin: Address;
  createdAt: number;
  ttl: number;
  hops: number;
  payload: unknown;
  signature: Hex;
};
