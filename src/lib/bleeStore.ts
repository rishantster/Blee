import { registerPlugin } from '@capacitor/core';

export interface BleeStorePlugin {
  init(): Promise<{ ready: boolean; journalMode?: string }>;
  loadPayments(): Promise<{ payments: string[] }>;
  replacePayments(options: { payments: string[] }): Promise<{ count: number }>;
  getValue(options: { key: string }): Promise<{ value?: string | null }>;
  setValue(options: { key: string; value: string }): Promise<void>;
  removeValue(options: { key: string }): Promise<void>;
  reserveSigningIntent(options: {
    signingId: string;
    sessionId: string;
    chainId: number | string;
    sender: string;
    recipient: string;
    value: string;
    authorizationNonce: string;
    expiresAt: number | string;
    minTxNonce?: number | string;
  }): Promise<{ reserved: boolean; txNonce?: number | null }>;
  finalizeSigningIntent(options: {
    signingId: string;
    sessionId: string;
    authorization: string;
    broadcast: string;
    bundleHash: string;
  }): Promise<{ ready: boolean }>;
  abortSigningIntent(options: { signingId: string; sessionId: string; reason?: string }): Promise<void>;
}

/**
 * BleeStore is registered exactly once for the entire WebView bundle.
 * Import this proxy wherever native SQLite/signing storage is needed.
 */
export const BleeStore = registerPlugin<BleeStorePlugin>('BleeStore');
