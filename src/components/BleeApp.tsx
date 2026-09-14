'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { isAddress, parseUnits } from 'viem';
import { getActiveNetwork } from '../lib/networkConfig';
import { createAndDeliverOfflineSolPayment } from '../lib/solanaPaymentCoordinator';
import {
  exportEncryptedWalletBackup,
  importEncryptedWalletBackup,
  importPrivateKey,
  revealPrivateKey,
} from '../lib/walletRecovery';
import { useBleeView } from '../hooks/useBleeView';
import { BleeBiometric, type BiometricStatus } from '../lib/biometric';
import type { MeshPeer, PaymentRecord } from '../types/domain';
import { RecipientField } from './RecipientField';

type PrimaryTab = 'home' | 'nearby' | 'activity' | 'profile';
type Screen =
  | PrimaryTab
  | 'send'
  | 'confirm-send'
  | 'send-success'
  | 'receive'
  | 'activity-detail'
  | 'edit-profile'
  | 'settings'
  | 'backup-recovery'
  | 'network-security';
type BackupMode = 'overview' | 'reveal' | 'import-key' | 'restore';
type ReceiveAsset = 'usdc' | 'sol';
type SendAsset = 'usdc' | 'sol';
type SendResult = {
  asset: SendAsset;
  route: string;
  state: string;
  txHash?: string;
  paymentId?: string;
  signedTransactionSha256?: string;
  recipients?: number;
};
type IconName =
  | 'home' | 'send' | 'receive' | 'nearby' | 'activity' | 'person' | 'copy'
  | 'refresh' | 'close' | 'external' | 'wallet' | 'check' | 'wifi' | 'lock'
  | 'shield' | 'arrowDown' | 'clock' | 'chevron' | 'back' | 'settings' | 'edit'
  | 'backup' | 'key' | 'network' | 'camera' | 'logout' | 'info' | 'fingerprint';

function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };
  switch (name) {
    case 'home': return <svg {...common}><path d="M4 10.7 12 4l8 6.7V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1z"/></svg>;
    case 'send': return <svg {...common}><path d="M5 12h14"/><path d="m14 7 5 5-5 5"/></svg>;
    case 'receive': return <svg {...common}><path d="M12 4v13"/><path d="m7 12 5 5 5-5"/><path d="M5 20h14"/></svg>;
    case 'nearby': return <svg {...common}><circle cx="12" cy="12" r="2.2"/><path d="M7.8 7.8a6 6 0 0 0 0 8.4"/><path d="M16.2 7.8a6 6 0 0 1 0 8.4"/></svg>;
    case 'activity': return <svg {...common}><path d="M3 12h4l2.2-5 4.2 10 2.2-5H21"/></svg>;
    case 'person': return <svg {...common}><circle cx="12" cy="8" r="3.2"/><path d="M5.5 20c.8-4 3-6 6.5-6s5.7 2 6.5 6"/></svg>;
    case 'copy': return <svg {...common}><rect x="8" y="8" width="10" height="10" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>;
    case 'refresh': return <svg {...common}><path d="M20 7v5h-5"/><path d="M4 17v-5h5"/><path d="M6.1 9a7 7 0 0 1 11.3-2L20 12"/><path d="m4 12 2.6 5a7 7 0 0 0 11.3-2"/></svg>;
    case 'close': return <svg {...common}><path d="M6 6l12 12M18 6 6 18"/></svg>;
    case 'external': return <svg {...common}><path d="M14 5h5v5"/><path d="m19 5-8 8"/><path d="M18 13v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>;
    case 'wallet': return <svg {...common}><path d="M4 7.5A2.5 2.5 0 0 1 6.5 5H18v14H6.5A2.5 2.5 0 0 1 4 16.5z"/><path d="M4 8h14"/><path d="M15 12h5v4h-5a2 2 0 0 1 0-4Z"/></svg>;
    case 'check': return <svg {...common}><path d="m5 12 4 4L19 6"/></svg>;
    case 'wifi': return <svg {...common}><path d="M5 10.5a10 10 0 0 1 14 0"/><path d="M8 13.5a6 6 0 0 1 8 0"/><path d="M10.5 16.5a2.5 2.5 0 0 1 3 0"/><circle cx="12" cy="19" r=".8" fill="currentColor" stroke="none"/></svg>;
    case 'lock': return <svg {...common}><rect x="5" y="10" width="14" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>;
    case 'shield': return <svg {...common}><path d="M12 3 5.5 5.7v5.5c0 4.3 2.5 7.8 6.5 9.8 4-2 6.5-5.5 6.5-9.8V5.7z"/><path d="m9 12 2 2 4-4"/></svg>;
    case 'arrowDown': return <svg {...common}><path d="M12 4v14"/><path d="m6.5 12.5 5.5 5.5 5.5-5.5"/></svg>;
    case 'clock': return <svg {...common}><circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/></svg>;
    case 'chevron': return <svg {...common}><path d="m9 6 6 6-6 6"/></svg>;
    case 'back': return <svg {...common}><path d="m15 18-6-6 6-6"/></svg>;
    case 'settings': return <svg {...common}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21h-4v-.1A1.7 1.7 0 0 0 9 19.3a1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H3v-4h.1A1.7 1.7 0 0 0 4.7 9a1.7 1.7 0 0 0-.3-1.9L4.3 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3V3h4v.1A1.7 1.7 0 0 0 15 4.7a1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9A1.7 1.7 0 0 0 21 10h.1v4H21a1.7 1.7 0 0 0-1.6 1Z"/></svg>;
    case 'edit': return <svg {...common}><path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17v3Z"/><path d="m14 8 3 3"/></svg>;
    case 'backup': return <svg {...common}><path d="M12 3v12"/><path d="m7 8 5-5 5 5"/><path d="M5 14v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5"/></svg>;
    case 'key': return <svg {...common}><circle cx="8" cy="15" r="4"/><path d="m11 12 8-8"/><path d="m16 7 2 2"/><path d="m14 9 2 2"/></svg>;
    case 'network': return <svg {...common}><circle cx="12" cy="12" r="8"/><path d="M4 12h16"/><path d="M12 4a13 13 0 0 1 0 16"/><path d="M12 4a13 13 0 0 0 0 16"/></svg>;
    case 'camera': return <svg {...common}><path d="M4 8h4l1.5-2h5L16 8h4v11H4z"/><circle cx="12" cy="13" r="3"/></svg>;
    case 'logout': return <svg {...common}><path d="M10 5H5v14h5"/><path d="M14 8l4 4-4 4"/><path d="M18 12H9"/></svg>;
    case 'info': return <svg {...common}><circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7h.01"/></svg>;
    case 'fingerprint': return <svg {...common}><path d="M8.2 9.2A4.8 4.8 0 0 1 17 12c0 4.8-1.8 7.7-4.8 9"/><path d="M5.4 15.8C5 14.7 5 13.4 5 12a7 7 0 0 1 12.9-3.8"/><path d="M8 17.5c.7-1.4.9-3.1.9-5.5a3.1 3.1 0 0 1 6.2 0c0 3.7-.9 6.3-2.8 8.1"/><path d="M11.8 15.6c.3-1 .4-2.2.4-3.6"/></svg>;
  }
}

function Brand({ compact = false }: { compact?: boolean }) {
  return <div className={`blee-brand ${compact ? 'compact' : ''}`} data-blee-brand="lockup"><img className="blee-wordmark" src="/brand/blee-wordmark.svg" alt="Blee"/></div>;
}

function PasswordField({ label, value, onChange, placeholder, autoComplete }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; autoComplete?: string }) {
  const [revealed, setRevealed] = useState(false);
  return <label className="password-field-label"><span>{label}</span><div className="password-input"><input type={revealed ? 'text' : 'password'} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} autoComplete={autoComplete} autoCapitalize="none" autoCorrect="off" spellCheck={false}/><button type="button" onClick={() => setRevealed((current) => !current)} aria-label={revealed ? 'Hide passphrase' : 'Show passphrase'}>{revealed ? 'Hide' : 'Show'}</button></div></label>;
}

function short(value?: string | null) {
  if (!value) return '—';
  return `${value.slice(0, 6)}…${value.slice(-4)}`;
}

function formatAmount(value: string | number | null | undefined, max = 6) {
  if (value === null || value === undefined) return '0.00';
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '0.00';
  return parsed.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: max });
}

function parseSolLamports(value: string): bigint {
  const clean = value.trim();
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,9})?$/.test(clean)) throw new Error('Enter a valid SOL amount with up to 9 decimal places.');
  const lamports = parseUnits(clean, 9);
  if (lamports <= 0n) throw new Error('Enter an amount greater than zero.');
  return lamports;
}

