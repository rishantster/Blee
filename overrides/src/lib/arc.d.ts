// Type-only shim for the human-readable override tree.
//
// The build copies overrides/src/lib/payments.ts into src/lib/payments.ts, where
// the real src/lib/arc.ts is used at runtime. This declaration exists only so
// `tsc --noEmit` can also parse the standalone override tree.

export const ARC_RPC: string;
export const ARC_USDC: `0x${string}`;
export const ARC_USDC_DECIMALS: number;
export const USDC_EIP712_NAME: string;
export const USDC_EIP712_VERSION: string;
export const arcTestnet: any;
export const transferAuthorizationTypes: any;

export const usdcAbi: readonly [
  {
    readonly type: 'function';
    readonly name: 'balanceOf';
    readonly stateMutability: 'view';
    readonly inputs: readonly [{ readonly name: 'account'; readonly type: 'address' }];
    readonly outputs: readonly [{ readonly name: ''; readonly type: 'uint256' }];
  },
  {
    readonly type: 'function';
    readonly name: 'transferWithAuthorization';
    readonly stateMutability: 'nonpayable';
    readonly inputs: readonly [
      { readonly name: 'from'; readonly type: 'address' },
      { readonly name: 'to'; readonly type: 'address' },
      { readonly name: 'value'; readonly type: 'uint256' },
      { readonly name: 'validAfter'; readonly type: 'uint256' },
      { readonly name: 'validBefore'; readonly type: 'uint256' },
      { readonly name: 'nonce'; readonly type: 'bytes32' },
      { readonly name: 'signature'; readonly type: 'bytes' }
    ];
    readonly outputs: readonly [];
  },
  {
    readonly type: 'function';
    readonly name: 'authorizationState';
    readonly stateMutability: 'view';
    readonly inputs: readonly [
      { readonly name: 'authorizer'; readonly type: 'address' },
      { readonly name: 'nonce'; readonly type: 'bytes32' }
    ];
    readonly outputs: readonly [{ readonly name: ''; readonly type: 'bool' }];
  },
  {
    readonly type: 'event';
    readonly name: 'AuthorizationUsed';
    readonly anonymous: false;
    readonly inputs: readonly [
      { readonly name: 'authorizer'; readonly type: 'address'; readonly indexed: true },
      { readonly name: 'nonce'; readonly type: 'bytes32'; readonly indexed: true }
    ];
  }
];
