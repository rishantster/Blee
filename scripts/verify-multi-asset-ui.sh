#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

# BLEE_SPRINT_6B1_MULTI_ASSET_UI_V1
# SOL becomes visible without changing the established USDC send engine. Balances
# remain separate, Receive explicitly selects a rail, and Solana readiness comes
# only from the read-only Solana wallet projection.
grep -q 'data-blee-multi-asset-ui="v1"' src/components/BleeApp.tsx || fail "multi-asset home marker missing"
grep -q 'SOL BALANCE' src/components/BleeApp.tsx || fail "SOL balance card missing"
grep -q 'Solana Mainnet' src/components/BleeApp.tsx || fail "Solana Mainnet label missing"
grep -q 'app.solana.balance' src/components/BleeApp.tsx || fail "SOL balance is not sourced from isolated Solana projection"
grep -q 'app.solana.offlineReady' src/components/BleeApp.tsx || fail "SOL offline readiness is not presented"
grep -q "type ReceiveAsset = 'usdc' | 'sol'" src/components/BleeApp.tsx || fail "Receive rail selector type missing"
grep -q "setReceiveAsset('sol')" src/components/BleeApp.tsx || fail "Receive cannot select SOL"
grep -q "receiveAsset === 'sol' ? app.solana.address" src/components/BleeApp.tsx || fail "SOL Receive does not use the isolated Solana address"
grep -q 'SOL · Solana Mainnet' src/components/BleeApp.tsx || fail "SOL Receive network label missing"
grep -q 'data-blee-solana-network="mainnet"' src/components/BleeApp.tsx || fail "Solana network security card missing"
grep -q 'Send USDC' src/components/BleeApp.tsx || fail "existing Send action is not explicitly constrained to USDC"
grep -q 'app.sendPayment(payAddress, payAmount' src/components/BleeApp.tsx || fail "existing USDC send path changed unexpectedly"
if grep -Eq 'createAndDeliverOfflineSolPayment|sendSignedSolanaTransaction|createSolanaRpc|helius-rpc[.]com' src/components/BleeApp.tsx; then
  fail "Sprint 6B1 presentation must not introduce SOL signing/submission into BleeApp"
fi
if grep -Eq 'projectedBalance.*solana|solana.*projectedBalance' src/components/BleeApp.tsx; then
  fail "USDC and SOL balances must never be combined"
fi

printf 'VERIFIED: multi-asset UI exposes SOL separately without changing USDC send semantics\n'
