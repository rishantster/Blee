import {
  appendTransactionMessageInstructions,
  createSignerFromKeyPair,
  createTransactionMessage,
  generateKeyPairSigner,
  getBase64EncodedWireTransaction,
  isInstructionForProgram,
  isInstructionWithAccounts,
  isInstructionWithData,
  lamports,
  pipe,
  setTransactionMessageFeePayerSigner,
  setTransactionMessageLifetimeUsingBlockhash,
  signTransactionMessageWithSigners,
  type Blockhash,
  type Instruction,
} from '@solana/kit';
import {
  getCreateAccountInstruction,
  getInitializeNonceAccountInstruction,
  identifySystemInstruction,
  parseCreateAccountInstruction,
  parseInitializeNonceAccountInstruction,
  SYSTEM_PROGRAM_ADDRESS,
  SystemInstruction,
} from '@solana-program/system';
import { BleeStore } from './bleeStore';
import {
  getSolanaLatestBlockhash,
  getSolanaRentExemption,
  looksLikeSolanaPublicKey,
  sendSignedSolanaNonceSetupTransaction,
} from './solanaGateway';
import {
  registerPreparedSolanaNonceSlot,
  SOLANA_NONCE_ACCOUNT_SPACE,
  type SolanaNonceSlot,
} from './solanaNoncePool';
import type { SolanaLocalSigner } from './solanaVault';

export const SOLANA_NONCE_PREPARATION_KEY_PREFIX = 'solana.nonce-preparation.v1';
const MAX_NONCE_SLOTS = 16;
const MAX_SIGNED_TRANSACTION_B64_CHARS = 48_000;
const RECENT_BLOCKHASHES_SYSVAR = 'SysvarRecentB1ockHashes11111111111111111111';
const RENT_SYSVAR = 'SysvarRent111111111111111111111111111111111';

type SolanaNoncePreparationState = 'signed' | 'submitted' | 'confirmed';

export type SolanaNoncePreparation = Readonly<{
  version: 1;
  networkId: 'solana-mainnet';
  authority: string;
  index: number;
  setupId: string;
  nonceAccountAddress: string;
  rentLamports: string;
  blockhash: string;
  lastValidBlockHeight: string;
  signedTransactionBase64: string;
  signedTransactionSha256: string;
  state: SolanaNoncePreparationState;
  signature?: string;
  createdAt: number;
  submittedAt?: number;
  confirmedAt?: number;
}>;

function assertIndex(index: number): number {
  if (!Number.isInteger(index) || index < 0 || index >= MAX_NONCE_SLOTS) {
    throw new Error('Solana nonce slot index is invalid');
  }
  return index;
}

function preparationKey(authority: string, index: number): string {
  return `${SOLANA_NONCE_PREPARATION_KEY_PREFIX}.${authority}.${assertIndex(index)}`;
}

async function ensureStore(): Promise<void> {
  const result = await BleeStore.init();
  if (!result.ready) throw new Error('Blee payment storage is unavailable');
}

