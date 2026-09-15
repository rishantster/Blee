#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

PROJECTION="src/lib/solanaActivity.ts"
HOOK="src/hooks/useSolanaActivityView.ts"
VIEW="src/hooks/useBleeView.ts"
SIGNAL="src/lib/solanaActivitySignal.ts"
OUTBOX="src/lib/solanaMeshOutbox.ts"
INBOX="src/lib/solanaMeshStore.ts"

for file in "$PROJECTION" "$HOOK" "$VIEW" "$SIGNAL" "$OUTBOX" "$INBOX"; do
  [ -f "$file" ] || fail "SOL activity file missing: $file"
done

grep -q 'BLEE_SOLANA_ACTIVITY_PROJECTION_V1' "$PROJECTION" || fail "SOL activity projection marker missing"
grep -q 'loadOutboundSolanaMeshPayments' "$PROJECTION" || fail "SOL Activity does not read the durable outbox"
grep -q 'loadStoredSolanaMeshPayments' "$PROJECTION" || fail "SOL Activity does not read the durable inbox"
grep -q "row.role !== 'recipient'" "$PROJECTION" || fail "courier custody can leak into user Activity"
grep -q "railId: 'solana-sol'" "$PROJECTION" || fail "SOL Activity rail identity missing"
grep -q "networkId: 'solana-mainnet'" "$PROJECTION" || fail "SOL Activity network identity missing"
grep -q "assetSymbol: 'SOL'" "$PROJECTION" || fail "SOL Activity asset identity missing"
grep -q "state: 'mesh-delivered'" "$PROJECTION" || fail "received SOL custody is not represented as durable nearby delivery"
grep -q 'useSolanaActivityView' "$VIEW" || fail "SOL Activity read model is not exposed through useBleeView"
grep -q 'BLEE_UNIFIED_ACTIVITY_PRESENTATION_V1' "$VIEW" || fail "unified Activity presentation boundary missing"
grep -q 'activityPayments' "$VIEW" || fail "SOL Activity is not merged into a presentation-only Activity feed"
grep -q 'SOLANA_ACTIVITY_CHANGED_EVENT' "$HOOK" || fail "SOL Activity does not observe its durable mutation signal"
grep -q "blee:solana-activity-changed" "$SIGNAL" || fail "SOL Activity signal name is missing"
grep -q 'signalSolanaActivityChanged' "$OUTBOX" || fail "durable SOL outbox mutations do not refresh Activity"
grep -q 'signalSolanaActivityChanged' "$INBOX" || fail "durable SOL inbox mutations do not refresh Activity"

if grep -Eq "state: 'submitted'|state: 'settled'|sendSignedSolanaTransaction|sendSignedSolanaNonceSetupTransaction|createSolanaRpc|helius-rpc[.]com|BleePaymentNotifier" "$PROJECTION" "$HOOK" "$SIGNAL"; then
  fail "SOL Activity projection must never settle, submit, notify or access provider RPC"
fi

printf 'VERIFIED: SOL Activity is durable-store derived, live-refreshing, courier-hidden and settlement-neutral\n'
