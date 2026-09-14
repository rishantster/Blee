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

# BLEE_SPRINT_6_MULTI_ASSET_UI_V3
# Cross-rail presentation invariants after the approved wallet-home redesign.
# The Home screen may present a single active-rail hero plus an Assets list, but
# USDC and SOL must remain separately sourced and separately routed.
grep -q 'data-blee-multi-asset-ui="v1"' "$APP" || fail "multi-asset home marker missing"
grep -q 'home-assets-card' "$APP" || fail "multi-asset Assets surface missing"
grep -q 'asset-token-usdc' "$APP" || fail "USDC asset presentation missing"
grep -q 'asset-token-sol' "$APP" || fail "SOL asset presentation missing"
grep -q 'Solana Mainnet' "$APP" || fail "Solana Mainnet label missing"
grep -q 'app.solana.balance' "$APP" || fail "SOL balance is not sourced from isolated Solana projection"
grep -q 'app.solana.offlineReady' "$APP" || fail "SOL offline readiness is not presented"
grep -q "type ReceiveAsset = 'usdc' | 'sol'" "$APP" || fail "Receive rail selector type missing"
grep -q "setReceiveAsset('sol')" "$APP" || fail "Receive cannot select SOL"
grep -q "receiveAsset === 'sol' ? app.solana.address" "$APP" || fail "SOL Receive does not use the isolated Solana address"
grep -q 'SOL · Solana Mainnet' "$APP" || fail "SOL Receive network label missing"
grep -q 'data-blee-solana-network="mainnet"' "$APP" || fail "Solana network security card missing"

# Enabling SOL Send must not replace or bypass the existing Arc/USDC engine.
grep -q "type SendAsset = 'usdc' | 'sol'" "$APP" || fail "Send rail selector contract missing"
grep -q "setPayAsset('usdc')" "$APP" || fail "Send cannot explicitly select USDC"
grep -q "const result = await app.sendPayment(payAddress, payAmount" "$APP" || fail "existing USDC send path changed unexpectedly"
grep -q "setPayResult({ asset: 'usdc', ...result })" "$APP" || fail "USDC send result is not explicitly rail-bound"

# UI code may invoke the guarded SOL coordinator, but may never submit directly
# to a provider/RPC or combine SOL with the Arc balance projection.
if grep -Eq 'sendSignedSolanaTransaction|createSolanaRpc|https://api[.](mainnet-beta|devnet|testnet)[.]solana[.]com|helius-rpc[.]com' "$APP"; then
  fail "multi-asset UI bypasses the guarded Solana coordinator/gateway boundary"
fi
if grep -Eq 'projectedBalance.*solana|solana.*projectedBalance' "$APP"; then
  fail "USDC and SOL balances must never be combined"
fi

printf 'VERIFIED: multi-asset UI keeps SOL separate while preserving the explicit Arc/USDC send path\n'
