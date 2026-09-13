#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() { echo "SANITY FAIL: $*" >&2; exit 1; }
pass() { echo "SANITY OK: $*"; }

required=(
  "build-blee.command"
  "ARCHITECTURE.md"
  "UI_ARCHITECTURE.md"
  "scripts/verify-canonical-build.py"
  "scripts/verify-production-final-v5.py"
  "scripts/verify-apk-integrity.sh"
  "scripts/apply-blee-adaptive-nearby-v3.py"
  "scripts/apply-blee-adaptive-nearby-v3-compilefix.py"
  "scripts/apply-blee-nearby-speed-profile-v2.py"
  "scripts/apply-blee-pull-refresh-v1.py"
  "scripts/apply-blee-qr-ux-v2.py"
  "scripts/apply-blee-notification-permission-v1.py"
  "scripts/apply-blee-contacts-backend-only-v2.py"
  "scripts/apply-blee-contacts-sync-v1.py"
  "scripts/apply-blee-contacts-react-v4.py"
  "scripts/apply-blee-contacts-react-v4-compilefix.py"
  "scripts/resume-android-build.sh"
  "mesh-v2/android/BleeBleReliability.javafrag"
)
for file in "${required[@]}"; do
  [ -f "$file" ] || fail "missing required file: $file"
done
pass "Blee 2.7 canonical inputs exist"

[ "$(find . -maxdepth 1 -type f -name 'build-blee*.command' | wc -l | tr -d ' ')" = "1" ] \
  || fail "more than one root Blee build entrypoint exists"
pass "single root build entrypoint"

bash -n build-blee.command
bash -n scripts/resume-android-build.sh
bash -n scripts/verify-apk-integrity.sh
python3 -m py_compile scripts/apply-blee-*.py scripts/verify-*.py
pass "shell + Python build tooling parses"

grep -q 'CANONICAL_BLEE_BUILDER_V3' build-blee.command || fail "Blee 2.7 builder marker missing"
grep -q 'APP_VERSION="2.7.0"' build-blee.command || fail "Blee 2.7 artifact version missing"
grep -q 'versionCode 17' build-blee.command || fail "Android versionCode 17 missing"
grep -q 'versionName "2.7.0"' build-blee.command || fail "Android versionName 2.7.0 missing"
grep -q 'rm -rf "$ROOT/android" "$ROOT/.next" "$ROOT/out"' build-blee.command || fail "clean generated-state reset missing"
grep -q 'python3 scripts/verify-production-final-v5.py' build-blee.command || fail "final source verifier missing"
grep -q 'bash scripts/verify-apk-integrity.sh "$FINAL_APK"' build-blee.command || fail "final APK binary verifier missing"
pass "canonical clean build + final gates pinned"

grep -q 'exec bash "$ROOT/build-blee.command"' scripts/resume-android-build.sh \
  || fail "legacy resume command does not delegate to canonical build"
pass "legacy resume path cannot diverge"

python3 - <<'PY'
from pathlib import Path
s = Path('build-blee.command').read_text()
order = [
    'python3 scripts/apply-blee-runtime-reliability.py',
    'python3 scripts/apply-blee-ble-transport-v4.py',
    'python3 scripts/apply-blee-ble-diagnostics.py',
    'python3 scripts/apply-blee-bitchat-reliability.py',
    'python3 scripts/apply-blee-gatt-interop.py',
    'python3 scripts/apply-blee-transport-core-v2.py',
    'python3 scripts/apply-blee-adaptive-nearby-v3.py',
    'python3 scripts/apply-blee-adaptive-nearby-v3-compilefix.py',
    'npm run check',
    'npm run build',
    'npx cap sync android',
    'python3 scripts/verify-production-final-v5.py',
    './gradlew --no-daemon assembleDebug --stacktrace',
    'bash scripts/verify-apk-integrity.sh "$FINAL_APK"',
]
positions=[]
cursor=-1
for token in order:
    pos=s.find(token, cursor+1)
    if pos < 0:
        raise SystemExit(f'SANITY FAIL: serialized stage missing/misplaced: {token}')
    positions.append(pos); cursor=pos
if positions != sorted(positions):
    raise SystemExit('SANITY FAIL: production build stages are out of order')
print('SANITY OK: canonical native/web/build/binary stages are serialized')
PY

grep -q 'BLEE_BITCHAT_STYLE_BLE_RELIABILITY_V1' mesh-v2/android/BleeBleReliability.javafrag || fail "Bitchat BLE reliability fragment missing"
grep -q 'BLEE_BITCHAT_ANDROID_GATT_PARITY_V1' mesh-v2/android/BleeBleReliability.javafrag || fail "Bitchat Android GATT parity missing"
grep -q 'BLE_GATT_CONNECT_TIMEOUT_MS = 30_000L' mesh-v2/android/BleeBleReliability.javafrag || fail "GATT establishment timeout missing"
grep -q 'Scanning is intentionally continuous through connection establishment' mesh-v2/android/BleeBleReliability.javafrag || fail "continuous-scan GATT establishment missing"
pass "physically proven BLE base contract pinned"

grep -q 'BLEE_ADAPTIVE_NEARBY_V3' scripts/apply-blee-adaptive-nearby-v3.py || fail "adaptive Nearby v3 missing"
grep -q 'Strategy.P2P_CLUSTER' scripts/apply-blee-adaptive-nearby-v3.py || fail "Nearby P2P cluster strategy missing"
grep -q 'BLE_GRACE_MS = 15_000L' scripts/apply-blee-adaptive-nearby-v3.py || fail "15s BLE grace baseline missing"
grep -q 'GATT_TIMEOUT_THRESHOLD = 2' scripts/apply-blee-adaptive-nearby-v3.py || fail "two-failure GATT baseline missing"
grep -q 'play-services-nearby:19.5.0' scripts/apply-blee-adaptive-nearby-v3.py || fail "Nearby dependency missing"
pass "Adaptive Nearby baseline pinned"

chain="scripts/apply-blee-adaptive-nearby-v3-compilefix.py"
for token in \
  'apply-blee-payment-notifications.py' \
  'apply-blee-nearby-stability-v1.py' \
  'apply-blee-qr-ux-v2.py' \
  'apply-blee-pull-refresh-v1.py' \
  'apply-blee-nearby-speed-profile-v2.py' \
  'apply-blee-activity-identity-v2.py' \
  'apply-blee-contacts-backend-only-v2.py' \
  'apply-blee-contacts-react-v4.py' \
  'apply-blee-notification-permission-v1.py' \
  'verify-production-final-v5.py'; do
  grep -q "$token" "$chain" || fail "final production chain missing $token"
done
pass "Blee 2.7 production feature chain pinned"

for forbidden in \
  'dist/*.apk' \
  'dist/*.apk.sha256' \
  'node_modules/*' \
  '.blee-tools/*' \
  'android/**/build/*' \
  'android/.gradle/*'; do
  if git ls-files "$forbidden" | grep -q .; then
    fail "generated artifact is tracked: $forbidden"
  fi
done
pass "generated artifacts are not tracked"

python3 scripts/verify-canonical-build.py
pass "canonical Blee 2.7 repository contract"

echo
echo "Blee 2.7 repository sanity passed."
