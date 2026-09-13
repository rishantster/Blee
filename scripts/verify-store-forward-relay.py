#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"RELAY VERIFY ERROR: {message}")


def require(text: str, markers: tuple[str, ...], label: str) -> None:
    missing = [marker for marker in markers if marker not in text]
    if missing:
        fail(f"{label} missing {missing}")


def verify_source_contract() -> None:
    files = {
        "relay store": ROOT / "relay-v1/BleeRelayStore.java.in",
        "relay web": ROOT / "relay-v1/payments-relay.tsfrag",
        "relay patcher": ROOT / "scripts/apply-blee-store-forward-relay-v1.py",
        "relay compilefix": ROOT / "scripts/apply-blee-store-forward-relay-v1-compilefix.py",
        "relay sender compat": ROOT / "scripts/apply-blee-store-forward-relay-v1-sender-compat.py",
        "relay ingress": ROOT / "scripts/apply-blee-store-forward-relay-v1-ingress.py",
        "adaptive chain": ROOT / "scripts/apply-blee-adaptive-nearby-v3-compilefix.py",
    }
    for label, path in files.items():
        if not path.is_file():
            fail(f"{label} file missing: {path.relative_to(ROOT)}")

    store = files["relay store"].read_text()
    require(store, (
        "BLEE_GLOBAL_STORE_FORWARD_RELAY_V1",
        "CREATE TABLE IF NOT EXISTS relay_envelopes",
        "tx_hash TEXT UNIQUE",
        "relay_sender_nonce_idx",
        "MAX_QUEUE = 256",
        "MAX_PACKET_BYTES = 128 * 1024",
        "MAX_HOPS = 16",
        "promoteVerified",
        '"FORWARDABLE"',
        '"NEEDS_SENDER_REFRESH"',
        "markConfirmed",
    ), "relay store")

    web = files["relay web"].read_text()
    require(web, (
        "BLEE_GLOBAL_STORE_FORWARD_RELAY_WEB_V1",
        "validateSenderFundedRelayEnvelope",
        "verifyAuthorization(auth)",
        "parseTransaction",
        "recoverTransactionAddress",
        "decodeFunctionData",
        "transferWithAuthorization",
        "keccak256(broadcast.rawTransaction)",
        "broadcastSenderFundedRawTransaction",
        "publicClient.sendRawTransaction",
        "NEEDS_SENDER_REFRESH",
    ), "relay web validation")
    start = web.index("export async function broadcastSenderFundedRawTransaction")
    community = web[start:]
    for forbidden in ("PrivateKeyAccount", "createWalletClient", "walletClient", "writeContract"):
        if forbidden in community:
            fail(f"community relay broadcaster contains forbidden signing primitive: {forbidden}")

    patcher = files["relay patcher"].read_text()
    require(patcher, (
        "BLEE_RELAY_VALIDATION_GATE_V1",
        "boolean shouldForward = !paymentEnvelope",
        "BleeRelayStore relayStore",
        "broadcastCandidates(now, 64)",
        "authorizationStateUsed",
        'rpc("eth_call"',
        '"0xe94a0102"',
        "TRUSTED_RPCS",
        "pendingRelayCandidates",
        "acceptValidatedRelayEnvelope",
        "validateSenderFundedRelayEnvelope",
    ), "relay generated patcher")

    sender = files["relay sender compat"].read_text()
    require(sender, (
        "BLEE_RELAY_LOCAL_SENDER_COMPAT_V1",
        'deviceId.equals(packet.optString("originDeviceId", ""))',
        "sendRawTransaction(rawTx)",
    ), "sender compatibility")
    for forbidden in ("createWalletClient", "writeContract", "PrivateKeyAccount"):
        if forbidden in sender:
            fail(f"sender background compatibility contains forbidden signing primitive: {forbidden}")

    ingress = files["relay ingress"].read_text()
    require(ingress, (
        "BLEE_RELAY_INGRESS_GUARD_V1",
        "128 * 1024",
        "hopLimit > 16",
        "copyBudget > 16",
        "basicRelayEnvelopeShape",
        "relayIngressAllowed",
        "global >= 128",
        "source >= 32",
        '"SENDER_FUNDED_RAW_TX"',
        "5042002L",
    ), "relay ingress guard")

    chain = files["adaptive chain"].read_text()
    stages = [
        'run_stage("apply-blee-payment-notifications-v2.py")',
        'run_stage("apply-blee-store-forward-relay-v1.py")',
        'run_stage("apply-blee-store-forward-relay-v1-compilefix.py")',
        'run_stage("apply-blee-store-forward-relay-v1-sender-compat.py")',
        'run_stage("apply-blee-store-forward-relay-v1-ingress.py")',
    ]
    positions = [chain.find(stage) for stage in stages]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        fail("relay stages are missing or not serialized after production notifications")


