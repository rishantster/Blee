#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

required=(
  package.json
  package-lock.json
  next.config.ts
  tsconfig.json
  capacitor.config.ts
  .env.example
  app/globals.css
  src/components/BleeApp.tsx
  src/components/BleeRuntime.tsx
  src/components/RecipientField.tsx
  src/components/RecipientField.module.css
  src/hooks/useBlee.ts
  src/hooks/useBleeView.ts
  src/hooks/useContacts.ts
  src/lib/bleeStore.ts
  src/lib/persistence.ts
  src/lib/payments.ts
  src/lib/atomicSigning.ts
  src/lib/walletRecovery.ts
  src/lib/walletRestore.ts
  src/lib/networkConfig.ts
  src/lib/rails.ts
  src/lib/solanaGateway.ts
  src/lib/solanaVault.ts
  src/lib/solanaSession.ts
  plugins/blee-store/package.json
  plugins/blee-nearby/package.json
  android/gradlew
  android/app/build.gradle
  android/app/src/main/AndroidManifest.xml
  android/app/src/main/java/com/blee/payments/MainActivity.java
  android/app/src/main/java/com/blee/payments/BleeMeshService.java
  android/app/src/main/java/com/blee/payments/BleeMeshDb.java
  android/app/src/main/java/com/blee/payments/BleeMeshPlugin.java
  android/app/src/main/java/com/blee/payments/BleeContactsPlugin.java
  android/app/src/main/java/com/blee/payments/BleePaymentNotifier.java
  android/app/src/main/java/com/blee/payments/BleePaymentEventReceiver.java
  android/app/src/main/java/com/blee/payments/BleePeerProfile.java
)

for path in "${required[@]}"; do
  [ -f "$path" ] || fail "missing source file: $path"
done

PACKAGE_VERSION="$(node -p "require('./package.json').version")"
LOCK_VERSION="$(node -p "require('./package-lock.json').version")"
LOCK_ROOT_VERSION="$(node -p "require('./package-lock.json').packages[''].version")"

[ "$PACKAGE_VERSION" = "2.7.1" ] || fail "package version is $PACKAGE_VERSION, expected 2.7.1"
[ "$LOCK_VERSION" = "$PACKAGE_VERSION" ] || fail "package-lock version is $LOCK_VERSION, expected $PACKAGE_VERSION"
[ "$LOCK_ROOT_VERSION" = "$PACKAGE_VERSION" ] || fail "package-lock root package version is $LOCK_ROOT_VERSION, expected $PACKAGE_VERSION"

grep -Eq 'versionCode[[:space:]]+18' android/app/build.gradle || fail "Android versionCode must be 18"
grep -Eq 'versionName[[:space:]]+"2[.]7[.]1"' android/app/build.gradle || fail "Android versionName must be 2.7.1"
grep -Eq 'sourceCompatibility[[:space:]]+JavaVersion.VERSION_21' android/app/build.gradle || fail "Android sourceCompatibility must be Java 21"
grep -Eq 'targetCompatibility[[:space:]]+JavaVersion.VERSION_21' android/app/build.gradle || fail "Android targetCompatibility must be Java 21"

for legacy in legacy bootstrap professional ui-v4 ui-v5 mesh-v2 overrides; do
  if git ls-files "$legacy/**" | grep -q .; then
    fail "legacy build input is still tracked at $legacy/"
  fi
done

if git ls-files 'scripts/apply-blee-*' 'scripts/finish-blee-*' 'scripts/resume-android-build.sh' | grep -q .; then
  fail "legacy source mutation/recovery scripts are still tracked"
fi

if git ls-files 'android/app/src/main/assets/**' | grep -q .; then
  fail "generated Capacitor Android assets must not be tracked"
fi
if git ls-files 'android/**/build/**' 'plugins/**/android/build/**' | grep -q .; then
  fail "generated Android/Gradle build output must not be tracked"
fi

grep -q 'plugins/\*\*/android/build/' .gitignore || fail "native plugin build output is not ignored"
grep -q '^\.env\.local$' .gitignore || fail "local Helius build configuration must stay untracked"
grep -q '^NEXT_PUBLIC_BLEE_HELIUS_SECURE_RPC=https://YOUR-SECURE-ENDPOINT-fast-mainnet[.]helius-rpc[.]com$' .env.example || fail "Helius Secure RPC example configuration missing"

