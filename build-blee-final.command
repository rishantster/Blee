#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

EXPECTED_BRANCH="blee-v1-sqlite"
EXPECTED_APK="Blee-1.1.0-hackathon-debug.apk"
OLD_APK_SHA256="d5d4f8177535064568205bc757bc679109b185e9ec03c90de715b1143d427eea"

CURRENT_BRANCH="$(git branch --show-current)"
if [ "$CURRENT_BRANCH" != "$EXPECTED_BRANCH" ]; then
  echo "ERROR: You are on branch '$CURRENT_BRANCH', expected '$EXPECTED_BRANCH'."
  echo "Run: git checkout $EXPECTED_BRANCH"
  exit 1
fi

echo "Fetching latest Blee 1.1 source..."
git fetch origin "$EXPECTED_BRANCH"
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$EXPECTED_BRANCH")"
if [ "$LOCAL" != "$REMOTE" ]; then
  echo "Updating local branch to latest Blee 1.1..."
  git pull --ff-only origin "$EXPECTED_BRANCH"
fi

echo "Building from commit: $(git rev-parse --short HEAD)"

grep -q 'APP_NAME="Blee-1.1.0-hackathon-debug.apk"' build-blee-macos.command || {
  echo "ERROR: Local build script is not the Blee 1.1 builder."
  exit 1
}

test -f scripts/apply-blee-1.1.py || { echo "ERROR: Missing Blee 1.1 overlay script."; exit 1; }
test -f overrides/src/lib/networkConfig.ts || { echo "ERROR: Missing configurable network support."; exit 1; }
test -f overrides/src/lib/walletRecovery.ts || { echo "ERROR: Missing wallet recovery support."; exit 1; }
test -f overrides/src/components/BleeAdvancedSettings.tsx || { echo "ERROR: Missing Blee 1.1 Settings UI."; exit 1; }

echo "Removing stale APK/build outputs..."
rm -rf dist android .next out
mkdir -p dist

bash build-blee-macos.command

APK="$ROOT/dist/$EXPECTED_APK"
if [ ! -f "$APK" ]; then
  echo "ERROR: Expected Blee 1.1 APK was not produced: $APK"
  exit 1
fi

SHA="$(shasum -a 256 "$APK" | awk '{print $1}')"
if [ "$SHA" = "$OLD_APK_SHA256" ]; then
  echo "ERROR: Build produced the exact SHA-256 of the previous Blee APK. Refusing to present it as 1.1."
  exit 1
fi

grep -Eq 'versionCode[[:space:]]+3' android/app/build.gradle || {
  echo "ERROR: Android versionCode 3 was not applied."
  exit 1
}
grep -Eq 'versionName[[:space:]]+"1\.1\.0"' android/app/build.gradle || {
  echo "ERROR: Android versionName 1.1.0 was not applied."
  exit 1
}
grep -q '@drawable/blee_launcher' android/app/src/main/AndroidManifest.xml || {
  echo "ERROR: Blee launcher icon is not wired into AndroidManifest.xml."
  exit 1
}
grep -q 'BleeAdvancedSettings' src/components/BleeApp.tsx || { echo "ERROR: Settings UI was not wired into BleeApp."; exit 1; }
grep -q 'BLEE_NETWORK_STARTUP_PROFILE' src/lib/arc.ts || { echo "ERROR: Startup network profile was not wired into settlement."; exit 1; }
grep -q 'getActiveNetwork' src/lib/arc.ts || { echo "ERROR: Active network lookup is missing from settlement runtime."; exit 1; }

# Verify the actual packaged binary, not just the source tree.
echo "Verifying Blee 1.1 features inside compiled APK..."
VERIFY_DIR="$(mktemp -d)"
trap 'rm -rf "$VERIFY_DIR"' EXIT
unzip -q "$APK" -d "$VERIFY_DIR"
WEB_ROOT="$VERIFY_DIR/assets/public"

grep -R -q 'Wallet recovery' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing Wallet recovery UI."; exit 1; }
grep -R -q 'Add network' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing Add network UI."; exit 1; }
grep -R -q 'blee.networks.v1' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing persistent network profiles."; exit 1; }
grep -R -q 'blee.active-network.v1' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing active-network persistence."; exit 1; }
grep -R -q 'wallet.vault.v2' "$WEB_ROOT" || { echo "ERROR: Compiled APK wallet recovery is not using the existing encrypted Blee vault."; exit 1; }
grep -R -q 'Mainnet status' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing mainnet/testnet disclosure."; exit 1; }
grep -R -q 'Blee 1.1' "$WEB_ROOT" || { echo "ERROR: Compiled APK does not identify itself as Blee 1.1."; exit 1; }
grep -R -q 'Network transaction reverted' "$WEB_ROOT" || { echo "ERROR: Configurable settlement runtime was not compiled into the APK."; exit 1; }
grep -R -q 'Blee SQLite initialization failed' "$WEB_ROOT" || { echo "ERROR: SQLite startup hotfix was not compiled into the APK."; exit 1; }
if grep -R -q 'ARC DROP' "$WEB_ROOT"; then
  echo "ERROR: Old ARC DROP branding still exists in packaged web assets."
  exit 1
fi

DEX_STRINGS="$VERIFY_DIR/blee-dex-strings.txt"
find "$VERIFY_DIR" -maxdepth 1 -name 'classes*.dex' -print0 | xargs -0 strings > "$DEX_STRINGS"
grep -q 'BleeStorePlugin' "$DEX_STRINGS" || { echo "ERROR: Native BleeStorePlugin missing from APK."; exit 1; }
grep -q 'BleeNearbyPlugin' "$DEX_STRINGS" || { echo "ERROR: Native BleeNearbyPlugin missing from APK."; exit 1; }
grep -q 'SQLiteOpenHelper' "$DEX_STRINGS" || { echo "ERROR: SQLite implementation missing from APK."; exit 1; }

rm -rf "$VERIFY_DIR"
trap - EXIT

echo
echo "============================================================"
echo "✅ VERIFIED NEW BLEE 1.1 APK"
echo "File: $APK"
echo "SHA-256: $SHA"
echo "Version: 1.1.0 (Android versionCode 3)"
echo "Verified: SQLite startup + BLE/LAN + wallet recovery + active custom networks + Blee launcher"
echo "This SHA differs from the previous uploaded APK."
echo "============================================================"
echo
open "$ROOT/dist" 2>/dev/null || true
