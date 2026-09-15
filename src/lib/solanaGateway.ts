const DEFAULT_TIMEOUT_MS = 8_000;
const SEND_TIMEOUT_MS = 15_000;
const MAX_SIGNED_TRANSACTION_B64_CHARS = 48_000;
const MAX_WIRE_TRANSACTION_BYTES = 1232;
const BASE58_RE = /^[1-9A-HJ-NP-Za-km-z]+$/;
const BASE58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
const SYSTEM_PROGRAM_ADDRESS = '11111111111111111111111111111111';

/**
 * BLEE_HELIUS_SECURE_RPC_V1
 *
 * Option A: the APK talks directly to a Helius Secure RPC endpoint. Secure RPC
 * URLs are masked by Helius for frontend/mobile use and contain no API-key
 * query parameter. The endpoint is supplied at build time through a public Next
 * environment variable, so no account-specific URL is committed to the repo.
 *
 * The historical file/class names remain temporarily for import compatibility;
 * this module no longer routes through a Blee gateway or generic RPC proxy.
 */
export const BLEE_HELIUS_SECURE_RPC_ENV = 'NEXT_PUBLIC_BLEE_HELIUS_SECURE_RPC' as const;

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

/** @deprecated Name retained while existing settlement imports migrate. */
export class SolanaGatewayError extends Error {
  readonly code: SolanaGatewayErrorCode;
  readonly status?: number;
  readonly rpcCode?: number;

  constructor(code: SolanaGatewayErrorCode, message: string, status?: number, rpcCode?: number) {
    super(message);
    this.name = 'SolanaGatewayError';
    this.code = code;
    this.status = status;
    this.rpcCode = rpcCode;
  }
}

type JsonRpcError = {
  code?: number;
  message?: string;
  data?: unknown;
};

type JsonRpcEnvelope<T> = {
  jsonrpc?: string;
  id?: number | string;
  result?: T;
  error?: JsonRpcError;
};

function configuredSecureRpcUrl(): string {
  const raw = String(process.env.NEXT_PUBLIC_BLEE_HELIUS_SECURE_RPC || '').trim();
  if (!raw) {
    throw new SolanaGatewayError(
      'SOL_RPC_UNAVAILABLE',
      `${BLEE_HELIUS_SECURE_RPC_ENV} is not configured for this Blee build`,
    );
  }
  let url: URL;
  try { url = new URL(raw); } catch {
    throw new SolanaGatewayError('SOL_RPC_UNAVAILABLE', 'Blee Helius Secure RPC URL is invalid');
  }
  const hostname = url.hostname.toLowerCase();
  if (
    url.protocol !== 'https:'
    || url.username
    || url.password
    || url.search
    || url.hash
    || !hostname.endsWith('-fast-mainnet.helius-rpc.com')
    || hostname === 'fast-mainnet.helius-rpc.com'
    || hostname === 'sender.helius-rpc.com'
  ) {
    throw new SolanaGatewayError(
      'SOL_RPC_UNAVAILABLE',
      'Blee requires a Helius Secure Mainnet RPC URL with no API key, query string or Sender endpoint',
    );
  }
  return url.toString().replace(/\/$/, '');
}

export function getConfiguredHeliusSecureRpcUrl(): string {
  return configuredSecureRpcUrl();
}

function normalizeRpcError(error: JsonRpcError | undefined, status?: number): SolanaGatewayError {
  const message = String(error?.message || `Solana RPC request failed${status ? ` (${status})` : ''}`).trim();
  if (status === 429 || /rate.?limit|too many requests/i.test(message)) {
    return new SolanaGatewayError('SOL_RPC_RATE_LIMITED', 'Helius Secure RPC rate limit reached', status, error?.code);
  }
  if (status && status >= 500) {
    return new SolanaGatewayError('SOL_RPC_UNAVAILABLE', 'Helius Secure RPC is unavailable', status, error?.code);
  }
  if (/invalid param|invalid request|invalid transaction|failed to sanitize/i.test(message)) {
    return new SolanaGatewayError('SOL_INVALID_TRANSACTION', message, status, error?.code);
  }
  if (/blockhash not found|nonce/i.test(message)) {
    return new SolanaGatewayError('SOL_NONCE_INVALID', message, status, error?.code);
  }
  return new SolanaGatewayError('SOL_PROVIDER_REJECTED_TRANSACTION', message, status, error?.code);
}