if grep -q 'configure-native[.]mjs' package.json; then
  fail "package.json still references removed configure-native.mjs"
fi
if grep -q 'cap add android' package.json; then
  fail "Android is tracked source; package.json must not recreate it with cap add"
fi

grep -q 'root: process.cwd()' next.config.ts || fail "Turbopack workspace root is not pinned to this repository"

STORE_REGISTRATIONS="$(grep -R "registerPlugin.*BleeStore" src --include='*.ts' --include='*.tsx' | wc -l | tr -d ' ')"
[ "$STORE_REGISTRATIONS" = "1" ] || fail "BleeStore must be registered exactly once, found $STORE_REGISTRATIONS registrations"
grep -q "registerPlugin<BleeStorePlugin>('BleeStore')" src/lib/bleeStore.ts || fail "canonical BleeStore proxy registration missing"
grep -q "from './bleeStore'" src/lib/payments.ts || fail "payments does not use canonical BleeStore proxy"
grep -q "from './bleeStore'" src/lib/atomicSigning.ts || fail "atomic signing does not use canonical BleeStore proxy"
grep -q "from './bleeStore'" src/lib/walletRecovery.ts || fail "wallet recovery does not use canonical BleeStore proxy"
grep -q "from './bleeStore'" src/lib/persistence.ts || fail "persistence does not use canonical BleeStore proxy"

MESH_REGISTRATIONS="$(grep -R "registerPlugin.*BleeMesh" src --include='*.ts' --include='*.tsx' | wc -l | tr -d ' ')"
[ "$MESH_REGISTRATIONS" = "1" ] || fail "BleeMesh must be registered exactly once, found $MESH_REGISTRATIONS registrations"
CONTACT_REGISTRATIONS="$(grep -R "registerPlugin.*BleeContacts" src --include='*.ts' --include='*.tsx' | wc -l | tr -d ' ')"
[ "$CONTACT_REGISTRATIONS" = "1" ] || fail "BleeContacts must be registered exactly once, found $CONTACT_REGISTRATIONS registrations"

grep -q 'BleeMeshPlugin.class' android/app/src/main/java/com/blee/payments/MainActivity.java || fail "MainActivity does not register BleeMeshPlugin"
grep -q 'BleeContactsPlugin.class' android/app/src/main/java/com/blee/payments/MainActivity.java || fail "MainActivity does not register BleeContactsPlugin"
grep -q 'BleeQrScannerPlugin.class' android/app/src/main/java/com/blee/payments/MainActivity.java || fail "MainActivity does not register BleeQrScannerPlugin"
grep -q 'BleeMeshService' android/app/src/main/AndroidManifest.xml || fail "BleeMeshService missing from manifest"

grep -q "direction === 'out' ? 'outgoing'" src/lib/persistence.ts || fail "payment storage boundary does not map canonical outgoing direction"
grep -q "direction === 'in' ? 'incoming'" src/lib/persistence.ts || fail "payment storage boundary does not map canonical incoming direction"
grep -q "direction === 'outgoing'" src/lib/persistence.ts || fail "payment load boundary does not normalize native outgoing direction"
grep -q "direction === 'incoming'" src/lib/persistence.ts || fail "payment load boundary does not normalize native incoming direction"
grep -q "useBleeView" src/components/BleeApp.tsx || fail "Blee UI is not using the durable ledger projection"
grep -q "blee:ledger-changed" src/hooks/useBleeView.ts || fail "durable ledger projection is not listening for native updates"
grep -q "USDC pending" src/components/BleeApp.tsx || fail "Home does not expose pending incoming funds"

if [ -e src/lib/nativeNotifications.ts ] || [ -e android/app/src/main/java/com/blee/payments/BleeNotificationsPlugin.java ]; then
  fail "redundant JavaScript notification bridge is still present"
fi
if grep -q 'notifyPaymentReceived' src/hooks/useBleeView.ts; then
  fail "UI projection must not own native payment notifications"
