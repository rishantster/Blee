#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

# BLEE_SPRINT_5A_MESH_CAPABILITY_PROOF_V1
# Solana support is advertised only above the stable BLE transport. The existing
# EVM packet signature authenticates the Blee identity and an independent
# Ed25519 proof binds the advertised Solana address to that same identity.
[ -f src/lib/meshCapabilities.ts ] || fail "mesh capability proof module missing"
grep -q 'BLEE_MESH_CAPABILITY_PROOF_V1' src/lib/meshCapabilities.ts || fail "mesh capability proof contract marker missing"
grep -q "CAPABILITY_DOMAIN = 'BLEE_SOLANA_CAPABILITY_V1'" src/lib/meshCapabilities.ts || fail "mesh capability proof domain missing"
grep -q 'crypto.subtle.sign' src/lib/meshCapabilities.ts || fail "Solana capability is not signed by the local Solana key"
grep -q 'crypto.subtle.verify' src/lib/meshCapabilities.ts || fail "peer Solana capability proof is not verified"
grep -q 'evm=.*toLowerCase' src/lib/meshCapabilities.ts || fail "capability proof is not bound to the EVM Blee identity"
grep -q "rail=solana-sol" src/lib/meshCapabilities.ts || fail "capability proof is not rail-bound"
grep -q "network=solana-mainnet" src/lib/meshCapabilities.ts || fail "capability proof is not network-bound"
grep -q 'export type MeshCapabilitiesV1' src/types/domain.ts || fail "mesh capability domain type missing"
grep -q 'solanaAddress?: string' src/types/domain.ts || fail "peer Solana address projection missing"
grep -q 'capabilitiesVerified?: boolean' src/types/domain.ts || fail "peer capability verification state missing"
grep -q 'static final int MAX_BYTES = 20' android/app/src/main/java/com/blee/payments/BleePeerProfile.java || fail "native BLE profile size changed"
if grep -qi 'solana' android/app/src/main/java/com/blee/payments/BleePeerProfile.java; then
  fail "Solana capability data must not enter the 20-byte native BLE profile"
fi
if grep -Eq 'createSolanaRpc|https://api[.](mainnet-beta|devnet|testnet)[.]solana[.]com|helius-rpc[.]com' src/lib/meshCapabilities.ts; then
  fail "mesh capability proof must not introduce an RPC path"
fi

printf 'VERIFIED: Solana mesh capability proof is dual-key bound above the unchanged BLE identity profile\n'

# BLEE_SPRINT_5A2_LIVE_CAPABILITY_EXCHANGE_V1
# Capability exchange is injected into the already EVM-signed hello packet, not
# the native identity/profile characteristic. Solana signer warm-up may never
# delay or break Arc discovery, and only dual-key-verified data is cached.
[ -f src/lib/meshCapabilityStore.ts ] || fail "verified peer capability cache missing"
grep -q "MESH_CAPABILITY_STORE_PREFIX = 'mesh.peer-capabilities.v1'" src/lib/meshCapabilityStore.ts || fail "peer capability cache key missing"
grep -q "from './bleeStore'" src/lib/meshCapabilityStore.ts || fail "peer capability cache must use canonical SQLite-backed BleeStore"
grep -q 'verifyMeshCapabilitiesV1' src/lib/meshCapabilityStore.ts || fail "cached peer capabilities are not re-verified"
grep -q 'BLEE_MESH_CAPABILITY_HELLO_V1' src/lib/meshProtocol.ts || fail "live hello capability exchange marker missing"
grep -q 'getSolanaSignerForPrimarySession' src/lib/meshProtocol.ts || fail "hello does not consult the authenticated Solana session"
grep -q "type === 'hello'" src/lib/meshProtocol.ts || fail "capability data is not restricted to hello packets"
grep -q 'createMeshCapabilitiesV1' src/lib/meshProtocol.ts || fail "local hello does not create a cryptographic capability proof"
grep -q 'verifyMeshCapabilitiesV1' src/lib/meshProtocol.ts || fail "incoming hello capability proof is not verified"
grep -q 'saveVerifiedPeerMeshCapabilities' src/lib/meshProtocol.ts || fail "verified peer capability is not durably cached"
grep -q "rails: \['arc-usdc'\]" src/lib/meshProtocol.ts || fail "Arc-only fail-safe hello fallback missing"
grep -q 'packet.origin.toLowerCase' src/lib/meshProtocol.ts || fail "hello display address is not bound to packet origin"
if grep -Eq 'localStorage|sessionStorage' src/lib/meshCapabilityStore.ts; then
  fail "peer capability cache must not use browser storage"
fi
if grep -Eq 'createSolanaRpc|https://api[.](mainnet-beta|devnet|testnet)[.]solana[.]com|helius-rpc[.]com' src/lib/meshProtocol.ts src/lib/meshCapabilityStore.ts; then
  fail "live capability exchange introduced a direct Solana RPC path"
fi

printf 'VERIFIED: live nearby hello exchanges and durably caches only verified Solana capabilities\n'
