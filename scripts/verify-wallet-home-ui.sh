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
USDC="public/brand/usdc-token.svg"
SOL="public/brand/solana-logomark.svg"

[ -f "$CSS" ] || fail "wallet home stylesheet missing"
[ -f "$USDC" ] || fail "USDC mark missing"
[ -f "$SOL" ] || fail "Solana mark missing"
grep -q 'BLEE_WALLET_HOME_COMPACT_V5' "$CSS" || fail "compact wallet home marker missing"
grep -q 'data-blee-home-ui="wallet-reference-v3"' "$APP" || fail "approved wallet home marker missing"
grep -q 'home-balance-hero' "$APP" || fail "single balance hero missing"
grep -q 'home-assets-card' "$APP" || fail "assets section missing"
grep -q 'asset-token-usdc' "$APP" || fail "USDC asset row missing"
grep -q 'asset-token-sol' "$APP" || fail "Solana asset row missing"
grep -q 'home-nearby-card' "$APP" || fail "nearby home preview missing"
grep -q 'home-activity-card' "$APP" || fail "home activity preview missing"
grep -q "import './wallet-home.css';" "$LAYOUT" || fail "wallet home stylesheet is not loaded"
grep -q '^\.home-balance-label,$' "$CSS" || fail "hero balance label suppression missing"
grep -q '^\.home-balance-meta { display: none !important; }$' "$CSS" || fail "hero network/test-fund metadata suppression missing"
grep -q 'home-modern-section\[aria-label="Assets"\] .home-heading-action' "$CSS" || fail "Assets View all suppression missing"
grep -q "background-image: url('/brand/usdc-token.svg')" "$CSS" || fail "official USDC mark not used"
grep -q "background-image: url('/brand/solana-logomark.svg')" "$CSS" || fail "official Solana mark not used"

# UI may display both assets but must not numerically combine independent rails.
grep -q 'projectedBalance' "$APP" || fail "USDC balance projection missing"
grep -q 'app.solana.balance' "$APP" || fail "SOL balance projection missing"
if grep -Eq 'projectedBalance.*solana|solana.*projectedBalance' "$APP"; then
  fail "home UI must not combine USDC and SOL operational balances"
fi

printf 'VERIFIED: compact wallet home centers the balance and uses official independent asset marks\n'
