// BLEE_EXPLICIT_LOGOUT_ONLY: wallet remains unlocked until explicit logout while process is alive.
// BLEE_PERSISTENT_SESSION: explicit logout only; no inactivity auto-lock.
'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { formatUnits, getAddress, isAddress, parseUnits, type Address, type Hex } from 'viem';
import type { PrivateKeyAccount } from 'viem/accounts';
import type { MeshPacket, MeshPeer, PaymentRecord, TransferAuthorization } from '../types/domain';
import { hasVault, createVault, unlockVault, getVaultAddress } from '../lib/vault';
import {
  authorizationExpired,
  authorizationUsed,
  checkArc,
  createAuthorization,
  displayAuthAmount,
  getBalance,
  publicClient,
  scanIncomingSettlements,
  submitAuthorization,
  transactionStatus,
  verifyAuthorization,
  verifyReceipt,
} from '../lib/payments';
import {
  getAlias,
  initPersistence,
  loadChainCursor,
  loadLastBalance,
  loadPayments,
  nativePersistenceAvailable,
  saveChainCursor,
  saveLastBalance,
  savePayments,
  setAlias as persistAlias,
} from '../lib/persistence';
import { ARC_USDC_DECIMALS } from '../lib/arc';
import { BleeNearby, nativeNearbyAvailable, nativePlatform } from '../lib/nativeNearby';
import { createMeshPacket, forwarded, FrameAssembler, packetFrames, verifyMeshPacket } from '../lib/meshProtocol';

const HELLO_EVERY_MS = 5_000;
const PEER_STALE_MS = 18_000;
const TRANSPORT_HELLO_COOLDOWN_MS = 2_000;
const NETWORK_TICK_MS = 7_000;
const OFFLINE_RETRY_MS = 6_000;
const SUBMITTED_RECOVERY_MS = 90_000;
const INITIAL_CHAIN_LOOKBACK_BLOCKS = 2_000n;
const transportHelloAt = new Map<string, number>();

type SendResult = { id: string; route: PaymentRecord['route']; state: PaymentRecord['state']; txHash?: Hex };

const STATE_RANK: Record<PaymentRecord['state'], number> = {
  'verification-pending': 0,
  'queued-local': 1,
  'mesh-broadcast': 2,
  'mesh-delivered': 3,
  submitted: 4,
  settled: 5,
  failed: 6,
};

function advanceState(current: PaymentRecord['state'], next: PaymentRecord['state']) {
  if (next === 'settled') return 'settled';
  if (current === 'settled' || current === 'failed') return current;
  if (next === 'failed') return 'failed';
  return STATE_RANK[next] >= STATE_RANK[current] ? next : current;
}

function updateRow(rows: PaymentRecord[], id: string, patch: Partial<PaymentRecord>) {
  const now = Date.now();
  return rows.map((r) => {
    if (r.id !== id) return r;
    return {
      ...r,
      ...patch,
      state: patch.state ? advanceState(r.state, patch.state) : r.state,
      updatedAt: now,
    };
  });
}

function uniquePaymentId(auth: TransferAuthorization): string {
  return `${auth.from}:${auth.nonce}`.toLowerCase();
}

function transportFromId(id: string): 'lan' | 'ble' {
  return id.startsWith('lan:') || id.startsWith('udp:') ? 'lan' : 'ble';
}

function retryDelay(attempts: number) {
  const base = Math.min(60_000, 2_000 * (2 ** Math.min(Math.max(attempts - 1, 0), 5)));
  return base + Math.floor(Math.random() * 900);
}

type PeerIdentity = { alias?: string; avatar?: string; updatedAt: number };

const PROFILE_PHOTO_KEY = 'blee.profile-photo.v1';
const PEER_IDENTITIES_KEY = 'blee.peer-identities.v1';
const MAX_AVATAR_DATA_URL_LENGTH = 24_000;

function storageGet(key: string): string | null {
  try { return typeof window !== 'undefined' ? window.localStorage.getItem(key) : null; } catch { return null; }
}

