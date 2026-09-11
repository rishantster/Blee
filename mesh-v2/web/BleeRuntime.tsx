'use client';

import { useEffect, useRef, useState } from 'react';
import { Capacitor, registerPlugin, type PluginListenerHandle } from '@capacitor/core';
import BleeApp from '../../src/components/BleeApp';

type MeshStatus = {
  running: boolean;
  protocol: string;
  wallet?: string | null;
  relayMode?: string;
  relayConfigured?: boolean;
};

type MeshPlugin = {
  start(): Promise<{ running: boolean; protocol: string }>;
  status(): Promise<MeshStatus>;
  ensureNotificationPermission(): Promise<{ granted?: boolean } | void>;
  addListener(
    eventName: 'ledgerChanged',
    listener: (event: { paymentId?: string; eventType?: string }) => void,
  ): Promise<PluginListenerHandle>;
};

const BleeMesh = registerPlugin<MeshPlugin>('BleeMesh');

export default function BleeRuntime() {
  const [revision, setRevision] = useState(0);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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

    (async () => {
      try {
        await BleeMesh.start();
        await BleeMesh.ensureNotificationPermission();
        listener = await BleeMesh.addListener('ledgerChanged', refreshLedger);
      } catch (error) {
        console.warn('Blee Mesh v2 native runtime is unavailable', error);
      }
    })();

    const onVisible = () => {
      if (document.visibilityState === 'visible') refreshLedger();
    };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', refreshLedger);

    return () => {
      active = false;
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', refreshLedger);
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
      listener?.remove().catch(() => undefined);
    };
  }, []);

  return <BleeApp key={`ledger-${revision}`} />;
}
