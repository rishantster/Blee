#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

# BLEE_SPRINT_6A_SOLANA_WALLET_VIEW_V4
# SOL operational chain state remains read-only and independently sourced through
# the canonical Helius Secure RPC adapter. Home may value that isolated quantity
# using direct public DIA market data, but valuation remains presentation-only.
[ -f src/hooks/useSolanaWalletView.ts ] || fail "SOL wallet presentation hook missing"
grep -q 'BLEE_SOLANA_WALLET_VIEW_V1' src/hooks/useSolanaWalletView.ts || fail "SOL wallet view contract marker missing"
grep -q "from '../lib/solanaGateway'" src/hooks/useSolanaWalletView.ts || fail "SOL wallet view does not use the canonical Solana RPC adapter"
grep -q 'getSolBalance' src/hooks/useSolanaWalletView.ts || fail "SOL confirmed balance projection missing"
grep -q 'listSolanaNonceSlots' src/hooks/useSolanaWalletView.ts || fail "SOL offline readiness is not derived from durable nonce slots"
grep -q 'getSolanaSignerForPrimarySession' src/hooks/useSolanaWalletView.ts || fail "SOL wallet view is not tied to authenticated primary session"
grep -q 'loadOutboundSolanaMeshPayments' src/hooks/useSolanaWalletView.ts || fail "SOL durable outbound state projection missing"
grep -q 'offlineReady: sessionReady && readyNonceCount > 0' src/hooks/useSolanaWalletView.ts || fail "SOL offline readiness guard missing"
grep -q 'formatUnits(balanceLamports, SOL_DECIMALS)' src/hooks/useSolanaWalletView.ts || fail "SOL 9-decimal display projection missing"
grep -q 'BLEE_MULTI_ASSET_PRESENTATION_BOUNDARY_V2' src/hooks/useBleeView.ts || fail "multi-asset presentation boundary marker missing"
grep -q 'const solana = useSolanaWalletView(core.account)' src/hooks/useBleeView.ts || fail "SOL wallet view is not attached to the authenticated app projection"
grep -q '^    solana,$' src/hooks/useBleeView.ts || fail "SOL view is not exposed as an isolated nested projection"
grep -q "pricingSource: 'dia-direct'" src/hooks/useBleeView.ts || fail "portfolio price source is not direct DIA"
grep -q 'BLEE_HELIUS_SECURE_RPC_V1' src/lib/solanaGateway.ts || fail "Helius Secure RPC boundary marker missing"
grep -q 'NEXT_PUBLIC_BLEE_HELIUS_SECURE_RPC' src/lib/solanaGateway.ts || fail "Helius Secure RPC build configuration missing"

if grep -Eq 'sendSignedSolanaTransaction|createAndDeliverOfflineSolPayment|prepareSignedOfflineSolTransfer|reserveSolanaNonceSlot' src/hooks/useSolanaWalletView.ts; then
  fail "SOL presentation hook must remain read-only"
fi
if grep -Eq 'createSolanaRpc|https://api[.](mainnet-beta|devnet|testnet)[.]solana[.]com|[?&]api-key=|x-api-key|HELIUS_API_KEY' src/hooks/useSolanaWalletView.ts src/lib/solanaGateway.ts; then
  fail "SOL wallet path contains a generic public RPC or provider credential"
fi
if grep -q 'sender[.]helius-rpc[.]com' src/lib/solanaGateway.ts; then
  fail "Blee V1 payment path must not use Helius Sender because Sender requires an extra tip instruction"
fi
if grep -Eq 'localStorage|sessionStorage' src/hooks/useSolanaWalletView.ts; then
  fail "SOL wallet view must not create browser-persisted financial state"
fi

printf 'VERIFIED: SOL operational balance uses keyless Helius Secure RPC while direct DIA valuation remains presentation-only\n'