async function rpcCall<T>(method: string, params: unknown[] = [], timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const endpoint = configuredSecureRpcUrl();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        accept: 'application/json',
        'content-type': 'application/json',
      },
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
      signal: controller.signal,
      cache: 'no-store',
    });

    let body: JsonRpcEnvelope<T> | null = null;
    try { body = await response.json() as JsonRpcEnvelope<T>; } catch {}

    if (!response.ok) throw normalizeRpcError(body?.error, response.status);
    if (!body || body.error) throw normalizeRpcError(body?.error, response.status);
    if (!Object.prototype.hasOwnProperty.call(body, 'result')) {
      throw new SolanaGatewayError('SOL_INTERNAL_ERROR', 'Helius Secure RPC returned no result');
    }
    return body.result as T;
  } catch (error) {
    if (error instanceof SolanaGatewayError) throw error;
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new SolanaGatewayError('SOL_RPC_UNAVAILABLE', 'Helius Secure RPC request timed out');
    }
    throw new SolanaGatewayError('SOL_RPC_UNAVAILABLE', 'Helius Secure RPC is unavailable');
  } finally {
    clearTimeout(timeout);
  }
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

export type SolanaLatestBlockhash = {
  blockhash: string;
  lastValidBlockHeight: bigint;
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

function safeUnsignedInteger(value: unknown, label: string): bigint {
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value) || value < 0) {
      throw new SolanaGatewayError('SOL_INTERNAL_ERROR', `${label} is outside the safe JSON integer range`);
    }
    return BigInt(value);
  }
  try {
    const parsed = BigInt(String(value));
    if (parsed < 0n) throw new Error('negative');
    return parsed;
  } catch {
    throw new SolanaGatewayError('SOL_INTERNAL_ERROR', `${label} is invalid`);
  }
}

function decodeBase64Wire(value: string): Uint8Array {
  const clean = value.trim();
  if (!clean || clean.length > MAX_SIGNED_TRANSACTION_B64_CHARS) {
    throw new SolanaGatewayError('SOL_TRANSACTION_TOO_LARGE', 'Signed Solana transaction is too large');
  }
  try {
    const binary = atob(clean);
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    if (bytes.byteLength <= 64 || bytes.byteLength > MAX_WIRE_TRANSACTION_BYTES) {
      throw new SolanaGatewayError('SOL_INVALID_TRANSACTION', 'Signed Solana transaction has an invalid wire size');
    }
    return bytes;
  } catch (error) {
    if (error instanceof SolanaGatewayError) throw error;
    throw new SolanaGatewayError('SOL_INVALID_TRANSACTION', 'Signed Solana transaction is not valid base64');
  }
}

function readShortVec(bytes: Uint8Array, offset = 0): { value: number; next: number } {
  let value = 0;
  let shift = 0;
  let cursor = offset;
  for (let count = 0; count < 3; count += 1) {
    const byte = bytes[cursor++];
    if (byte === undefined) throw new SolanaGatewayError('SOL_INVALID_TRANSACTION', 'Signed Solana transaction is truncated');
    value |= (byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) return { value, next: cursor };
    shift += 7;
  }
  throw new SolanaGatewayError('SOL_INVALID_TRANSACTION', 'Signed Solana transaction signature count is invalid');
}

function base58Encode(bytes: Uint8Array): string {
  let leadingZeroes = 0;
  while (leadingZeroes < bytes.length && bytes[leadingZeroes] === 0) leadingZeroes += 1;
  let value = 0n;
  for (const byte of bytes) value = (value << 8n) | BigInt(byte);
  let encoded = '';
  while (value > 0n) {
    const remainder = Number(value % 58n);
    encoded = BASE58_ALPHABET[remainder] + encoded;
    value /= 58n;
  }
  return '1'.repeat(leadingZeroes) + (encoded || (leadingZeroes ? '' : '1'));
}

