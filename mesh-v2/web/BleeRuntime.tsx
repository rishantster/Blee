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

type MeshPlugin = {
  start(): Promise<{ running: boolean; protocol: string }>;
  status(): Promise<MeshStatus>;
  ensureNotificationPermission(): Promise<{ granted?: boolean } | void>;
  pendingEnvelopes(): Promise<{ packets: string[] }>;
  acceptEnvelope(options: { messageId: string }): Promise<{ accepted: boolean; paymentId?: string }>;
  addListener(
    eventName: 'ledgerChanged',
    listener: (event: { paymentId?: string; eventType?: string }) => void,
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
  const [revision, setRevision] = useState(0);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const processing = useRef(false);

  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return;
    let active = true;
    let listener: PluginListenerHandle | null = null;

    const refreshLedger = () => {
      if (!active) return;
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
      refreshTimer.current = setTimeout(() => {
        if (active) setRevision((value) => value + 1);
      }, 180);
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
        listener = await BleeMesh.addListener('ledgerChanged', () => {
          void verifyPendingOfflinePayments();
          refreshLedger();
        });
        await Promise.allSettled([verifyPendingOfflinePayments(), refreshSettlementProfile()]);
      } catch (error) {
        console.warn('Blee Mesh v2 native runtime is unavailable', error);
      }
    })();

    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        void verifyPendingOfflinePayments();
        void refreshSettlementProfile();
        refreshLedger();
      }
    };
    const onFocus = () => {
      void verifyPendingOfflinePayments();
      void refreshSettlementProfile();
      refreshLedger();
    };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', onFocus);

    return () => {
      active = false;
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', onFocus);
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
      listener?.remove().catch(() => undefined);
    };
  }, []);

  return <BleeApp key={`ledger-${revision}`} />;
}
