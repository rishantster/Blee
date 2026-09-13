'use client';

import { useEffect, useRef, useState } from 'react';
import { Capacitor, registerPlugin, type PluginListenerHandle } from '@capacitor/core';
import type { Address } from 'viem';
import { BleeApp } from './BleeApp';
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
  avatar?: string | null;
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
  rejectEnvelope(options: { messageId: string; reason: string }): Promise<{ rejected: boolean }>;
  addListener(
    eventName: 'ledgerChanged' | 'peerChanged',
    listener: (event: Record<string, unknown>) => void,
  ): Promise<PluginListenerHandle>;
};

const BleeMesh = registerPlugin<MeshPlugin>('BleeMesh');

// BLEE_CANONICAL_WALLET_CASE_V1
const bleeCanonicalWallet = (value: unknown) => {
  const raw = String(value || '').trim();
  return /^0x[0-9a-fA-F]{40}$/.test(raw) ? raw.toLowerCase() : raw;
};


// BLEE_CONTACTS_RUNTIME_UI_DISABLED_STABILITY_V1

// BLEE_SOFT_REFRESH_NATIVE_BRIDGE_V2
// Pull-to-refresh must never reload the WebView because the unlocked vault
// session is intentionally memory-resident. Re-query native/durable state in
// place and wake the same projection paths used for real ledger/peer events.
if (typeof window !== 'undefined' && !(window as any).__bleeSoftRefreshNativeInstalled) {
  (window as any).__bleeSoftRefreshNativeInstalled = true;
  window.addEventListener('blee:refresh-all', () => {
    void (async () => {
      try { await (BleeMesh as any).manualRefresh?.(); } catch {}
      try {
        const snapshot = await (BleeMesh as any).nearbyPeers?.();
        const peers = Array.isArray(snapshot?.peers) ? snapshot.peers : [];
        (window as any).__bleeMeshPeers = peers;
        window.dispatchEvent(new CustomEvent('blee:native-nearby', { detail: { peers } }));
      } catch {}
      try { await (BleeMesh as any).pendingEnvelopes?.(); } catch {}

      // Existing app hooks use these lifecycle signals for network balance,
      // settlement receipt and persisted-state reconciliation. They are safe
      // because the document itself is not replaced.
      try { window.dispatchEvent(new Event('focus')); } catch {}
      try { window.dispatchEvent(new Event('online')); } catch {}
      try { window.dispatchEvent(new Event('pageshow')); } catch {}
      try { document.dispatchEvent(new Event('visibilitychange')); } catch {}
      window.setTimeout(() => {
        window.dispatchEvent(new CustomEvent('blee:refresh-complete'));
      }, 520);
    })();
  });
}


// BLEE_PRODUCTION_EVENT_UI_V1
const SHOW_INTERNAL_DIAGNOSTICS = false;

// BLEE_CANONICAL_WALLET_TEXT_V1
if (typeof window !== 'undefined' && typeof document !== 'undefined' && !(window as any).__bleeWalletCaseNormalizerInstalled) {
  (window as any).__bleeWalletCaseNormalizerInstalled = true;
  let queued = false;
  const normalizeWalletText = () => {
    queued = false;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const updates: Array<[Text, string]> = [];
    while (walker.nextNode()) {
      const node = walker.currentNode as Text;
      const value = node.nodeValue || '';
      if (!/0x[0-9a-fA-F]{40}/.test(value)) continue;
      const parent = node.parentElement;
      if (parent && /^\s*0x[0-9a-fA-F]{40}\s*$/.test(value)) {
        parent.classList.add('blee-canonical-wallet-text');
      }
      const next = value.replace(/0x[0-9a-fA-F]{40}/g, (address) => address.toLowerCase());
      if (next !== value) updates.push([node, next]);
    }
    for (const [node, next] of updates) node.nodeValue = next;
  };
  const queueWalletTextNormalization = () => {
    if (queued) return;
    queued = true;
    window.requestAnimationFrame(normalizeWalletText);
  };
  const observer = new MutationObserver(queueWalletTextNormalization);
  window.addEventListener('DOMContentLoaded', () => {
    observer.observe(document.body, { subtree: true, childList: true, characterData: true });
    queueWalletTextNormalization();
  }, { once: true });
  if (document.readyState !== 'loading') {
    observer.observe(document.body, { subtree: true, childList: true, characterData: true });
    queueWalletTextNormalization();
  }
}


