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
  src/lib/rails.ts
  src/lib/solanaGateway.ts
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
grep -q 'post(context, paymentId, "receiver", "Payment received", body, true)' android/app/src/main/java/com/blee/payments/BleePaymentNotifier.java || fail "verified incoming payment notifications must alert"

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

# BLEE_SOLANA_SECRET_BOUNDARY_V1
# Solana provider credentials must never enter APK-bound source. The client may
# know only the public Blee gateway; provider selection and credentials live on
# the server side.
grep -q "BLEE_SOLANA_GATEWAY = 'https://rpc.blee.app'" src/lib/solanaGateway.ts || fail "canonical Solana gateway URL missing"
grep -q "id: 'solana-sol'" src/lib/rails.ts || fail "Solana payment rail registry missing"
grep -q "settlementModel: 'solana-durable-nonce'" src/lib/rails.ts || fail "Solana durable-nonce settlement model missing"

APK_BOUND_DIRS=(src android plugins public app)
for dir in "${APK_BOUND_DIRS[@]}"; do
  [ -e "$dir" ] || continue
  if grep -RIEq --exclude='*.map' 'helius-rpc[.]com|HELIUS_API_KEY|NEXT_PUBLIC_HELIUS|VITE_HELIUS|EXPO_PUBLIC_HELIUS' "$dir"; then
    fail "provider credential material or Helius endpoint found in APK-bound source: $dir"
  fi
  if grep -RIEq --exclude='*.map' 'https://api[.](mainnet-beta|devnet|testnet)[.]solana[.]com' "$dir"; then
    fail "direct Solana RPC endpoint found in APK-bound source: $dir; use rpc.blee.app"
  fi
done

printf 'VERIFIED: Blee 2.7.1 source-first repository contract\n'
printf 'VERIFIED: offline receive projection, notifications and contacts contract\n'
printf 'VERIFIED: single plugin ownership and generated-output hygiene\n'
printf 'VERIFIED: Solana client is gateway-only with no provider credential surface\n'