function assertPreparation(input: unknown, authority: string, index: number): SolanaNoncePreparation {
  const value = input as Partial<SolanaNoncePreparation> | null | undefined;
  if (!value || value.version !== 1 || value.networkId !== 'solana-mainnet') {
    throw new Error('Unsupported Solana nonce preparation version');
  }
  if (value.authority !== authority || value.index !== index) {
    throw new Error('Solana nonce preparation identity mismatch');
  }
  if (!looksLikeSolanaPublicKey(String(value.authority || ''))) {
    throw new Error('Solana nonce preparation authority is invalid');
  }
  if (!looksLikeSolanaPublicKey(String(value.nonceAccountAddress || ''))) {
    throw new Error('Solana nonce preparation account is invalid');
  }
  if (!looksLikeSolanaPublicKey(String(value.blockhash || ''))) {
    throw new Error('Solana nonce preparation blockhash is invalid');
  }
  if (value.state !== 'signed' && value.state !== 'submitted' && value.state !== 'confirmed') {
    throw new Error('Solana nonce preparation state is invalid');
  }
  const signedTransactionBase64 = String(value.signedTransactionBase64 || '').trim();
  if (!signedTransactionBase64 || signedTransactionBase64.length > MAX_SIGNED_TRANSACTION_B64_CHARS) {
    throw new Error('Solana nonce preparation transaction is invalid');
  }
  const digest = String(value.signedTransactionSha256 || '').toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(digest)) {
    throw new Error('Solana nonce preparation digest is invalid');
  }
  const setupId = String(value.setupId || '').trim();
  if (!setupId || setupId.length > 160) throw new Error('Solana nonce setup ID is invalid');

  let rentLamports: bigint;
  let lastValidBlockHeight: bigint;
  try {
    rentLamports = BigInt(String(value.rentLamports));
    lastValidBlockHeight = BigInt(String(value.lastValidBlockHeight));
  } catch {
    throw new Error('Solana nonce preparation numeric data is invalid');
  }
  if (rentLamports <= 0n || lastValidBlockHeight <= 0n) {
    throw new Error('Solana nonce preparation numeric data is invalid');
  }

  const createdAt = Number(value.createdAt);
  if (!Number.isFinite(createdAt) || createdAt <= 0) throw new Error('Solana nonce preparation timestamp is invalid');
  if (value.submittedAt !== undefined && (!Number.isFinite(Number(value.submittedAt)) || Number(value.submittedAt) <= 0)) {
    throw new Error('Solana nonce submission timestamp is invalid');
  }
  if (value.confirmedAt !== undefined && (!Number.isFinite(Number(value.confirmedAt)) || Number(value.confirmedAt) <= 0)) {
    throw new Error('Solana nonce confirmation timestamp is invalid');
  }

  return {
    version: 1,
    networkId: 'solana-mainnet',
    authority,
    index,
    setupId,
    nonceAccountAddress: String(value.nonceAccountAddress),
    rentLamports: rentLamports.toString(),
    blockhash: String(value.blockhash),
    lastValidBlockHeight: lastValidBlockHeight.toString(),
    signedTransactionBase64,
    signedTransactionSha256: digest,
    state: value.state,
    signature: value.signature ? String(value.signature) : undefined,
    createdAt,
    submittedAt: value.submittedAt === undefined ? undefined : Number(value.submittedAt),
    confirmedAt: value.confirmedAt === undefined ? undefined : Number(value.confirmedAt),
  };
}

async function readPreparation(authority: string, index: number): Promise<SolanaNoncePreparation | null> {
  await ensureStore();
  const key = preparationKey(authority, index);
  const { value } = await BleeStore.getValue({ key });
  if (!value) return null;
  let parsed: unknown;
  try { parsed = JSON.parse(value) as unknown; } catch { throw new Error('Solana nonce preparation is damaged'); }
  return assertPreparation(parsed, authority, index);
}

async function persistPreparation(value: SolanaNoncePreparation): Promise<void> {
  await ensureStore();
  await BleeStore.setValue({
    key: preparationKey(value.authority, value.index),
    value: JSON.stringify(value),
  });
}

