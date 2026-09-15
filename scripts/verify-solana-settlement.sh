#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

SETTLEMENT="src/lib/solanaSettlement.ts"
HOOK="src/hooks/useSolanaSettlementView.ts"
GATEWAY="src/lib/solanaGateway.ts"
ACTIVITY="src/lib/solanaActivity.ts"
DOMAIN="src/types/domain.ts"
NETWORK="src/lib/paymentNetwork.ts"

for file in "$SETTLEMENT" "$HOOK" "$GATEWAY" "$ACTIVITY" "$DOMAIN" "$NETWORK"; do
  [ -f "$file" ] || fail "SOL settlement file missing: $file"
done

grep -q 'BLEE_SOLANA_SETTLEMENT_V1' "$SETTLEMENT" || fail "SOL settlement lifecycle marker missing"
grep -q "SOLANA_SETTLEMENT_JOURNAL_KEY = 'solana.settlement.v1'" "$SETTLEMENT" || fail "durable SOL settlement journal key missing"
grep -q 'loadOutboundSolanaMeshPayments' "$SETTLEMENT" || fail "sender durable custody cannot enter settlement"
grep -q 'loadStoredSolanaMeshPayments' "$SETTLEMENT" || fail "recipient/courier durable custody cannot enter settlement"
grep -q "source: row.role" "$SETTLEMENT" || fail "recipient/courier settlement source identity missing"
grep -q 'signedTransactionBase64: envelope.signedTransactionBase64' "$SETTLEMENT" || fail "settlement does not preserve exact durable signed bytes"
grep -q 'signedTransactionSha256: envelope.signedTransactionSha256' "$SETTLEMENT" || fail "settlement does not bind exact transaction digest"
grep -q 'sendSignedSolanaTransaction' "$SETTLEMENT" || fail "settlement does not submit through canonical Blee gateway"
grep -q 'getSolanaSignatureStatuses' "$SETTLEMENT" || fail "settlement confirmation polling missing"
grep -q 'getSolanaTransaction' "$SETTLEMENT" || fail "independent transaction summary verification missing"
grep -q 'summary.sender !== row.senderSolana' "$SETTLEMENT" || fail "finality does not verify sender"
grep -q 'summary.recipient !== row.recipientSolana' "$SETTLEMENT" || fail "finality does not verify recipient"
grep -q "String(summary.amountLamports || '') !== row.amountLamports" "$SETTLEMENT" || fail "finality does not verify SOL amount"
grep -q "state: confirmation === 'finalized' ? 'finalized' : 'confirmed'" "$SETTLEMENT" || fail "confirmed/finalized states are not separated"
grep -q "row.source !== 'sender'" "$SETTLEMENT" || fail "courier/recipient could attempt local nonce rearm"
grep -q "slot.state !== 'advanced'" "$SETTLEMENT" || fail "nonce could be rearmed before independently observing advancement"
grep -q 'rearmAdvancedSolanaNonceSlot' "$SETTLEMENT" || fail "finalized sender nonce rearm missing"
grep -q 'BLEE_SOLANA_SETTLEMENT_WORKER_V1' "$HOOK" || fail "automatic foreground settlement worker missing"
grep -q "window.addEventListener('online'" "$HOOK" || fail "settlement worker does not wake when internet returns"
grep -q 'SETTLEMENT_TICK_MS = 30_000' "$HOOK" || fail "bounded settlement retry cadence missing"
grep -q 'Gateway returned an invalid SOL payment signature' "$GATEWAY" || fail "payment submission signature is not validated"
grep -q 'solanaSignature' "$DOMAIN" || fail "Solana transaction signature presentation metadata missing"
grep -q 'SOLANA_MAINNET_EXPLORER' "$NETWORK" || fail "Solana explorer boundary missing"
grep -q 'row.solanaSignature' "$NETWORK" || fail "Solana explorer link is not gated by a real settlement signature"
grep -q 'loadSolanaSettlementRecords' "$ACTIVITY" || fail "SOL Activity does not consume durable settlement state"
grep -q 'BLEE_SOLANA_ACTIVITY_PROJECTION_V2' "$ACTIVITY" || fail "settlement-aware SOL Activity projection marker missing"

if grep -Eq 'BleePaymentNotifier|notifyPayment|new Notification|Notification\.requestPermission' "$SETTLEMENT" "$HOOK"; then
  fail "SOL settlement must remain silent and must not own user notifications"
fi
if grep -Eq 'getSolanaSignerForPrimarySession|unlockSolanaVault|signTransaction|signMessage|generateKeyPair|createKeyPair' "$SETTLEMENT" "$HOOK"; then
  fail "SOL settlement must replay exact signed bytes and must never sign or rebuild payments"
fi
if grep -Eq 'helius-rpc[.]com|api[.]helius|mainnet-beta[.]solana[.]com|x-api-key|HELIUS_API_KEY' "$SETTLEMENT" "$HOOK" "$GATEWAY"; then
  fail "provider RPC or credentials leaked into APK-bound SOL settlement code"
fi

printf 'VERIFIED: SOL settlement replays exact durable bytes through Blee Gateway, verifies finality, stays notification-silent, and rearms only finalized sender nonces\n'
