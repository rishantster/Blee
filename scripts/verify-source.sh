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
  src/hooks/useBlee.ts
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
)

for path in "${required[@]}"; do
  [ -f "$path" ] || fail "missing source file: $path"
done

PACKAGE_VERSION="$(node -p "require('./package.json').version")"
[ "$PACKAGE_VERSION" = "2.7.0" ] || fail "package version is $PACKAGE_VERSION, expected 2.7.0"

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
grep -q 'BleeMeshService' android/app/src/main/AndroidManifest.xml || fail "BleeMeshService missing from manifest"
grep -q 'blee-recipient-qr-icon' src/components/BleeApp.tsx || fail "Send recipient QR control missing from tracked UI source"

printf 'VERIFIED: Blee 2.7 source-first repository contract\n'