// BLEE_SOFT_REFRESH_V2
// Native-style pull-to-refresh. The WebView and unlocked wallet session stay
// alive; only application data/projections are re-queried.
if (typeof window !== 'undefined' && typeof document !== 'undefined' && !(window as any).__bleeSoftRefreshInstalled) {
  (window as any).__bleeSoftRefreshInstalled = true;
  let startY = 0;
  let pull = 0;
  let tracking = false;
  let refreshing = false;
  const threshold = 74;

  const ensureIndicator = () => {
    let node = document.getElementById('blee-pull-refresh-indicator');
    if (!node) {
      node = document.createElement('div');
      node.id = 'blee-pull-refresh-indicator';
      node.innerHTML = '<span></span>';
      document.body.appendChild(node);
    }
    return node;
  };

  const ensureRefreshSplash = () => {
    let node = document.getElementById('blee-refresh-splash');
    if (!node) {
      node = document.createElement('div');
      node.id = 'blee-refresh-splash';
      node.innerHTML = '<div class="blee-refresh-mark"><img src="/brand/blee-logo.svg" alt="" /></div>';
      document.body.appendChild(node);
    }
    return node;
  };

  const playSoftSwish = () => {
    try {
      const AudioContextCtor = (window as any).AudioContext || (window as any).webkitAudioContext;
      if (!AudioContextCtor) return;
      const ctx = new AudioContextCtor();
      const duration = 0.38;
      const frames = Math.max(1, Math.floor(ctx.sampleRate * duration));
      const buffer = ctx.createBuffer(1, frames, ctx.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < frames; i += 1) {
        const t = i / frames;
        const envelope = Math.sin(Math.PI * t) * (1 - t * 0.34);
        data[i] = (Math.random() * 2 - 1) * envelope * 0.18;
      }
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      const filter = ctx.createBiquadFilter();
      filter.type = 'bandpass';
      filter.Q.value = 0.72;
      filter.frequency.setValueAtTime(420, ctx.currentTime);
      filter.frequency.exponentialRampToValueAtTime(1900, ctx.currentTime + duration * 0.55);
      filter.frequency.exponentialRampToValueAtTime(760, ctx.currentTime + duration);
      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + 0.07);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + duration);
      source.connect(filter);
      filter.connect(gain);
      gain.connect(ctx.destination);
      source.start();
      source.stop(ctx.currentTime + duration);
      window.setTimeout(() => { try { void ctx.close(); } catch {} }, 650);
    } catch {}
  };

  const setPull = (value: number) => {
    pull = Math.max(0, Math.min(104, value));
    document.documentElement.style.setProperty('--blee-pull-offset', `${Math.round(pull * 0.46)}px`);
    document.documentElement.classList.toggle('blee-pulling', pull > 0);
    const node = ensureIndicator();
    node.style.setProperty('--blee-pull-progress', String(Math.min(1, pull / threshold)));
    node.classList.toggle('ready', pull >= threshold);
  };

  const resetPull = () => {
    tracking = false;
    if (!refreshing) {
      setPull(0);
      document.documentElement.classList.remove('blee-pulling');
    }
  };

  const finishRefresh = () => {
    if (!refreshing) return;
    refreshing = false;
    ensureIndicator().classList.remove('refreshing');
    ensureRefreshSplash().classList.remove('visible');
    document.documentElement.classList.remove('blee-refreshing');
    document.documentElement.style.setProperty('--blee-pull-offset', '0px');
    setPull(0);
  };

  const refreshAll = () => {
    if (refreshing) return;
    refreshing = true;
    const indicator = ensureIndicator();
    const splash = ensureRefreshSplash();
    indicator.classList.add('refreshing');
    splash.classList.remove('visible');
    // restart CSS animation even for rapid consecutive refreshes
    void splash.offsetWidth;
    splash.classList.add('visible');
    document.documentElement.classList.add('blee-refreshing');
    document.documentElement.style.setProperty('--blee-pull-offset', '24px');
    playSoftSwish();
    window.dispatchEvent(new CustomEvent('blee:refresh-all', { detail: { source: 'gesture' } }));
    window.setTimeout(finishRefresh, 920);
  };

  window.addEventListener('blee:refresh-complete', () => {
    // Keep the branded animation visible long enough to feel deliberate rather
    // than flash, but finish promptly once all projections have been woken.
    window.setTimeout(finishRefresh, 260);
  });

  document.addEventListener('touchstart', (event) => {
    if (refreshing || window.scrollY > 1 || event.touches.length !== 1) return;
    const target = event.target as HTMLElement | null;
    if (target?.closest('input,textarea,select,[contenteditable="true"],button')) return;
    startY = event.touches[0].clientY;
    pull = 0;
    tracking = true;
  }, { passive: true });

  document.addEventListener('touchmove', (event) => {
    if (!tracking || event.touches.length !== 1) return;
    const delta = event.touches[0].clientY - startY;
    if (delta <= 0) { resetPull(); return; }
    if (window.scrollY > 1) { resetPull(); return; }
    event.preventDefault();
    setPull(Math.pow(delta, 0.86));
  }, { passive: false });

  document.addEventListener('touchend', () => {
    if (!tracking) return;
    const shouldRefresh = pull >= threshold;
    tracking = false;
    if (shouldRefresh) refreshAll();
    else resetPull();
  }, { passive: true });
  document.addEventListener('touchcancel', resetPull, { passive: true });

  // The legacy funds-card refresh control now drives the exact same complete,
  // non-destructive refresh instead of owning a separate/stale balance path.
  document.addEventListener('click', (event) => {
    const button = (event.target as HTMLElement | null)?.closest('button');
    if (!button) return;
    if (button.closest('#blee-refresh-splash')) return;
    const label = `${button.getAttribute('aria-label') || ''} ${button.getAttribute('title') || ''} ${button.textContent || ''}`.trim().toLowerCase();
    if (label === 'refresh' || label.includes('refresh balance') || label.includes('refresh funds') || label.includes('refresh wallet')) {
      event.preventDefault();
      event.stopPropagation();
      refreshAll();
    }
  }, true);
}


