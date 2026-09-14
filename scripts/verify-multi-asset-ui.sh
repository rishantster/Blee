#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

APP="src/components/BleeApp.tsx"
VIEW="src/hooks/useBleeView.ts"
MARKET="src/lib/marketData.ts"
[ -f "$APP" ] || fail "Blee wallet UI missing"
[ -f "$VIEW" ] || fail "Blee presentation projection missing"
[ -f "$MARKET" ] || fail "SOL market valuation source missing"

# BLEE_SPRINT_6_MULTI_ASSET_UI_V7
# USDC and SOL remain independent operational/spendable balances. Home may show
# their aggregate USDC-equivalent market value as a presentation-only portfolio.
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
grep -q 'BLEE_MULTI_ASSET_PRESENTATION_BOUNDARY_V2' "$VIEW" || fail "portfolio valuation boundary missing"
grep -q 'BLEE_PORTFOLIO_VALUATION_V1' "$VIEW" || fail "portfolio valuation projection missing"
grep -q 'totalUsdcEquivalent' "$VIEW" || fail "combined USDC-equivalent portfolio value missing"
grep -Fq 'usdcQuantity + (solUsdValue ?? 0)' "$VIEW" || fail "portfolio total does not preserve known USDC value when SOL pricing is unavailable"
grep -q 'valuationComplete' "$VIEW" || fail "portfolio valuation completeness state missing"
grep -q 'app.portfolio.totalUsdcEquivalent' "$APP" || fail "Home hero is not using cumulative portfolio valuation"
grep -q 'projectedBalance' "$APP" || fail "USDC asset quantity is not kept independent"
grep -q 'app.portfolio.solUsdValue' "$APP" || fail "SOL asset row does not show its USD value"

# BLEE_MARKET_DATA_V3
# Public market quotation is intentionally direct and keyless. This is separate
# from operational Solana RPC, which must continue to use the Blee gateway.
grep -q 'BLEE_MARKET_DATA_V3' "$MARKET" || fail "direct DIA market-data boundary missing"
grep -Fq "https://api.diadata.org/v1/assetQuotation/Solana/0x0000000000000000000000000000000000000000" "$MARKET" || fail "canonical DIA SOL quotation endpoint missing"
grep -q 'Number(body.Price)' "$MARKET" || fail "DIA Price field is not used for SOL/USD valuation"
grep -q "pricingSource: 'dia-direct'" "$VIEW" || fail "portfolio pricing source is not direct DIA"
if grep -q "from './solanaGateway'" "$MARKET"; then
  fail "presentation-only DIA pricing must not be routed through the Solana gateway"
fi
if grep -Eq '/v1/market/sol-usd|rpc[.]blee[.]app|api[.]jup[.]ag|helius-rpc[.]com|api[.]coingecko[.]com|api[.]binance[.]com|x-api-key|api[_-]?key|authorization:[[:space:]]*bearer' "$MARKET"; then
  fail "SOL market valuation uses an unintended gateway/provider or credential surface"
fi

grep -q "type ReceiveAsset = 'usdc' | 'sol'" "$APP" || fail "Receive rail selector type missing"
grep -q "setReceiveAsset('sol')" "$APP" || fail "Receive cannot select SOL"
grep -q "receiveAsset === 'sol' ? app.solana.address" "$APP" || fail "SOL Receive does not use isolated Solana address"

# Spendability remains asset-specific despite the combined Home valuation.
grep -q "type SendAsset = 'usdc' | 'sol'" "$APP" || fail "Send rail selector contract missing"
grep -q "setPayAsset('usdc')" "$APP" || fail "Send cannot explicitly select USDC"
grep -Fq 'value > Number(app.available || 0)' "$APP" || fail "USDC spend check no longer uses USDC-only available balance"
grep -Fq 'lamports > app.solana.balanceLamports' "$APP" || fail "SOL spend check no longer uses SOL-only balance"
grep -q "const result = await app.sendPayment(payAddress, payAmount" "$APP" || fail "existing USDC send path changed unexpectedly"
grep -q "setPayResult({ asset: 'usdc', ...result })" "$APP" || fail "USDC send result is not explicitly rail-bound"
grep -q 'createAndDeliverOfflineSolPayment' "$APP" || fail "SOL send does not use guarded coordinator"

if grep -Eq 'sendSignedSolanaTransaction|createSolanaRpc|https://api[.](mainnet-beta|devnet|testnet)[.]solana[.]com|helius-rpc[.]com' "$APP"; then
  fail "multi-asset UI bypasses guarded Solana coordinator/gateway boundary"
fi

printf 'VERIFIED: Home uses direct DIA SOL/USD valuation while USDC and SOL remain separate spendable rails\n'