fi
grep -q 'BleePaymentNotifier.received' android/app/src/main/java/com/blee/payments/BleeMeshPlugin.java || fail "verified receive path does not notify natively"
grep -q 'PAYMENT_ENVELOPE_RECEIVED' android/app/src/main/java/com/blee/payments/BleePaymentEventReceiver.java || fail "transport detection notification path missing"
grep -q 'post(context, paymentId, "receiver", "Payment received", body, false)' android/app/src/main/java/com/blee/payments/BleePaymentNotifier.java || fail "verified receive must update the existing receiver notification without re-alerting"

# BLEE_NOTIFICATION_SINGLE_OWNER_V1
grep -q '"counterpartyAlias", "recipientName"' plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java || fail "sender notification does not prefer Blee counterparty alias"
if grep -Fq 'BleePaymentNotifier.detected(this' android/app/src/main/java/com/blee/payments/BleeMeshService.java; then
  fail "mesh service must not directly own receiver detection notifications"
fi
if grep -Fq 'BleePaymentNotifier.delivered(this' android/app/src/main/java/com/blee/payments/BleeMeshService.java; then
  fail "delivery ACK must not create a sender lifecycle notification"
fi
if grep -Fq 'paymentNotification(result.notificationTitle' android/app/src/main/java/com/blee/payments/BleeMeshService.java; then
  fail "mesh lifecycle ProcessResult still emits user notifications"
fi
if grep -Fq 'paymentNotification("Payment confirmed"' android/app/src/main/java/com/blee/payments/BleeMeshService.java; then
  fail "chain confirmation must stay in Activity instead of creating another notification"
fi
SERVICE_PAYMENT_NOTIFICATION_CALLS="$(grep -c 'paymentNotification(' android/app/src/main/java/com/blee/payments/BleeMeshService.java)"
[ "$SERVICE_PAYMENT_NOTIFICATION_CALLS" = "1" ] || fail "legacy mesh payment notification path still has call sites"
printf 'VERIFIED: Android payment notifications are side-scoped, alias-aware and single-stream\n'

grep -q "RecipientField" src/components/BleeApp.tsx || fail "Send screen is not using the canonical recipient control"
if grep -q 'blee-recipient-qr-icon' src/components/BleeApp.tsx; then
  fail "legacy absolute QR control is still rendered by BleeApp"
fi
grep -q "Choose saved contact" src/components/RecipientField.tsx || fail "recipient control is missing contacts action"
grep -q "Scan recipient QR code" src/components/RecipientField.tsx || fail "recipient control is missing QR action"
grep -q "grid-template-columns: minmax(0, 1fr) auto" src/components/RecipientField.module.css || fail "recipient controls are not laid out in a non-overlapping grid"
grep -q "registerPlugin<ContactsPlugin>('BleeContacts')" src/hooks/useContacts.ts || fail "contacts UI is not using dedicated contacts bridge"
grep -q "listContacts" android/app/src/main/java/com/blee/payments/BleeContactsPlugin.java || fail "native contacts list API missing"
grep -q "saveContact" android/app/src/main/java/com/blee/payments/BleeContactsPlugin.java || fail "native contacts save API missing"
grep -q "deleteContact" android/app/src/main/java/com/blee/payments/BleeContactsPlugin.java || fail "native contacts delete API missing"
if grep -Eq 'listContacts|saveContact|deleteContact|contactCandidates' android/app/src/main/java/com/blee/payments/BleeMeshPlugin.java; then
  fail "contacts API leaked back into transport plugin"
fi

grep -q 'PROFILE_UUID' android/app/src/main/java/com/blee/payments/BleeMeshService.java || fail "connection-bound BLE profile characteristic missing"
grep -q 'BleePeerProfile.decodeBound' android/app/src/main/java/com/blee/payments/BleeMeshService.java || fail "BLE profile is not bound to authenticated wallet session"
grep -q 'verification_pending' android/app/src/main/java/com/blee/payments/BleeMeshDb.java || fail "recipient verification-pending lifecycle missing"
grep -q 'rejectPendingEnvelope' android/app/src/main/java/com/blee/payments/BleeMeshDb.java || fail "invalid envelope rejection missing"
grep -q 'rejectEnvelope' android/app/src/main/java/com/blee/payments/BleeMeshPlugin.java || fail "native verifier rejection bridge missing"
grep -q 'rejectEnvelope' src/components/BleeRuntime.tsx || fail "WebView verifier rejection missing"
grep -q "state === 'verification-pending'" src/hooks/useBleeView.ts || fail "unverified funds are not excluded from projected value"
grep -q 'projectedBalance' src/components/BleeApp.tsx || fail "verified offline receive is not projected into displayed balance"
grep -q 'senderName: aliasRef.current' src/hooks/useBlee.ts || fail "durable payment envelope is missing sender display identity"

