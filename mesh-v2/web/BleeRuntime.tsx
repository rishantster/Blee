'use client';

import { useEffect, useRef, useState } from 'react';
import { Capacitor, registerPlugin, type PluginListenerHandle } from '@capacitor/core';
import type { Address } from 'viem';
import { BleeApp } from '../../src/components/BleeApp';
import { refreshSenderFundedSettlementProfile, verifyAuthorization } from '../../src/lib/payments';

type MeshStatus = {
  running: boolean;
  protocol: string;
  wallet?: string | null;
  broadcastMode?: string;
  senderPaysGas?: boolean;
  relayPaysGas?: boolean;
};

type MeshPeerSnapshot = {
  transportId: string;
  wallet?: string | null;
  displayName?: string | null;
  rssi?: number;
  lastSeen?: number;
  transport?: 'ble';
};

type BleDiagnostics = Record<string, string | number | boolean | null | undefined>;

type MeshPlugin = {
  start(): Promise<{ running: boolean; protocol: string }>;
  status(): Promise<MeshStatus>;
  ensureNotificationPermission(): Promise<{ granted?: boolean } | void>;
  pendingEnvelopes(): Promise<{ packets: string[] }>;
  nearbyPeers(): Promise<{ peers: MeshPeerSnapshot[] }>;
  diagnostics(): Promise<BleDiagnostics>;
  rearmBluetooth(): Promise<{ requested?: boolean }>;
  acceptEnvelope(options: { messageId: string }): Promise<{ accepted: boolean; paymentId?: string }>;
  addListener(
    eventName: 'ledgerChanged' | 'peerChanged',
    listener: (event: Record<string, unknown>) => void,
  ): Promise<PluginListenerHandle>;
};

const BleeMesh = registerPlugin<MeshPlugin>('BleeMesh');

function authorizationFromPayment(payment: Record<string, unknown>) {
  const candidate = (payment.authorization ?? payment.auth) as Record<string, unknown> | undefined;
  if (!candidate) return null;
  const required = ['from', 'to', 'value', 'validAfter', 'validBefore', 'nonce', 'signature'] as const;
  if (!required.every((key) => typeof candidate[key] === 'string' && candidate[key])) return null;
  return candidate as any;
}

function bool(value: unknown) {
  return value === true;
}

function numberValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function diagnosticSummary(d: BleDiagnostics | null): string {
  if (!d) return 'Collecting Bluetooth diagnostics…';
  if (!bool(d.adapterPresent)) return 'This phone does not expose a Bluetooth adapter to Blee.';
  if (!bool(d.bluetoothEnabled)) return 'Bluetooth is turned off.';
  if (!bool(d.scanPermission) || !bool(d.connectPermission) || !bool(d.advertisePermission)) {
    return 'One or more Android Bluetooth permissions are missing.';
  }
  if (!bool(d.serviceRunning)) return 'The Blee nearby foreground service is not running.';
  if (d.advertiserAvailable === false) return 'BLE advertising is unavailable on this phone.';
  if (d.scannerAvailable === false) return 'BLE scanning is unavailable on this phone.';
  if (numberValue(d.advertiseFailures) > 0 && !bool(d.advertiserActive)) {
    return `BLE advertising is failing (${String(d.lastError || 'unknown error')}).`;
  }
  if (!bool(d.advertiserActive)) return 'Blee is not currently advertising over Bluetooth.';
  if (!bool(d.scannerActive)) return 'Blee is not currently scanning over Bluetooth.';
  if (numberValue(d.rawScanResults) === 0) return 'Scanner is active, but this phone has not seen any BLE advertisements yet.';
  if (numberValue(d.bleeAdvertisements) === 0) return 'Bluetooth scanning works, but no Blee advertisement has been detected.';
  if (numberValue(d.gattAttempts) === 0) return 'A Blee advertisement was seen, but a GATT connection was not attempted.';
  if (numberValue(d.gattConnected) === 0) return 'Blee sees the other phone, but the BLE GATT connection is failing.';
  if (numberValue(d.servicesDiscovered) === 0) return 'GATT connected, but the Blee service could not be discovered.';
  if (numberValue(d.identityReads) === 0) {
    return numberValue(d.identityFailures) > 0
      ? 'The Blee service was found, but wallet identity reads are failing.'
      : 'The Blee service was found, but no wallet identity has been read yet.';
  }
  if (numberValue(d.resolvedPeerCount) === 0) return 'Wallet identity was read, but the native peer was not retained.';
  return 'Bluetooth discovery path is healthy on this phone.';
}

