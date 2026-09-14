#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

# BLEE_SPRINT_3B_NETWORK_BOUNDARY_VERIFY_V1
# Historical rows from an inactive Arc network must remain visible/auditable,
# but their EIP-3009 authorization must not be exposed to the active settlement
# loop. Balance snapshots and scan cursors are also namespaced by network so a
# release switch cannot reuse Testnet state as Mainnet state.
grep -q 'BLEE_INACTIVE_NETWORK_AUTH_ARCHIVE_V1' src/lib/persistence.ts || fail "inactive-network authorization archive boundary missing"
grep -q 'archivedAuthorization?: TransferAuthorization' src/types/domain.ts || fail "historical authorization field missing"
grep -q 'network.networkId === activeArc.id' src/lib/persistence.ts || fail "active Arc settlement eligibility check missing"
grep -q 'authorization: row.authorization ?? archivedAuthorization' src/lib/persistence.ts || fail "historical authorization is not preserved on durable rewrite"
grep -q 'BLEE_NETWORK_SCOPED_CACHE_V1' src/lib/persistence.ts || fail "network-scoped balance/cursor cache boundary missing"
grep -q 'stateKey(kind:.*networkId' src/lib/persistence.ts || fail "network-scoped state key helper missing"
grep -q "active.id !== ARC_TESTNET.id" src/lib/persistence.ts || fail "legacy balance/cursor migration is not restricted to Arc Testnet"

printf 'VERIFIED: inactive Arc history is non-settleable and Arc caches are network-scoped\n'

# BLEE_SPRINT_3C_PRESENTATION_BOUNDARY_VERIFY_V1
# Activity/presentation identity is derived from each payment's persisted network,
# not from the currently active release network. Active balance badges and pending
# value must ignore history from another Arc environment.
[ -f src/lib/paymentNetwork.ts ] || fail "payment network presentation boundary missing"
grep -q 'export function paymentNetworkId' src/lib/paymentNetwork.ts || fail "payment network resolver missing"
grep -q "return row.railId === 'solana-sol' ? 'solana-mainnet' : 'arc-testnet'" src/lib/paymentNetwork.ts || fail "legacy network fallback must remain Arc Testnet"
grep -q 'export function paymentExplorerUrl' src/lib/paymentNetwork.ts || fail "per-payment explorer resolver missing"
grep -q 'export function isActiveArcPayment' src/lib/paymentNetwork.ts || fail "active Arc projection guard missing"
grep -q 'export function paymentProjectionKey' src/lib/paymentNetwork.ts || fail "network-aware Activity key missing"
grep -q 'paymentProjectionKey(row)' src/hooks/useBleeView.ts || fail "durable UI merge is not network-aware"
ACTIVE_PROJECTION_GUARDS="$(grep -c 'isActiveArcPayment(row)' src/hooks/useBleeView.ts | tr -d ' ')"
[ "$ACTIVE_PROJECTION_GUARDS" -ge 2 ] || fail "pending/verifying projections are not both restricted to active Arc"

printf 'VERIFIED: payment presentation identity and active Arc projections are network-isolated\n'
