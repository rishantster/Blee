// Type-only shim for the human-readable override tree.
//
// The build copies overrides/src/lib/payments.ts into src/lib/payments.ts, where
// the real src/lib/arc.ts is used at runtime. This declaration exists only so
// `tsc --noEmit` can also parse the standalone override tree without treating
// the source snapshot as a second package.

export const ARC_RPC: string;
export const ARC_USDC: `0x${string}`;
export const ARC_USDC_DECIMALS: number;
export const USDC_EIP712_NAME: string;
export const USDC_EIP712_VERSION: string;
export const arcTestnet: any;
export const transferAuthorizationTypes: any;
export const usdcAbi: any;
