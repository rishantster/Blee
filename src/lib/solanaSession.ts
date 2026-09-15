import type { PrivateKeyAccount } from 'viem/accounts';
import {
  provisionSolanaVaultAfterPrimaryUnlock,
  unlockSolanaVault,
  type SolanaLocalSigner,
} from './solanaVault';

/**
 * A WeakMap deliberately ties the Solana signer lifetime to the already-
 * authenticated Arc/EVM account object. Blee's explicit logout drops that
 * primary account object from React state/ref, making the Solana session
 * unreachable without introducing a second long-lived global secret holder.
 */
const solanaSessions = new WeakMap<PrivateKeyAccount, Promise<SolanaLocalSigner | null>>();

export function beginSolanaSessionAfterPrimaryUnlock(
  primaryAccount: PrivateKeyAccount,
  passphrase: string,
): void {
  if (solanaSessions.has(primaryAccount)) return;

  const task = (async () => {
    await provisionSolanaVaultAfterPrimaryUnlock(passphrase);
    return unlockSolanaVault(passphrase);
  })().catch(() => null);

  solanaSessions.set(primaryAccount, task);
}

export async function getSolanaSignerForPrimarySession(
  primaryAccount: PrivateKeyAccount | null | undefined,
): Promise<SolanaLocalSigner | null> {
  if (!primaryAccount) return null;
  const task = solanaSessions.get(primaryAccount);
  return task ? task : null;
}
