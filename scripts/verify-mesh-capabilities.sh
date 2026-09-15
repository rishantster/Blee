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

# BLEE_SPRINT_5B1_SOLANA_MESH_ENVELOPE_V1
# Exact signed SOL bytes are wrapped only after recipient SOL support has been
# cryptographically verified. Receiver/courier custody must persist the entire
# authenticated packet in canonical SQLite storage and fail closed on a
# paymentId conflict. This layer never submits or mutates the signed transaction.
[ -f src/lib/solanaMeshEnvelope.ts ] || fail "SOL mesh payment envelope module missing"
[ -f src/lib/solanaMeshStore.ts ] || fail "SOL mesh durable custody store missing"
grep -q 'BLEE_SOLANA_MESH_PAYMENT_ENVELOPE_V1' src/lib/solanaMeshEnvelope.ts || fail "SOL mesh envelope contract marker missing"
grep -q 'prepareSolanaMeshPaymentPacket' src/lib/solanaMeshEnvelope.ts || fail "SOL mesh packet preparation missing"
grep -q 'loadVerifiedPeerMeshCapabilities' src/lib/solanaMeshEnvelope.ts || fail "SOL recipient is not sourced from verified peer capabilities"
grep -q "createMeshPacket(input.primaryAccount, 'sol-payment'" src/lib/solanaMeshEnvelope.ts || fail "SOL exact signed bytes are not carried by the framed mesh packet"
grep -q 'verifyMeshCapabilitiesV1(packet.origin' src/lib/solanaMeshEnvelope.ts || fail "SOL sender capability proof is not verified on receipt"
grep -q 'MAX_WIRE_TRANSACTION_BYTES = 1232' src/lib/solanaMeshEnvelope.ts || fail "Solana wire-size ceiling missing"
grep -q "crypto.subtle.digest('SHA-256'" src/lib/solanaMeshEnvelope.ts || fail "SOL wire digest verification missing"
grep -q 'signedTransactionSha256' src/lib/solanaMeshEnvelope.ts || fail "SOL envelope exact-byte digest missing"
grep -q 'BLEE_SOLANA_MESH_DURABLE_CUSTODY_V1' src/lib/solanaMeshStore.ts || fail "SOL durable custody contract marker missing"
grep -q "SOLANA_MESH_INBOX_KEY = 'mesh.solana-inbox.v1'" src/lib/solanaMeshStore.ts || fail "SOL durable inbox key missing"
grep -q "from './bleeStore'" src/lib/solanaMeshStore.ts || fail "SOL durable custody must use canonical SQLite-backed BleeStore"
grep -q 'validateSolanaMeshPaymentEnvelope' src/lib/solanaMeshStore.ts || fail "stored SOL packets are not cryptographically revalidated"
grep -q "role = 'recipient'" src/lib/solanaMeshStore.ts || fail "recipient custody role missing"
grep -q "role = 'courier'" src/lib/solanaMeshStore.ts || fail "courier custody role missing"
grep -q 'conflicts with different signed transaction bytes' src/lib/solanaMeshStore.ts || fail "SOL paymentId conflict is not fail-closed"
grep -q "'sol-payment'" src/types/domain.ts || fail "SOL mesh packet type missing"
grep -q 'export type SolanaMeshPaymentEnvelopeV1' src/types/domain.ts || fail "SOL mesh envelope domain type missing"
if grep -Eq 'localStorage|sessionStorage' src/lib/solanaMeshEnvelope.ts src/lib/solanaMeshStore.ts; then
  fail "SOL mesh envelope/custody must not use browser storage"
fi
if grep -Eq 'sendSignedSolanaTransaction|createSolanaRpc|https://api[.](mainnet-beta|devnet|testnet)[.]solana[.]com|helius-rpc[.]com' src/lib/solanaMeshEnvelope.ts src/lib/solanaMeshStore.ts; then
  fail "SOL mesh layer must not broadcast or introduce a direct RPC path"
fi

printf 'VERIFIED: exact signed SOL mesh envelope is capability-bound and durably stored for recipient/courier custody\n'

