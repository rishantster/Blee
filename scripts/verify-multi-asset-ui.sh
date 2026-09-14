#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

APP="src/components/BleeApp.tsx"
[ -f "$APP" ] || fail "Blee wallet UI missing"

# BLEE_SPRINT_6_MULTI_ASSET_UI_V4
# The approved wallet UI can visually unify the wallet while USDC/Arc and
# SOL/Solana remain independently sourced, addressed and routed.
grep -q 'data-blee-multi-asset-ui="v1"' "$APP" || fail "multi-asset home marker missing"
grep -q 'data-blee-home-ui="approved-v4"' "$APP" || fail "approved Home presentation missing"
grep -q 'home-assets-card' "$APP" || fail "multi-asset Assets surface missing"
grep -q 'TokenLogo asset="usdc"' "$APP" || fail "official USDC asset presentation missing"
grep -q 'TokenLogo asset="sol"' "$APP" || fail "official SOL asset presentation missing"
grep -q "'/brand/usdc-token.svg'" "$APP" || fail "USDC official asset path missing"
grep -q "'/brand/solana-logomark.svg'" "$APP" || fail "Solana official asset path missing"
grep -q 'Solana Mainnet' "$APP" || fail "Solana Mainnet label missing"
grep -q 'app.solana.balance' "$APP" || fail "SOL balance is not sourced from isolated Solana projection"
grep -q 'app.solana.offlineReady' "$APP" || fail "SOL offline readiness is not presented"
grep -q "type ReceiveAsset = 'usdc' | 'sol'" "$APP" || fail "Receive rail selector type missing"
grep -q "setReceiveAsset('sol')" "$APP" || fail "Receive cannot select SOL"
grep -q "receiveAsset === 'sol' ? app.solana.address" "$APP" || fail "SOL Receive does not use isolated Solana address"

# Enabling SOL Send must not replace or bypass the existing Arc/USDC engine.
grep -q "type SendAsset = 'usdc' | 'sol'" "$APP" || fail "Send rail selector contract missing"
grep -q "setPayAsset('usdc')" "$APP" || fail "Send cannot explicitly select USDC"
grep -q "const result = await app.sendPayment(payAddress, payAmount" "$APP" || fail "existing USDC send path changed unexpectedly"
grep -q "setPayResult({ asset: 'usdc', ...result })" "$APP" || fail "USDC send result is not explicitly rail-bound"
grep -q 'createAndDeliverOfflineSolPayment' "$APP" || fail "SOL send does not use guarded coordinator"

if grep -Eq 'sendSignedSolanaTransaction|createSolanaRpc|https://api[.](mainnet-beta|devnet|testnet)[.]solana[.]com|helius-rpc[.]com' "$APP"; then
  fail "multi-asset UI bypasses guarded Solana coordinator/gateway boundary"
fi
if grep -Eq 'projectedBalance.*solana|solana.*projectedBalance' "$APP"; then
  fail "USDC and SOL balances must never be combined"
fi

printf 'VERIFIED: multi-asset UI keeps SOL separate while preserving the explicit Arc/USDC send path\n'
