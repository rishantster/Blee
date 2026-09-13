#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "SANITY FAIL: $*" >&2
  exit 1
}

pass() {
  echo "SANITY OK: $*"
}

required=(
  "build-blee.command"
  "scripts/verify-canonical-build.py"
  "scripts/verify-blee-mesh-v2.py"
  "scripts/apply-blee-runtime-reliability.py"
  "scripts/apply-blee-ble-transport-v4.py"
  "scripts/apply-blee-ble-diagnostics.py"
  "scripts/apply-blee-bitchat-reliability.py"
  "scripts/apply-blee-gatt-interop.py"
  "scripts/apply-blee-transport-core-v2.py"
  "scripts/apply-blee-adaptive-nearby-v3.py"
  "scripts/apply-blee-adaptive-nearby-v3-compilefix.py"
  "scripts/resume-android-build.sh"
  "mesh-v2/android/BleeBleReliability.javafrag"
  ".github/workflows/verify-build.yml"
)
for file in "${required[@]}"; do
  [ -f "$file" ] || fail "missing required file: $file"
done
pass "required canonical inputs exist"

[ "$(find . -maxdepth 1 -type f -name 'build-blee*.command' | wc -l | tr -d ' ')" = "1" ] \
  || fail "more than one root Blee build entrypoint exists"
[ -f build-blee.command ] || fail "canonical builder missing"
pass "single canonical build entrypoint"

bash -n build-blee.command
bash -n scripts/resume-android-build.sh
pass "canonical build shell syntax"

python3 -m py_compile scripts/apply-blee-*.py scripts/verify-*.py
pass "Python patchers/verifiers compile"

grep -q 'CANONICAL_BLEE_BUILDER_V2' build-blee.command || fail "canonical builder marker missing"
grep -q 'python3 scripts/apply-blee-ble-diagnostics.py' build-blee.command || fail "BLE diagnostics stage missing"
grep -q 'python3 scripts/apply-blee-bitchat-reliability.py' build-blee.command || fail "Bitchat reliability stage missing"
grep -q 'python3 scripts/apply-blee-gatt-interop.py' build-blee.command || fail "GATT interop stage missing"
grep -q 'python3 scripts/apply-blee-transport-core-v2.py' build-blee.command || fail "transport core v2 stage missing"
grep -q 'python3 scripts/apply-blee-adaptive-nearby-v3.py' build-blee.command || fail "adaptive Nearby v3 stage missing"
grep -q 'python3 scripts/apply-blee-adaptive-nearby-v3-compilefix.py' build-blee.command || fail "adaptive Nearby v3 compile-hardening stage missing"

python3 - <<'PY'
from pathlib import Path

s = Path('build-blee.command').read_text()
patch_order = [
    'python3 scripts/apply-blee-runtime-reliability.py',
    'python3 scripts/apply-blee-ble-transport-v4.py',
    'python3 scripts/apply-blee-ble-diagnostics.py',
    'python3 scripts/apply-blee-bitchat-reliability.py',
    'python3 scripts/apply-blee-gatt-interop.py',
    'python3 scripts/apply-blee-transport-core-v2.py',
    'python3 scripts/apply-blee-adaptive-nearby-v3.py',
    'python3 scripts/apply-blee-adaptive-nearby-v3-compilefix.py',
]
positions = []
for token in patch_order:
    i = s.find(token)
    if i < 0:
        raise SystemExit(f'SANITY FAIL: serialized build stage missing: {token}')
    positions.append(i)
if positions != sorted(positions):
    raise SystemExit('SANITY FAIL: native transport stages are out of order')

cursor = positions[-1]
for token in (
    'npm run check',
    'npm run build',
    'npx cap sync android',
    'python3 scripts/verify-blee-mesh-v2.py',
    'python3 scripts/verify-canonical-build.py',
):
    i = s.find(token, cursor + 1)
    if i < 0:
        raise SystemExit(f'SANITY FAIL: post-patch build stage missing or misplaced: {token}')
    cursor = i
print('SANITY OK: BLE/adaptive/runtime/build stages are serialized')
PY