# BLEE_SPRINT_5B2_SOLANA_LIVE_RECEIVE_V1
# Live receive must authenticate the outer EVM packet, validate the SOL envelope,
# durably commit exact signed bytes, and only then ACK. Courier forwarding uses
# the existing framed transport after verifyMeshPacket returns, so persistence
# necessarily completes before the caller can forward the packet.
grep -q 'BLEE_SOLANA_MESH_LIVE_RECEIVE_V1' src/lib/meshProtocol.ts || fail "live SOL receive marker missing"
grep -q 'validateAuthenticatedSolanaMeshPaymentEnvelope' src/lib/meshProtocol.ts || fail "live SOL receive does not validate the authenticated inner envelope"
grep -q 'storeVerifiedInboundSolanaMeshPayment' src/lib/meshProtocol.ts || fail "live SOL receive does not durably store before returning"
grep -q 'allowCourier: true' src/lib/meshProtocol.ts || fail "live SOL courier custody is not enabled"
grep -q 'BLEE_SOLANA_ACK_AFTER_DURABLE_STORE_V1' src/lib/meshProtocol.ts || fail "durable SOL ACK ordering marker missing"
grep -q "createMeshPacket(input.account, 'sol-ack'" src/lib/meshProtocol.ts || fail "recipient durable SOL ACK packet missing"
grep -q 'durable: true' src/lib/meshProtocol.ts || fail "recipient SOL ACK is not marked durable"
grep -q 'verifyMeshCapabilitiesV1(packet.origin, raw.recipientCapabilities)' src/lib/meshProtocol.ts || fail "SOL ACK recipient capability proof is not verified"
grep -q 'WeakRef<PrivateKeyAccount>' src/lib/meshProtocol.ts || fail "mesh runtime must not create a second strong global primary signer holder"
grep -q "processSolanaRuntime: false" src/lib/solanaMeshEnvelope.ts || fail "standalone SOL validation can recursively re-enter the live receive runtime"
grep -q 'storeVerifiedInboundSolanaMeshPayment' src/lib/solanaMeshStore.ts || fail "verified live custody entry point missing"
grep -q "'sol-ack'" src/types/domain.ts || fail "SOL durable ACK packet type missing"
grep -q 'export type SolanaMeshDeliveryAckV1' src/types/domain.ts || fail "SOL durable ACK domain type missing"
if grep -Eq 'sendSignedSolanaTransaction|createSolanaRpc|https://api[.](mainnet-beta|devnet|testnet)[.]solana[.]com|helius-rpc[.]com' src/lib/meshProtocol.ts; then
  fail "live SOL mesh receive must not submit on-chain or introduce direct RPC"
fi

printf 'VERIFIED: live SOL receive commits before ACK and courier forwarding remains exact-byte durable\n'

# BLEE_SPRINT_5B3_SOLANA_OUTBOUND_DELIVERY_V1
# Sender delivery persists the exact SOL envelope before transport, retries only
# refresh the outer EVM-signed packet, and completion requires a matching durable
# recipient ACK to update the SQLite-backed outbox.
[ -f src/lib/solanaMeshOutbox.ts ] || fail "SOL mesh sender outbox missing"
[ -f src/lib/solanaMeshDelivery.ts ] || fail "SOL mesh outbound delivery module missing"
grep -q "SOLANA_MESH_OUTBOX_KEY = 'mesh.solana-outbox.v1'" src/lib/solanaMeshOutbox.ts || fail "SOL sender outbox key missing"
grep -q "from './bleeStore'" src/lib/solanaMeshOutbox.ts || fail "SOL sender outbox must use canonical SQLite-backed BleeStore"
grep -q 'BLEE_SOLANA_MESH_OUTBOX_V1' src/lib/solanaMeshOutbox.ts || fail "SOL sender outbox contract marker missing"
grep -q 'applyVerifiedSolanaDeliveryAck' src/lib/solanaMeshOutbox.ts || fail "SOL sender outbox cannot consume durable ACK"
grep -q 'BLEE_SOLANA_MESH_OUTBOUND_DELIVERY_V1' src/lib/solanaMeshDelivery.ts || fail "SOL outbound delivery contract marker missing"
grep -q 'BLEE_SOLANA_OUTBOX_BEFORE_TRANSPORT_V1' src/lib/solanaMeshDelivery.ts || fail "SOL outbox-before-transport ordering marker missing"
grep -q 'persistOutboundSolanaMeshPayment' src/lib/solanaMeshDelivery.ts || fail "SOL sender does not durably persist before transport"
grep -q 'prepareSolanaMeshPaymentPacket' src/lib/solanaMeshDelivery.ts || fail "SOL sender does not use verified payment envelope builder"
grep -q "createMeshPacket(input.primaryAccount, 'sol-payment', existing.envelope)" src/lib/solanaMeshDelivery.ts || fail "SOL retry does not refresh only the outer packet"
grep -q 'existing.envelope.signedTransactionSha256' src/lib/solanaMeshDelivery.ts || fail "SOL retry exact-byte digest guard missing"
grep -q 'BLEE_SOLANA_ACK_CONSUME_V1' src/lib/meshProtocol.ts || fail "live SOL ACK consumption marker missing"
grep -q "import('./solanaMeshOutbox')" src/lib/meshProtocol.ts || fail "verified SOL ACK is not routed to durable sender outbox"
if grep -Eq 'localStorage|sessionStorage' src/lib/solanaMeshOutbox.ts src/lib/solanaMeshDelivery.ts; then
  fail "SOL sender delivery state must not use browser storage"
