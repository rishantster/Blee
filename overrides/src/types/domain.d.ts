import type { Address, Hex } from 'viem';

// Type-only shim for overrides/src/lib/payments.ts. The real runtime definition
// remains src/types/domain.ts from the reconstructed Blee source snapshot.
export type TransferAuthorization = {
  from: Address;
  to: Address;
  value: string;
  validAfter: string;
  validBefore: string;
  nonce: Hex;
  signature: Hex;
};