grep -q 'BLEE_BITCHAT_STYLE_BLE_RELIABILITY_V1' mesh-v2/android/BleeBleReliability.javafrag \
  || fail "Bitchat BLE reliability fragment marker missing"
grep -q 'BLEE_RADIO_ARBITRATION_V2' mesh-v2/android/BleeBleReliability.javafrag \
  || fail "vendor-neutral BLE radio arbitration marker missing"
grep -q 'BLEE_BITCHAT_ANDROID_GATT_PARITY_V1' mesh-v2/android/BleeBleReliability.javafrag \
  || fail "Bitchat Android GATT lifecycle marker missing"
grep -q 'BLEE_SAFE_GATT_BOOTSTRAP_1M_V1' mesh-v2/android/BleeBleReliability.javafrag \
  || fail "safe 1M GATT bootstrap marker missing"
grep -q 'BLE_CONNECT_FRESHNESS_MS = 4_000L' mesh-v2/android/BleeBleReliability.javafrag \
  || fail "fresh-advertisement GATT admission missing"
grep -q 'BLE_GATT_CONNECT_TIMEOUT_MS = 30_000L' mesh-v2/android/BleeBleReliability.javafrag \
  || fail "base GATT establishment timeout marker missing"
grep -q 'scheduleGattConnectTimeout' mesh-v2/android/BleeBleReliability.javafrag \
  || fail "GATT establishment watchdog missing"
grep -q 'No connected GATT operation progress' mesh-v2/android/BleeBleReliability.javafrag \
  || fail "post-connect GATT watchdog separation missing"
grep -q 'localRoleTokenPayload' mesh-v2/android/BleeBleReliability.javafrag \
  || fail "deterministic BLE role token missing"
grep -q 'advertiser_slot_busy_scanner_first' mesh-v2/android/BleeBleReliability.javafrag \
  || fail "scanner-first advertiser recovery missing"
grep -q 'pauseScanForGatt' mesh-v2/android/BleeBleReliability.javafrag \
  || fail "GATT radio compatibility hook missing"
grep -q 'Scanning is intentionally continuous through connection establishment' mesh-v2/android/BleeBleReliability.javafrag \
  || fail "continuous-scan GATT establishment missing"

grep -q 'BLEE_GATT_INTEROP_V1' scripts/apply-blee-gatt-interop.py \
  || fail "GATT interop marker missing"
grep -q 'BLEE_TRANSPORT_CORE_V2' scripts/apply-blee-transport-core-v2.py \
  || fail "transport core v2 marker missing"
grep -q 'class BleTransportV2' scripts/apply-blee-transport-core-v2.py \
  || fail "transport core v2 runtime owner missing"
grep -q 'direct_scan_result' scripts/apply-blee-transport-core-v2.py \
  || fail "live ScanResult direct-connect path missing"
grep -q 'setServiceUuid(new ParcelUuid(SERVICE_UUID))' scripts/apply-blee-transport-core-v2.py \
  || fail "service-filtered scan path missing"
grep -q 'addServiceData(new ParcelUuid(SERVICE_UUID), localPeerId)' scripts/apply-blee-transport-core-v2.py \
  || fail "stable peer ID scan response missing"
grep -q 'PROPERTY_WRITE_NO_RESPONSE' scripts/apply-blee-transport-core-v2.py \
  || fail "Bitchat-style GATT characteristic capabilities missing"
grep -q 'recordPeerDelivery' scripts/apply-blee-transport-core-v2.py \
  || fail "durable peer-specific packet accounting missing"

# Adaptive v3 must be a genuine offline second transport, not another GATT retry.
grep -q 'BLEE_ADAPTIVE_NEARBY_V3' scripts/apply-blee-adaptive-nearby-v3.py \
  || fail "adaptive Nearby v3 marker missing"
grep -q 'play-services-nearby:19.5.0' scripts/apply-blee-adaptive-nearby-v3.py \
  || fail "Nearby Connections dependency not pinned"
grep -q 'Strategy.P2P_CLUSTER' scripts/apply-blee-adaptive-nearby-v3.py \
  || fail "Nearby cluster strategy missing"