/** Solana transaction id is the first signer signature in the wire transaction. */
function signatureFromSignedWire(value: string): string {
  const bytes = decodeBase64Wire(value);
  const { value: signatureCount, next } = readShortVec(bytes);
  if (signatureCount < 1 || signatureCount > 16) {
    throw new SolanaGatewayError('SOL_INVALID_TRANSACTION', 'Signed Solana transaction has an invalid signer count');
  }
  const end = next + signatureCount * 64;
  if (end >= bytes.length) throw new SolanaGatewayError('SOL_INVALID_TRANSACTION', 'Signed Solana transaction signatures are truncated');
  const signature = base58Encode(bytes.slice(next, next + 64));
  if (!looksLikeSolanaSignature(signature)) {
    throw new SolanaGatewayError('SOL_INVALID_SIGNATURE', 'Signed Solana transaction contains an invalid primary signature');
  }
  return signature;
}

export async function getSolanaHealth(): Promise<SolanaHealth> {
  const result = await rpcCall<string>('getHealth');
  if (result !== 'ok') throw new SolanaGatewayError('SOL_RPC_UNAVAILABLE', 'Helius Secure RPC health check failed');
  return { ok: true, cluster: 'mainnet-beta' };
}

export async function getSolBalance(address: string): Promise<bigint> {
  const clean = address.trim();
  if (!looksLikeSolanaPublicKey(clean)) throw new SolanaGatewayError('SOL_INVALID_ADDRESS', 'Invalid Solana address');
  const result = await rpcCall<{ value?: number | string }>('getBalance', [clean, { commitment: 'confirmed' }]);
  return safeUnsignedInteger(result?.value, 'SOL balance');
}

export async function getSolanaNonceAccount(address: string): Promise<SolanaNonceState> {
  const clean = address.trim();
  if (!looksLikeSolanaPublicKey(clean)) throw new SolanaGatewayError('SOL_INVALID_ADDRESS', 'Invalid Solana nonce account');
  const result = await rpcCall<{ value?: unknown }>('getAccountInfo', [clean, { encoding: 'jsonParsed', commitment: 'confirmed' }]);
  const value = result?.value as any;
  if (!value) {
    return { address: clean, authority: '', nonce: '', lamportsPerSignature: '0', lamports: '0', valid: false };
  }
  if (String(value.owner || '') !== SYSTEM_PROGRAM_ADDRESS || value.executable === true) {
    return { address: clean, authority: '', nonce: '', lamportsPerSignature: '0', lamports: safeUnsignedInteger(value.lamports, 'nonce balance').toString(), valid: false };
  }

  const modernInfo = value?.data?.program === 'nonce' && value?.data?.parsed?.type === 'initialized'
    ? value.data.parsed.info
    : null;
  const legacyInfo = value?.data?.nonce?.initialized || null;
  const info = modernInfo || legacyInfo;
  const authority = String(info?.authority || '').trim();
  const nonce = String(info?.blockhash || info?.nonce || '').trim();
  const fee = info?.feeCalculator?.lamportsPerSignature;
  if (!looksLikeSolanaPublicKey(authority) || !looksLikeSolanaPublicKey(nonce)) {
    return {
      address: clean,
      authority,
      nonce,
      lamportsPerSignature: '0',
      lamports: safeUnsignedInteger(value.lamports, 'nonce balance').toString(),
      valid: false,
    };
  }
  return {
    address: clean,
    authority,
    nonce,
    lamportsPerSignature: safeUnsignedInteger(fee, 'nonce fee').toString(),
    lamports: safeUnsignedInteger(value.lamports, 'nonce balance').toString(),
    valid: true,
  };
}

export async function getSolanaRentExemption(space: number): Promise<bigint> {
  if (!Number.isInteger(space) || space < 0 || space > 10_240) {
    throw new SolanaGatewayError('SOL_INVALID_TRANSACTION', 'Invalid Solana account size');
  }
  const result = await rpcCall<number | string>('getMinimumBalanceForRentExemption', [space, { commitment: 'confirmed' }]);
  return safeUnsignedInteger(result, 'rent exemption');
}