# BLEE_SOLANA_SECRET_BOUNDARY_V2
# The APK may contain only a Helius Secure RPC URL generated specifically for
# frontend/mobile use. Ordinary Helius API keys, query-key endpoints, Sender,
# and generic public Solana RPC fallbacks remain forbidden.
grep -q 'BLEE_HELIUS_SECURE_RPC_V1' src/lib/solanaGateway.ts || fail "Helius Secure RPC client boundary missing"
grep -q 'NEXT_PUBLIC_BLEE_HELIUS_SECURE_RPC' src/lib/solanaGateway.ts || fail "Helius Secure RPC build-time configuration missing"
grep -q -- "-fast-mainnet.helius-rpc.com" src/lib/solanaGateway.ts || fail "Helius Secure Mainnet hostname restriction missing"
grep -q "url.protocol !== 'https:'" src/lib/solanaGateway.ts || fail "Helius Secure RPC HTTPS restriction missing"
grep -q 'url.search' src/lib/solanaGateway.ts || fail "Helius Secure RPC query-string rejection missing"
grep -q "rpcCall<string>('sendTransaction'" src/lib/solanaGateway.ts || fail "direct standard Solana transaction submission missing"
grep -q "id: 'solana-sol'" src/lib/rails.ts || fail "Solana payment rail registry missing"
grep -q "settlementModel: 'solana-durable-nonce'" src/lib/rails.ts || fail "Solana durable-nonce settlement model missing"

# BLEE_SOLANA_VAULT_V1
# Solana identity is stored in an independent encrypted vault. The working
# Arc/EVM vault must remain unchanged and Solana private key material must not be
# persisted in plaintext or exposed through a reusable client secret.
grep -q "SOLANA_VAULT_KEY = 'wallet.solana.v1'" src/lib/solanaVault.ts || fail "Solana vault storage key missing"
grep -q "algorithm: 'Ed25519'" src/lib/solanaVault.ts || fail "Solana vault is not Ed25519"
grep -q "SOLANA_KDF_ITERATIONS = 600_000" src/lib/solanaVault.ts || fail "Solana vault PBKDF2 work factor changed unexpectedly"
grep -q "name: 'PBKDF2'" src/lib/solanaVault.ts || fail "Solana vault PBKDF2 derivation missing"
grep -q "name: 'AES-GCM'" src/lib/solanaVault.ts || fail "Solana vault AES-GCM encryption missing"
grep -q "name: 'Ed25519'" src/lib/solanaVault.ts || fail "Solana vault Ed25519 key generation/import missing"
grep -q "from './bleeStore'" src/lib/solanaVault.ts || fail "Solana vault must use canonical BleeStore persistence"
if grep -Eq 'localStorage|sessionStorage' src/lib/solanaVault.ts; then
  fail "Solana key material must not use browser storage"
fi

# BLEE_MULTI_WALLET_BACKUP_V2
# Backup v2 exports only encrypted vault objects. Restore is journaled before
# either wallet is replaced, so an interrupted dual-wallet restore rolls forward
# before Arc or Solana identity can be read again.
grep -q "formatVersion: 2" src/lib/walletRecovery.ts || fail "Backup v2 export missing"
grep -q "wallets:" src/lib/walletRecovery.ts || fail "Backup v2 wallet bundle missing"
grep -q "BLEE_BACKUP_V1_COMPAT_V1" src/lib/walletRecovery.ts || fail "Backup v1 compatibility guard missing"
grep -q "WALLET_RESTORE_JOURNAL_KEY = 'wallet.restore.v2.pending'" src/lib/walletRestore.ts || fail "crash-safe wallet restore journal missing"
grep -q "commitWalletRestoreCrashSafe" src/lib/walletRecovery.ts || fail "Backup v2 import does not use crash-safe restore"
grep -q "recoverPendingWalletRestore" src/lib/vault.ts || fail "Arc vault does not recover interrupted dual-wallet restore"
grep -q "recoverPendingWalletRestore" src/lib/solanaVault.ts || fail "Solana vault does not recover interrupted dual-wallet restore"
grep -q "getEncryptedSolanaVaultSnapshot" src/lib/walletRecovery.ts || fail "Backup v2 does not include encrypted Solana vault snapshot"
if grep -Eq 'revealPrivateKey\(|unlockSolanaVault\(' src/lib/walletRestore.ts; then
  fail "wallet restore journal must never decrypt private keys"
