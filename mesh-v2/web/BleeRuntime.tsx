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

type MeshPlugin = {
  start(): Promise<{ running: boolean; protocol: string }>;
  status(): Promise<MeshStatus>;
  ensureNotificationPermission(): Promise<{ granted?: boolean } | void>;
  pendingEnvelopes(): Promise<{ packets: string[] }>;
  nearbyPeers(): Promise<{ peers: MeshPeerSnapshot[] }>;
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

export default function BleeRuntime() {
  // BLEE_RUNTIME_NO_REMOUNT_V1
  // This revision intentionally re-renders the parent without changing the
  // BleeApp element identity. The old key={`ledger-${revision}`} forced a full
  // unmount/remount on focus/visibility/native-ledger events and wiped the
  // unlocked in-memory wallet session whenever the user left and returned.
  const [, setRevision] = useState(0);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const processing = useRef(false);

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

  return <BleeApp />;
}
