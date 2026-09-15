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
const fallback: BiometricStatus = { available: false, enrolled: false, enabled: false, reason: 'Android fingerprint unavailable' };

function isAndroidNative() {
  return typeof window !== 'undefined' && Capacitor.getPlatform() === 'android';
}

function normalizeStatus(status: BiometricStatus): BiometricStatus {
  const usable = Boolean(status.available && status.enrolled);
  return {
    ...status,
    available: usable,
    enabled: usable && Boolean(status.enabled),
  };
}

export const BleeBiometric = {
  async status(): Promise<BiometricStatus> {
    if (!isAndroidNative()) return fallback;
    try { return normalizeStatus(await Native.status()); }
    catch (error) { return { ...fallback, reason: error instanceof Error ? error.message : fallback.reason }; }
  },
  async enroll(passphrase: string) {
    if (!isAndroidNative()) throw new Error('Fingerprint unlock is available in the Android app');
    if (passphrase.length < 8) throw new Error('Use a passphrase of at least 8 characters');
    const status = await BleeBiometric.status();
    if (!status.available || !status.enrolled) throw new Error(status.reason || 'Fingerprint authentication is not available on this phone');
    return Native.enroll({ passphrase });
  },
  async unlock(): Promise<BiometricUnlockResult> {
    if (!isAndroidNative()) throw new Error('Fingerprint unlock is available in the Android app');
    const status = await BleeBiometric.status();
    if (!status.available || !status.enrolled || !status.enabled) throw new Error('Fingerprint unlock is not available on this phone');
    return Native.unlock();
  },
  async disable() {
    if (!isAndroidNative()) return { enabled: false };
    return Native.disable();
  },
};

// BLEE_BIOMETRIC_CAPABILITY_GATE_V2
// Fingerprint UI is only valid when Android confirms a real fingerprint sensor
// and at least one enrolled fingerprint. Generic biometrics (for example face
// only) must never cause Blee to surface a fingerprint action.
export async function syncBleeBiometricCapability(): Promise<boolean> {
  if (typeof document === 'undefined') return false;
  const root = document.documentElement;
  let usable = false;
  try {
    const status = await BleeBiometric.status();
    usable = Boolean(status.available && status.enrolled);
  } catch {
    usable = false;
  }
  root.dataset.bleeBiometric = usable ? 'available' : 'unavailable';

  // Defensive DOM guard for transitions/hydration. React remains authoritative,
  // but an unsupported phone must never briefly expose a dead fingerprint CTA.
  const apply = () => {
    const nodes = document.querySelectorAll<HTMLElement>('button,[role="button"],.biometric-opt-in,.biometric-unlock,.fingerprint-action');
    nodes.forEach((node) => {
      const fingerprintControl = /fingerprint/i.test(node.textContent || '')
        || node.classList.contains('biometric-opt-in')
        || node.classList.contains('biometric-unlock')
        || node.classList.contains('fingerprint-action');
      if (!fingerprintControl) return;
      node.hidden = !usable;
      node.setAttribute('aria-hidden', usable ? 'false' : 'true');
    });
  };
  apply();
  return usable;
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
