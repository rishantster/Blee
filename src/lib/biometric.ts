'use client';

import { Capacitor, registerPlugin } from '@capacitor/core';

export type BiometricStatus = {
  available: boolean;
  enrolled: boolean;
  enabled: boolean;
  reason?: string;
};

type BiometricUnlockResult = { passphrase: string };

type NativeBleeBiometric = {
  status(): Promise<BiometricStatus>;
  enroll(options: { passphrase: string }): Promise<{ enabled: boolean }>;
  unlock(): Promise<BiometricUnlockResult>;
  disable(): Promise<{ enabled: boolean }>;
};

const Native = registerPlugin<NativeBleeBiometric>('BleeBiometric');
const fallback: BiometricStatus = { available: false, enrolled: false, enabled: false, reason: 'Android biometrics unavailable' };

function isAndroidNative() {
  return typeof window !== 'undefined' && Capacitor.getPlatform() === 'android';
}

export const BleeBiometric = {
  async status(): Promise<BiometricStatus> {
    if (!isAndroidNative()) return fallback;
    try { return await Native.status(); }
    catch (error) { return { ...fallback, reason: error instanceof Error ? error.message : fallback.reason }; }
  },
  async enroll(passphrase: string) {
    if (!isAndroidNative()) throw new Error('Fingerprint unlock is available in the Android app');
    if (passphrase.length < 8) throw new Error('Use a passphrase of at least 8 characters');
    return Native.enroll({ passphrase });
  },
  async unlock(): Promise<BiometricUnlockResult> {
    if (!isAndroidNative()) throw new Error('Fingerprint unlock is available in the Android app');
    return Native.unlock();
  },
  async disable() {
    if (!isAndroidNative()) return { enabled: false };
    return Native.disable();
  },
};


// BLEE_BIOMETRIC_CAPABILITY_GATE_V1
export async function syncBleeBiometricCapability(): Promise<boolean> {
  if (typeof document === 'undefined') return false;
  const root = document.documentElement;
  let available = false;
  try {
    const status: any = await BleeBiometric.status();
    available = Boolean(status?.available);
  } catch {
    available = false;
  }
  root.dataset.bleeBiometric = available ? 'available' : 'unavailable';

  // Defensive guard for any biometric action rendered by a later sheet/screen.
  // The React UI remains authoritative; this prevents unsupported hardware from
  // ever exposing a dead fingerprint control during transitions/hydration.
  const apply = () => {
    const nodes = document.querySelectorAll<HTMLElement>('button,[role="button"],.biometric-opt-in,.biometric-unlock,.fingerprint-action');
    nodes.forEach((node) => {
      const fingerprintControl = /fingerprint/i.test(node.textContent || '')
        || node.classList.contains('biometric-opt-in')
        || node.classList.contains('biometric-unlock')
        || node.classList.contains('fingerprint-action');
      if (!fingerprintControl) return;
      node.hidden = !available;
      node.setAttribute('aria-hidden', available ? 'false' : 'true');
    });
  };
  apply();
  return available;
}

if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  queueMicrotask(() => { void syncBleeBiometricCapability(); });
  const observer = new MutationObserver(() => {
    if (document.documentElement.dataset.bleeBiometric !== 'available') {
      void syncBleeBiometricCapability();
    }
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void syncBleeBiometricCapability();
  });
}