function formatValue(key: string, value: unknown): string {
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (value === null || value === undefined || value === '') return '—';
  if (key.toLowerCase().includes('wallet') && typeof value === 'string' && /^0x[0-9a-fA-F]{40}$/.test(value)) {
    return `${value.slice(0, 8)}…${value.slice(-6)}`;
  }
  if (key.toLowerCase().includes('at') && typeof value === 'number' && value > 1_000_000_000_000) {
    return new Date(value).toLocaleTimeString();
  }
  return String(value);
}

const DIAGNOSTIC_ROWS: Array<[string, string]> = [
  ['serviceRunning', 'Nearby service'],
  ['bluetoothEnabled', 'Bluetooth enabled'],
  ['scanPermission', 'Scan permission'],
  ['connectPermission', 'Connect permission'],
  ['advertisePermission', 'Advertise permission'],
  ['multipleAdvertisementSupported', 'Peripheral advertising support'],
  ['scannerAvailable', 'Scanner available'],
  ['scannerActive', 'Scanner active'],
  ['advertiserAvailable', 'Advertiser available'],
  ['advertiserActive', 'Advertiser active'],
  ['gattServerActive', 'GATT server active'],
  ['localWalletResolved', 'Local wallet resolved'],
  ['scanStarts', 'Scan starts'],
  ['rawScanResults', 'All BLE advertisements seen'],
  ['bleeAdvertisements', 'Blee advertisements seen'],
  ['advertiseStarts', 'Advertise attempts'],
  ['advertiseSuccesses', 'Advertise successes'],
  ['advertiseFailures', 'Advertise failures'],
  ['gattAttempts', 'GATT attempts'],
  ['gattConnected', 'GATT connections'],
  ['servicesDiscovered', 'Blee services discovered'],
  ['identityReads', 'Wallet identities read'],
  ['identityFailures', 'Identity read failures'],
  ['resolvedPeerCount', 'Resolved nearby peers'],
  ['lastRssi', 'Last RSSI'],
  ['lastTransportId', 'Last BLE device'],
  ['lastWallet', 'Last resolved wallet'],
  ['lastPhase', 'Last BLE phase'],
  ['lastError', 'Last BLE error'],
  ['lastSeenAt', 'Last scan result'],
];