function formatTimestamp(value?: number | null) {
  if (!value) return '—';
  return new Date(value).toLocaleString(undefined, { year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function paymentStatus(row: PaymentRecord) {
  switch (row.state) {
    case 'verification-pending': return 'Verifying nearby';
    case 'settled': return row.direction === 'in' ? 'Received' : 'Confirmed';
    case 'submitted': return 'Settlement submitted';
    case 'mesh-delivered': return row.direction === 'in' ? 'Received nearby' : 'Delivered nearby';
    case 'mesh-broadcast': return 'Sending nearby';
    case 'queued-local': return 'Queued safely';
    case 'failed': return row.error || 'Failed';
  }
}

function paymentStatusDetail(row: PaymentRecord) {
  switch (row.state) {
    case 'verification-pending': return 'Stored durably on this phone while the sender authorization is verified locally.';
    case 'settled': return 'Final on Arc Testnet.';
    case 'submitted': return 'Submitted to Arc and awaiting confirmation.';
    case 'mesh-delivered': return 'Stored by the recipient. Settlement is still pending.';
    case 'mesh-broadcast': return 'Blee is delivering the signed payment to the intended recipient.';
    case 'queued-local': return 'Stored durably on this phone until a safe route is available.';
    case 'failed': return row.error || 'This payment could not complete.';
  }
}

type Identity = { alias?: string; avatar?: string } | undefined;

function PersonAvatar({ name, src, size = 'md' }: { name: string; src?: string | null; size?: 'sm' | 'md' | 'lg' | 'xl' }) {
  return <span className={`person-avatar ${size}`}>{src ? <img src={src} alt=""/> : name.slice(0, 1).toUpperCase()}</span>;
}

function TokenLogo({ asset, className = '' }: { asset: SendAsset; className?: string }) {
  return <img className={className} src={asset === 'sol' ? '/brand/solana-logomark.svg' : '/brand/usdc-token.svg'} alt="" aria-hidden="true"/>;
}

async function prepareProfilePhoto(file: File): Promise<string> {
  if (!file.type.startsWith('image/')) throw new Error('Choose an image file');
  if (file.size > 12 * 1024 * 1024) throw new Error('Choose an image smaller than 12 MB');
  const source = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Could not read this image'));
    reader.onload = () => resolve(String(reader.result || ''));
    reader.readAsDataURL(file);
  });
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image(); img.onload = () => resolve(img); img.onerror = () => reject(new Error('Could not open this image')); img.src = source;
  });
  const size = 128;
  const canvas = document.createElement('canvas'); canvas.width = size; canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Could not prepare profile photo');
  const side = Math.min(image.naturalWidth, image.naturalHeight);
  ctx.drawImage(image, (image.naturalWidth - side) / 2, (image.naturalHeight - side) / 2, side, side, 0, 0, size, size);
  for (const quality of [0.76, 0.64, 0.52, 0.42]) {
    const data = canvas.toDataURL('image/jpeg', quality);
    if (data.length <= 24_000) return data;
  }
  throw new Error('Could not compress this photo enough for nearby sharing');
}

async function copyText(value: string) {
  try { if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(value); return; } } catch {}
  const input = document.createElement('textarea');
  input.value = value; input.setAttribute('readonly', ''); input.style.position = 'fixed'; input.style.opacity = '0'; document.body.appendChild(input); input.select();
  const copied = document.execCommand('copy'); input.remove(); if (!copied) throw new Error('Could not copy to clipboard');
}

