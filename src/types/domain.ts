import type { Address, Hex } from 'viem';

export type BleeAssetId = 'usdc' | 'sol';
export type BleeRailId = 'arc-usdc' | 'solana-sol';
export type BleeNetworkId = 'arc-testnet' | 'arc-mainnet' | 'solana-mainnet';
export type BleeEnvironment = 'testnet' | 'mainnet';
export type BleeChainFamily = 'evm' | 'solana';

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
  /**
   * Network identity is persisted with the payment. These remain optional at
   * the TypeScript boundary only for backwards compatibility with 2.7.1 rows;
   * persistence canonicalizes missing legacy metadata to Arc Testnet.
   */
  railId?: BleeRailId;
  networkId?: BleeNetworkId;
  assetId?: BleeAssetId;
  assetSymbol?: 'USDC' | 'SOL';
  environment?: BleeEnvironment;
  chainFamily?: BleeChainFamily;
  authorization?: TransferAuthorization;
  /**
   * Exact EIP-3009 authorization retained for audit/history when this payment
   * belongs to an Arc network other than the release-selected settlement
   * network. Persistence writes it back as `authorization`, but runtime
   * settlement code never sees it through the active `authorization` field.
   */
  archivedAuthorization?: TransferAuthorization;
  txHash?: Hex;
  error?: string;
  attempts?: number;
  lastAttemptAt?: number;
  nextRetryAt?: number;
  durablyReceivedAt?: number;
  submittedAt?: number;
  settledAt?: number;
};

export type MeshSolanaCapabilityV1 = {
  networkId: 'solana-mainnet';
  address: string;
  proofBase64: string;
};

export type MeshCapabilitiesV1 = {
  version: 1;
  rails: BleeRailId[];
  solana?: MeshSolanaCapabilityV1;
};

export type SolanaMeshPaymentEnvelopeV1 = {
  version: 1;
  railId: 'solana-sol';
  networkId: 'solana-mainnet';
  paymentId: string;
  senderSolana: string;
  recipientEvm: Address;
  recipientSolana: string;
  amountLamports: string;
  nonceAccountAddress: string;
  nonce: string;
  signedTransactionBase64: string;
  signedTransactionSha256: string;
  senderCapabilities: MeshCapabilitiesV1;
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
  rails?: BleeRailId[];
  solanaAddress?: string;
  capabilitiesVerified?: boolean;
};

export type MeshPacketType = 'hello' | 'payment' | 'ack' | 'receipt' | 'sol-payment';

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