export default function BleeRuntime() {
  // BLEE_RUNTIME_NO_REMOUNT_V1
  // This revision intentionally re-renders the parent without changing the
  // BleeApp element identity. The old key={`ledger-${revision}`} forced a full
  // unmount/remount on focus/visibility/native-ledger events and wiped the
  // unlocked in-memory wallet session whenever the user left and returned.
  const [, setRevision] = useState(0);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const processing = useRef(false);
  const [nativeReady, setNativeReady] = useState(false);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [diagnostics, setDiagnostics] = useState<BleDiagnostics | null>(null);
  const [diagnosticAction, setDiagnosticAction] = useState('');

  useEffect(() => {
    setNativeReady(Capacitor.isNativePlatform());
  }, []);

  useEffect(() => {
    if (!nativeReady || !diagnosticsOpen) return;
    let active = true;
    const tick = async () => {
      try {
        const snapshot = await BleeMesh.diagnostics();
        if (active) setDiagnostics(snapshot);
      } catch (error) {
        if (active) setDiagnostics({ lastError: error instanceof Error ? error.message : String(error) });
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 1200);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, [nativeReady, diagnosticsOpen]);

  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return;
    let active = true;
    let ledgerListener: PluginListenerHandle | null = null;
    let peerListener: PluginListenerHandle | null = null;

    const refreshLedger = () => {
      if (!active) return;
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
      refreshTimer.current = setTimeout(() => {
        if (!active) return;
        setRevision((value) => value + 1);
        window.dispatchEvent(new CustomEvent('blee:ledger-changed'));
      }, 180);
    };

    const publishNativePeers = async () => {
      if (!active) return;
      try {
        const { peers } = await BleeMesh.nearbyPeers();
        const snapshots = Array.isArray(peers) ? peers : [];
        (window as any).__bleeMeshPeers = snapshots;
        window.dispatchEvent(new CustomEvent('blee:native-nearby', { detail: { peers: snapshots } }));
      } catch {
        // Native peer discovery is best-effort; the foreground service keeps
        // scanning and will emit peerChanged when Bluetooth recovers.
      }
    };

    const refreshSettlementProfile = async () => {
      try {
        const status = await BleeMesh.status();
        if (status.wallet) await refreshSenderFundedSettlementProfile(status.wallet as Address);
      } catch {
        // Offline is expected. The most recent chain nonce/fee profile remains cached.
      }
    };

    const verifyPendingOfflinePayments = async () => {
      if (!active || processing.current) return;
      processing.current = true;
      try {
        const status = await BleeMesh.status();
        const wallet = status.wallet?.toLowerCase();
        if (!wallet) return;
        const { packets } = await BleeMesh.pendingEnvelopes();
        let accepted = false;
        for (const raw of packets || []) {
          try {
            const packet = JSON.parse(raw) as Record<string, any>;
            const payment = JSON.parse(String(packet.payload || '{}')) as Record<string, unknown>;
            const auth = authorizationFromPayment(payment);
            if (!auth || String(auth.to).toLowerCase() !== wallet) continue;
            if (!(await verifyAuthorization(auth))) continue;
            const result = await BleeMesh.acceptEnvelope({ messageId: String(packet.messageId || '') });
            accepted = result.accepted || accepted;
          } catch (error) {
            console.warn('Ignored invalid Blee Mesh payment envelope', error);
          }
        }
        if (accepted) refreshLedger();
      } finally {
        processing.current = false;
      }
    };

    (async () => {
      try {
        await BleeMesh.start();
        await BleeMesh.ensureNotificationPermission();
        ledgerListener = await BleeMesh.addListener('ledgerChanged', () => {
          void verifyPendingOfflinePayments();
          refreshLedger();
        });
        peerListener = await BleeMesh.addListener('peerChanged', () => {
          void publishNativePeers();
        });
        await Promise.allSettled([
          verifyPendingOfflinePayments(),
          refreshSettlementProfile(),
          publishNativePeers(),
        ]);
      } catch (error) {
        console.warn('Blee Mesh v2 native runtime is unavailable', error);
      }
    })();

    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        void BleeMesh.start().catch(() => undefined);
        void verifyPendingOfflinePayments();
        void refreshSettlementProfile();
        void publishNativePeers();
        refreshLedger();
      }
    };
    const onFocus = () => {
      void BleeMesh.start().catch(() => undefined);
      void verifyPendingOfflinePayments();
      void refreshSettlementProfile();
      void publishNativePeers();
      refreshLedger();
    };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', onFocus);

    return () => {
      active = false;
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', onFocus);
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
      ledgerListener?.remove().catch(() => undefined);
      peerListener?.remove().catch(() => undefined);
    };
  }, []);

  const rearmBluetooth = async () => {
    setDiagnosticAction('Restarting Bluetooth discovery…');
    try {
      await BleeMesh.rearmBluetooth();
      setDiagnosticAction('Restart requested. Watching the BLE path…');
      window.setTimeout(async () => {
        try { setDiagnostics(await BleeMesh.diagnostics()); } catch {}
      }, 800);
    } catch (error) {
      setDiagnosticAction(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <>
      <BleeApp />
      {nativeReady && (
        <button
          type="button"
          aria-label="Open Bluetooth diagnostics"
          onClick={() => setDiagnosticsOpen(true)}
          style={{
            position: 'fixed', right: 12, bottom: 'calc(78px + env(safe-area-inset-bottom))', zIndex: 1200,
            minWidth: 42, height: 30, padding: '0 10px', borderRadius: 999, border: '1px solid rgba(0,0,0,.14)',
            background: '#111', color: '#fff', fontSize: 11, fontWeight: 700, letterSpacing: '.04em',
            boxShadow: '0 6px 20px rgba(0,0,0,.15)',
          }}
        >
          BLE
        </button>
      )}

      {nativeReady && diagnosticsOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Bluetooth diagnostics"
          onClick={(event) => { if (event.currentTarget === event.target) setDiagnosticsOpen(false); }}
          style={{
            position: 'fixed', inset: 0, zIndex: 2200, background: 'rgba(0,0,0,.34)', display: 'flex',
            alignItems: 'flex-end', justifyContent: 'center', paddingTop: 40,
          }}
        >
          <div
            style={{
              width: '100%', maxWidth: 560, maxHeight: '86vh', overflowY: 'auto', background: '#f7f6f2', color: '#111',
              borderRadius: '24px 24px 0 0', padding: '20px 18px calc(18px + env(safe-area-inset-bottom))',
              boxShadow: '0 -14px 44px rgba(0,0,0,.18)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 10 }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '.08em', opacity: .55 }}>BLE DIAGNOSTICS</div>
                <div style={{ fontSize: 23, fontWeight: 760, lineHeight: 1.15, marginTop: 3 }}>Nearby transport</div>
              </div>
              <button
                type="button"
                onClick={() => setDiagnosticsOpen(false)}
                style={{ width: 36, height: 36, borderRadius: 18, border: '1px solid rgba(0,0,0,.12)', background: '#fff', fontSize: 18 }}
              >
                ×
              </button>
            </div>

            <div style={{ padding: '14px 15px', borderRadius: 16, background: '#111', color: '#fff', marginBottom: 14 }}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4 }}>Current diagnosis</div>
              <div style={{ fontSize: 14, lineHeight: 1.45, opacity: .86 }}>{diagnosticSummary(diagnostics)}</div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr', border: '1px solid rgba(0,0,0,.08)', borderRadius: 16, overflow: 'hidden', background: '#fff' }}>
              {DIAGNOSTIC_ROWS.map(([key, label], index) => (
                <div
                  key={key}
                  style={{
                    display: 'flex', justifyContent: 'space-between', gap: 18, padding: '10px 12px', fontSize: 12,
                    borderTop: index === 0 ? 'none' : '1px solid rgba(0,0,0,.06)',
                  }}
                >
                  <span style={{ opacity: .58 }}>{label}</span>
                  <span style={{ fontWeight: 650, textAlign: 'right', wordBreak: 'break-word' }}>{formatValue(key, diagnostics?.[key])}</span>
                </div>
              ))}
            </div>

            {diagnosticAction && <div style={{ fontSize: 12, opacity: .65, marginTop: 10 }}>{diagnosticAction}</div>}

            <button
              type="button"
              onClick={() => void rearmBluetooth()}
              style={{
                width: '100%', height: 48, border: 0, borderRadius: 15, background: '#111', color: '#fff',
                fontSize: 14, fontWeight: 720, marginTop: 14,
              }}
            >
              Restart Bluetooth discovery
            </button>
            <div style={{ fontSize: 11, lineHeight: 1.45, opacity: .5, marginTop: 10, textAlign: 'center' }}>
              Keep Wi-Fi off on both phones while testing. This panel refreshes automatically.
            </div>
          </div>
        </div>
      )}
    </>
  );
}