function downloadText(filename: string, body: string) {
  const blob = new Blob([body], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.rel = 'noopener'; document.body.appendChild(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function ScreenHeader({ title, onBack, trailing }: { title: string; onBack?: () => void; trailing?: React.ReactNode }) {
  return <header className="screen-header"><div className="header-side">{onBack && <button className="icon-button ghost" onClick={onBack} aria-label="Back"><Icon name="back"/></button>}</div><h1>{title}</h1><div className="header-side right">{trailing}</div></header>;
}

function EmptyState({ icon, title, copy }: { icon: IconName; title: string; copy: string }) {
  return <div className="empty-state"><span><Icon name={icon} size={22}/></span><strong>{title}</strong><p>{copy}</p></div>;
}

function PaymentRow({ row, identity, onOpen }: { row: PaymentRecord; identity?: Identity; onOpen: (row: PaymentRecord) => void }) {
  const incoming = row.direction === 'in';
  const name = row.counterpartyAlias || identity?.alias || short(row.counterparty);
  return <button className="transaction-row" onClick={() => onOpen(row)}><PersonAvatar name={name} src={row.counterpartyAvatar || identity?.avatar} size="sm"/><span className="transaction-main"><strong>{incoming ? `From ${name}` : `To ${name}`}</strong><small>{paymentStatus(row)}</small></span><span className="transaction-value"><strong className={incoming && row.state === 'settled' ? 'positive' : ''}>{incoming ? '+' : '−'}{formatAmount(row.amount)} USDC</strong><small>{new Date(row.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</small></span><Icon name="chevron" size={15}/></button>;
}

function BottomNav({ active, onChange }: { active: PrimaryTab; onChange: (tab: PrimaryTab) => void }) {
  return <nav className="bottom-nav" aria-label="Primary navigation">{([
    ['home', 'home', 'Home'], ['nearby', 'nearby', 'Nearby'], ['activity', 'activity', 'Activity'], ['profile', 'person', 'Profile'],
  ] as Array<[PrimaryTab, IconName, string]>).map(([tab, icon, label]) => <button key={tab} className={active === tab ? 'active' : ''} onClick={() => onChange(tab)}><Icon name={icon}/><span>{label}</span></button>)}</nav>;
}

export function BleeApp() {
  const app = useBleeView();
  const network = getActiveNetwork();
  const [screen, setScreen] = useState<Screen>('home');
  const historyRef = useRef<Screen[]>([]);
  const [activityFilter, setActivityFilter] = useState<'all' | 'sent' | 'received'>('all');
  const [selectedPayment, setSelectedPayment] = useState<PaymentRecord | null>(null);
  const [payPeer, setPayPeer] = useState<MeshPeer | null>(null);
  const [payAlias, setPayAlias] = useState('');
  const [payAddress, setPayAddress] = useState('');
  const [payAmount, setPayAmount] = useState('');
  const [payAsset, setPayAsset] = useState<SendAsset>('usdc');
  const [payError, setPayError] = useState('');
  const [payResult, setPayResult] = useState<SendResult | null>(null);
  const [solPayBusy, setSolPayBusy] = useState(false);
  const [receiveAsset, setReceiveAsset] = useState<ReceiveAsset>('usdc');
  const [passphrase, setPassphrase] = useState('');
  const [confirmPassphrase, setConfirmPassphrase] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [authError, setAuthError] = useState('');
  const [biometricStatus, setBiometricStatus] = useState<BiometricStatus>({ available: false, enrolled: false, enabled: false });
  const [biometricBusy, setBiometricBusy] = useState(false);
  const [useBiometricNext, setUseBiometricNext] = useState(false);
  const biometricAutoAttempted = useRef(false);
  const [profileName, setProfileName] = useState('');
  const [profilePhotoDraft, setProfilePhotoDraft] = useState<string | null>(null);
  const [profilePhotoError, setProfilePhotoError] = useState('');
  const [nearbyError, setNearbyError] = useState('');
  const [copied, setCopied] = useState(false);
  const [backupMode, setBackupMode] = useState<BackupMode>('overview');
  const [walletPassphrase, setWalletPassphrase] = useState('');
  const [walletMessage, setWalletMessage] = useState('');
  const [revealedKey, setRevealedKey] = useState('');
  const [importKey, setImportKey] = useState('');
  const [importPassphrase, setImportPassphrase] = useState('');
  const [backupJson, setBackupJson] = useState('');
  const [confirmImport, setConfirmImport] = useState('');
  const [launchSplashDone, setLaunchSplashDone] = useState(false);
  const photoInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => { setProfileName(app.alias); }, [app.alias]);
  useEffect(() => { setProfilePhotoDraft(app.profilePhoto || null); }, [app.profilePhoto]);
  useEffect(() => { const timer = window.setTimeout(() => setLaunchSplashDone(true), 760); return () => window.clearTimeout(timer); }, []);
  useEffect(() => {
    if (!app.persistenceReady) return;
    let active = true;
    void BleeBiometric.status().then((status) => {
      if (!active) return;
      setBiometricStatus(status);
      if (!app.account && app.vaultExists && !status.enabled) setUseBiometricNext(window.localStorage.getItem('blee.biometric.setup') === '1');
    });
    return () => { active = false; };
  }, [app.persistenceReady, app.vaultExists, app.account]);

  const refreshBiometricStatus = async () => { const status = await BleeBiometric.status(); setBiometricStatus(status); return status; };
  const handleBiometricUnlock = async () => {
    if (biometricBusy) return;
    setAuthError(''); setBiometricBusy(true);
    try { const result = await BleeBiometric.unlock(); await app.unlock(result.passphrase); historyRef.current = []; setScreen('home'); setPassphrase(''); }
    catch (error) { const message = error instanceof Error ? error.message : 'Fingerprint unlock was not completed'; if (!/cancel/i.test(message)) setAuthError(message); }
    finally { setBiometricBusy(false); }
  };
  useEffect(() => {
    if (!launchSplashDone || !app.persistenceReady || app.account || !app.vaultExists || !biometricStatus.enabled || biometricAutoAttempted.current) return;
    biometricAutoAttempted.current = true; void handleBiometricUnlock();
  }, [launchSplashDone, app.persistenceReady, app.account, app.vaultExists, biometricStatus.enabled]);

  const visiblePayments = useMemo(() => app.payments.filter((row) => row.direction !== 'relay'), [app.payments]);
  const filteredPayments = useMemo(() => visiblePayments.filter((row) => activityFilter === 'all' || (activityFilter === 'sent' ? row.direction === 'out' : row.direction === 'in')), [visiblePayments, activityFilter]);
  const recentPayments = visiblePayments.slice(0, 2);
  const nearbyPeers = app.peers.slice(0, 3);
  const pendingPayments = visiblePayments.filter((row) => row.state !== 'settled' && row.state !== 'failed');
  const projectedBalance = Number(app.available || 0) + Number(app.pendingIncoming || 0);
  const portfolioBalance = app.portfolio.totalUsdcEquivalent;
  const activeTab: PrimaryTab = ['home', 'nearby', 'activity', 'profile'].includes(screen) ? screen as PrimaryTab : 'home';

  const navigate = (next: Screen) => { historyRef.current = [...historyRef.current, screen].slice(-12); setScreen(next); };
  const goBack = (fallback: Screen = 'home') => { const previous = historyRef.current.pop(); setScreen(previous || fallback); };
  const selectTab = (tab: PrimaryTab) => { historyRef.current = []; setScreen(tab); };

  const copyAddress = async () => {
    const address = app.account?.address || app.vaultAddress;
    if (!address) return;
    await copyText(address); setCopied(true); setTimeout(() => setCopied(false), 1200);
  };
  const copyReceiveAddress = async () => {
    const address = receiveAsset === 'sol' ? app.solana.address : app.account?.address;
    if (!address) return;
    await copyText(address); setCopied(true); setTimeout(() => setCopied(false), 1200);
  };
  const toggleNearby = async () => {
    setNearbyError('');
    try { if (app.meshStarted) await app.stopMesh(); else await app.startMesh(); }
    catch (error) { setNearbyError(error instanceof Error ? error.message : 'Nearby could not be changed'); }
  };
  const openSend = (peer?: MeshPeer) => {
    setPayPeer(peer || null); setPayAlias(peer?.alias || ''); setPayAddress(peer?.address || ''); setPayAmount(''); setPayAsset('usdc'); setPayError(''); setPayResult(null); navigate('send');
  };
  const reviewSend = () => {
    const clean = payAddress.trim(); setPayError('');
    if (!isAddress(clean)) { setPayError(payAsset === 'sol' ? 'Choose a valid Blee recipient.' : 'Enter a valid recipient address.'); return; }
    if (payAsset === 'sol') {
      let lamports: bigint;
      try { lamports = parseSolLamports(payAmount); } catch (error) { setPayError(error instanceof Error ? error.message : 'Enter a valid SOL amount.'); return; }
      if (!app.solana.sessionReady || !app.solana.address) { setPayError('Solana wallet is still preparing.'); return; }
      if (!app.solana.offlineReady) { setPayError('Set up offline SOL payments before sending.'); return; }
      if (!app.meshStarted) { setPayError('Turn on Nearby before sending SOL over Blee Mesh.'); return; }
      if (app.solana.gatewayReachable === true && app.solana.balanceLamports !== null && lamports > app.solana.balanceLamports) { setPayError('Amount exceeds your confirmed SOL balance.'); return; }
      setPayAddress(clean); navigate('confirm-send'); return;
    }
    const value = Number(payAmount);
    if (!Number.isFinite(value) || value <= 0) { setPayError('Enter an amount greater than zero.'); return; }
    if (value > Number(app.available || 0)) { setPayError('Amount exceeds your confirmed spendable balance.'); return; }
    setPayAddress(clean); navigate('confirm-send');
  };
  const submitSend = async () => {
    setPayError('');
    if (payAsset === 'sol') {
      if (!app.account) { setPayError('Unlock Blee before sending SOL.'); return; }
      setSolPayBusy(true);
      try {
        const result = await createAndDeliverOfflineSolPayment({ primaryAccount: app.account, recipientEvm: payAddress, amountLamports: parseSolLamports(payAmount).toString() });
        const state = result.delivery.state === 'delivered' ? 'mesh-delivered' : result.delivery.state === 'broadcast' ? 'mesh-broadcast' : 'queued-local';
        setPayResult({ asset: 'sol', route: 'ble-mesh', state, paymentId: result.paymentId, signedTransactionSha256: result.prepared.signedTransactionSha256, recipients: result.recipients });
        void app.solana.refresh(); navigate('send-success');
      } catch (error) { setPayError(error instanceof Error ? error.message : 'SOL payment could not be created'); }
      finally { setSolPayBusy(false); }
      return;
    }
    try { const result = await app.sendPayment(payAddress, payAmount, payAlias || payPeer?.alias); setPayResult({ asset: 'usdc', ...result }); navigate('send-success'); }
    catch (error) { setPayError(error instanceof Error ? error.message : 'Payment could not be created'); }
  };
  const resetSend = () => { setPayPeer(null); setPayAlias(''); setPayAddress(''); setPayAmount(''); setPayAsset('usdc'); setPayError(''); setPayResult(null); setSolPayBusy(false); historyRef.current = []; setScreen('home'); };
  const openPayment = (row: PaymentRecord) => { setSelectedPayment(row); navigate('activity-detail'); };
  const shareAddress = async () => {
    const address = receiveAsset === 'sol' ? app.solana.address : app.account?.address;
    if (!address) return;
    try { if (navigator.share) await navigator.share({ title: `Blee ${receiveAsset === 'sol' ? 'SOL' : 'USDC'} address`, text: address }); else await copyReceiveAddress(); } catch {}
  };

  const handleBackup = async () => {
    setWalletMessage('');
    try { const backup = await exportEncryptedWalletBackup(); downloadText(`blee-wallet-backup-${Date.now()}.json`, backup); setWalletMessage('Encrypted backup created. Your passphrase is still required to restore it.'); }
    catch (error) { setWalletMessage(error instanceof Error ? error.message : 'Could not export wallet backup'); }
  };
  const handleReveal = async () => {
    setWalletMessage(''); setRevealedKey('');
    try { const key = await revealPrivateKey(walletPassphrase); setRevealedKey(key); setWalletMessage('Private key revealed for 30 seconds. Keep it private.'); setTimeout(() => setRevealedKey(''), 30_000); }
    catch (error) { setWalletMessage(error instanceof Error ? error.message : 'Could not reveal private key'); }
  };
  const handleImportPrivateKey = async () => {
    setWalletMessage(''); if (importPassphrase.length < 8) { setWalletMessage('Use a passphrase of at least 8 characters.'); return; } if (confirmImport !== 'IMPORT') { setWalletMessage('Type IMPORT to confirm wallet replacement.'); return; }
    try { const address = await importPrivateKey(importKey, importPassphrase); setWalletMessage(`Wallet ${short(address)} imported. Reloading Blee…`); setTimeout(() => window.location.reload(), 700); }
    catch (error) { setWalletMessage(error instanceof Error ? error.message : 'Could not import private key'); }
  };
  const handleRestoreBackup = async () => {
    setWalletMessage(''); if (confirmImport !== 'IMPORT') { setWalletMessage('Type IMPORT to confirm wallet replacement.'); return; }
    try { const address = await importEncryptedWalletBackup(backupJson); setWalletMessage(`Wallet ${short(address)} restored. Reloading Blee…`); setTimeout(() => window.location.reload(), 700); }
    catch (error) { setWalletMessage(error instanceof Error ? error.message : 'Could not restore wallet backup'); }
  };

  if (!launchSplashDone || !app.persistenceReady) return <main className="blee-app auth-stage"><section className="splash-screen"><div className="splash-logo"><Brand/></div></section></main>;
  if (app.storageError) return <main className="blee-app auth-stage"><section className="auth-screen narrow"><Brand/><div className="auth-copy"><span className="kicker">STORAGE UNAVAILABLE</span><h1>Blee stopped safely.</h1><p>{app.storageError}</p></div><div className="inline-alert"><Icon name="shield"/><span>Your durable payment journal is required before the wallet can open.</span></div></section></main>;

  if (!app.account) {
    const existing = app.vaultExists;
    if (backupMode === 'import-key' || backupMode === 'restore') {
      return <main className="blee-app auth-stage"><section className="auth-screen recovery-auth"><Brand/><button className="subflow-back auth-back" onClick={() => { setBackupMode('overview'); setWalletMessage(''); setConfirmImport(''); }}><Icon name="back"/>Back</button><div className="auth-copy"><span className="kicker">{backupMode === 'import-key' ? 'IMPORT WALLET' : 'RESTORE WALLET'}</span><h1>{backupMode === 'import-key' ? 'Use an existing private key' : 'Restore an encrypted Blee backup'}</h1><p>{backupMode === 'import-key' ? 'The imported key will be encrypted locally with a new Blee passphrase.' : 'Your backup stays encrypted. You will unlock it with the passphrase used when the backup was created.'}</p></div><div className="form-stack">{backupMode === 'import-key' ? <><label><span>Private key</span><input type="password" value={importKey} onChange={(e) => setImportKey(e.target.value)} placeholder="0x…" autoCapitalize="none" autoCorrect="off"/></label><PasswordField label="New Blee passphrase" value={importPassphrase} onChange={setImportPassphrase} placeholder="Minimum 8 characters" autoComplete="new-password"/><div className="field-help"><Icon name="lock" size={14}/><span>Minimum 8 characters. The private key is encrypted before it is stored.</span></div><label><span>Type IMPORT to confirm</span><input value={confirmImport} onChange={(e) => setConfirmImport(e.target.value)} placeholder="IMPORT" autoCapitalize="characters"/></label><button className="primary-button" disabled={!importKey || importPassphrase.length < 8 || confirmImport !== 'IMPORT'} onClick={() => void handleImportPrivateKey()}>Import wallet</button></> : <><label><span>Encrypted backup JSON</span><textarea value={backupJson} onChange={(e) => setBackupJson(e.target.value)} rows={8} placeholder='{"format":"blee-wallet-backup",…}'/></label><label><span>Type IMPORT to confirm</span><input value={confirmImport} onChange={(e) => setConfirmImport(e.target.value)} placeholder="IMPORT" autoCapitalize="characters"/></label><button className="primary-button" disabled={!backupJson || confirmImport !== 'IMPORT'} onClick={() => void handleRestoreBackup()}>Restore wallet</button></>}{walletMessage && <div className="inline-alert"><Icon name="info"/><span>{walletMessage}</span></div>}</div></section></main>;
    }
    const canCreate = displayName.trim().length >= 2 && passphrase.length >= 8 && passphrase === confirmPassphrase;
    const canUnlock = passphrase.length > 0;
    return <main className="blee-app auth-stage"><section className="auth-screen"><Brand/><div className="auth-copy minimal"><h1>{existing ? 'Unlock Blee' : 'Create wallet'}</h1>{existing && <p>Use your passphrase or fingerprint.</p>}</div><div className="form-stack">{!existing && <label><span>Display name</span><input value={displayName} maxLength={24} onChange={(e) => setDisplayName(e.target.value)} placeholder="How people nearby will see you" autoComplete="nickname"/></label>}<PasswordField label={existing ? 'Passphrase' : 'Create passphrase'} value={passphrase} onChange={setPassphrase} placeholder={existing ? 'Enter your passphrase' : 'Minimum 8 characters'} autoComplete={existing ? 'current-password' : 'new-password'}/>{!existing && <PasswordField label="Confirm passphrase" value={confirmPassphrase} onChange={setConfirmPassphrase} placeholder="Repeat your passphrase" autoComplete="new-password"/>}{!existing && <div className="field-help"><Icon name="lock" size={14}/><span>Minimum 8 characters. Your key is encrypted on this device.</span></div>}{biometricStatus.available && !biometricStatus.enabled && <button type="button" className={`biometric-opt-in ${useBiometricNext ? 'selected' : ''}`} onClick={() => setUseBiometricNext((current) => !current)}><span className="biometric-icon"><img src="/brand/fingerprint-clean.svg" alt=""/></span><span><strong>Use fingerprint next time</strong><small>{useBiometricNext ? 'Fingerprint setup will follow this passphrase.' : 'Optional on this device.'}</small></span><span className={`mini-check ${useBiometricNext ? 'on' : ''}`}>{useBiometricNext ? '✓' : ''}</span></button>}{existing && biometricStatus.enabled && <button type="button" className="secondary-button full biometric-unlock" disabled={biometricBusy || app.busy} onClick={() => void handleBiometricUnlock()}><img src="/brand/fingerprint-clean.svg" alt=""/>{biometricBusy ? 'Checking fingerprint…' : 'Unlock with fingerprint'}</button>}{authError && <div className="inline-alert error"><Icon name="info"/><span>{authError}</span></div>}<button className="primary-button" disabled={app.busy || (existing ? !canUnlock : !canCreate)} onClick={async () => { setAuthError(''); try { const enteredPassphrase = passphrase; if (existing) await app.unlock(enteredPassphrase); else { await app.create(enteredPassphrase); app.setAlias(displayName.trim()); } if (useBiometricNext && biometricStatus.available && !biometricStatus.enabled) { try { await BleeBiometric.enroll(enteredPassphrase); window.localStorage.removeItem('blee.biometric.setup'); await refreshBiometricStatus(); } catch (biometricError) { console.warn('Biometric setup not completed', biometricError); } } historyRef.current = []; setScreen('home'); setPassphrase(''); setConfirmPassphrase(''); } catch (error) { setAuthError(error instanceof Error ? error.message : 'Could not open Blee'); } }}>{app.busy ? 'Opening…' : existing ? 'Unlock' : 'Create wallet'}</button><div className="auth-alternatives"><button className="secondary-button full" onClick={() => { setBackupMode('import-key'); setWalletMessage(''); setConfirmImport(''); }}>{existing ? 'Replace with private key' : 'Import private key'}</button><button className="text-action" onClick={() => { setBackupMode('restore'); setWalletMessage(''); setConfirmImport(''); }}>{existing ? 'Restore another Blee backup' : 'Restore encrypted backup'}</button></div></div><div className="auth-foot"><span><Icon name="shield" size={15}/>Encrypted locally</span><span><Icon name="activity" size={15}/>Durable payment journal</span></div></section></main>;
  }

  const renderHome = () => {
    const featuredPeer = nearbyPeers[0];
    return <div className="screen-content home-screen" data-blee-multi-asset-ui="v1" data-blee-home-ui="approved-v4"><div className="app-topbar"><Brand compact/><button className="home-profile-button" onClick={() => selectTab('profile')} aria-label="Open profile"><PersonAvatar name={app.alias} src={app.profilePhoto}/></button></div><section className="home-balance-hero" aria-label="Portfolio balance"><div className="home-balance-value"><strong>{portfolioBalance === null ? '—' : formatAmount(portfolioBalance, 2)}</strong><span>USDC</span></div></section><div className="primary-actions"><button className="action-button send" onClick={() => openSend()}><Icon name="send"/><span>Send</span></button><button className="action-button" onClick={() => navigate('receive')}><Icon name="receive"/><span>Receive</span></button></div>{(app.solana.pendingOutboundCount > 0 || app.verifyingIncoming > 0 || app.pendingIncoming > 0) && <div className="home-alert-stack">{app.solana.pendingOutboundCount > 0 && <div className="pending-strip"><Icon name="clock"/><div><strong>{app.solana.pendingOutboundCount} SOL payment{app.solana.pendingOutboundCount > 1 ? 's' : ''} pending delivery</strong><small>Signed transaction bytes remain durable on this phone and retry over Blee Mesh.</small></div></div>}{app.verifyingIncoming > 0 && <div className="pending-strip"><Icon name="shield"/><div><strong>Verifying nearby payment{app.verifyingIncoming > 1 ? 's' : ''}</strong><small>Stored durably on this phone. Sender authorization is being checked locally.</small></div></div>}{app.pendingIncoming > 0 && <div className="pending-strip"><Icon name="clock"/><div><strong>+{formatAmount(app.pendingIncoming)} USDC pending</strong><small>Received nearby and verified. Included in the displayed balance until Arc confirms settlement.</small></div></div>}</div>}
      <section className="home-modern-section" aria-label="Nearby"><div className="home-modern-heading"><h2>Nearby</h2><button className={`home-discovery-status ${app.meshStarted ? '' : 'offline'}`} onClick={() => selectTab('nearby')}><span className="status-dot"/>{app.meshStarted ? 'Discovering' : 'Nearby off'}</button></div>{featuredPeer ? <button className="home-nearby-card" onClick={() => openSend(featuredPeer)} aria-label={`Pay ${featuredPeer.alias}`}><PersonAvatar name={featuredPeer.alias} src={app.identityFor(featuredPeer.address)?.avatar}/><span className="home-nearby-copy"><strong>{featuredPeer.alias}</strong><small>Nearby via Bluetooth</small></span><span className="home-pay-button">Pay</span></button> : <div className="home-nearby-card"><div className="home-nearby-empty"><span><Icon name="nearby"/></span><span><strong>{app.meshStarted ? 'Looking for someone nearby' : 'Nearby is off'}</strong><small>{app.meshStarted ? 'Keep Bluetooth on. Blee is discovering people around you.' : 'Turn on Nearby to find another Blee user.'}</small></span></div></div>}</section>
      <section className="home-modern-section" aria-label="Assets"><div className="home-modern-heading"><h2>Assets</h2></div><div className="home-assets-card"><div className="home-asset-row"><TokenLogo asset="usdc" className="asset-logo"/><span className="home-asset-main"><strong>USDC</strong><small>{network.name}</small></span><span className="home-asset-value"><strong>{formatAmount(projectedBalance, 2)} USDC</strong><small>${formatAmount(projectedBalance, 2)}</small></span></div><div className="home-asset-row"><TokenLogo asset="sol" className="asset-logo"/><span className="home-asset-main"><strong>Solana</strong><small>Mainnet</small></span><span className="home-asset-value"><strong>{app.solana.balance === null ? '—' : `${formatAmount(app.solana.balance, 4)} SOL`}</strong><small>{app.solana.balance === null ? 'Not synced' : app.portfolio.solUsdValue === null ? 'USD value unavailable' : `$${formatAmount(app.portfolio.solUsdValue, 2)}`}</small></span></div></div></section>
      <section className="home-modern-section" aria-label="Activity"><div className="home-modern-heading"><h2>Activity</h2><button className="home-heading-action" onClick={() => selectTab('activity')}>View all <Icon name="chevron" size={15}/></button></div><div className="home-activity-card">{recentPayments.length ? recentPayments.map((row) => { const incoming = row.direction === 'in'; const identity = app.identityFor(row.counterparty); const name = row.counterpartyAlias || identity?.alias || short(row.counterparty); const symbol = row.assetSymbol || 'USDC'; return <button className="home-activity-row" key={`${row.direction}:${row.id}`} onClick={() => openPayment(row)}><span className="home-activity-icon"><Icon name={incoming ? 'receive' : 'send'} size={20}/></span><span className="home-activity-copy"><strong>{incoming ? `Received from ${name}` : `Sent to ${name}`}</strong><small>{paymentStatus(row)} · {new Date(row.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</small></span><span className="home-activity-amount"><strong>{incoming ? '+' : '−'}{formatAmount(row.amount, symbol === 'SOL' ? 4 : 2)} {symbol}</strong></span></button>; }) : <div className="home-section-empty">Your payments will appear here.</div>}</div></section>
    </div>;
  };

  const renderNearby = () => {
    const radarPeers = app.peers.slice(0, 3);
    return <div className="screen-content nearby-screen" data-blee-nearby-ui="approved-pulse-v2"><header className="nearby-screen-header"><div><h1>Nearby</h1><p>Find someone. Tap to pay.</p></div><button className="nearby-info-button" aria-label="How nearby payments work" onClick={() => document.getElementById('nearby-help')?.scrollIntoView({ behavior: 'smooth', block: 'center' })}><Icon name="info" size={24}/></button></header><section className="nearby-visibility-card"><span className="nearby-bluetooth-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v18l6-5-6-4 6-4-6-5Z"/><path d="m6 7 12 9M6 17 18 8"/></svg></span><span className="nearby-visibility-copy"><strong>{app.meshStarted ? 'Visible to nearby people' : 'Nearby visibility is off'}</strong><small>{app.meshStarted ? 'Others can find you on Blee' : 'Turn it on so other Blee users can find you'}</small></span><button className={`switch ${app.meshStarted ? 'on' : ''}`} onClick={() => void toggleNearby()} aria-label="Nearby visibility"><span/></button></section>{nearbyError && <div className="nearby-error-wrap"><div className="inline-alert error"><Icon name="info"/><span>{nearbyError}</span></div></div>}<section className="nearby-radar-wrap" aria-label="Nearby discovery field"><div className="nearby-radar"><div className="radar-self"><span className="radar-self-mark"><PersonAvatar name={app.alias} src={app.profilePhoto} size="lg"/></span><small>You</small></div>{radarPeers.map((peer, index) => <button className={`radar-peer radar-peer-${index}`} key={`radar:${peer.address}:${peer.transportId}`} onClick={() => openSend(peer)} aria-label={`Pay ${peer.alias}`}><span className="radar-peer-avatar"><PersonAvatar name={peer.alias} src={app.identityFor(peer.address)?.avatar} size="lg"/></span><span className="radar-peer-name">{peer.alias}</span></button>)}</div><div className={`nearby-radar-status ${app.meshStarted ? '' : 'offline'}`}><span className="nearby-online-dot"/>{app.meshStarted ? 'Looking for people nearby' : 'Nearby is off'}</div><p className="nearby-radar-helper">{app.meshStarted ? 'Keep Bluetooth on to stay connected' : 'Turn on visibility to discover people around you'}</p></section><section className="nearby-people-section"><div className="nearby-people-heading"><h2>People nearby</h2><span className="nearby-count-pill">{app.peers.length}</span><button className="nearby-refresh-button" aria-label="Refresh nearby people" onClick={() => window.dispatchEvent(new CustomEvent('blee:refresh-all', { detail: { source: 'nearby-screen' } }))}><Icon name="refresh" size={22}/></button></div><div className="nearby-people-list">{app.meshStarted && app.peers.length ? app.peers.map((peer) => <div className="nearby-person-row" key={`${peer.address}:${peer.transportId}`}><PersonAvatar name={peer.alias} src={app.identityFor(peer.address)?.avatar}/><span className="nearby-person-copy"><strong>{peer.alias}</strong><small><span className="nearby-online-dot"/>Available to pay</small></span><button className="nearby-pay-button" onClick={() => openSend(peer)}>Pay</button></div>) : <div className="nearby-list-empty"><strong>{app.meshStarted ? 'No one nearby yet' : 'Nearby is off'}</strong><small>{app.meshStarted ? 'Blee is still scanning. Keep Bluetooth enabled on both phones.' : 'Turn on visibility above to start discovering Blee users.'}</small></div>}</div></section><footer className="nearby-trust-footer" id="nearby-help"><div className="nearby-trust-line"><Icon name="shield" size={20}/><span>No wallet address. No QR code.</span></div><button className="nearby-help-link" onClick={() => navigate('network-security')}>How nearby payments work</button></footer></div>;
  };

  const renderActivity = () => <div className="screen-content"><ScreenHeader title="Activity" trailing={pendingPayments.length ? <span className="count-badge">{pendingPayments.length}</span> : null}/><div className="filter-tabs" role="tablist" aria-label="Activity filter"><button className={activityFilter === 'all' ? 'active' : ''} onClick={() => setActivityFilter('all')}>All</button><button className={activityFilter === 'sent' ? 'active' : ''} onClick={() => setActivityFilter('sent')}>Sent</button><button className={activityFilter === 'received' ? 'active' : ''} onClick={() => setActivityFilter('received')}>Received</button></div>{filteredPayments.length ? <div className="surface-list activity-list">{filteredPayments.map((row) => <PaymentRow key={`${row.direction}:${row.id}`} row={row} identity={app.identityFor(row.counterparty)} onOpen={openPayment}/>)}</div> : <EmptyState icon="activity" title={visiblePayments.length ? 'Nothing in this view' : 'No activity yet'} copy={visiblePayments.length ? 'Choose another activity filter.' : 'Settled, pending and nearby payments stay in the durable payment journal.'}/>}</div>;

  const renderProfile = () => <div className="screen-content profile-screen approved-screen" data-blee-profile-ui="approved-v1"><header className="profile-screen-header"><h1>Profile</h1><button className="profile-settings-button" onClick={() => navigate('settings')} aria-label="Settings"><Icon name="settings" size={30}/></button></header><section className="profile-hero-row"><PersonAvatar name={app.alias} src={app.profilePhoto} size="xl"/><div className="profile-hero-copy"><h2>{app.alias}</h2><button className="profile-edit-pill" onClick={() => { setProfileName(app.alias); setProfilePhotoDraft(app.profilePhoto || null); navigate('edit-profile'); }}>Edit profile</button></div></section><h2 className="profile-addresses-title">Your addresses</h2><div className="profile-address-list"><button className="profile-address-row" onClick={() => void copyAddress()}><span className="profile-row-icon"><Icon name="network" size={31}/></span><span className="profile-row-copy"><span className="profile-row-title"><strong>Arc Testnet</strong><span className="profile-testnet-pill">Testnet</span></span><code>{short(app.account?.address || app.vaultAddress)}</code></span><Icon name={copied ? 'check' : 'copy'} size={24}/></button><button className="profile-address-row" disabled={!app.solana.address} onClick={() => app.solana.address && void copyText(app.solana.address)}><span className="profile-row-icon"><TokenLogo asset="sol"/></span><span className="profile-row-copy"><span className="profile-row-title"><strong>Solana Mainnet</strong></span><code>{short(app.solana.address)}</code></span><Icon name="copy" size={24}/></button></div><div className="profile-menu-group"><button className="profile-menu-row" onClick={() => navigate('settings')}><span className="profile-row-icon"><Icon name="settings" size={29}/></span><span className="profile-row-copy"><strong>Settings</strong><small>Backup, fingerprint and networks</small></span><Icon name="chevron" size={24}/></button><button className="profile-menu-row" onClick={() => { setProfileName(app.alias); setProfilePhotoDraft(app.profilePhoto || null); navigate('edit-profile'); }}><span className="profile-row-icon"><Icon name="nearby" size={30}/></span><span className="profile-row-copy"><strong>Your nearby identity</strong><small>People on Blee see your name and photo.</small></span><Icon name="chevron" size={24}/></button></div><p className="profile-manage-label">Manage profile</p></div>;

  const renderSend = () => {
    const sol = payAsset === 'sol';
    const solRouteReady = app.solana.sessionReady && app.solana.offlineReady && app.meshStarted;
    const networkReady = sol ? solRouteReady : (app.arcReachable || (app.meshStarted && Boolean(payPeer)));
    const statusTitle = sol ? (!app.solana.sessionReady ? 'Solana wallet is preparing' : !app.solana.offlineReady ? 'Set up offline payments' : !app.meshStarted ? 'Turn on Nearby' : 'Ready for offline SOL delivery') : (networkReady ? 'Ready to send' : 'Waiting for a connection');
    const statusCopy = sol ? (!app.solana.offlineReady ? 'Prepare SOL for sending without internet.' : !app.meshStarted ? 'Nearby is required for offline SOL delivery.' : 'Your signed SOL payment can move over Blee Mesh.') : (networkReady ? 'Blee will use the safest available route.' : 'Your payment will stay on this phone until it can be forwarded.');
    return <div className="screen-content send-screen approved-screen" data-blee-send-asset={payAsset} data-blee-send-ui="approved-v1"><ScreenHeader title="Send" onBack={() => goBack('home')} trailing={<button className="approved-help-button" onClick={() => navigate('network-security')} aria-label="Send help">?</button>}/><div className="approved-segmented" role="tablist" aria-label="Send asset"><button className={!sol ? 'active' : ''} onClick={() => { setPayAsset('usdc'); setPayError(''); }}>USDC</button><button className={sol ? 'active' : ''} onClick={() => { setPayAsset('sol'); setPayError(''); }}>SOL</button></div><div className="send-network-row">{sol && <TokenLogo asset="sol"/>}<span>{sol ? 'Solana Mainnet' : 'Arc Testnet'}</span><span>⌄</span>{!sol && <span className="send-network-pill">Test funds</span>}</div><label className="send-recipient-label">To</label><div className="send-recipient-wrap">{payPeer ? <div className="recipient-summary"><PersonAvatar name={payPeer.alias} src={app.identityFor(payPeer.address)?.avatar}/><span><strong>{payPeer.alias}</strong><code>{short(payPeer.address)}</code></span><button className="text-action" onClick={() => { setPayPeer(null); setPayAddress(''); setPayAlias(''); }}>Change</button></div> : <RecipientField walletLayout value={payAddress} placeholder={sol ? 'Choose a Blee recipient' : 'Name or wallet address'} onNearby={() => selectTab('nearby')} onChange={(value) => { setPayAddress(value); setPayAlias(''); }} onSelectContact={(contact) => setPayAlias(contact.displayName || '')}/>}</div><div className="send-amount-area"><input className="send-amount-input" inputMode="decimal" value={payAmount} onChange={(e) => setPayAmount(e.target.value.replace(/[^0-9.]/g, ''))} placeholder="0.00" aria-label={`${sol ? 'SOL' : 'USDC'} amount`}/><div className="send-token-chip"><TokenLogo asset={sol ? 'sol' : 'usdc'}/><span>{sol ? 'SOL' : 'USDC'}</span><span>⌄</span></div><div className="send-balance-copy">{sol ? (app.solana.balance === null ? <><span>Balance unavailable</span><br/><button onClick={() => void app.solana.refresh()}>Retry</button></> : `${formatAmount(app.solana.balance, 9)} SOL available`) : `${formatAmount(app.available)} USDC available`}</div></div><div className="send-status-area"><button className="send-status-card" disabled={sol && app.solana.offlineReady} onClick={() => { if (sol && !app.solana.offlineReady) navigate('network-security'); }}><span><Icon name={sol ? 'wifi' : 'network'} size={30}/></span><span><strong>{statusTitle}</strong><small>{statusCopy}</small></span>{sol && !app.solana.offlineReady && <Icon name="chevron" size={22}/>}</button>{sol && <div className="send-fee-note"><Icon name="info" size={20}/><span>Fees are paid in SOL.</span></div>}</div>{payError && <div className="inline-alert error"><Icon name="info"/><span>{payError}</span></div>}<div className="sticky-action"><button className="primary-button" disabled={!payAddress || !payAmount || (sol && !solRouteReady)} onClick={reviewSend}>Review payment</button><div className="send-action-helper">Choose a recipient and enter an amount.</div></div></div>;
  };

  const renderConfirmSend = () => {
    const sol = payAsset === 'sol';
    const recipientName = payAlias || payPeer?.alias || app.identityFor(payAddress)?.alias || short(payAddress);
    return <div className="screen-content" data-blee-confirm-asset={payAsset}><ScreenHeader title="Confirm send" onBack={() => goBack('send')}/><div className="confirm-recipient"><PersonAvatar name={recipientName} src={payPeer ? app.identityFor(payPeer.address)?.avatar : app.identityFor(payAddress)?.avatar} size="lg"/><strong>{recipientName}</strong><small>{short(payAddress)}</small></div>{sol ? <section className="confirm-card"><div><span>Amount</span><strong>{formatAmount(payAmount, 9)} SOL</strong></div><div><span>Network</span><strong>Solana Mainnet</strong></div><div><span>Settlement</span><strong>Sender-funded</strong></div><div><span>Offline signing</span><strong>Durable nonce</strong></div><div><span>Delivery</span><strong>Blee Mesh</strong></div></section> : <section className="confirm-card"><div><span>Amount</span><strong>{formatAmount(payAmount)} USDC</strong></div><div><span>Network</span><strong>Arc Testnet</strong></div><div><span>Settlement</span><strong>Sender-funded</strong></div><div><span>Delivery</span><strong>{app.arcReachable ? 'Online' : payPeer && app.meshStarted ? 'Nearby first' : 'Durable queue'}</strong></div></section>}<div className="quiet-note"><Icon name="shield"/><span>{sol ? 'Blee will reserve one prepared nonce, sign the exact SOL transaction locally, persist those exact bytes, and only then transmit them over Bluetooth Mesh.' : 'The amount, recipient and settlement authorization are signed by your wallet. Courier phones cannot change them or spend their own gas for your payment.'}</span></div>{payError && <div className="inline-alert error"><Icon name="info"/><span>{payError}</span></div>}<div className="sticky-action"><button className="primary-button" disabled={sol ? solPayBusy || !app.solana.offlineReady : app.busy} onClick={() => void submitSend()}>{sol ? (solPayBusy ? 'Signing SOL payment…' : 'Confirm and send SOL') : (app.busy ? 'Securing payment…' : 'Confirm and send')}</button></div></div>;
  };

  const renderSendSuccess = () => {
    if (payResult?.asset === 'sol') {
      const delivered = payResult.state === 'mesh-delivered'; const broadcasting = payResult.state === 'mesh-broadcast';
      const kicker = delivered ? 'DELIVERED NEARBY' : broadcasting ? 'SENDING NEARBY' : 'PAYMENT SECURED';
      const title = delivered ? 'SOL payment delivered' : broadcasting ? 'SOL payment is on its way' : 'SOL payment queued safely';
      const copy = delivered ? 'The intended recipient durably stored and acknowledged the exact signed SOL transaction. On-chain submission is a separate settlement step.' : broadcasting ? 'The exact sender-signed SOL transaction is stored durably and has entered Blee Mesh. It is not marked delivered until the intended recipient acknowledges it.' : 'The exact sender-signed SOL transaction is stored durably on this phone and can retry without rebuilding or re-signing it.';
      return <div className="screen-content success-screen" data-blee-success-asset="sol"><button className="close-success" onClick={resetSend} aria-label="Close"><Icon name="close"/></button><div className="success-mark"><Icon name={delivered ? 'check' : 'clock'} size={34}/></div><span className="kicker">{kicker}</span><h1>{title}</h1><div className="success-amount">{formatAmount(payAmount, 9)} <span>SOL</span></div><p>{copy}</p><div className="quiet-note"><Icon name="network"/><span>Solana Mainnet · sender-funded · durable nonce. This screen does not claim on-chain confirmation.</span></div><div className="success-actions"><button className="primary-button" onClick={resetSend}>Done</button></div></div>;
    }
    const state = payResult?.state || 'queued-local'; const settled = state === 'settled'; const submitted = state === 'submitted'; const delivered = state === 'mesh-delivered'; const broadcasting = state === 'mesh-broadcast';
    const kicker = settled ? 'CONFIRMED' : submitted ? 'SUBMITTED' : delivered ? 'DELIVERED NEARBY' : broadcasting ? 'SENDING NEARBY' : 'PAYMENT SECURED';
    const title = settled ? 'Payment confirmed' : submitted ? 'Settlement submitted' : delivered ? 'Payment delivered' : broadcasting ? 'Payment is on its way' : 'Payment queued safely';
    const copy = settled ? 'Your transfer is confirmed on Arc Testnet.' : submitted ? 'Your sender-funded transaction is on Arc Testnet and is awaiting confirmation.' : delivered ? 'The intended recipient stored and acknowledged the payment. Settlement will continue automatically when an internet route is available.' : broadcasting ? 'Blee has started nearby delivery. It is not marked delivered until the intended recipient stores it and acknowledges it.' : 'The signed payment is stored durably on this phone and will retry automatically when a safe route is available.';
    return <div className="screen-content success-screen"><button className="close-success" onClick={resetSend} aria-label="Close"><Icon name="close"/></button><div className="success-mark"><Icon name={settled ? 'check' : 'clock'} size={34}/></div><span className="kicker">{kicker}</span><h1>{title}</h1><div className="success-amount">{formatAmount(payAmount)} <span>USDC</span></div><p>{copy}</p>{payResult?.txHash && network.explorerUrl && <a className="secondary-button" href={`${network.explorerUrl}/tx/${payResult.txHash}`} target="_blank" rel="noreferrer">View on explorer <Icon name="external"/></a>}<div className="success-actions"><button className="primary-button" onClick={() => { historyRef.current = []; setScreen('activity'); }}>View activity</button><button className="text-action" onClick={resetSend}>Done</button></div></div>;
  };

  const renderReceive = () => {
    const sol = receiveAsset === 'sol';
    const address = sol ? app.solana.address : app.account!.address;
    return <div className="screen-content receive-screen approved-screen" data-blee-receive-asset={receiveAsset} data-blee-receive-ui="approved-v1"><ScreenHeader title="Receive" onBack={() => goBack('home')} trailing={<button className="approved-help-button" onClick={() => navigate('network-security')} aria-label="Receive help">?</button>}/><div className="approved-segmented" role="tablist" aria-label="Receive asset"><button className={!sol ? 'active' : ''} onClick={() => { setReceiveAsset('usdc'); setCopied(false); }}>USDC</button><button className={sol ? 'active' : ''} onClick={() => { setReceiveAsset('sol'); setCopied(false); }}>SOL</button></div>{address ? <><section className="receive-asset-hero"><TokenLogo asset={sol ? 'sol' : 'usdc'} className="receive-asset-logo"/><h2>Receive {sol ? 'SOL' : 'USDC'}</h2><p>{sol ? 'Solana Mainnet' : 'Network: Arc Testnet'}</p>{!sol && <span className="receive-network-pill">Test funds</span>}</section><div className="receive-qr-card"><QRCodeSVG value={address} size={280} level="M" bgColor="#ffffff" fgColor="#090909"/></div><p className="receive-qr-caption">QR code</p><div className="receive-profile"><PersonAvatar name={app.alias} src={app.profilePhoto}/><strong>{app.alias}</strong></div><button className="receive-address-button" onClick={() => void copyReceiveAddress()}><span>{short(address)}</span><Icon name={copied ? 'check' : 'copy'} size={22}/></button><p className="receive-warning">{sol ? 'Only send SOL on Solana to this address.' : 'Only send test USDC on Arc Testnet.'}</p><div className="receive-actions"><button className="receive-copy" onClick={() => void copyReceiveAddress()}><Icon name="copy" size={23}/>Copy address</button><button className="receive-share" onClick={() => void shareAddress()}><Icon name="backup" size={23}/>Share</button></div><div className="receive-nearby-row"><span className="receive-nearby-icon"><Icon name="nearby" size={26}/></span><span><strong>Paying nearby?</strong><small>Find me on Blee. No QR needed.</small></span><button onClick={() => selectTab('nearby')}>Open Nearby →</button></div></> : <EmptyState icon="wallet" title="Solana wallet is preparing" copy="Your SOL address appears here after the authenticated Solana session is ready."/>}</div>;
  };

  const renderActivityDetail = () => {
    if (!selectedPayment) return renderActivity();
    const incoming = selectedPayment.direction === 'in';
    const counterparty = selectedPayment.counterpartyAlias || app.identityFor(selectedPayment.counterparty)?.alias || short(selectedPayment.counterparty);
    return <div className="screen-content"><ScreenHeader title="Payment details" onBack={() => { setSelectedPayment(null); goBack('activity'); }}/><div className="detail-hero"><PersonAvatar name={counterparty} src={app.identityFor(selectedPayment.counterparty)?.avatar} size="lg"/><span>{incoming ? 'Received from' : 'Sent to'} {counterparty}</span><h1>{incoming ? '+' : '−'}{formatAmount(selectedPayment.amount)} USDC</h1><small>{formatTimestamp(selectedPayment.createdAt)}</small></div><section className="timeline-card"><div className="timeline-row done"><span/><div><strong>Created</strong><small>{formatTimestamp(selectedPayment.createdAt)}</small></div></div>{selectedPayment.durablyReceivedAt && <div className="timeline-row done"><span/><div><strong>Delivered nearby</strong><small>{formatTimestamp(selectedPayment.durablyReceivedAt)}</small></div></div>}{selectedPayment.submittedAt && <div className="timeline-row done"><span/><div><strong>Submitted to Arc</strong><small>{formatTimestamp(selectedPayment.submittedAt)}</small></div></div>}{selectedPayment.settledAt && <div className="timeline-row done"><span/><div><strong>Confirmed</strong><small>{formatTimestamp(selectedPayment.settledAt)}</small></div></div>}{(!selectedPayment.settledAt && !(selectedPayment.state === 'submitted' && selectedPayment.submittedAt)) && <div className={`timeline-row ${selectedPayment.state === 'failed' ? 'failed' : 'current'}`}><span/><div><strong>{paymentStatus(selectedPayment)}</strong><small>{paymentStatusDetail(selectedPayment)}</small></div></div>}</section><section className="detail-list"><div><span>Counterparty</span><strong>{counterparty}</strong></div><div><span>Route</span><strong>{selectedPayment.route === 'arc-direct' ? 'Arc Testnet' : selectedPayment.route === 'ble-mesh' ? 'Blee Mesh' : 'Durable queue'}</strong></div><div><span>Status</span><strong>{paymentStatus(selectedPayment)}</strong></div></section>{selectedPayment.txHash && network.explorerUrl && <a className="secondary-button full" href={`${network.explorerUrl}/tx/${selectedPayment.txHash}`} target="_blank" rel="noreferrer">View transaction <Icon name="external"/></a>}</div>;
  };

  const renderEditProfile = () => <div className="screen-content edit-profile-screen approved-screen" data-blee-edit-profile-ui="approved-v1"><ScreenHeader title="Edit profile" onBack={() => { setProfileName(app.alias); setProfilePhotoDraft(app.profilePhoto || null); setProfilePhotoError(''); goBack('profile'); }}/><section className="edit-profile-photo"><PersonAvatar name={profileName || app.alias} src={profilePhotoDraft} size="xl"/><button className="camera-button" onClick={() => photoInputRef.current?.click()} aria-label="Change photo"><Icon name="camera" size={24}/></button><input ref={photoInputRef} type="file" accept="image/*" hidden onChange={async (event) => { const file = event.target.files?.[0]; event.currentTarget.value = ''; if (!file) return; setProfilePhotoError(''); try { setProfilePhotoDraft(await prepareProfilePhoto(file)); } catch (error) { setProfilePhotoError(error instanceof Error ? error.message : 'Could not use this photo'); } }}/></section><div className="profile-photo-actions"><button className="change-photo" onClick={() => photoInputRef.current?.click()}>Change photo</button>{profilePhotoDraft && <button className="remove-photo" onClick={() => setProfilePhotoDraft(null)}>Remove photo</button>}</div><label className="field-block"><span>Display name</span><input value={profileName} maxLength={24} onChange={(e) => setProfileName(e.target.value)} placeholder="Your name"/></label><p className="profile-visibility-copy">Your name and photo are visible to people nearby.</p>{profilePhotoError && <div className="inline-alert error"><Icon name="info"/><span>{profilePhotoError}</span></div>}<section className="recognition-row"><span className="profile-row-icon"><Icon name="person" size={29}/></span><span><strong>Help people recognize you</strong><small>Use a name and photo your contacts know.</small></span></section><div className="sticky-action"><button className="primary-button" disabled={!profileName.trim()} onClick={() => { app.setAlias(profileName.trim()); app.setProfilePhoto(profilePhotoDraft); goBack('profile'); }}>Save changes</button></div></div>;

  const renderSettings = () => <div className="screen-content settings-screen approved-screen" data-blee-settings-ui="approved-v1"><ScreenHeader title="Settings" onBack={() => goBack('profile')}/><section className="settings-section"><h2 className="settings-section-title">SECURITY</h2><button className="settings-row" onClick={() => navigate('backup-recovery')}><span className="settings-row-icon"><Icon name="backup" size={30}/></span><span className="settings-row-copy"><strong>Backup & recovery</strong><small>Backups and private keys</small></span><Icon name="chevron" size={24}/></button>{biometricStatus.available && <div className="settings-row"><span className="settings-row-icon"><img src="/brand/fingerprint-clean.svg" alt=""/></span><span className="settings-row-copy"><strong>Fingerprint unlock</strong><small>{biometricStatus.enabled ? 'Enabled on this device' : 'Available on this device'}</small></span><button className={`switch ${biometricStatus.enabled ? 'on' : ''}`} onClick={async () => { if (biometricStatus.enabled) { await BleeBiometric.disable(); await refreshBiometricStatus(); } else { window.localStorage.setItem('blee.biometric.setup', '1'); setUseBiometricNext(true); await app.lock(); } }} aria-label="Fingerprint unlock"><span/></button></div>}<button className="settings-row" onClick={() => navigate('network-security')}><span className="settings-row-icon"><Icon name="shield" size={31}/></span><span className="settings-row-copy"><strong>Network & security</strong><small>Networks and nearby payments</small></span><Icon name="chevron" size={24}/></button></section><section className="settings-section"><h2 className="settings-section-title">ACTIVE NETWORKS</h2><button className="settings-row" onClick={() => navigate('network-security')}><span className="settings-row-icon"><Icon name="network" size={31}/></span><span className="settings-row-copy"><span className="settings-network-title"><strong>Arc Testnet</strong><span className="profile-testnet-pill">Testnet</span></span><small>Use a test network</small></span><Icon name="chevron" size={24}/></button><button className="settings-row" onClick={() => navigate('network-security')}><span className="settings-row-icon"><TokenLogo asset="sol"/></span><span className="settings-row-copy"><strong>Solana Mainnet</strong><small>Use the Solana network</small></span><Icon name="chevron" size={24}/></button></section><button className="logout-button" onClick={() => void app.lock()}><Icon name="logout" size={25}/>Log out</button><p className="build-note">Blee 2.7</p></div>;

  const renderBackupRecovery = () => <div className="screen-content"><ScreenHeader title="Backup & recovery" onBack={() => { setBackupMode('overview'); setWalletMessage(''); goBack('settings'); }}/>{backupMode === 'overview' && <><section className="security-hero"><Icon name="shield" size={28}/><h2>Keep control of your wallet</h2><p>Your encrypted wallet stays on this device. Keep a backup somewhere you control.</p></section><div className="menu-list"><button onClick={() => void handleBackup()}><span className="menu-icon"><Icon name="backup"/></span><span><strong>Download encrypted backup</strong><small>Requires your passphrase to restore</small></span><Icon name="chevron"/></button><button onClick={() => setBackupMode('reveal')}><span className="menu-icon"><Icon name="key"/></span><span><strong>Reveal private key</strong><small>Passphrase required</small></span><Icon name="chevron"/></button><button onClick={() => setBackupMode('import-key')}><span className="menu-icon"><Icon name="wallet"/></span><span><strong>Import private key</strong><small>Replace this device wallet</small></span><Icon name="chevron"/></button><button onClick={() => setBackupMode('restore')}><span className="menu-icon"><Icon name="backup"/></span><span><strong>Restore encrypted backup</strong><small>Replace this device wallet</small></span><Icon name="chevron"/></button></div></>}{backupMode === 'reveal' && <div className="subflow"><button className="subflow-back" onClick={() => { setBackupMode('overview'); setWalletMessage(''); setRevealedKey(''); }}><Icon name="back"/>Back</button><h2>Reveal private key</h2><p>Only do this somewhere private. Blee hides the key again after 30 seconds.</p><PasswordField label="Wallet passphrase" value={walletPassphrase} onChange={setWalletPassphrase} placeholder="Enter passphrase" autoComplete="current-password"/><button className="primary-button" disabled={!walletPassphrase} onClick={() => void handleReveal()}>Reveal key</button>{revealedKey && <div className="secret-card"><code>{revealedKey}</code><button onClick={() => void copyText(revealedKey)}><Icon name="copy"/>Copy</button></div>}</div>}{backupMode === 'import-key' && <div className="subflow"><button className="subflow-back" onClick={() => { setBackupMode('overview'); setWalletMessage(''); }}><Icon name="back"/>Back</button><h2>Import private key</h2><p>This replaces the wallet on this device.</p><label className="field-block"><span>Private key</span><input type="password" value={importKey} onChange={(e) => setImportKey(e.target.value)} placeholder="0x…" autoCapitalize="none"/></label><PasswordField label="New Blee passphrase" value={importPassphrase} onChange={setImportPassphrase} placeholder="Minimum 8 characters" autoComplete="new-password"/><label className="field-block"><span>Type IMPORT to confirm</span><input value={confirmImport} onChange={(e) => setConfirmImport(e.target.value)} placeholder="IMPORT"/></label><button className="primary-button" disabled={!importKey || importPassphrase.length < 8 || confirmImport !== 'IMPORT'} onClick={() => void handleImportPrivateKey()}>Import wallet</button></div>}{backupMode === 'restore' && <div className="subflow"><button className="subflow-back" onClick={() => { setBackupMode('overview'); setWalletMessage(''); }}><Icon name="back"/>Back</button><h2>Restore encrypted backup</h2><p>Paste a Blee encrypted backup JSON file. Its existing passphrase remains required when you unlock it.</p><label className="field-block"><span>Backup JSON</span><textarea value={backupJson} onChange={(e) => setBackupJson(e.target.value)} rows={7} placeholder='{"format":"blee-wallet-backup",…}'/></label><label className="field-block"><span>Type IMPORT to confirm</span><input value={confirmImport} onChange={(e) => setConfirmImport(e.target.value)} placeholder="IMPORT"/></label><button className="primary-button" disabled={!backupJson || confirmImport !== 'IMPORT'} onClick={() => void handleRestoreBackup()}>Restore wallet</button></div>}{walletMessage && <div className="inline-alert"><Icon name="info"/><span>{walletMessage}</span></div>}</div>;

  const renderNetworkSecurity = () => <div className="screen-content"><ScreenHeader title="Network & security" onBack={() => goBack('settings')}/><section className="network-card"><div className="network-title"><span className="menu-icon"><Icon name="network"/></span><div><span className="kicker">USDC SETTLEMENT</span><strong>Arc Testnet</strong><small>Chain 5042002</small></div><span className="status-badge">TESTNET</span></div><div className="network-detail"><span>Payment token</span><strong>USDC</strong></div><div className="network-detail"><span>Settlement model</span><strong>Sender-funded</strong></div></section><section className="network-card" data-blee-solana-network="mainnet"><div className="network-title"><span className="menu-icon"><TokenLogo asset="sol"/></span><div><span className="kicker">SOL SETTLEMENT</span><strong>Solana Mainnet</strong><small>{app.solana.address ? short(app.solana.address) : 'Wallet preparing'}</small></div><span className="status-badge">MAINNET</span></div><div className="network-detail"><span>Asset</span><strong>SOL</strong></div><div className="network-detail"><span>Offline readiness</span><strong>{app.solana.offlineReady ? `${app.solana.readyNonceCount} prepared` : 'Not prepared'}</strong></div><div className="network-detail"><span>RPC boundary</span><strong>Blee Gateway</strong></div></section><div className="settings-toggle-list"><div><span className="menu-icon"><Icon name="nearby"/></span><span><strong>Nearby payments</strong><small>Discover and pay Blee users nearby</small></span><button className={`switch ${app.meshStarted ? 'on' : ''}`} onClick={() => void toggleNearby()}><span/></button></div><div><span className="menu-icon"><Icon name="shield"/></span><span><strong>Automatic mesh relay</strong><small>Carry signed packets; relay phones never pay another user’s gas</small></span><span className="status-badge">ON</span></div><div><span className="menu-icon"><Icon name="activity"/></span><span><strong>Payment journal</strong><small>SQLite + WAL · durable local history</small></span><span className="status-badge">ACTIVE</span></div></div><div className="quiet-note"><Icon name="info"/><span>USDC and SOL remain independent spendable balances. Home converts SOL to its USD value and shows a combined USDC-equivalent portfolio total for presentation only; spend checks, signing and settlement remain asset-specific.</span></div></div>;

  const renderCurrent = () => {
    switch (screen) {
      case 'home': return renderHome(); case 'nearby': return renderNearby(); case 'activity': return renderActivity(); case 'profile': return renderProfile(); case 'send': return renderSend(); case 'confirm-send': return renderConfirmSend(); case 'send-success': return renderSendSuccess(); case 'receive': return renderReceive(); case 'activity-detail': return renderActivityDetail(); case 'edit-profile': return renderEditProfile(); case 'settings': return renderSettings(); case 'backup-recovery': return renderBackupRecovery(); case 'network-security': return renderNetworkSecurity();
    }
  };

  const primary = ['home', 'nearby', 'activity', 'profile'].includes(screen);
  return <main className="blee-app"><section className={`blee-phone ${primary ? 'with-nav' : ''}`}><div className="screen-transition" key={screen}>{renderCurrent()}</div></section>{primary && <BottomNav active={activeTab} onChange={selectTab}/>}</main>;
}
