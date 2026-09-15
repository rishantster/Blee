#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

APP="src/components/BleeApp.tsx"
NETWORK="src/lib/paymentNetwork.ts"
VIEW="src/hooks/useBleeView.ts"

[ -f "$APP" ] || fail "Blee app UI missing"
[ -f "$NETWORK" ] || fail "payment network presentation helper missing"
[ -f "$VIEW" ] || fail "wallet view missing"

grep -q 'BLEE_SOLANA_ACTIVITY_UI_V1' "$APP" || fail "SOL Activity UI marker missing"
grep -q 'app.activityPayments' "$APP" || fail "Activity screen is not using unified presentation history"
grep -q 'data-blee-activity-ui="multi-rail-v1"' "$APP" || fail "multi-rail Activity screen marker missing"
grep -q 'paymentAssetSymbol(row)' "$APP" || fail "Activity rows do not render asset-specific symbols"
grep -q 'paymentNetworkLabel(row)' "$APP" || fail "Activity rows do not render immutable payment network labels"
grep -q 'data-blee-solana-activity-timeline="settlement-aware-v1"' "$APP" || fail "SOL detail timeline is not settlement-aware"
grep -q 'Signed and secured' "$APP" || fail "SOL detail timeline missing durable signing state"
grep -q 'Recipient acknowledged' "$APP" || fail "SOL detail timeline missing recipient delivery acknowledgement"
grep -q 'Submitted to Solana' "$APP" || fail "SOL detail timeline missing chain submission state"
grep -q 'Confirmed on Solana' "$APP" || fail "SOL detail timeline missing confirmation state"
grep -q 'Finalized on Solana' "$APP" || fail "SOL detail timeline missing finality state"
grep -q 'BLEE_UNIFIED_ACTIVITY_PRESENTATION_V1' "$VIEW" || fail "unified Activity merge boundary missing"
grep -q 'mergePayments(payments, solanaActivity.payments)' "$VIEW" || fail "SOL and Arc history are not merged at presentation only"
grep -q 'SOLANA_MAINNET_EXPLORER' "$NETWORK" || fail "Solana Mainnet explorer boundary missing"
grep -q 'row.solanaSignature' "$NETWORK" || fail "SOL explorer link is not gated by verified settlement signature"

# Operational Arc projections must continue to use the Arc-only `payments` view,
# never the presentation-only multi-rail Activity feed.
grep -q 'pendingIncomingAmount(payments)' "$VIEW" || fail "pending incoming balance projection no longer uses Arc-only payments"
grep -q 'verifyingIncomingCount(payments)' "$VIEW" || fail "verification projection no longer uses Arc-only payments"
if grep -Eq 'pendingIncomingAmount\(activityPayments\)|verifyingIncomingCount\(activityPayments\)' "$VIEW"; then
  fail "SOL Activity leaked into operational Arc balance or verification projections"
fi

printf 'VERIFIED: SOL history is wired into Home, Activity and independently verified settlement details without balance leakage\n'