export async function getSolanaLatestBlockhash(): Promise<SolanaLatestBlockhash> {
  const result = await rpcCall<{ value?: { blockhash?: string; lastValidBlockHeight?: number | string } }>('getLatestBlockhash', [{ commitment: 'confirmed' }]);
  const blockhash = String(result?.value?.blockhash || '').trim();
  if (!looksLikeSolanaPublicKey(blockhash)) throw new SolanaGatewayError('SOL_INTERNAL_ERROR', 'RPC returned an invalid Solana blockhash');
  const lastValidBlockHeight = safeUnsignedInteger(result?.value?.lastValidBlockHeight, 'last valid block height');
  if (lastValidBlockHeight <= 0n) throw new SolanaGatewayError('SOL_INTERNAL_ERROR', 'RPC returned an invalid block height');
  return { blockhash, lastValidBlockHeight };
}

export async function getSolanaSignatureStatuses(signatures: string[]): Promise<SolanaSignatureStatus[]> {
  if (!Array.isArray(signatures) || signatures.length < 1 || signatures.length > 20 || signatures.some((value) => !looksLikeSolanaSignature(value))) {
    throw new SolanaGatewayError('SOL_INVALID_SIGNATURE', 'Invalid Solana transaction signature list');
  }
  const result = await rpcCall<{ value?: Array<any | null> }>('getSignatureStatuses', [signatures, { searchTransactionHistory: true }]);
  const values = Array.isArray(result?.value) ? result.value : [];
  const rows: SolanaSignatureStatus[] = [];
  values.forEach((status, index) => {
    if (!status) return;
    rows.push({
      signature: signatures[index],
      confirmationStatus: status.confirmationStatus ?? null,
      err: status.err,
      slot: status.slot ?? null,
    });
  });
  return rows;
}

function parsedInstruction(input: unknown): { program: string; programId: string; type: string; info: Record<string, unknown> } {
  const row = input as any;
  const program = String(row?.program || '');
  const programId = String(row?.programId || '');
  const type = String(row?.parsed?.type || '');
  const info = row?.parsed?.info;
  if (!program || !programId || !type || !info || typeof info !== 'object') {
    throw new SolanaGatewayError('SOL_TRANSACTION_SHAPE_REJECTED', 'Solana transaction contains an unparsed instruction');
  }
  return { program, programId, type, info };
}

/**
 * Independently verifies the settled Blee payment shape from Solana RPC data.
 * The direct provider never gets to redefine Blee semantics: only exactly
 * AdvanceNonceAccount + native SOL Transfer is accepted, with no inner calls.
 */
export async function getSolanaTransaction(signature: string): Promise<SolanaTransactionSummary> {
  const clean = signature.trim();
  if (!looksLikeSolanaSignature(clean)) throw new SolanaGatewayError('SOL_INVALID_SIGNATURE', 'Invalid Solana transaction signature');
  const result = await rpcCall<any | null>('getTransaction', [clean, {
    encoding: 'jsonParsed',
    commitment: 'confirmed',
    maxSupportedTransactionVersion: 0,
  }]);
  if (!result) throw new SolanaGatewayError('SOL_TRANSACTION_NOT_FOUND', 'Solana transaction was not found');

  const signatures = result?.transaction?.signatures;
  const message = result?.transaction?.message;
  const keys = message?.accountKeys;
  const instructions = message?.instructions;
  if (!Array.isArray(signatures) || signatures[0] !== clean || !Array.isArray(keys) || !Array.isArray(instructions)) {
    throw new SolanaGatewayError('SOL_TRANSACTION_SHAPE_REJECTED', 'Solana transaction response has an invalid shape');
  }
  if (result?.meta?.err) throw new SolanaGatewayError('SOL_PROVIDER_REJECTED_TRANSACTION', 'Solana transaction failed on-chain');
  if (Array.isArray(result?.meta?.innerInstructions) && result.meta.innerInstructions.length > 0) {
    throw new SolanaGatewayError('SOL_TRANSACTION_SHAPE_REJECTED', 'Blee SOL payment must not contain inner instructions');
  }
  if (instructions.length !== 2) {
    throw new SolanaGatewayError('SOL_TRANSACTION_SHAPE_REJECTED', 'Blee SOL payment must contain exactly two instructions');
  }

  const feePayer = String(keys[0]?.pubkey || keys[0] || '').trim();
  if (!looksLikeSolanaPublicKey(feePayer)) throw new SolanaGatewayError('SOL_TRANSACTION_SHAPE_REJECTED', 'Blee SOL payment fee payer is invalid');
  const advance = parsedInstruction(instructions[0]);
  const transfer = parsedInstruction(instructions[1]);
  if (
    advance.program !== 'system'
    || advance.programId !== SYSTEM_PROGRAM_ADDRESS
    || advance.type !== 'advanceNonce'
    || String(advance.info.nonceAuthority || '').trim() !== feePayer
  ) {
    throw new SolanaGatewayError('SOL_TRANSACTION_SHAPE_REJECTED', 'Blee SOL instruction 0 is not the expected durable nonce advance');
  }
  if (
    transfer.program !== 'system'
    || transfer.programId !== SYSTEM_PROGRAM_ADDRESS
    || transfer.type !== 'transfer'
    || String(transfer.info.source || '').trim() !== feePayer
  ) {
    throw new SolanaGatewayError('SOL_TRANSACTION_SHAPE_REJECTED', 'Blee SOL instruction 1 is not the expected native transfer');
  }
  const recipient = String(transfer.info.destination || '').trim();
  if (!looksLikeSolanaPublicKey(recipient)) throw new SolanaGatewayError('SOL_TRANSACTION_SHAPE_REJECTED', 'Blee SOL recipient is invalid');
  const amountLamports = safeUnsignedInteger(transfer.info.lamports, 'SOL transfer amount');
  if (amountLamports <= 0n) throw new SolanaGatewayError('SOL_TRANSACTION_SHAPE_REJECTED', 'Blee SOL transfer amount is invalid');

  return {
    signature: clean,
    sender: feePayer,
    recipient,
    amountLamports: amountLamports.toString(),
    confirmationStatus: result?.meta?.err == null ? 'confirmed' : null,
    slot: result?.slot ?? null,
  };
}

