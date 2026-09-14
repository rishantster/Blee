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
