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
  src/lib/persistence.ts
  src/lib/nativeNotifications.ts
  src/lib/payments.ts
  src/lib/atomicSigning.ts
  plugins/blee-store/package.json
  plugins/blee-nearby/package.json
  android/gradlew
  android/app/build.gradle
  android/app/src/main/AndroidManifest.xml
  android/app/src/main/java/com/blee/payments/MainActivity.java
  android/app/src/main/java/com/blee/payments/BleeMeshService.java
  android/app/src/main/java/com/blee/payments/BleeMeshDb.java
  android/app/src/main/java/com/blee/payments/BleeMeshPlugin.java
  android/app/src/main/java/com/blee/payments/BleePaymentNotifier.java
  android/app/src/main/java/com/blee/payments/BleeNotificationsPlugin.java
)

for path in "${required[@]}"; do
  [ -f "$path" ] || fail "missing source file: $path"
done

PACKAGE_VERSION="$(node -p "require('./package.json').version")"
LOCK_VERSION="$(node -p "require('./package-lock.json').version")"
LOCK_ROOT_VERSION="$(node -p "require('./package-lock.json').packages[''].version")"

[ "$PACKAGE_VERSION" = "2.7.0" ] || fail "package version is $PACKAGE_VERSION, expected 2.7.0"
[ "$LOCK_VERSION" = "$PACKAGE_VERSION" ] || fail "package-lock version is $LOCK_VERSION, expected $PACKAGE_VERSION"
[ "$LOCK_ROOT_VERSION" = "$PACKAGE_VERSION" ] || fail "package-lock root package version is $LOCK_ROOT_VERSION, expected $PACKAGE_VERSION"

grep -Eq 'versionCode[[:space:]]+17' android/app/build.gradle || fail "Android versionCode must be 17"
grep -Eq 'versionName[[:space:]]+"2[.]7[.]0"' android/app/build.gradle || fail "Android versionName must be 2.7.0"
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

if grep -q 'configure-native[.]mjs' package.json; then
  fail "package.json still references removed configure-native.mjs"
fi
if grep -q 'cap add android' package.json; then
  fail "Android is tracked source; package.json must not recreate it with cap add"
fi

grep -q 'BleeMeshPlugin.class' android/app/src/main/java/com/blee/payments/MainActivity.java || fail "MainActivity does not register BleeMeshPlugin"
grep -q 'BleeQrScannerPlugin.class' android/app/src/main/java/com/blee/payments/MainActivity.java || fail "MainActivity does not register BleeQrScannerPlugin"
grep -q 'BleeNotificationsPlugin.class' android/app/src/main/java/com/blee/payments/MainActivity.java || fail "MainActivity does not register BleeNotificationsPlugin"
grep -q 'BleeMeshService' android/app/src/main/AndroidManifest.xml || fail "BleeMeshService missing from manifest"

grep -q "direction === 'out' ? 'outgoing'" src/lib/persistence.ts || fail "payment storage boundary does not map canonical outgoing direction"
grep -q "direction === 'in' ? 'incoming'" src/lib/persistence.ts || fail "payment storage boundary does not map canonical incoming direction"
grep -q "direction === 'outgoing'" src/lib/persistence.ts || fail "payment load boundary does not normalize native outgoing direction"
grep -q "direction === 'incoming'" src/lib/persistence.ts || fail "payment load boundary does not normalize native incoming direction"
grep -q "useBleeView" src/components/BleeApp.tsx || fail "Blee UI is not using the durable ledger projection"
grep -q "blee:ledger-changed" src/hooks/useBleeView.ts || fail "durable ledger projection is not listening for native updates"
grep -q "USDC pending" src/components/BleeApp.tsx || fail "Home does not expose pending incoming funds"

grep -q "RecipientField" src/components/BleeApp.tsx || fail "Send screen is not using the canonical recipient control"
if grep -q 'blee-recipient-qr-icon' src/components/BleeApp.tsx; then
  fail "legacy absolute QR control is still rendered by BleeApp"
fi
grep -q "Choose saved contact" src/components/RecipientField.tsx || fail "recipient control is missing contacts action"
grep -q "Scan recipient QR code" src/components/RecipientField.tsx || fail "recipient control is missing QR action"
grep -q "grid-template-columns: minmax(0, 1fr) auto" src/components/RecipientField.module.css || fail "recipient controls are not laid out in a non-overlapping grid"

grep -q "listContacts" android/app/src/main/java/com/blee/payments/BleeMeshPlugin.java || fail "native contacts list API missing"
grep -q "saveContact" android/app/src/main/java/com/blee/payments/BleeMeshPlugin.java || fail "native contacts save API missing"
grep -q "deleteContact" android/app/src/main/java/com/blee/payments/BleeMeshPlugin.java || fail "native contacts delete API missing"
grep -q "BleePaymentNotifier.received" android/app/src/main/java/com/blee/payments/BleeNotificationsPlugin.java || fail "native notification bridge does not use payment notifier"

grep -q 'post(context, paymentId, "receiver", "Payment received", body, true)' android/app/src/main/java/com/blee/payments/BleePaymentNotifier.java || fail "verified incoming payment notifications must alert"

printf 'VERIFIED: Blee 2.7 source-first repository contract\n'
printf 'VERIFIED: offline receive projection, notifications and contacts contract\n'
