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

# Remove stale build outputs so Finder cannot show an older APK as the result.
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

# Confirm the generated Android project was version-bumped before packaging.
grep -Eq 'versionCode[[:space:]]+3' android/app/build.gradle || {
  echo "ERROR: Android versionCode 3 was not applied."
  exit 1
}
grep -Eq 'versionName[[:space:]]+"1\.1\.0"' android/app/build.gradle || {
  echo "ERROR: Android versionName 1.1.0 was not applied."
  exit 1
}

# Confirm the 1.1 source features were actually overlaid into the compiled source tree.
grep -q 'BleeAdvancedSettings' src/components/BleeApp.tsx || { echo "ERROR: Settings UI was not wired into BleeApp."; exit 1; }
grep -q 'getActiveNetwork' src/lib/arc.ts || { echo "ERROR: Runtime network configuration was not wired into settlement."; exit 1; }

echo
echo "============================================================"
echo "✅ VERIFIED NEW BLEE 1.1 APK"
echo "File: $APK"
echo "SHA-256: $SHA"
echo "Version: 1.1.0 (Android versionCode 3)"
echo "This SHA differs from the previous uploaded APK."
echo "============================================================"
echo
open "$ROOT/dist" 2>/dev/null || true