async function sha256Base64Payload(value: string): Promise<string> {
  let bytes: Uint8Array;
  try {
    const binary = atob(value);
    bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  } catch {
    throw new Error('Signed Solana nonce setup is not valid base64');
  }
  if (bytes.byteLength < 64 || bytes.byteLength > 1232) {
    throw new Error('Signed Solana nonce setup has an invalid wire size');
  }
  const digestInput = new Uint8Array(bytes.byteLength);
  digestInput.set(bytes);
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', digestInput.buffer));
  digestInput.fill(0);
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function assertStoredDigest(value: SolanaNoncePreparation): Promise<void> {
  const digest = await sha256Base64Payload(value.signedTransactionBase64);
  if (digest !== value.signedTransactionSha256) {
    throw new Error('Stored Solana nonce setup bytes failed integrity verification');
  }
}

function assertExactNonceSetupShape(input: {
  instructions: readonly Instruction[];
  senderAddress: string;
  nonceAccountAddress: string;
  rentLamports: bigint;
}): void {
  if (input.instructions.length !== 2) {
    throw new Error('Solana nonce setup must contain exactly two instructions');
  }
  const createInstruction = input.instructions[0];
  const initializeInstruction = input.instructions[1];
  if (!createInstruction || !initializeInstruction) throw new Error('Solana nonce setup instruction shape is incomplete');

  if (
    !isInstructionForProgram(createInstruction, SYSTEM_PROGRAM_ADDRESS)
    || !isInstructionWithAccounts(createInstruction)
    || !isInstructionWithData(createInstruction)
    || createInstruction.accounts.length !== 2
    || identifySystemInstruction(createInstruction) !== SystemInstruction.CreateAccount
  ) {
    throw new Error('Solana nonce setup instruction 0 must be CreateAccount');
  }
  const parsedCreate = parseCreateAccountInstruction(createInstruction);
  if (
    parsedCreate.accounts.payer.address !== input.senderAddress
    || parsedCreate.accounts.newAccount.address !== input.nonceAccountAddress
    || parsedCreate.data.lamports !== input.rentLamports
    || parsedCreate.data.space !== BigInt(SOLANA_NONCE_ACCOUNT_SPACE)
    || parsedCreate.data.programAddress !== SYSTEM_PROGRAM_ADDRESS
  ) {
    throw new Error('Solana nonce CreateAccount instruction does not match the preparation');
  }

  if (
    !isInstructionForProgram(initializeInstruction, SYSTEM_PROGRAM_ADDRESS)
    || !isInstructionWithAccounts(initializeInstruction)
    || !isInstructionWithData(initializeInstruction)
    || initializeInstruction.accounts.length !== 3
    || identifySystemInstruction(initializeInstruction) !== SystemInstruction.InitializeNonceAccount
  ) {
    throw new Error('Solana nonce setup instruction 1 must be InitializeNonceAccount');
  }
  const parsedInitialize = parseInitializeNonceAccountInstruction(initializeInstruction);
  if (
    parsedInitialize.accounts.nonceAccount.address !== input.nonceAccountAddress
    || parsedInitialize.accounts.recentBlockhashesSysvar.address !== RECENT_BLOCKHASHES_SYSVAR
    || parsedInitialize.accounts.rentSysvar.address !== RENT_SYSVAR
    || parsedInitialize.data.nonceAuthority !== input.senderAddress
  ) {
    throw new Error('Solana nonce InitializeNonceAccount instruction does not match the preparation');
  }
}

/**
 * BLEE_SOLANA_NONCE_PREPARATION_V1
 *
 * Online preparation is local-signing only. The APK obtains only public chain
 * data from the Blee gateway, generates the nonce-account key locally, signs
 * the exact CreateAccount + InitializeNonceAccount transaction locally, and
 * persists those exact wire bytes before any submission attempt.
 */
export async function prepareSignedSolanaNonceSetup(input: {
  signer: SolanaLocalSigner;
  index: number;
}): Promise<SolanaNoncePreparation> {
  const index = assertIndex(input.index);
  const authority = input.signer.address;
  if (!looksLikeSolanaPublicKey(authority)) throw new Error('Solana wallet address is invalid');

  const existing = await readPreparation(authority, index);
  if (existing) {
    await assertStoredDigest(existing);
    return existing;
  }

  const senderSigner = await createSignerFromKeyPair(input.signer.keyPair);
  if (senderSigner.address !== authority) throw new Error('Solana signer does not match the wallet address');
  const nonceAccountSigner = await generateKeyPairSigner();
  const [rentLamports, latestBlockhash] = await Promise.all([
    getSolanaRentExemption(SOLANA_NONCE_ACCOUNT_SPACE),
    getSolanaLatestBlockhash(),
  ]);

  const createInstruction = getCreateAccountInstruction({
    payer: senderSigner,
    newAccount: nonceAccountSigner,
    lamports: lamports(rentLamports),
    space: BigInt(SOLANA_NONCE_ACCOUNT_SPACE),
    programAddress: SYSTEM_PROGRAM_ADDRESS,
  });
  const initializeInstruction = getInitializeNonceAccountInstruction({
    nonceAccount: nonceAccountSigner.address,
    nonceAuthority: senderSigner.address,
  });

  const transactionMessage = pipe(
    createTransactionMessage({ version: 0 }),
    (message) => setTransactionMessageFeePayerSigner(senderSigner, message),
    (message) => setTransactionMessageLifetimeUsingBlockhash({
      blockhash: latestBlockhash.blockhash as Blockhash,
      lastValidBlockHeight: latestBlockhash.lastValidBlockHeight,
    }, message),
    (message) => appendTransactionMessageInstructions([createInstruction, initializeInstruction], message),
  );

  assertExactNonceSetupShape({
    instructions: transactionMessage.instructions,
    senderAddress: authority,
    nonceAccountAddress: nonceAccountSigner.address,
    rentLamports,
  });

  const signedTransaction = await signTransactionMessageWithSigners(transactionMessage);
  const signedTransactionBase64 = getBase64EncodedWireTransaction(signedTransaction);
  const signedTransactionSha256 = await sha256Base64Payload(signedTransactionBase64);
  const now = Date.now();
  const value: SolanaNoncePreparation = {
    version: 1,
    networkId: 'solana-mainnet',
    authority,
    index,
    setupId: `solana-mainnet:${authority}:${index}:${nonceAccountSigner.address}`,
    nonceAccountAddress: nonceAccountSigner.address,
    rentLamports: rentLamports.toString(),
    blockhash: latestBlockhash.blockhash,
    lastValidBlockHeight: latestBlockhash.lastValidBlockHeight.toString(),
    signedTransactionBase64,
    signedTransactionSha256,
    state: 'signed',
    createdAt: now,
  };
  await persistPreparation(value);
  return value;
}

/**
 * Submission is an explicit online step and may only replay the exact locally
 * signed setup bytes. The gateway must validate the strict nonce-setup shape
 * and forward bytes unchanged; it never signs or mutates the transaction.
 */
export async function submitPreparedSolanaNonceSetup(input: {
  authority: string;
  index: number;
}): Promise<SolanaNoncePreparation> {
  const preparation = await readPreparation(input.authority, assertIndex(input.index));
  if (!preparation) throw new Error('Solana nonce setup has not been prepared');
  await assertStoredDigest(preparation);
  if (preparation.state === 'confirmed') return preparation;

  const result = await sendSignedSolanaNonceSetupTransaction({
    setupId: preparation.setupId,
    nonceAccountAddress: preparation.nonceAccountAddress,
    signedTransactionBase64: preparation.signedTransactionBase64,
  });
  const next: SolanaNoncePreparation = {
    ...preparation,
    state: 'submitted',
    signature: result.signature,
    submittedAt: preparation.submittedAt || Date.now(),
  };
  await persistPreparation(next);
  return next;
}

/**
 * A slot becomes available to offline SOL only after the gateway independently
 * reads the initialized nonce account and the nonce-pool registrar verifies the
 * account authority and current nonce value.
 */
export async function confirmPreparedSolanaNonceSetup(input: {
  authority: string;
  index: number;
}): Promise<{ preparation: SolanaNoncePreparation; slot: SolanaNonceSlot }> {
  const preparation = await readPreparation(input.authority, assertIndex(input.index));
  if (!preparation) throw new Error('Solana nonce setup has not been prepared');
  await assertStoredDigest(preparation);
  if (preparation.state === 'signed') throw new Error('Solana nonce setup has not been submitted');

  const slot = await registerPreparedSolanaNonceSlot({
    index: preparation.index,
    address: preparation.nonceAccountAddress,
    authority: preparation.authority,
  });
  const next: SolanaNoncePreparation = {
    ...preparation,
    state: 'confirmed',
    confirmedAt: preparation.confirmedAt || Date.now(),
  };
  await persistPreparation(next);
  return { preparation: next, slot };
}

export async function getSolanaNoncePreparation(
  authority: string,
  index: number,
): Promise<SolanaNoncePreparation | null> {
  const preparation = await readPreparation(authority, assertIndex(index));
  if (preparation) await assertStoredDigest(preparation);
  return preparation;
}