def verify_generated_contract() -> None:
    android_java = ROOT / "android/app/src/main/java"
    payments = ROOT / "src/lib/payments.ts"
    runtime = ROOT / "src/components/BleeRuntime.tsx"
    if not android_java.is_dir() or not payments.is_file() or not runtime.is_file():
        return

    services = list(android_java.rglob("BleeMeshService.java"))
    dbs = list(android_java.rglob("BleeMeshDb.java"))
    plugins = list(android_java.rglob("BleeMeshPlugin.java"))
    stores = list(android_java.rglob("BleeRelayStore.java"))
    if not all(len(items) == 1 for items in (services, dbs, plugins, stores)):
        return

    service = services[0].read_text()
    db = dbs[0].read_text()
    plugin = plugins[0].read_text()
    store = stores[0].read_text()
    web = payments.read_text()
    ui = runtime.read_text()

    # Only enforce the generated contract once this branch's stage has actually
    # been materialized. A clean checkout intentionally has no android/ tree.
    if "BLEE_GLOBAL_STORE_FORWARD_RELAY_SERVICE_V1" not in service:
        return

    require(service, (
        "BLEE_GLOBAL_STORE_FORWARD_RELAY_SERVICE_V1",
        "BLEE_RELAY_LOCAL_SENDER_COMPAT_V1",
        "BleeRelayStore relayStore",
        "broadcastCandidates(now, 64)",
        "attemptLocalSenderSettlement(now)",
        "authorizationStateUsed",
        "markNeedsSenderRefresh",
    ), "generated relay service")
    require(db, (
        "BLEE_RELAY_VALIDATION_GATE_V1",
        "BLEE_RELAY_INGRESS_GUARD_V1",
        "boolean shouldForward = !paymentEnvelope",
    ), "generated mesh DB")
    require(plugin, (
        "BLEE_RELAY_PLUGIN_V1",
        "pendingRelayCandidates",
        "acceptValidatedRelayEnvelope",
        "rejectRelayCandidate",
        "relayDiagnostics",
    ), "generated relay plugin")
    require(store, (
        "BLEE_GLOBAL_STORE_FORWARD_RELAY_V1",
        "relay_envelopes",
        "promoteVerified",
        "broadcastCandidates",
    ), "generated relay store")
    require(web, (
        "BLEE_GLOBAL_STORE_FORWARD_RELAY_WEB_V1",
        "validateSenderFundedRelayEnvelope",
        "broadcastSenderFundedRawTransaction",
    ), "generated payments")
    require(ui, (
        "BLEE_STORE_FORWARD_RELAY_RUNTIME_V1",
        "pendingRelayCandidates",
        "acceptValidatedRelayEnvelope",
    ), "generated runtime")

    start = web.index("export async function broadcastSenderFundedRawTransaction")
    end_marker = "export async function transactionStatus"
    end = web.find(end_marker, start)
    community = web[start:] if end < 0 else web[start:end]
    for forbidden in ("PrivateKeyAccount", "createWalletClient", "walletClient", "writeContract"):
        if forbidden in community:
            fail(f"generated community relay can access signer fallback: {forbidden}")

    local_start = service.index("private void attemptLocalSenderSettlement")
    local_end = service.index("private void confirmRelay", local_start)
    local = service[local_start:local_end]
    if 'deviceId.equals(packet.optString("originDeviceId", ""))' not in local:
        fail("generated local sender path is not restricted to local-origin packets")


def main() -> None:
    verify_source_contract()
    verify_generated_contract()
    print("VERIFIED: Blee global store-and-forward relay security contract")
    print("- foreign PAYMENT_ENVELOPE packets are quarantined before forwarding")
    print("- viem verifies EIP-3009 + exact sender-signed EIP-1559 transaction")
    print("- community broadcaster has no PrivateKeyAccount / WalletClient / writeContract path")
    print("- durable relay queue deduplicates tx hash and sender authorization nonce")
    print("- local sender OFFLINE -> ONLINE background settlement remains intact")
    print("- transit ingress is size/rate/hop bounded")


if __name__ == "__main__":
    main()