function storageSet(key: string, value: string | null) {
  try {
    if (typeof window === 'undefined') return;
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {}
}

function safeAlias(value?: string | null) {
  const next = (value || '').trim().replace(/\s+/g, ' ').slice(0, 24);
  return next || undefined;
}

function safeAvatar(value?: string | null) {
  if (!value || value.length > MAX_AVATAR_DATA_URL_LENGTH) return undefined;
  return /^data:image\/(?:png|jpe?g|webp);base64,/i.test(value) ? value : undefined;
}

function loadPeerIdentities(): Record<string, PeerIdentity> {
  try {
    const raw = storageGet(PEER_IDENTITIES_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, PeerIdentity>;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch { return {}; }
}

export function useBlee() {
  const [vaultExists, setVaultExists] = useState(false);
  const [vaultAddress, setVaultAddress] = useState<string | null>(null);
  const [account, setAccount] = useState<PrivateKeyAccount | null>(null);
  const [alias, setAliasState] = useState('blee_user');
  const [profilePhoto, setProfilePhotoState] = useState<string | null>(null);
  const [peerIdentities, setPeerIdentities] = useState<Record<string, PeerIdentity>>({});
  const [balance, setBalance] = useState<string | null>(null);
  const [balanceAt, setBalanceAt] = useState<number | null>(null);
  const [arcReachable, setArcReachable] = useState<boolean | null>(null);
  const [payments, setPaymentsState] = useState<PaymentRecord[]>([]);
  const [peers, setPeers] = useState<MeshPeer[]>([]);

  // BLEE_NATIVE_NEARBY_PEER_MERGE_V1
  // The old UI peer list came from the legacy local-network transport. Native
  // Mesh v2 now publishes Bluetooth-resolved wallets as a second source so
  // discovery works with Wi-Fi completely disabled.
  useEffect(() => {
    if (typeof window === 'undefined') return;

    const applyNativePeers = (input: unknown) => {
      const source = Array.isArray(input) ? input : [];
      const normalized = source
        .filter((raw: any) => raw && typeof raw.transportId === 'string' && /^0x[0-9a-fA-F]{40}$/.test(String(raw.wallet || '')))
        .map((raw: any) => {
          const wallet = String(raw.wallet).toLowerCase();
          const transportId = String(raw.transportId);
          const fallback = `${wallet.slice(0, 6)}…${wallet.slice(-4)}`;
          const displayName = String(raw.displayName || '').trim() || fallback;
          return {
            id: wallet,
            transportId,
            address: wallet,
            wallet,
            walletAddress: wallet,
            recipient: wallet,
            alias: displayName,
            displayName,
            name: displayName,
            // BLEE_PRODUCTION_NATIVE_PEER_MERGE_V1
            avatar: typeof raw.avatar === 'string' && raw.avatar ? raw.avatar : null,
            rssi: Number(raw.rssi || 0),
            lastSeen: Number(raw.lastSeen || Date.now()),
            transport: 'ble',
            source: 'ble',
            authenticated: true,
            __bleeNative: true,
          } as any;
        });

      // BLEE_NATIVE_PRESENCE_AUTHORITATIVE_V1
      // The native snapshot/event is authoritative for whether a native peer is
      // currently present. Previous native rows may enrich name/avatar, but an
      // absent native wallet must not survive forever as a ghost after disconnect.
      setPeers((current: any) => {
        const existing = Array.isArray(current) ? current : [];
        const previousByWallet = new Map<string, any>();
        const legacyByWallet = new Map<string, any>();
        for (const peer of existing) {
          const wallet = String(peer?.wallet || peer?.walletAddress || peer?.address || '').toLowerCase();
          if (!/^0x[0-9a-f]{40}$/.test(wallet)) continue;
          previousByWallet.set(wallet, peer);
          if (!peer?.__bleeNative) legacyByWallet.set(wallet, peer);
        }

        const nextByWallet = new Map<string, any>();
        for (const peer of normalized) {
          const wallet = String(peer.wallet || '').toLowerCase();
          if (!/^0x[0-9a-f]{40}$/.test(wallet)) continue;
          const previous = previousByWallet.get(wallet);
          const legacy = legacyByWallet.get(wallet);
          const nativeHasName = peer.displayName && !peer.displayName.startsWith('0x');
          nextByWallet.set(wallet, {
            ...(legacy || previous || {}),
            ...peer,
            wallet,
            displayName: nativeHasName ? peer.displayName : (previous?.displayName || legacy?.displayName || previous?.name || peer.displayName),
            name: nativeHasName ? peer.displayName : (previous?.name || legacy?.name || previous?.displayName || peer.name),
            alias: nativeHasName ? peer.displayName : (previous?.alias || legacy?.alias || previous?.displayName || peer.alias),
            avatar: peer.avatar || previous?.avatar || legacy?.avatar || null,
          });
        }

        for (const [wallet, peer] of legacyByWallet.entries()) {
          if (!nextByWallet.has(wallet)) nextByWallet.set(wallet, peer);
        }
        const nonWallet = existing.filter((peer: any) => {
          const wallet = String(peer?.wallet || peer?.walletAddress || peer?.address || '').toLowerCase();
          return !/^0x[0-9a-f]{40}$/.test(wallet) && !peer?.__bleeNative;
        });
        return [...nonWallet, ...nextByWallet.values()] as any;
      });
    };

    const initial = (window as any).__bleeMeshPeers;
    if (Array.isArray(initial)) applyNativePeers(initial);

    const onNativePeers = (event: Event) => {
      const detail = (event as CustomEvent<{ peers?: unknown[] }>).detail;
      applyNativePeers(detail?.peers ?? (window as any).__bleeMeshPeers ?? []);
    };
    window.addEventListener('blee:native-nearby', onNativePeers as EventListener);
    return () => window.removeEventListener('blee:native-nearby', onNativePeers as EventListener);
  }, []);
  const [meshStarted, setMeshStarted] = useState(false);
  const [meshState, setMeshState] = useState('stopped');
  const [relayEnabled, setRelayEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [persistenceReady, setPersistenceReady] = useState(false);
  const [persistenceMode, setPersistenceMode] = useState<'sqlite' | 'unavailable'>('unavailable');
  const [storageError, setStorageError] = useState<string | null>(null);
  const bleAvailable = nativeNearbyAvailable();
  const platform = nativePlatform();

  const accountRef = useRef<PrivateKeyAccount | null>(null);
  const aliasRef = useRef('blee_user');
  const profilePhotoRef = useRef<string | null>(null);
  const peerIdentitiesRef = useRef<Record<string, PeerIdentity>>({});
  const balanceRef = useRef<string | null>(null);
  const paymentsRef = useRef<PaymentRecord[]>([]);
  const peersRef = useRef<MeshPeer[]>([]);
  const arcRef = useRef<boolean>(false);
  const meshStartedRef = useRef(false);
  const relayRef = useRef(true);
  const seenRef = useRef(new Map<string, number>());
  const assemblerRef = useRef(new FrameAssembler());
  const listenerHandles = useRef<Array<{ remove: () => Promise<void> }>>([]);
  const settlementLocksRef = useRef(new Set<string>());
  const persistenceQueueRef = useRef<Promise<void>>(Promise.resolve());
  const tickRunningRef = useRef(false);
  const nearbyRetryRunningRef = useRef(false);
  const sendQueueRef = useRef<Promise<void>>(Promise.resolve());

  /**
   * Serialize every payment journal mutation through SQLite. React is updated
   * only after the native transaction commits. This is what makes ACK mean
   * "the receiver has a durable copy", not merely "a BLE packet arrived".
   */
  const commitPayments = useCallback(async (
    updater: PaymentRecord[] | ((rows: PaymentRecord[]) => PaymentRecord[]),
  ): Promise<PaymentRecord[]> => {
    let committed: PaymentRecord[] = paymentsRef.current;
    const work = persistenceQueueRef.current.then(async () => {
      const current = paymentsRef.current;
      const next = typeof updater === 'function' ? updater(current) : updater;
      committed = await savePayments(next);
      paymentsRef.current = committed;
      setPaymentsState(committed);
    });
    persistenceQueueRef.current = work.catch(() => undefined);
    await work;
    return committed;
  }, []);

  useEffect(() => {
    let dead = false;
    (async () => {
      try {
        const info = await initPersistence();
        const [storedAlias, storedPayments, vaultPresent, storedVaultAddress] = await Promise.all([
          getAlias(), loadPayments(), hasVault(), getVaultAddress(),
        ]);
        if (dead) return;
        aliasRef.current = storedAlias;
        setAliasState(storedAlias);
        const storedPhoto = safeAvatar(storageGet(PROFILE_PHOTO_KEY)) || null;
        const storedIdentities = loadPeerIdentities();
        profilePhotoRef.current = storedPhoto;
        peerIdentitiesRef.current = storedIdentities;
        setProfilePhotoState(storedPhoto);
        setPeerIdentities(storedIdentities);
        const restoredAt = Date.now();
        const restoredPayments = storedPayments.map((row) => {
          if (!row.authorization || row.state === 'settled' || row.state === 'failed') return row;
          if (!authorizationExpired(row.authorization)) return row;
          return {
            ...row,
            state: 'failed' as const,
            error: 'Payment authorization expired before settlement',
            nextRetryAt: undefined,
            updatedAt: restoredAt,
          };
        });
        const durablePayments = restoredPayments.some((row, index) => row !== storedPayments[index])
          ? await savePayments(restoredPayments)
          : restoredPayments;
        paymentsRef.current = durablePayments;
        setPaymentsState(durablePayments);
        setVaultExists(vaultPresent);
        setVaultAddress(storedVaultAddress);
        setPersistenceMode(info.native ? 'sqlite' : 'unavailable');
        setStorageError(null);
      } catch (error) {
        if (!dead) {
          setPersistenceMode('unavailable');
          setStorageError(error instanceof Error ? error.message : 'Native SQLite payment storage is unavailable');
        }
      } finally {
        if (!dead) setPersistenceReady(true);
      }
    })();
    return () => { dead = true; };
  }, []);

  useEffect(() => {
    accountRef.current = account;
    if (!account) return;
    let dead = false;
    loadLastBalance(account.address).then((cached) => {
      if (!dead && cached) { balanceRef.current = cached.value; setBalance(cached.value); setBalanceAt(cached.at); }
    }).catch(() => undefined);
    return () => { dead = true; };
  }, [account]);

  useEffect(() => { balanceRef.current = balance; }, [balance]);
  useEffect(() => { peersRef.current = peers; }, [peers]);
  useEffect(() => { profilePhotoRef.current = profilePhoto; }, [profilePhoto]);
  useEffect(() => { peerIdentitiesRef.current = peerIdentities; }, [peerIdentities]);
  useEffect(() => { arcRef.current = Boolean(arcReachable); }, [arcReachable]);
  useEffect(() => { meshStartedRef.current = meshStarted; }, [meshStarted]);
  useEffect(() => { relayRef.current = relayEnabled; }, [relayEnabled]);

  const reservedUnits = useMemo(() => payments
    .filter((p) => p.direction === 'out' && p.state !== 'settled' && p.state !== 'failed' && p.authorization)
    .reduce((sum, p) => sum + BigInt(p.authorization!.value), 0n), [payments]);

  const pendingIncomingUnits = useMemo(() => payments
    .filter((p) => p.direction === 'in' && (p.state === 'mesh-delivered' || p.state === 'submitted') && p.authorization)
    .reduce((sum, p) => sum + BigInt(p.authorization!.value), 0n), [payments]);

  const reserved = Number(formatUnits(reservedUnits, ARC_USDC_DECIMALS));
  const pendingIncoming = Number(formatUnits(pendingIncomingUnits, ARC_USDC_DECIMALS));
  const available = useMemo(() => {
    if (balance === null) return null;
    try {
      const confirmed = parseUnits(balance, ARC_USDC_DECIMALS);
      const spendable = confirmed > reservedUnits ? confirmed - reservedUnits : 0n;
      return Number(formatUnits(spendable, ARC_USDC_DECIMALS));
    } catch { return 0; }
  }, [balance, reservedUnits]);

  const setAlias = useCallback((value: string) => {
    const safe = value.trim().replace(/\s+/g, ' ').slice(0, 24) || 'blee_user';
    aliasRef.current = safe;
    setAliasState(safe);
    persistAlias(safe).catch(() => undefined);
  }, []);

  const rememberIdentity = useCallback((address: string, nextAlias?: string | null, nextAvatar?: string | null) => {
    if (!isAddress(address)) return;
    const key = address.toLowerCase();
    const aliasValue = safeAlias(nextAlias);
    const avatarValue = safeAvatar(nextAvatar);
    if (!aliasValue && !avatarValue) return;
    const current = peerIdentitiesRef.current[key] || { updatedAt: 0 };
    const resolvedAlias = aliasValue || current.alias;
    const resolvedAvatar = avatarValue || current.avatar;
    if (resolvedAlias === current.alias && resolvedAvatar === current.avatar) return;
    const next: PeerIdentity = {
      alias: resolvedAlias,
      avatar: resolvedAvatar,
      updatedAt: Date.now(),
    };
    const all = { ...peerIdentitiesRef.current, [key]: next };
    peerIdentitiesRef.current = all;
    setPeerIdentities(all);
    storageSet(PEER_IDENTITIES_KEY, JSON.stringify(all));

    if (aliasValue && paymentsRef.current.some((row) =>
      row.counterparty.toLowerCase() === key && row.counterpartyAlias !== aliasValue)) {
      commitPayments((rows) => rows.map((row) =>
        row.counterparty.toLowerCase() === key && row.counterpartyAlias !== aliasValue
          ? { ...row, counterpartyAlias: aliasValue, updatedAt: Date.now() }
          : row)).catch(() => undefined);
    }
  }, [commitPayments]);

  const identityFor = useCallback((address?: string | null) => {
    if (!address) return undefined;
    return peerIdentitiesRef.current[address.toLowerCase()];
  }, []);

  const setProfilePhoto = useCallback((value: string | null) => {
    const clean = value ? safeAvatar(value) : undefined;
    if (value && !clean) throw new Error('Profile photo is too large or unsupported');
    const next = clean || null;
    profilePhotoRef.current = next;
    setProfilePhotoState(next);
    storageSet(PROFILE_PHOTO_KEY, next);
  }, []);

  const create = useCallback(async (passphrase: string) => {
    setBusy(true);
    try {
      const next = await createVault(passphrase);
      setAccount(next);
      accountRef.current = next;
      setVaultExists(true);
      setVaultAddress(next.address);
      return next.address;
    } finally { setBusy(false); }
  }, []);

  const unlock = useCallback(async (passphrase: string) => {
    setBusy(true);
    try {
      const next = await unlockVault(passphrase);
      setAccount(next);
      accountRef.current = next;
      setVaultAddress(next.address);
      return next.address;
    } finally { setBusy(false); }
  }, []);

  const lock = useCallback(async () => {
    if (meshStartedRef.current && nativeNearbyAvailable()) {
      await BleeNearby.stopMesh().catch(() => undefined);
    }
    for (const h of listenerHandles.current) await h.remove().catch(() => undefined);
    listenerHandles.current = [];
    setMeshStarted(false);
    meshStartedRef.current = false;
    setPeers([]);
    setAccount(null);
    accountRef.current = null;
    balanceRef.current = null;
    setBalance(null);
    setBalanceAt(null);
    // Deliberately do NOT clear payments. SQLite remains the source of truth
    // across lock/logout, process death, phone reboot and ordinary cache clears.
  }, []);

  const refreshBalance = useCallback(async () => {
    const a = accountRef.current;
    if (!a) return null;
    const fresh = await getBalance(a.address);
    const at = Date.now();
    await saveLastBalance(a.address, fresh, at).catch(() => undefined);
    balanceRef.current = fresh;
    setBalance(fresh);
    setBalanceAt(at);
    return fresh;
  }, []);

  const refreshNetwork = useCallback(async () => {
    const online = await checkArc();
    setArcReachable(online);
    arcRef.current = online;
    if (online && accountRef.current) {
      try { await refreshBalance(); } catch {}
    }
    return online;
  }, [refreshBalance]);

  const sendFrames = useCallback(async (packet: MeshPacket) => {
    if (!nativeNearbyAvailable() || !meshStartedRef.current) return 0;
    let recipients = 0;
    for (const frame of packetFrames(packet)) {
      const result = await BleeNearby.send({ data: frame });
      recipients = Math.max(recipients, result.recipients || 0);
    }
    return recipients;
  }, []);

  const broadcastHello = useCallback(async () => {
    const a = accountRef.current;
    if (!a || !meshStartedRef.current) return;
    const packet = await createMeshPacket(a, 'hello', {
      alias: aliasRef.current,
      address: a.address,
      arcReachable: arcRef.current,
      avatar: profilePhotoRef.current || undefined,
    });
    seenRef.current.set(packet.id, Date.now());
    await sendFrames(packet);
  }, [sendFrames]);

  const broadcastReceiptOnce = useCallback(async (auth: TransferAuthorization, txHash: Hex) => {
    const a = accountRef.current;
    if (!a || !meshStartedRef.current) return;
    const packet = await createMeshPacket(a, 'receipt', {
      paymentId: uniquePaymentId(auth), authorization: auth, txHash,
      alias: aliasRef.current, avatar: profilePhotoRef.current || undefined,
    });
    seenRef.current.set(packet.id, Date.now());
    await sendFrames(packet);
  }, [sendFrames]);

  const broadcastReceipt = useCallback(async (auth: TransferAuthorization, txHash: Hex) => {
    await broadcastReceiptOnce(auth, txHash).catch(() => undefined);
    for (const delay of [1200, 3500, 8000]) {
      setTimeout(() => broadcastReceiptOnce(auth, txHash).catch(() => undefined), delay);
    }
  }, [broadcastReceiptOnce]);

  const upsertIncoming = useCallback(async (auth: TransferAuthorization, opts?: {
    alias?: string;
    txHash?: Hex;
    state?: PaymentRecord['state'];
    route?: PaymentRecord['route'];
    createdAt?: number;
  }) => {
    const pid = uniquePaymentId(auth);
    const now = Date.now();
    const row: PaymentRecord = {
      id: pid,
      direction: 'in',
      counterparty: auth.from,
      counterpartyAlias: opts?.alias,
      amount: displayAuthAmount(auth),
      createdAt: opts?.createdAt || now,
      updatedAt: now,
      state: opts?.state || 'mesh-delivered',
      route: opts?.route || 'ble-mesh',
      authorization: auth,
      txHash: opts?.txHash,
      durablyReceivedAt: now,
    };
    const committed = await commitPayments((rows) => {
      const existing = rows.find((r) => r.id === pid && r.direction === 'in');
      if (!existing) return [row, ...rows];
      return rows.map((r) => r.id === pid && r.direction === 'in' ? {
        ...r,
        counterpartyAlias: opts?.alias || r.counterpartyAlias,
        authorization: auth,
        txHash: opts?.txHash || r.txHash,
        state: advanceState(r.state, opts?.state || r.state),
        route: opts?.route || r.route,
        durablyReceivedAt: r.durablyReceivedAt || now,
        updatedAt: now,
        error: undefined,
      } : r);
    });
    return committed.find((r) => r.id === pid && r.direction === 'in') || row;
  }, [commitPayments]);

  const markAuthSettled = useCallback(async (auth: TransferAuthorization, txHash?: Hex) => {
    const pid = uniquePaymentId(auth);
    await commitPayments((rows) => rows.map((r) =>
      (r.id === pid || r.authorization?.nonce.toLowerCase() === auth.nonce.toLowerCase())
        ? { ...r, state: 'settled', txHash: txHash || r.txHash, error: undefined, settledAt: Date.now(), nextRetryAt: undefined, updatedAt: Date.now() }
        : r));
    try { await refreshBalance(); } catch {}
  }, [commitPayments, refreshBalance]);

  const settleRecord = useCallback(async (record: PaymentRecord) => {
    const a = accountRef.current;
    if (!a || !record.authorization || !arcRef.current) return;
    const auth = record.authorization;
    const lockKey = uniquePaymentId(auth);
    if (settlementLocksRef.current.has(lockKey)) return;
    if (record.nextRetryAt && record.nextRetryAt > Date.now()) return;
    settlementLocksRef.current.add(lockKey);
    const attempts = (record.attempts || 0) + 1;
    try {
      if (authorizationExpired(auth)) {
        await commitPayments((rows) => updateRow(rows, record.id, { state: 'failed', error: 'Payment authorization expired before settlement', attempts, lastAttemptAt: Date.now() }));
        return;
      }
      if (await authorizationUsed(auth.from, auth.nonce)) {
        await markAuthSettled(auth, record.txHash);
        return;
      }

      if (record.txHash) {
        const status = await transactionStatus(record.txHash);
        if (status === 'success') {
          if (await verifyReceipt(auth, record.txHash) || await authorizationUsed(auth.from, auth.nonce)) {
            await markAuthSettled(auth, record.txHash);
          }
          return;
        }
        if (status === 'pending') return;
      }

      const submittedAt = Date.now();
      await commitPayments((rows) => updateRow(rows, record.id, {
        state: 'submitted', attempts, lastAttemptAt: submittedAt, submittedAt, error: undefined, nextRetryAt: undefined,
      }));

      const hash = await submitAuthorization(a, auth, async (txHash) => {
        // Persist the hash before waiting for the receipt. A crash after this
        // point can reconcile the exact transaction instead of guessing.
        await commitPayments((rows) => updateRow(rows, record.id, { state: 'submitted', txHash, submittedAt: Date.now(), error: undefined }));
      });
      await markAuthSettled(auth, hash);
      await broadcastReceipt(auth, hash);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Settlement failed';
      try {
        if (await authorizationUsed(auth.from, auth.nonce)) {
          const latest = paymentsRef.current.find((r) => r.id === record.id);
          await markAuthSettled(auth, latest?.txHash || record.txHash);
          return;
        }
      } catch {}
      const latest = paymentsRef.current.find((r) => r.id === record.id);
      const hasHash = Boolean(latest?.txHash);
      await commitPayments((rows) => rows.map((r) => r.id === record.id ? {
        ...r,
        state: hasHash ? 'submitted' : (r.direction === 'out' ? 'queued-local' : 'mesh-delivered'),
        error: msg,
        attempts,
        lastAttemptAt: Date.now(),
        nextRetryAt: Date.now() + retryDelay(attempts),
        updatedAt: Date.now(),
      } : r));
    } finally {
      settlementLocksRef.current.delete(lockKey);
    }
  }, [broadcastReceipt, commitPayments, markAuthSettled]);

  const expireAuthorizations = useCallback(async () => {
    const now = Date.now();
    const hasExpired = paymentsRef.current.some((row) =>
      row.authorization
      && row.state !== 'settled'
      && row.state !== 'failed'
      && authorizationExpired(row.authorization),
    );
    if (!hasExpired) return;
    await commitPayments((rows) => rows.map((row) => {
      if (!row.authorization || row.state === 'settled' || row.state === 'failed') return row;
      if (!authorizationExpired(row.authorization)) return row;
      return {
        ...row,
        state: 'failed',
        error: 'Payment authorization expired before settlement',
        nextRetryAt: undefined,
        updatedAt: now,
      };
    }));
  }, [commitPayments]);

  const reconcilePayments = useCallback(async () => {
    if (!accountRef.current || !arcRef.current) return;
    const rows = paymentsRef.current.filter((p) => p.authorization && p.state !== 'settled' && p.state !== 'failed');
    for (const row of rows.slice(0, 40)) {
      const auth = row.authorization!;
      try {
        if (row.txHash && await verifyReceipt(auth, row.txHash)) {
          await markAuthSettled(auth, row.txHash);
          continue;
        }
        if (await authorizationUsed(auth.from, auth.nonce)) {
          await markAuthSettled(auth, row.txHash);
          continue;
        }
        if (authorizationExpired(auth)) {
          await commitPayments((current) => updateRow(current, row.id, { state: 'failed', error: 'Payment authorization expired before settlement', nextRetryAt: undefined }));
          continue;
        }
        if (row.state === 'submitted' && Date.now() - (row.submittedAt || row.lastAttemptAt || row.createdAt) > SUBMITTED_RECOVERY_MS) {
          const status = row.txHash ? await transactionStatus(row.txHash) : 'reverted';
          if (status === 'reverted') {
            await commitPayments((current) => current.map((r) => r.id === row.id ? {
              ...r,
              state: r.direction === 'out' ? 'queued-local' : 'mesh-delivered',
              txHash: undefined,
              error: 'Settlement was interrupted; queued for a safe retry',
              nextRetryAt: Date.now() + 1000,
              updatedAt: Date.now(),
            } : r));
          }
        }
      } catch {}
    }
  }, [commitPayments, markAuthSettled]);

  const syncIncomingFromChain = useCallback(async () => {
    const a = accountRef.current;
    if (!a || !arcRef.current) return;
    const toBlock = await publicClient.getBlockNumber();
    const cursor = await loadChainCursor(a.address);
    const fromBlock = cursor === null
      ? (toBlock > INITIAL_CHAIN_LOOKBACK_BLOCKS ? toBlock - INITIAL_CHAIN_LOOKBACK_BLOCKS : 0n)
      : cursor + 1n;
    if (fromBlock <= toBlock) {
      const settlements = await scanIncomingSettlements(a.address, fromBlock, toBlock);
      if (settlements.length) {
        await commitPayments((rows) => {
          const next = [...rows];
          for (const settlement of settlements) {
            const knownAlias = peerIdentitiesRef.current[settlement.from.toLowerCase()]?.alias;
            const existingIndex = next.findIndex((r) => r.direction === 'in' && (r.id === settlement.id || r.txHash?.toLowerCase() === settlement.txHash.toLowerCase()));
            if (existingIndex >= 0) {
              next[existingIndex] = {
                ...next[existingIndex],
                id: settlement.id,
                counterparty: settlement.from,
                counterpartyAlias: next[existingIndex].counterpartyAlias || knownAlias,
                amount: settlement.amount,
                state: 'settled',
                route: next[existingIndex].route || 'arc-direct',
                txHash: settlement.txHash,
                settledAt: Date.now(),
                error: undefined,
                updatedAt: Date.now(),
              };
            } else {
              next.unshift({
                id: settlement.id,
                direction: 'in',
                counterparty: settlement.from,
                counterpartyAlias: knownAlias,
                amount: settlement.amount,
                createdAt: Date.now(),
                updatedAt: Date.now(),
                state: 'settled',
                route: 'arc-direct',
                txHash: settlement.txHash,
                settledAt: Date.now(),
              });
            }
          }
          return next;
        });
      }
      await saveChainCursor(a.address, toBlock).catch(() => undefined);
    }
  }, [commitPayments]);

  const flushQueues = useCallback(async () => {
    if (!accountRef.current || !arcRef.current) return;
    const a = accountRef.current;
    const now = Date.now();
    const candidates = paymentsRef.current.filter((p) => {
      if (!p.authorization || p.state === 'settled' || p.state === 'failed' || p.state === 'submitted') return false;
      if (p.nextRetryAt && p.nextRetryAt > now) return false;
      if (p.direction === 'out') return true;
      if (p.direction === 'in') return p.authorization.to.toLowerCase() === a.address.toLowerCase();
      if (p.direction === 'relay') return relayRef.current;
      return false;
    });
    for (const record of candidates.slice(0, 3)) await settleRecord(record);
  }, [settleRecord]);

  const retryNearbyDelivery = useCallback(async () => {
    const a = accountRef.current;
    if (!a || !meshStartedRef.current || nearbyRetryRunningRef.current) return;
    nearbyRetryRunningRef.current = true;
    try {
      const now = Date.now();
      const candidates = paymentsRef.current.filter((p) =>
        p.direction === 'out' && p.authorization &&
        (p.state === 'queued-local' || p.state === 'mesh-broadcast') &&
        !authorizationExpired(p.authorization) &&
        (!p.nextRetryAt || p.nextRetryAt <= now));
      for (const row of candidates.slice(0, 2)) {
        try {
          const packet = await createMeshPacket(a, 'payment', { authorization: row.authorization, alias: aliasRef.current, avatar: profilePhotoRef.current || undefined });
          seenRef.current.set(packet.id, Date.now());
          const recipients = await sendFrames(packet);
          if (recipients > 0) {
            await commitPayments((rows) => updateRow(rows, row.id, {
              state: 'mesh-broadcast', route: 'ble-mesh', attempts: (row.attempts || 0) + 1,
              lastAttemptAt: Date.now(), nextRetryAt: Date.now() + OFFLINE_RETRY_MS,
            }));
          }
        } catch {}
      }
    } finally { nearbyRetryRunningRef.current = false; }
  }, [commitPayments, sendFrames]);

  const handlePacket = useCallback(async (packet: MeshPacket, transportId: string) => {
    const now = Date.now();
    for (const [id, at] of seenRef.current) if (now - at > 5 * 60_000) seenRef.current.delete(id);
    if (seenRef.current.has(packet.id)) return;
    if (!(await verifyMeshPacket(packet))) return;
    seenRef.current.set(packet.id, now);

    const a = accountRef.current;
    if (packet.type === 'hello') {
      const p = packet.payload as { alias?: string; address?: string; arcReachable?: boolean; avatar?: string };
      if (p.address && isAddress(p.address) && (!a || p.address.toLowerCase() !== a.address.toLowerCase())) {
        rememberIdentity(p.address, p.alias, p.avatar);
        const transport = transportFromId(transportId);
        const peer: MeshPeer = {
          transportId,
          address: getAddress(p.address),
          alias: (p.alias || 'nearby').slice(0, 24),
          hops: packet.hops,
          lastSeen: now,
          arcReachable: Boolean(p.arcReachable),
          transport,
        };
        setPeers((rows) => {
          const existing = rows.find((x) => x.address.toLowerCase() === peer.address.toLowerCase());
          if (existing?.transport === 'lan' && peer.transport === 'ble') {
            return rows.map((x) => x.address.toLowerCase() === peer.address.toLowerCase()
              ? { ...x, lastSeen: now, arcReachable: peer.arcReachable || x.arcReachable }
              : x);
          }
          const rest = rows.filter((x) => x.address.toLowerCase() !== peer.address.toLowerCase());
          return [peer, ...rest].sort((x, y) => (x.transport === 'lan' ? -1 : 0) - (y.transport === 'lan' ? -1 : 0) || x.hops - y.hops);
        });
      }
    }

    if (packet.type === 'payment' && a) {
      const p = packet.payload as { authorization?: TransferAuthorization; alias?: string; avatar?: string };
      const auth = p.authorization;
      if (auth && await verifyAuthorization(auth)) {
        rememberIdentity(auth.from, p.alias, p.avatar);
        const pid = uniquePaymentId(auth);
        if (auth.to.toLowerCase() === a.address.toLowerCase()) {
          // SQLite COMMIT FIRST. Only after this resolves do we send the ACK.
          // The sender can now safely disappear and the receiver still owns a
          // durable signed authorization it can settle when internet returns.
          const record = await upsertIncoming(auth, {
            alias: p.alias,
            state: 'mesh-delivered',
            route: 'ble-mesh',
            createdAt: packet.createdAt || now,
          });
          const ack = await createMeshPacket(a, 'ack', { paymentId: pid, nonce: auth.nonce, receiver: a.address, durable: true });
          seenRef.current.set(ack.id, Date.now());
          await sendFrames(ack);
          if (arcRef.current) setTimeout(() => settleRecord(record).catch(() => undefined), 80);
        } else if (relayRef.current) {
          await commitPayments((rows) => rows.some((r) => r.id === `${pid}:relay`) ? rows : [{
            id: `${pid}:relay`,
            direction: 'relay',
            counterparty: auth.to,
            amount: displayAuthAmount(auth),
            createdAt: now,
            updatedAt: now,
            state: 'mesh-broadcast',
            route: 'ble-mesh',
            authorization: auth,
            durablyReceivedAt: now,
          }, ...rows]);
        }
      }
    }

    if (packet.type === 'ack') {
      const p = packet.payload as { paymentId?: string; nonce?: Hex; receiver?: Address; durable?: boolean };
      if (p.paymentId && p.nonce && p.receiver && p.durable) {
        const outgoing = paymentsRef.current.find((row) =>
          row.id === p.paymentId
          && row.direction === 'out'
          && row.authorization,
        );
        const auth = outgoing?.authorization;
        const authenticatedRecipient = Boolean(
          auth
          && packet.origin.toLowerCase() === auth.to.toLowerCase()
          && p.receiver.toLowerCase() === auth.to.toLowerCase()
          && p.nonce.toLowerCase() === auth.nonce.toLowerCase()
          && p.paymentId === uniquePaymentId(auth),
        );
        if (authenticatedRecipient) {
          await commitPayments((rows) => updateRow(rows, p.paymentId!, {
            state: 'mesh-delivered',
            error: undefined,
            nextRetryAt: undefined,
          }));
        }
      }
    }

    if (packet.type === 'receipt' && a) {
      const p = packet.payload as { paymentId?: string; authorization?: TransferAuthorization; txHash?: Hex; alias?: string; avatar?: string };
      const auth = p.authorization;
      if (auth && p.txHash && await verifyAuthorization(auth)) {
        rememberIdentity(auth.from, p.alias, p.avatar);
        const pid = uniquePaymentId(auth);
        if (auth.to.toLowerCase() === a.address.toLowerCase()) {
          await upsertIncoming(auth, { alias: p.alias || identityFor(auth.from)?.alias, txHash: p.txHash, state: 'submitted', route: 'arc-direct', createdAt: packet.createdAt || now });
        }
        if (auth.from.toLowerCase() === a.address.toLowerCase()) {
          await commitPayments((rows) => updateRow(rows, pid, { state: 'submitted', txHash: p.txHash, error: undefined }));
        }
        if (arcRef.current && await verifyReceipt(auth, p.txHash)) await markAuthSettled(auth, p.txHash);
      }
    }

    const next = forwarded(packet);
    if (next && meshStartedRef.current) {
      setTimeout(() => sendFrames(next).catch(() => undefined), 40 + Math.floor(Math.random() * 140));
    }
  }, [commitPayments, identityFor, markAuthSettled, rememberIdentity, sendFrames, settleRecord, upsertIncoming]);

  const startMesh = useCallback(async () => {
    if (!nativeNearbyAvailable()) throw new Error('Native nearby bridge is not available in this runtime');
    if (!accountRef.current) throw new Error('Unlock wallet first');
    if (meshStartedRef.current) return;

    const packetHandle = await BleeNearby.addListener('packet', ({ peerId, data }) => {
      const packet = assemblerRef.current.push(data);
      if (packet) handlePacket(packet, peerId).catch(() => undefined);
    });
    const peerHandle = await BleeNearby.addListener('peerSeen', ({ id, rssi }) => {
      const now = Date.now();
      setPeers((rows) => rows.map((p) => p.transportId === id ? { ...p, rssi, lastSeen: now } : p));
      const lastHello = transportHelloAt.get(id) || 0;
      if (now - lastHello > TRANSPORT_HELLO_COOLDOWN_MS) {
        transportHelloAt.set(id, now);
        setTimeout(() => broadcastHello().catch(() => undefined), 150);
      }
    });
    const stateHandle = await BleeNearby.addListener('state', ({ state }) => setMeshState(state));
    listenerHandles.current = [packetHandle, peerHandle, stateHandle];
    await BleeNearby.startMesh();
    setMeshStarted(true);
    meshStartedRef.current = true;
    setMeshState('running');
    await broadcastHello();
    setTimeout(() => broadcastHello().catch(() => undefined), 800);
    setTimeout(() => broadcastHello().catch(() => undefined), 2400);
  }, [broadcastHello, handlePacket]);

  const stopMesh = useCallback(async () => {
    if (nativeNearbyAvailable()) await BleeNearby.stopMesh().catch(() => undefined);
    for (const h of listenerHandles.current) await h.remove().catch(() => undefined);
    listenerHandles.current = [];
    setMeshStarted(false);
    meshStartedRef.current = false;
    setMeshState('stopped');
    setPeers([]);
  }, []);

  const sendPaymentCore = useCallback(async (toText: string, amount: string, counterpartyAlias?: string): Promise<SendResult> => {
    const a = accountRef.current;
    if (!a) throw new Error('Unlock wallet first');
    if (!persistenceReady) throw new Error('Payment storage is still starting');
    if (!isAddress(toText)) throw new Error('Enter a valid EVM address');
    const to = getAddress(toText);
    if (to.toLowerCase() === a.address.toLowerCase()) throw new Error('Cannot pay your own wallet');

    let amountUnits: bigint;
    try { amountUnits = parseUnits(amount, ARC_USDC_DECIMALS); } catch { throw new Error('Enter a valid amount with up to 6 decimals'); }
    if (amountUnits <= 0n) throw new Error('Enter a valid amount');
    const confirmedBalance = balanceRef.current;
    if (confirmedBalance === null) throw new Error('Connect once before creating an offline payment');
    const liveReservedUnits = paymentsRef.current
      .filter((row) =>
        row.direction === 'out'
        && row.authorization
        && row.state !== 'settled'
        && row.state !== 'failed',
      )
      .reduce((sum, row) => sum + BigInt(row.authorization!.value), 0n);
    const confirmedUnits = parseUnits(confirmedBalance, ARC_USDC_DECIMALS);
    const spendableUnits = confirmedUnits > liveReservedUnits ? confirmedUnits - liveReservedUnits : 0n;
    if (amountUnits > spendableUnits) throw new Error('Amount exceeds your confirmed spendable balance');

    setBusy(true);
    try {
      const auth = await createAuthorization(a, to, amount);
      const id = uniquePaymentId(auth);
      const base: PaymentRecord = {
        id,
        direction: 'out',
        counterparty: to,
        counterpartyAlias,
        senderName: aliasRef.current,
        senderAvatar: profilePhotoRef.current || undefined,
        amount,
        createdAt: Date.now(),
        updatedAt: Date.now(),
        state: 'queued-local',
        route: 'local-queue',
        authorization: auth,
      };
      // The signed authorization is durable before any network attempt begins.
      await commitPayments((rows) => [base, ...rows]);

      if (await checkArc()) {
        setArcReachable(true);
        arcRef.current = true;
        try {
          const submittedAt = Date.now();
          await commitPayments((rows) => updateRow(rows, id, { state: 'submitted', route: 'arc-direct', submittedAt, attempts: 1, lastAttemptAt: submittedAt, error: undefined }));
          const txHash = await submitAuthorization(a, auth, async (hash) => {
            await commitPayments((rows) => updateRow(rows, id, { state: 'submitted', route: 'arc-direct', txHash: hash, submittedAt: Date.now(), error: undefined }));
          });
          await markAuthSettled(auth, txHash);
          if (meshStartedRef.current) await broadcastReceipt(auth, txHash);
          return { id, route: 'arc-direct', state: 'settled', txHash };
        } catch (directError) {
          const latest = paymentsRef.current.find((r) => r.id === id);
          if (latest?.txHash) {
            return { id, route: 'arc-direct', state: 'submitted', txHash: latest.txHash };
          }
          if (meshStartedRef.current) {
            const packet = await createMeshPacket(a, 'payment', { authorization: auth, alias: aliasRef.current, avatar: profilePhotoRef.current || undefined });
            seenRef.current.set(packet.id, Date.now());
            const recipients = await sendFrames(packet);
            await commitPayments((rows) => updateRow(rows, id, {
              state: recipients > 0 ? 'mesh-broadcast' : 'queued-local',
              route: recipients > 0 ? 'ble-mesh' : 'local-queue',
              nextRetryAt: Date.now() + OFFLINE_RETRY_MS,
              error: recipients > 0 ? undefined : 'No nearby recipient acknowledged yet',
            }));
            return { id, route: recipients > 0 ? 'ble-mesh' : 'local-queue', state: recipients > 0 ? 'mesh-broadcast' : 'queued-local' };
          }
          throw directError;
        }
      }

      setArcReachable(false);
      arcRef.current = false;
      if (meshStartedRef.current) {
        const packet = await createMeshPacket(a, 'payment', { authorization: auth, alias: aliasRef.current, avatar: profilePhotoRef.current || undefined });
        seenRef.current.set(packet.id, Date.now());
        const recipients = await sendFrames(packet);
        await commitPayments((rows) => updateRow(rows, id, {
          state: recipients > 0 ? 'mesh-broadcast' : 'queued-local',
          route: recipients > 0 ? 'ble-mesh' : 'local-queue',
          nextRetryAt: Date.now() + OFFLINE_RETRY_MS,
        }));
        return { id, route: recipients > 0 ? 'ble-mesh' : 'local-queue', state: recipients > 0 ? 'mesh-broadcast' : 'queued-local' };
      }
      return { id, route: 'local-queue', state: 'queued-local' };
    } finally { setBusy(false); }
  }, [broadcastReceipt, commitPayments, markAuthSettled, persistenceReady, sendFrames]);

  const sendPayment = useCallback((
    toText: string,
    amount: string,
    counterpartyAlias?: string,
  ): Promise<SendResult> => {
    let resolveResult!: (value: SendResult) => void;
    let rejectResult!: (reason?: unknown) => void;
    const result = new Promise<SendResult>((resolve, reject) => {
      resolveResult = resolve;
      rejectResult = reject;
    });

    const work = sendQueueRef.current.then(async () => {
      try {
        resolveResult(await sendPaymentCore(toText, amount, counterpartyAlias));
      } catch (error) {
        rejectResult(error);
      }
    });
    sendQueueRef.current = work.catch(() => undefined);
    return result;
  }, [sendPaymentCore]);

  useEffect(() => {
    if (!account || !persistenceReady) return;
    let dead = false;
    const tick = async () => {
      if (tickRunningRef.current) return;
      tickRunningRef.current = true;
      try {
        await expireAuthorizations();
        const online = await refreshNetwork();
        if (!dead && online) {
          await reconcilePayments();
          await syncIncomingFromChain();
          await flushQueues();
        } else if (!dead) {
          await retryNearbyDelivery();
        }
        if (!dead) setPeers((rows) => rows.filter((p) => Date.now() - p.lastSeen < PEER_STALE_MS));
      } finally { tickRunningRef.current = false; }
    };
    tick().catch(() => undefined);
    const timer = setInterval(() => tick().catch(() => undefined), NETWORK_TICK_MS);
    return () => { dead = true; clearInterval(timer); };
  }, [account, persistenceReady, expireAuthorizations, refreshNetwork, reconcilePayments, retryNearbyDelivery, syncIncomingFromChain, flushQueues]);

  useEffect(() => {
    if (!account || !persistenceReady || meshStartedRef.current || !nativeNearbyAvailable()) return;
    const timer = setTimeout(() => {
      startMesh().catch(() => setMeshState('needs-attention'));
    }, 250);
    return () => clearTimeout(timer);
  }, [account, persistenceReady, startMesh]);

  useEffect(() => {
    if (!account || !nativeNearbyAvailable()) return;
    const resume = () => {
      if (document.visibilityState === 'visible' && !meshStartedRef.current) {
        startMesh().catch(() => setMeshState('needs-attention'));
      }
      if (document.visibilityState === 'visible') refreshNetwork().catch(() => undefined);
    };
    document.addEventListener('visibilitychange', resume);
    window.addEventListener('online', resume);
    return () => {
      document.removeEventListener('visibilitychange', resume);
      window.removeEventListener('online', resume);
    };
  }, [account, refreshNetwork, startMesh]);

  useEffect(() => {
    if (!meshStarted || !account) return;
    const timer = setInterval(() => {
      broadcastHello().catch(() => undefined);
      retryNearbyDelivery().catch(() => undefined);
    }, HELLO_EVERY_MS);
    return () => clearInterval(timer);
  }, [meshStarted, account, broadcastHello, retryNearbyDelivery]);

  useEffect(() => () => {
    if (meshStartedRef.current) BleeNearby.stopMesh().catch(() => undefined);
  }, []);

  return {
    vaultExists,
    vaultAddress,
    account,
    alias,
    setAlias,
    profilePhoto,
    setProfilePhoto,
    peerIdentities,
    identityFor,
    create,
    unlock,
    lock,
    balance,
    balanceAt,
    available,
    reserved,
    pendingIncoming,
    arcReachable,
    refreshNetwork,
    payments,
    peers,
    bleAvailable,
    platform,
    meshStarted,
    meshState,
    startMesh,
    stopMesh,
    relayEnabled,
    setRelayEnabled,
    busy,
    sendPayment,
    persistenceReady,
    persistenceMode,
    nativePersistenceAvailable: nativePersistenceAvailable(),
    storageError,
  };
}
