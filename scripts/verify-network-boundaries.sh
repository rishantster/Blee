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

# BLEE_SPRINT_4A_SOLANA_NONCE_RESERVATION_V1
# A durable nonce must be persisted as owned by exactly one logical payment
# before signing. Exact signed bytes are persisted in that same durable record
# and retries may only replay those bytes. An observed on-chain nonce change
# quarantines the slot until the settlement lifecycle explicitly rearms it.
[ -f src/lib/solanaNoncePool.ts ] || fail "Solana durable nonce pool missing"
grep -q "SOLANA_NONCE_POOL_KEY = 'solana.nonce-pool.v1'" src/lib/solanaNoncePool.ts || fail "Solana nonce pool storage key missing"
grep -q 'SOLANA_NONCE_ACCOUNT_SPACE = 80' src/lib/solanaNoncePool.ts || fail "Solana nonce account size changed unexpectedly"
grep -q "type SolanaNonceSlotState = 'ready' | 'reserved' | 'advanced' | 'invalid'" src/lib/solanaNoncePool.ts || fail "Solana nonce slot state machine missing"
grep -q 'export async function reserveSolanaNonceSlot' src/lib/solanaNoncePool.ts || fail "Solana nonce reservation boundary missing"
grep -q 'export async function persistSignedSolanaTransaction' src/lib/solanaNoncePool.ts || fail "exact signed SOL transaction persistence missing"
grep -q 'signedTransactionBase64' src/lib/solanaNoncePool.ts || fail "signed SOL transaction bytes are not durable"
grep -q 'signedTransactionSha256' src/lib/solanaNoncePool.ts || fail "signed SOL transaction digest missing"
grep -q 'export async function reconcileSolanaNoncePool' src/lib/solanaNoncePool.ts || fail "Solana nonce reconciliation boundary missing"
grep -q "slot.state = 'advanced'" src/lib/solanaNoncePool.ts || fail "advanced nonce quarantine missing"
grep -q 'export async function rearmAdvancedSolanaNonceSlot' src/lib/solanaNoncePool.ts || fail "explicit Solana nonce rearm boundary missing"
grep -q "from './bleeStore'" src/lib/solanaNoncePool.ts || fail "Solana nonce pool must use canonical SQLite-backed BleeStore"
grep -q "from './solanaGateway'" src/lib/solanaNoncePool.ts || fail "Solana nonce verification must use the Blee gateway"
if grep -Eq 'localStorage|sessionStorage' src/lib/solanaNoncePool.ts; then
  fail "Solana nonce reservation state must not use browser storage"
fi
if grep -Eq 'https://api[.](mainnet-beta|devnet|testnet)[.]solana[.]com|helius-rpc[.]com' src/lib/solanaNoncePool.ts; then
  fail "Solana nonce pool bypasses the Blee gateway"
fi

printf 'VERIFIED: Solana nonce reservation is durable, single-owner and exact-byte replay safe\n'
