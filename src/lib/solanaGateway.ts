export const BLEE_SOLANA_GATEWAY = 'https://rpc.blee.app' as const;

const DEFAULT_TIMEOUT_MS = 8_000;
const MAX_SIGNED_TRANSACTION_B64_CHARS = 48_000;
const BASE58_RE = /^[1-9A-HJ-NP-Za-km-z]+$/;

export type SolanaGatewayErrorCode =
  | 'SOL_GATEWAY_UNAVAILABLE'
  | 'SOL_RPC_UNAVAILABLE'
  | 'SOL_RPC_RATE_LIMITED'
  | 'SOL_INVALID_ADDRESS'
  | 'SOL_INVALID_SIGNATURE'
  | 'SOL_INVALID_TRANSACTION'
  | 'SOL_TRANSACTION_SHAPE_REJECTED'
  | 'SOL_TRANSACTION_TOO_LARGE'
  | 'SOL_PAYMENT_ID_CONFLICT'
  | 'SOL_DUPLICATE_TRANSACTION'
  | 'SOL_NONCE_INVALID'
  | 'SOL_PROVIDER_REJECTED_TRANSACTION'
  | 'SOL_TRANSACTION_NOT_FOUND'
  | 'SOL_INTERNAL_ERROR';

export class SolanaGatewayError extends Error {
  readonly code: SolanaGatewayErrorCode;
  readonly status?: number;

  constructor(code: SolanaGatewayErrorCode, message: string, status?: number) {
    super(message);
    this.name = 'SolanaGatewayError';
    this.code = code;
    this.status = status;
  }
}

type GatewayErrorBody = {
  error?: SolanaGatewayErrorCode | string;
  message?: string;
  requestId?: string;
};

