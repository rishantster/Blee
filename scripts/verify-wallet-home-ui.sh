#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

BASE_CSS="app/wallet-home.css"
APPROVED_CSS="app/approved-wallet-ui.css"
LAYOUT="app/layout.tsx"
APP="src/components/BleeApp.tsx"
USDC="public/brand/usdc-token.svg"
SOL="public/brand/solana-logomark.svg"

[ -f "$BASE_CSS" ] || fail "wallet home base stylesheet missing"
[ -f "$APPROVED_CSS" ] || fail "approved wallet UI stylesheet missing"
[ -f "$USDC" ] || fail "USDC mark missing"
[ -f "$SOL" ] || fail "Solana mark missing"
grep -q 'data-blee-home-ui="approved-v4"' "$APP" || fail "approved wallet home marker missing"
grep -q 'home-balance-hero' "$APP" || fail "single balance hero missing"
grep -q 'home-assets-card' "$APP" || fail "assets section missing"
grep -q 'TokenLogo asset="usdc"' "$APP" || fail "USDC asset row missing official mark"
grep -q 'TokenLogo asset="sol"' "$APP" || fail "Solana asset row missing official mark"
grep -q 'home-nearby-card' "$APP" || fail "nearby home preview missing"
grep -q 'home-activity-card' "$APP" || fail "home activity preview missing"
grep -q "import './wallet-home.css';" "$LAYOUT" || fail "wallet home base stylesheet is not loaded"
grep -q "import './approved-wallet-ui.css';" "$LAYOUT" || fail "approved wallet stylesheet is not loaded last"
grep -q 'home-screen .home-balance-label' "$APPROVED_CSS" || fail "legacy hero label suppression missing"
grep -q 'home-screen .home-balance-meta' "$APPROVED_CSS" || fail "legacy hero network metadata suppression missing"
grep -q 'home-balance-value strong' "$APPROVED_CSS" || fail "centered premium balance treatment missing"

# With only two supported assets, the Assets heading intentionally has no View all action.
if grep -Eq 'aria-label="Assets"[^\n]*home-heading-action' "$APP"; then
  fail "Assets section must not expose a redundant View all action"
fi

# UI may display both assets but must not numerically combine independent rails.
grep -q 'projectedBalance' "$APP" || fail "USDC balance projection missing"
grep -q 'app.solana.balance' "$APP" || fail "SOL balance projection missing"
if grep -Eq 'projectedBalance.*solana|solana.*projectedBalance' "$APP"; then
  fail "home UI must not combine USDC and SOL operational balances"
fi

printf 'VERIFIED: approved wallet Home centers USDC, breathes correctly and uses official independent asset marks\n'
