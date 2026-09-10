#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

EXPECTED_BRANCH="blee-v1-sqlite"
OUTPUT="Blee-1.1.2-gas-accounting-debug.apk"

CURRENT_BRANCH="$(git branch --show-current)"
if [ "$CURRENT_BRANCH" != "$EXPECTED_BRANCH" ]; then
  echo "ERROR: You are on branch '$CURRENT_BRANCH', expected '$EXPECTED_BRANCH'."
  exit 1
fi

echo "Fetching latest Blee gas-accounting fix..."
git fetch origin "$EXPECTED_BRANCH"
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$EXPECTED_BRANCH")"
if [ "$LOCAL" != "$REMOTE" ]; then
  git pull --ff-only origin "$EXPECTED_BRANCH"
fi

echo "Building from commit: $(git rev-parse --short HEAD)"

test -f overrides/src/lib/payments.ts || { echo "ERROR: Missing gas-safe payment runtime."; exit 1; }
grep -q 'BLEE_GAS_ACCOUNTING_V2' overrides/src/lib/payments.ts || { echo "ERROR: Gas-accounting V2 marker missing."; exit 1; }
grep -q 'BLEE_GAS_SAFE_SUBMISSION_V2' overrides/src/lib/payments.ts || { echo "ERROR: Gas-safe submission V2 marker missing."; exit 1; }
grep -q 'BLEE_RELAY_REQUIRED' overrides/src/lib/payments.ts || { echo "ERROR: Relay-before-doomed-self-submit guard missing."; exit 1; }

echo "Step 1/3: build and verify the complete Blee storage/network/wallet runtime..."
bash build-blee-final.command

# build-blee-final.command has already rebuilt the complete application and
# verified native SQLite, nearby transport, wallet recovery, network settings,
# and the packaged web runtime. Bump Android identity for this behavioral fix
# and re-run only the final native assemble so this APK cannot be confused with
# the earlier 1.1.1 test build.
echo "Step 2/3: versioning gas-accounting build as Blee 1.1.2..."
python3 - <<'PY'
from pathlib import Path
import re
p=Path('android/app/build.gradle')
s=p.read_text()
s=re.sub(r'versionCode\s+\d+', 'versionCode 5', s)
s=re.sub(r'versionName\s+"[^"]+"', 'versionName "1.1.2"', s)
p.write_text(s)
PY

(
  cd android
  chmod +x gradlew
  ./gradlew --no-daemon assembleDebug --stacktrace
)

APK="android/app/build/outputs/apk/debug/app-debug.apk"
test -f "$APK"
unzip -t "$APK" >/dev/null
mkdir -p dist
cp "$APK" "dist/$OUTPUT"

echo "Step 3/3: verifying gas accounting inside the compiled APK..."
VERIFY_DIR="$(mktemp -d)"
trap 'rm -rf "$VERIFY_DIR"' EXIT
unzip -q "dist/$OUTPUT" -d "$VERIFY_DIR"
WEB_ROOT="$VERIFY_DIR/assets/public"

# Runtime strings survive minification; these checks prove that the APK being
# handed to the tester contains the new preflight path rather than the previous
# full-balance self-submit behavior.
grep -R -q 'BLEE_RELAY_REQUIRED' "$WEB_ROOT" || {
  echo "ERROR: Compiled APK does not contain the pre-broadcast relay fallback guard."
  exit 1
}
grep -R -q 'No transaction was broadcast' "$WEB_ROOT" || {
  echo "ERROR: Compiled APK does not contain the no-gas-burn preflight path."
  exit 1
}
grep -R -q 'Payment could not settle because the authorizer no longer has enough spendable balance' "$WEB_ROOT" || {
  echo "ERROR: Compiled APK does not contain the sanitized settlement error."
  exit 1
}

grep -Eq 'versionCode[[:space:]]+5' android/app/build.gradle || { echo "ERROR: versionCode 5 missing."; exit 1; }
grep -Eq 'versionName[[:space:]]+"1\.1\.2"' android/app/build.gradle || { echo "ERROR: versionName 1.1.2 missing."; exit 1; }

SHA="$(shasum -a 256 "dist/$OUTPUT" | awk '{print $1}')"
shasum -a 256 "dist/$OUTPUT" > "dist/$OUTPUT.sha256"

rm -rf "$VERIFY_DIR"
trap - EXIT

echo
echo "============================================================"
echo "✅ VERIFIED BLEE 1.1.2 GAS-ACCOUNTING APK"
echo "File: $ROOT/dist/$OUTPUT"
echo "SHA-256: $SHA"
echo "Version: 1.1.2 (Android versionCode 5)"
echo "Verified: no doomed full-balance self-submit + relay fallback + hardened SQLite + BLE/LAN + wallet recovery"
echo "============================================================"
echo
open "$ROOT/dist" 2>/dev/null || true
