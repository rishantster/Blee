import {
  address,
  appendTransactionMessageInstruction,
  createSignerFromKeyPair,
  createTransactionMessage,
  getBase64EncodedWireTransaction,
  isInstructionForProgram,
  isInstructionWithAccounts,
  isInstructionWithData,
  lamports,
  pipe,
  setTransactionMessageFeePayerSigner,
  setTransactionMessageLifetimeUsingDurableNonce,
  signTransactionMessageWithSigners,
  type Instruction,
  type Nonce,
} from '@solana/kit';
import {
  identifySystemInstruction,
  getTransferSolInstruction,
  parseAdvanceNonceAccountInstruction,
  parseTransferSolInstruction,
  SYSTEM_PROGRAM_ADDRESS,
  SystemInstruction,
} from '@solana-program/system';
import {
  persistSignedSolanaTransaction,
  reserveSolanaNonceSlot,
  type SolanaNonceReservation,
} from './solanaNoncePool';
import type { SolanaLocalSigner } from './solanaVault';

const RECENT_BLOCKHASHES_SYSVAR = 'SysvarRecentB1ockHashes11111111111111111111';

export type PreparedOfflineSolTransfer = Readonly<{
  railId: 'solana-sol';
  networkId: 'solana-mainnet';
  sender: string;
  paymentId: string;
  recipient: string;
  amountLamports: string;
  nonceAccountAddress: string;
  nonce: string;
  signedTransactionBase64: string;
  signedTransactionSha256: string;
  replayed: boolean;
}>;

function preparedFromReservation(
  reservation: SolanaNonceReservation,
  replayed: boolean,
): PreparedOfflineSolTransfer {
  if (!reservation.signedTransactionBase64 || !reservation.signedTransactionSha256) {
    throw new Error('Signed SOL transaction was not durably persisted');
  }
  return {
    railId: 'solana-sol',
    networkId: 'solana-mainnet',
    sender: reservation.authority,
    paymentId: reservation.paymentId,
    recipient: reservation.recipient,
    amountLamports: reservation.amountLamports,
    nonceAccountAddress: reservation.nonceAccountAddress,
    nonce: reservation.nonce,
    signedTransactionBase64: reservation.signedTransactionBase64,
    signedTransactionSha256: reservation.signedTransactionSha256,
    replayed,
  };
}

function assertExactSolPaymentShape(input: {
  instructions: readonly Instruction[];
  lifetimeNonce: string;
  nonceAccountAddress: string;
  senderAddress: string;
  recipientAddress: string;
  amountLamports: bigint;
  expectedNonce: string;
}): void {
  if (input.lifetimeNonce !== input.expectedNonce) {
    throw new Error('SOL transaction durable nonce does not match the reserved nonce');
  }
  if (input.instructions.length !== 2) {
    throw new Error('SOL payment transaction must contain exactly two instructions');
  }

  const advanceInstruction = input.instructions[0];
  const transferInstruction = input.instructions[1];
  if (!advanceInstruction || !transferInstruction) {
    throw new Error('SOL payment transaction instruction shape is incomplete');
  }

  if (
    !isInstructionForProgram(advanceInstruction, SYSTEM_PROGRAM_ADDRESS)
    || !isInstructionWithAccounts(advanceInstruction)
    || !isInstructionWithData(advanceInstruction)
    || advanceInstruction.accounts.length !== 3
    || identifySystemInstruction(advanceInstruction) !== SystemInstruction.AdvanceNonceAccount
  ) {
    throw new Error('SOL payment instruction 0 must be AdvanceNonceAccount');
  }
  const parsedAdvance = parseAdvanceNonceAccountInstruction(advanceInstruction);
  if (
    parsedAdvance.accounts.nonceAccount.address !== input.nonceAccountAddress
    || parsedAdvance.accounts.recentBlockhashesSysvar.address !== RECENT_BLOCKHASHES_SYSVAR
    || parsedAdvance.accounts.nonceAuthority.address !== input.senderAddress
  ) {
    throw new Error('SOL payment durable nonce accounts do not match the reservation');
  }

  if (
    !isInstructionForProgram(transferInstruction, SYSTEM_PROGRAM_ADDRESS)
    || !isInstructionWithAccounts(transferInstruction)
    || !isInstructionWithData(transferInstruction)
    || transferInstruction.accounts.length !== 2
    || identifySystemInstruction(transferInstruction) !== SystemInstruction.TransferSol
  ) {
    throw new Error('SOL payment instruction 1 must be a native SOL transfer');
  }
  const parsedTransfer = parseTransferSolInstruction(transferInstruction);
  if (
    parsedTransfer.accounts.source.address !== input.senderAddress
    || parsedTransfer.accounts.destination.address !== input.recipientAddress
    || parsedTransfer.data.amount !== input.amountLamports
  ) {
    throw new Error('SOL transfer does not match the reserved payment');
  }
}