async function submitExactSignedWire(signedTransactionBase64: string): Promise<{ signature: string; duplicate?: boolean }> {
  const expectedSignature = signatureFromSignedWire(signedTransactionBase64);
  try {
    const returned = String(await rpcCall<string>('sendTransaction', [signedTransactionBase64, {
      encoding: 'base64',
      skipPreflight: false,
      preflightCommitment: 'confirmed',
      maxRetries: 3,
    }], SEND_TIMEOUT_MS)).trim();
    if (!looksLikeSolanaSignature(returned) || returned !== expectedSignature) {
      throw new SolanaGatewayError('SOL_INVALID_SIGNATURE', 'RPC returned a signature that does not match the exact signed transaction bytes');
    }
    return { signature: returned };
  } catch (error) {
    if (error instanceof SolanaGatewayError && /already (?:been )?processed/i.test(error.message)) {
      return { signature: expectedSignature, duplicate: true };
    }
    throw error;
  }
}

export async function sendSignedSolanaTransaction(input: {
  paymentId: string;
  signedTransactionBase64: string;
}): Promise<{ signature: string; duplicate?: boolean }> {
  const paymentId = input.paymentId.trim();
  if (!paymentId || paymentId.length > 160) throw new SolanaGatewayError('SOL_INVALID_TRANSACTION', 'Invalid Blee payment ID');
  // paymentId remains the durable local idempotency key. Solana itself dedupes
  // replays because these are the same exact signed bytes/signature.
  return submitExactSignedWire(input.signedTransactionBase64.trim());
}

/**
 * Nonce-account setup is already locally constrained to exactly CreateAccount +
 * InitializeNonceAccount before signing. Direct RPC receives only those stored,
 * exact signed bytes and cannot mutate or re-sign them.
 */
export async function sendSignedSolanaNonceSetupTransaction(input: {
  setupId: string;
  nonceAccountAddress: string;
  signedTransactionBase64: string;
}): Promise<{ signature: string; duplicate?: boolean }> {
  const setupId = input.setupId.trim();
  const nonceAccountAddress = input.nonceAccountAddress.trim();
  if (!setupId || setupId.length > 160) throw new SolanaGatewayError('SOL_INVALID_TRANSACTION', 'Invalid Solana nonce setup ID');
  if (!looksLikeSolanaPublicKey(nonceAccountAddress)) throw new SolanaGatewayError('SOL_INVALID_ADDRESS', 'Invalid Solana nonce account');
  return submitExactSignedWire(input.signedTransactionBase64.trim());
}