fi
if grep -Eq 'sendSignedSolanaTransaction|createSolanaRpc|https://api[.](mainnet-beta|devnet|testnet)[.]solana[.]com|helius-rpc[.]com' src/lib/solanaMeshOutbox.ts src/lib/solanaMeshDelivery.ts; then
  fail "SOL outbound BLE delivery must not submit on-chain or introduce direct RPC"
fi

printf 'VERIFIED: outbound SOL delivery is durable-before-send, exact-byte retry safe and ACK-driven\n'

# BLEE_SPRINT_5C_SOLANA_PAYMENT_COORDINATOR_V1
# The UI-neutral coordinator must derive the recipient SOL address only from the
# verified nearby capability cache, use the authenticated session signer, create
# the durable-nonce transaction, and hand exact bytes to the durable mesh outbox.
[ -f src/lib/solanaPaymentCoordinator.ts ] || fail "SOL payment coordinator missing"
grep -q 'BLEE_SOLANA_OFFLINE_PAYMENT_COORDINATOR_V1' src/lib/solanaPaymentCoordinator.ts || fail "SOL payment coordinator marker missing"
grep -q 'loadVerifiedPeerMeshCapabilities' src/lib/solanaPaymentCoordinator.ts || fail "SOL coordinator does not source recipient from verified capabilities"
grep -q 'getSolanaSignerForPrimarySession' src/lib/solanaPaymentCoordinator.ts || fail "SOL coordinator bypasses authenticated Solana session"
grep -q 'prepareSignedOfflineSolTransfer' src/lib/solanaPaymentCoordinator.ts || fail "SOL coordinator does not use durable-nonce transaction builder"
grep -q 'recipient: capabilities.solana.address' src/lib/solanaPaymentCoordinator.ts || fail "SOL coordinator accepts an unverified recipient Solana address"
grep -q 'sendPreparedOfflineSolOverMesh' src/lib/solanaPaymentCoordinator.ts || fail "SOL coordinator does not hand signed payment to durable mesh delivery"
grep -q 'crypto.getRandomValues' src/lib/solanaPaymentCoordinator.ts || fail "SOL coordinator payment IDs are not cryptographically random"
grep -q 'retryPendingOutboundSolanaMeshPayments' src/lib/solanaPaymentCoordinator.ts || fail "SOL coordinator does not expose exact-byte durable retry"
if grep -Eq 'sendSignedSolanaTransaction|createSolanaRpc|https://api[.](mainnet-beta|devnet|testnet)[.]solana[.]com|helius-rpc[.]com' src/lib/solanaPaymentCoordinator.ts; then
  fail "SOL offline payment coordinator must not submit on-chain or introduce direct RPC"
fi
if grep -Eq 'BleeApp|useBleeView|React|tsx' src/lib/solanaPaymentCoordinator.ts; then
  fail "SOL payment coordinator must remain UI-neutral"
fi

printf 'VERIFIED: SOL payment coordinator is verified-peer bound, session signed and durable-mesh only\n'