fi

# BLEE_NETWORK_IDENTITY_V1
# Network identity is data attached to every durable payment. Legacy 2.7.1 rows
# without metadata are permanently interpreted as Arc Testnet, while newly
# created rows inherit only the release-approved active Arc profile.
grep -q "id: 'arc-mainnet'" src/lib/networkConfig.ts || fail "Arc Mainnet approved profile slot missing"
grep -q "operational: false" src/lib/networkConfig.ts || fail "Arc Mainnet must remain disabled until official parameters are populated"
grep -q "ACTIVE_ARC_NETWORK_ID: ArcNetworkId = 'arc-testnet'" src/lib/networkConfig.ts || fail "unexpected Arc release selector"
grep -q "networkId?: BleeNetworkId" src/types/domain.ts || fail "payment network identity missing from domain"
grep -q "railId?: BleeRailId" src/types/domain.ts || fail "payment rail identity missing from domain"
grep -q "BLEE_LEGACY_NETWORK_IDENTITY_V1" src/lib/persistence.ts || fail "legacy Arc Testnet history guard missing"
grep -q "normalizePayments(rows, 'legacy-testnet')" src/lib/persistence.ts || fail "legacy payment load must pin missing network metadata to Arc Testnet"
grep -q "normalizePayments(rows, 'active-release')" src/lib/persistence.ts || fail "new payments do not inherit release-selected network identity"
grep -q "export const ARC_CHAIN_ID = BLEE_ACTIVE_NETWORK.chainId" src/lib/arc.ts || fail "Arc chain ID remains hardcoded outside approved network config"
grep -q "supportedNetworkIds" src/lib/rails.ts || fail "Arc rail does not declare Testnet/Mainnet capability"

APK_BOUND_DIRS=(src android plugins public app)
for dir in "${APK_BOUND_DIRS[@]}"; do
  [ -e "$dir" ] || continue
  if grep -RIEq --exclude='*.map' '[?&]api-key=|x-api-key|HELIUS_API_KEY|VITE_HELIUS|EXPO_PUBLIC_HELIUS' "$dir"; then
    fail "provider API credential material found in APK-bound source: $dir"
  fi
  if grep -RIEq --exclude='*.map' 'https://api[.](mainnet-beta|devnet|testnet)[.]solana[.]com' "$dir"; then
    fail "generic public Solana RPC endpoint found in APK-bound source: $dir"
  fi
  if grep -RIEq --exclude='*.map' 'https://mainnet[.]helius-rpc[.]com|https://beta[.]helius-rpc[.]com|https://devnet[.]helius-rpc[.]com' "$dir"; then
    fail "ordinary Helius API-key RPC endpoint found in APK-bound source: $dir"
  fi
done

if grep -RIEq --exclude='*.map' 'sender[.]helius-rpc[.]com' src; then
  fail "Helius Sender is forbidden for Blee V1 because it requires a third tip instruction"
fi

printf 'VERIFIED: Blee 2.7.1 source-first repository contract\n'
printf 'VERIFIED: offline receive projection, notifications and contacts contract\n'
printf 'VERIFIED: single plugin ownership and generated-output hygiene\n'
printf 'VERIFIED: Solana client uses keyless Helius Secure RPC with no API-key surface\n'
printf 'VERIFIED: Solana identity vault is isolated, encrypted and BleeStore-backed\n'
printf 'VERIFIED: Backup v2 is encrypted, crash-safe and legacy-v1 compatible\n'
printf 'VERIFIED: network identity is durable and Arc Mainnet remains release-gated\n'
