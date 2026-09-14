#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

CSS="app/wallet-home.css"
LAYOUT="app/layout.tsx"
APP="src/components/BleeApp.tsx"

[ -f "$CSS" ] || fail "wallet home stylesheet missing"
grep -q 'BLEE_WALLET_HOME_REFERENCE_V3' "$CSS" || fail "approved wallet home style marker missing"
grep -q 'data-blee-home-ui="wallet-reference-v3"' "$APP" || fail "approved wallet home marker missing"
grep -q 'home-balance-hero' "$APP" || fail "single balance hero missing"
grep -q 'USDC BALANCE' "$APP" || fail "USDC hero label missing"
grep -q 'home-network-chip' "$APP" || fail "network badge missing"
grep -q 'home-assets-card' "$APP" || fail "assets section missing"
grep -q 'asset-token-usdc' "$APP" || fail "USDC asset row missing"
grep -q 'asset-token-sol' "$APP" || fail "Solana asset row missing"
grep -q 'home-nearby-card' "$APP" || fail "nearby home preview missing"
grep -q 'home-activity-card' "$APP" || fail "home activity preview missing"
grep -q "import './wallet-home.css';" "$LAYOUT" || fail "wallet home stylesheet is not loaded"

# UI may display both assets but must not numerically combine independent rails.
grep -q 'projectedBalance' "$APP" || fail "USDC balance projection missing"
grep -q 'app.solana.balance' "$APP" || fail "SOL balance projection missing"
if grep -Eq 'projectedBalance.*solana|solana.*projectedBalance' "$APP"; then
  fail "home UI must not combine USDC and SOL operational balances"
fi

printf 'VERIFIED: approved wallet home uses one premium balance hero with separate USDC and SOL asset rows\n'