// BLEE_WALLET_CANONICAL_PEERS_V1
function canonicalizeBleePeers(input: any[]) {
  const byWallet = new Map<string, any>();
  const unresolved: any[] = [];
  for (const peer of Array.isArray(input) ? input : []) {
    if (!peer) continue;
    const wallet = String(peer.wallet || '').toLowerCase();
    if (!/^0x[0-9a-f]{40}$/.test(wallet)) {
      unresolved.push(peer);
      continue;
    }
    const previous = byWallet.get(wallet);
    if (!previous) {
      byWallet.set(wallet, { ...peer, wallet });
      continue;
    }
    const previousName = String(previous.displayName || '').trim();
    const nextName = String(peer.displayName || '').trim();
    const previousAvatar = String(previous.avatar || '').trim();
    const nextAvatar = String(peer.avatar || '').trim();
    const previousSeen = Number(previous.lastSeen || 0);
    const nextSeen = Number(peer.lastSeen || 0);
    const fresher = nextSeen >= previousSeen ? peer : previous;
    byWallet.set(wallet, {
      ...previous,
      ...fresher,
      wallet,
      displayName: nextName || previousName,
      avatar: nextAvatar || previousAvatar,
      lastSeen: Math.max(previousSeen, nextSeen),
    });
  }
  return [...byWallet.values(), ...unresolved];
}

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
  // BLEE_RADIO_ARBITRATION_DIAGNOSTICS_V2
  // BLEE_ADAPTIVE_NEARBY_V3_DIAGNOSTICS
  const fallbackMode = String(d.fallbackMode || 'ble_primary');
  if (fallbackMode === 'nearby_connected') return 'Offline fallback connected. Blee is using the local Nearby transport because raw GATT could not establish reliably.';
  if (fallbackMode === 'nearby_active' || fallbackMode === 'nearby_starting') {
    const detail = String(d.lastNearbyError || '').trim();
    return detail
      ? `Raw BLE could not establish a stable link. Offline fallback is retrying (${detail}).`
      : 'Raw BLE could not establish a stable link. Blee switched to the offline Nearby transport.';
  }
  if (fallbackMode === 'permission_required') return 'Blee needs Nearby devices permission before it can use the offline fallback transport.';
  const radioMode = String(d.radioMode || '');
  const advertiserSlotBusy = String(d.lastAdvertiseError || '') === 'advertise_error_2'
    || numberValue(d.advertiserResourceFailures) > 0;
  if (!bool(d.scannerActive) && !bool(d.gattScanPaused)) return 'Blee is not currently scanning over Bluetooth.';
  if (numberValue(d.rawScanResults) === 0) return 'Scanner is active, but this phone has not seen any BLE advertisements yet.';
  if (numberValue(d.bleeAdvertisements) === 0) {
    return advertiserSlotBusy && radioMode === 'scanner_first'
      ? 'This phone has no free advertiser slot, so Blee switched to scanner-first mode and is waiting to see the other phone.'
      : 'Bluetooth scanning works, but no Blee advertisement has been detected.';
  }
  // BLEE_GATT_INTEROP_DIAGNOSTICS_V1
  if (d.lastScanConnectable === false) return 'Blee sees the other phone, but Android reports its BLE advertisement as non-connectable.';
  if (numberValue(d.gattAttempts) === 0) return 'A Blee advertisement was seen. Blee is coordinating which phone should open the GATT link.';
  if (numberValue(d.gattConnected) === 0) {
    if (numberValue(d.gattConnectionCallbacks) === 0) {
      return `Android accepted the ${String(d.lastConnectStrategy || 'BLE')} connection request but has not returned a GATT callback yet.`;
    }
    const detail = String(d.lastGattError || '').trim();
    return detail
      ? `Blee sees the other phone, but the GATT handshake is retrying (${detail}).`
      : `Android returned GATT status ${String(d.lastNativeGattStatus)} / state ${String(d.lastNativeGattState)}.`;
  }
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
  // BLEE_TRANSPORT_CORE_V2_DIAGNOSTICS
  ['transportEngine', 'Transport engine'],
  ['fallbackMode', 'Adaptive fallback'],
  ['fallbackReason', 'Fallback reason'],
  ['gatt147Count', 'GATT 147 timeouts'],
  ['nearbyAdvertising', 'Nearby fallback advertising'],
  ['nearbyDiscovering', 'Nearby fallback discovery'],
  ['nearbyEndpointsFound', 'Nearby endpoints found'],
  ['nearbyConnections', 'Nearby connections'],
  ['nearbyConnectedNow', 'Nearby connected now'],
  ['lastNearbyStatus', 'Last Nearby status'],
  ['lastNearbyError', 'Last Nearby error'],
  ['radioMode', 'Radio mode'],
  ['advertiserResourceFailures', 'Advertiser slot failures'],
  ['gattScanPaused', 'Scan paused for GATT'],
  ['gattServerActive', 'GATT server active'],
  ['gattServerReady', 'Blee GATT service ready'],
  ['serverConnections', 'Incoming GATT connections'],
  ['lastScanConnectable', 'Last Blee advertisement connectable'],
  ['lastAddressType', 'Last BLE address type'],
  ['lastDeviceType', 'Last BLE device type'],
  ['lastConnectStrategy', 'GATT connection strategy'],
  ['gattConnectionCallbacks', 'Android GATT callbacks'],
  ['lastNativeGattStatus', 'Last native GATT status'],
  ['lastNativeGattState', 'Last native GATT state'],
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
  ['lastServerPeer', 'Last incoming BLE device'],
  ['lastServerStatus', 'Last incoming GATT status'],
  ['lastServerState', 'Last incoming GATT state'],
  ['lastAdvertiseError', 'Last advertise error'],
  ['lastGattError', 'Last GATT error'],
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
    if (!SHOW_INTERNAL_DIAGNOSTICS || !nativeReady || !diagnosticsOpen) return;
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
      }, 24);
    };

    const publishNativePeerEvent = (event: Record<string, unknown>) => {
      if (!active) return;
      const transportId = String(event.transportId || '');
      if (!transportId) return;
      const current = Array.isArray((window as any).__bleeMeshPeers) ? [...(window as any).__bleeMeshPeers] : [];
      const index = current.findIndex((peer: any) => String(peer?.transportId || '') === transportId);
      if (event.present === false) {
        if (index >= 0) current.splice(index, 1);
      } else {
        const next = {
          ...(index >= 0 ? current[index] : {}),
          transportId,
          wallet: bleeCanonicalWallet(event.wallet),
          displayName: event.displayName,
          avatar: event.avatar,
          rssi: event.rssi,
          lastSeen: event.lastSeen,
          transport: event.transport || 'ble',
        };
        if (index >= 0) current[index] = next;
        else current.push(next);
      }
      const canonical = canonicalizeBleePeers(current);
      (window as any).__bleeMeshPeers = canonical;
      window.dispatchEvent(new CustomEvent('blee:native-nearby', { detail: { peers: canonical } }));
    };

    const publishNativePeers = async () => {
      if (!active) return;
      try {
        const { peers } = await BleeMesh.nearbyPeers();
        const snapshots = canonicalizeBleePeers(Array.isArray(peers) ? peers : []);
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
          let messageId = '';
          try {
            const packet = JSON.parse(raw) as Record<string, any>;
            messageId = String(packet.messageId || '');
            const reject = async (reason: string) => {
              if (!messageId) return;
              try { await BleeMesh.rejectEnvelope({ messageId, reason }); } catch {}
            };
            const payment = JSON.parse(String(packet.payload || '{}')) as Record<string, unknown>;
            const auth = authorizationFromPayment(payment);
            if (!auth) { await reject('Payment authorization is missing or malformed'); continue; }
            if (String(auth.to).toLowerCase() !== wallet) { await reject('Payment authorization recipient does not match this wallet'); continue; }
            if (!(await verifyAuthorization(auth))) { await reject('Payment authorization is invalid or expired'); continue; }
            const result = await BleeMesh.acceptEnvelope({ messageId });
            accepted = result.accepted || accepted;
          } catch (error) {
            if (messageId) {
              try { await BleeMesh.rejectEnvelope({ messageId, reason: 'Payment envelope could not be decoded safely' }); } catch {}
            }
            console.warn('Rejected invalid Blee Mesh payment envelope', error);
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
        peerListener = await BleeMesh.addListener('peerChanged', (event) => {
          publishNativePeerEvent(event);
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
    setDiagnosticAction('Restarting nearby transport…');
    try {
      await BleeMesh.rearmBluetooth();
      setDiagnosticAction('Restart requested. Watching the nearby transport…');
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
      {SHOW_INTERNAL_DIAGNOSTICS && nativeReady && (
        <button
          type="button"
          aria-label="Open nearby transport diagnostics"
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

      {SHOW_INTERNAL_DIAGNOSTICS && nativeReady && diagnosticsOpen && (
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
              Restart nearby transport
            </button>
            <div style={{ fontSize: 11, lineHeight: 1.45, opacity: .5, marginTop: 10, textAlign: 'center' }}>
              Keep Bluetooth and Wi-Fi enabled. Internet can stay off. This panel refreshes automatically.
            </div>
          </div>
        </div>
      )}
    </>
  );
}
