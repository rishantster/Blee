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
  "scripts/apply-blee-runtime-reliability.py"
  "scripts/apply-blee-ble-transport-v4.py"
  "scripts/apply-blee-ble-diagnostics.py"
  "scripts/apply-blee-bitchat-reliability.py"
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
pass "canonical build shell syntax"

python3 -m py_compile scripts/apply-blee-*.py scripts/verify-*.py
pass "Python patchers/verifiers compile"

grep -q 'CANONICAL_BLEE_BUILDER_V2' build-blee.command || fail "canonical builder marker missing"
grep -q 'python3 scripts/apply-blee-ble-diagnostics.py' build-blee.command || fail "BLE diagnostics stage missing"
grep -q 'python3 scripts/apply-blee-bitchat-reliability.py' build-blee.command || fail "Bitchat reliability stage missing"

python3 - <<'PY'
from pathlib import Path
s = Path('build-blee.command').read_text()
order = [
    'python3 scripts/apply-blee-runtime-reliability.py',
    'python3 scripts/apply-blee-ble-transport-v4.py',
    'python3 scripts/apply-blee-ble-diagnostics.py',
    'python3 scripts/apply-blee-bitchat-reliability.py',
    'npm run check',
    'npm run build',
    'npx cap sync android',
    'python3 scripts/verify-blee-mesh-v2.py',
    'python3 scripts/verify-canonical-build.py',
]
pos = []
for token in order:
    i = s.find(token)
    if i < 0:
        raise SystemExit(f'SANITY FAIL: serialized build stage missing: {token}')
    pos.append(i)
if pos != sorted(pos):
    raise SystemExit('SANITY FAIL: canonical build stages are out of order')
print('SANITY OK: BLE/runtime/build stages are serialized')
PY

grep -q 'BLEE_BITCHAT_STYLE_BLE_RELIABILITY_V1' mesh-v2/android/BleeBleReliability.javafrag \
  || fail "Bitchat BLE reliability fragment marker missing"
grep -q 'BLEE_BITCHAT_RELIABILITY_PATCHER_V1' scripts/apply-blee-bitchat-reliability.py \
  || fail "Bitchat reliability patcher marker missing"
pass "Bitchat-derived reliability layer pinned"

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
