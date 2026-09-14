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

grep -q "type SendAsset = 'usdc' | 'sol'" "$APP" || fail "send asset selector contract missing"
grep -q "createAndDeliverOfflineSolPayment" "$APP" || fail "SOL send UI is not wired to verified coordinator"
grep -q "parseUnits" "$APP" || fail "SOL amount is not converted to lamports exactly"
grep -q "data-blee-send-asset={payAsset}" "$APP" || fail "send asset presentation marker missing"
grep -q "app.solana.offlineReady" "$APP" || fail "SOL send does not fail closed without a prepared nonce"
grep -q "app.meshStarted" "$APP" || fail "SOL send does not require the Blee nearby transport"
grep -q "recipientEvm: payAddress" "$APP" || fail "SOL recipient is not passed as the Blee identity"
grep -q "amountLamports: parseSolLamports(payAmount).toString()" "$APP" || fail "SOL coordinator is not given exact lamports"
grep -q "const result = await app.sendPayment(payAddress, payAmount" "$APP" || fail "existing USDC send path was removed or bypassed"
grep -q "setPayResult({ asset: 'usdc', ...result })" "$APP" || fail "USDC send result identity missing"
grep -q "Solana Mainnet · sender-funded · durable nonce · Blee Mesh" "$APP" || fail "SOL route labeling is incomplete"
grep -q "Their SOL address is accepted only from the cryptographically verified capability" "$APP" || fail "SOL recipient binding is not explained in the UI"
grep -q "This screen does not claim on-chain confirmation" "$APP" || fail "SOL success screen may overstate settlement"

if grep -Eq 'recipientSolana[[:space:]]*:|sendSignedSolanaTransaction|createSolanaRpc|https://api[.](mainnet-beta|devnet|testnet)[.]solana[.]com|helius-rpc[.]com' "$APP"; then
  fail "SOL send UI must not accept a raw recipient Solana address or bypass the coordinator/gateway boundary"
fi

printf 'VERIFIED: SOL send UI is exact-lamport, verified-recipient, durable-nonce and coordinator-only\n'