/**
 * BLEE_SOLANA_DURABLE_PAYMENT_TX_V1
 *
 * Creates the only transaction shape Blee permits for an offline native SOL
 * payment: AdvanceNonceAccount first, then one System Program native SOL
 * transfer. The sender is fee payer, transfer source and nonce authority.
 *
 * Reservation is durable before signing. Once exact signed wire bytes exist,
 * retries return those bytes rather than rebuilding or re-signing a payment.
 */
export async function prepareSignedOfflineSolTransfer(input: {
  signer: SolanaLocalSigner;
  paymentId: string;
  recipient: string;
  amountLamports: string;
}): Promise<PreparedOfflineSolTransfer> {
  const reservation = await reserveSolanaNonceSlot({
    authority: input.signer.address,
    paymentId: input.paymentId,
    recipient: input.recipient,
    amountLamports: input.amountLamports,
  });

  // Exact-byte replay is mandatory. Re-running persistence recomputes the hash
  // and therefore also fails closed if durable bytes were corrupted.
  if (reservation.signedTransactionBase64) {
    const replay = await persistSignedSolanaTransaction({
      authority: reservation.authority,
      paymentId: reservation.paymentId,
      slotId: reservation.slotId,
      signedTransactionBase64: reservation.signedTransactionBase64,
    });
    return preparedFromReservation(replay, true);
  }

  const senderSigner = await createSignerFromKeyPair(input.signer.keyPair);
  if (senderSigner.address !== input.signer.address || senderSigner.address !== reservation.authority) {
    throw new Error('Solana signer does not match the reserved payment authority');
  }

  const nonceAccountAddress = address(reservation.nonceAccountAddress);
  const nonceAuthorityAddress = address(reservation.authority);
  const recipientAddress = address(reservation.recipient);
  const amountLamports = BigInt(reservation.amountLamports);
  const nonce = reservation.nonce as Nonce;

  const transferInstruction = getTransferSolInstruction({
    source: senderSigner,
    destination: recipientAddress,
    amount: lamports(amountLamports),
  });

  // Add the transfer first; the durable-nonce lifetime setter deliberately
  // prepends AdvanceNonceAccount so the final message is exactly [advance, transfer].
  const transactionMessage = pipe(
    createTransactionMessage({ version: 0 }),
    (message) => setTransactionMessageFeePayerSigner(senderSigner, message),
    (message) => appendTransactionMessageInstruction(transferInstruction, message),
    (message) => setTransactionMessageLifetimeUsingDurableNonce(
      {
        nonce,
        nonceAccountAddress,
        nonceAuthorityAddress,
      },
      message,
    ),
  );

  assertExactSolPaymentShape({
    instructions: transactionMessage.instructions,
    lifetimeNonce: transactionMessage.lifetimeConstraint.nonce,
    nonceAccountAddress: reservation.nonceAccountAddress,
    senderAddress: reservation.authority,
    recipientAddress: reservation.recipient,
    amountLamports,
    expectedNonce: reservation.nonce,
  });

  const signedTransaction = await signTransactionMessageWithSigners(transactionMessage);
  const signedTransactionBase64 = getBase64EncodedWireTransaction(signedTransaction);
  const persisted = await persistSignedSolanaTransaction({
    authority: reservation.authority,
    paymentId: reservation.paymentId,
    slotId: reservation.slotId,
    signedTransactionBase64,
  });

  return preparedFromReservation(persisted, false);
}