grep -q 'status == 147' scripts/apply-blee-adaptive-nearby-v3.py \
  || fail "GATT 147 fallback trigger missing"
grep -q 'BLE_GRACE_MS = 15_000L' scripts/apply-blee-adaptive-nearby-v3.py \
  || fail "no-peer adaptive fallback timer missing"
grep -q 'DUAL_SCAN_ON_MS = 8_000L' scripts/apply-blee-adaptive-nearby-v3.py \
  || fail "Bitchat-style dual-role scan window missing"
grep -q 'startAdvertising(localPeerIdBytes()' scripts/apply-blee-adaptive-nearby-v3.py \
  || fail "Nearby stable peer advertising missing"
grep -q 'startDiscovery(NEARBY_SERVICE_ID' scripts/apply-blee-adaptive-nearby-v3.py \
  || fail "Nearby discovery missing"
grep -q 'Payload.fromBytes' scripts/apply-blee-adaptive-nearby-v3.py \
  || fail "Nearby byte payload transport missing"
grep -q 'db.receive(raw, deviceId, publicKey)' scripts/apply-blee-adaptive-nearby-v3.py \
  || fail "Nearby payload does not feed canonical mesh packet verifier"
grep -q 'NEARBY_WIFI_DEVICES' scripts/apply-blee-adaptive-nearby-v3.py \
  || fail "Nearby Wi-Fi runtime permission wiring missing"
grep -q 'nearbyError(Throwable error)' scripts/apply-blee-adaptive-nearby-v3-compilefix.py \
  || fail "adaptive Java compile hardening missing"
pass "Adaptive Nearby v3 fallback contract pinned"

# The generated-service verifier must understand live transport ownership.
grep -q 'if "BLEE_TRANSPORT_CORE_V2" in service:' scripts/verify-blee-mesh-v2.py \
  || fail "mesh verifier is not transport-core-v2 aware"
grep -q 'ADVERTISE_MODE_BALANCED' scripts/verify-blee-mesh-v2.py \
  || fail "mesh verifier does not validate transport-core advertising"
grep -q 'addServiceData(new ParcelUuid(SERVICE_UUID), localPeerId)' scripts/verify-blee-mesh-v2.py \
  || fail "mesh verifier does not validate stable peer-ID advertising"
grep -q 'direct_scan_result' scripts/verify-blee-mesh-v2.py \
  || fail "mesh verifier does not validate direct ScanResult GATT"
pass "Transport verifier contract pinned"

if grep -q 'connectGattWithPreferredPhy' mesh-v2/android/BleeBleReliability.javafrag; then
  fail "multi-PHY negotiation must not run during initial GATT connection"
fi
python3 - <<'PY'
from pathlib import Path
s = Path('mesh-v2/android/BleeBleReliability.javafrag').read_text()
start = s.index('private void beginGattConnection')
end = s.index('private void openGattConnection', start)
block = s[start:end]
if 'pauseScanForGatt();' in block or 'postDelayed(() -> openGattConnection' in block:
    raise SystemExit('SANITY FAIL: GATT establishment still stops/delays scanning before connectGatt')
start = s.index('private void openGattConnection')
end = s.index('private void scheduleGattConnectTimeout', start)
if 'touchGatt(gatt)' in s[start:end]:
    raise SystemExit('SANITY FAIL: post-connect operation watchdog still starts before STATE_CONNECTED')
print('SANITY OK: Bitchat Android base connection lifecycle is pinned')
PY
pass "Bitchat-derived base BLE radio arbitration pinned"
pass "Android GATT interop recovery pinned"
pass "Adaptive v3 final transport ownership pinned"

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
pass "generated build artifacts are not tracked"

if git ls-files | grep -E '(^|/)(\.DS_Store|.*\.log)$' >/dev/null; then
  fail "OS/log junk is tracked"
fi
pass "no tracked OS/log junk"

python3 scripts/verify-canonical-build.py
pass "canonical repository contract"

echo
echo "Blee repository sanity passed."