async function gatewayFetch<T>(path: string, init?: RequestInit, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${BLEE_SOLANA_GATEWAY}${path}`, {
      ...init,
      headers: {
        accept: 'application/json',
        ...(init?.body ? { 'content-type': 'application/json' } : {}),
        ...(init?.headers || {}),
      },
      signal: controller.signal,
      cache: 'no-store',
    });

    let body: unknown = null;
    try { body = await response.json(); } catch {}

    if (!response.ok) {
      const errorBody = (body || {}) as GatewayErrorBody;
      const code = normalizeErrorCode(errorBody.error, response.status);
      throw new SolanaGatewayError(code, errorBody.message || code, response.status);
    }

    return body as T;
  } catch (error) {
    if (error instanceof SolanaGatewayError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new SolanaGatewayError('SOL_GATEWAY_UNAVAILABLE', 'Solana gateway request timed out');
    }
    throw new SolanaGatewayError('SOL_GATEWAY_UNAVAILABLE', 'Solana gateway is unavailable');
  } finally {
    clearTimeout(timeout);
  }
}

function normalizeErrorCode(value: unknown, status: number): SolanaGatewayErrorCode {
  const known = new Set<SolanaGatewayErrorCode>([
    'SOL_GATEWAY_UNAVAILABLE',
    'SOL_RPC_UNAVAILABLE',
    'SOL_RPC_RATE_LIMITED',
    'SOL_INVALID_ADDRESS',
    'SOL_INVALID_SIGNATURE',
    'SOL_INVALID_TRANSACTION',
    'SOL_TRANSACTION_SHAPE_REJECTED',
    'SOL_TRANSACTION_TOO_LARGE',
    'SOL_PAYMENT_ID_CONFLICT',
    'SOL_DUPLICATE_TRANSACTION',
    'SOL_NONCE_INVALID',
    'SOL_PROVIDER_REJECTED_TRANSACTION',
    'SOL_TRANSACTION_NOT_FOUND',
    'SOL_INTERNAL_ERROR',
  ]);
  if (typeof value === 'string' && known.has(value as SolanaGatewayErrorCode)) {
    return value as SolanaGatewayErrorCode;
  }
  if (status === 429) return 'SOL_RPC_RATE_LIMITED';
  if (status >= 500) return 'SOL_GATEWAY_UNAVAILABLE';
  return 'SOL_INTERNAL_ERROR';
}

export function looksLikeSolanaPublicKey(value: string): boolean {
  const clean = value.trim();
  return clean.length >= 32 && clean.length <= 44 && BASE58_RE.test(clean);
}

export function looksLikeSolanaSignature(value: string): boolean {
  const clean = value.trim();
  return clean.length >= 80 && clean.length <= 88 && BASE58_RE.test(clean);
}

export type SolanaHealth = {
  ok: true;
  cluster: 'mainnet-beta';
};

export type SolanaBalance = {
  address: string;
  lamports: string;
  commitment: string;
};

export type SolanaNonceState = {
  address: string;
  authority: string;
  nonce: string;
  lamportsPerSignature: string;
  lamports: string;
  valid: boolean;
};

export type SolanaSignatureStatus = {
  signature: string;
  confirmationStatus?: 'processed' | 'confirmed' | 'finalized' | null;
  err?: unknown;
  slot?: number | string | null;
};

export type SolanaTransactionSummary = {
  signature: string;
  sender?: string;
  recipient?: string;
  amountLamports?: string;
  confirmationStatus?: string | null;
  slot?: number | string | null;
};

export async function getSolanaHealth(): Promise<SolanaHealth> {
  return gatewayFetch<SolanaHealth>('/v1/solana/health');
}

export async function getSolBalance(address: string): Promise<bigint> {
  if (!looksLikeSolanaPublicKey(address)) {
    throw new SolanaGatewayError('SOL_INVALID_ADDRESS', 'Invalid Solana address');
  }
  const result = await gatewayFetch<SolanaBalance>(`/v1/solana/balance/${encodeURIComponent(address.trim())}`);
  try { return BigInt(result.lamports); } catch {
    throw new SolanaGatewayError('SOL_INTERNAL_ERROR', 'Gateway returned an invalid SOL balance');
  }
}

export async function getSolanaNonceAccount(address: string): Promise<SolanaNonceState> {
  if (!looksLikeSolanaPublicKey(address)) {
    throw new SolanaGatewayError('SOL_INVALID_ADDRESS', 'Invalid Solana nonce account');
  }
  return gatewayFetch<SolanaNonceState>('/v1/solana/nonce-account', {
    method: 'POST',
    body: JSON.stringify({ address: address.trim() }),
  });
}

export async function getSolanaRentExemption(space: number): Promise<bigint> {
  if (!Number.isInteger(space) || space < 0 || space > 10_240) {
    throw new SolanaGatewayError('SOL_INVALID_TRANSACTION', 'Invalid Solana account size');
  }
  const result = await gatewayFetch<{ lamports: string }>('/v1/solana/rent-exemption', {
    method: 'POST',
    body: JSON.stringify({ space }),
  });
  try { return BigInt(result.lamports); } catch {
    throw new SolanaGatewayError('SOL_INTERNAL_ERROR', 'Gateway returned an invalid rent value');
  }
}

export async function getSolanaSignatureStatuses(signatures: string[]): Promise<SolanaSignatureStatus[]> {
  if (!Array.isArray(signatures) || signatures.length < 1 || signatures.length > 20 || signatures.some((value) => !looksLikeSolanaSignature(value))) {
    throw new SolanaGatewayError('SOL_INVALID_SIGNATURE', 'Invalid Solana transaction signature list');
  }
  const result = await gatewayFetch<{ statuses: SolanaSignatureStatus[] }>('/v1/solana/signature-status', {
    method: 'POST',
    body: JSON.stringify({ signatures }),
  });
  return Array.isArray(result.statuses) ? result.statuses : [];
}

export async function getSolanaTransaction(signature: string): Promise<SolanaTransactionSummary> {
  if (!looksLikeSolanaSignature(signature)) {
    throw new SolanaGatewayError('SOL_INVALID_SIGNATURE', 'Invalid Solana transaction signature');
  }
  return gatewayFetch<SolanaTransactionSummary>('/v1/solana/transaction', {
    method: 'POST',
    body: JSON.stringify({ signature: signature.trim() }),
  });
}

export async function sendSignedSolanaTransaction(input: {
  paymentId: string;
  signedTransactionBase64: string;
}): Promise<{ signature: string; duplicate?: boolean }> {
  const paymentId = input.paymentId.trim();
  const signedTransactionBase64 = input.signedTransactionBase64.trim();
  if (!paymentId || paymentId.length > 160) {
    throw new SolanaGatewayError('SOL_INVALID_TRANSACTION', 'Invalid Blee payment ID');
  }
  if (!signedTransactionBase64 || signedTransactionBase64.length > MAX_SIGNED_TRANSACTION_B64_CHARS) {
    throw new SolanaGatewayError('SOL_TRANSACTION_TOO_LARGE', 'Signed Solana transaction is too large');
  }
  return gatewayFetch<{ signature: string; duplicate?: boolean }>('/v1/solana/send', {
    method: 'POST',
    body: JSON.stringify({ rail: 'solana-sol', paymentId, signedTransactionBase64 }),
  }, 15_000);
}
