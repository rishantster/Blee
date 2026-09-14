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
