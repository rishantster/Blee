#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(path: Path, markers: tuple[str, ...]) -> None:
    if not path.exists():
        raise SystemExit(f"VERIFY ERROR: missing {path.relative_to(ROOT)}")
    text = path.read_text(errors="replace")
    missing = [marker for marker in markers if marker not in text]
    if missing:
        raise SystemExit(f"VERIFY ERROR: {path.relative_to(ROOT)} missing {missing}")


def main() -> None:
    package = json.loads((ROOT / "package.json").read_text())
    if package.get("version") != "2.1.0":
        raise SystemExit(f"VERIFY ERROR: package version is {package.get('version')}, expected 2.1.0")

    require(
        ROOT / "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java",
        (
            "BLEE_STORE_MESH_V2",
            "payment_events",
            "mesh_inbox",
            "mesh_outbox",
            "mesh_seen_packets",
            "courier_envelopes",
            "settlement_jobs",
            "settlement_receipts",
            "setWriteAheadLoggingEnabled(true)",
        ),
    )
    require(
        ROOT / "src/lib/payments.ts",
        (
            "SENDER_FUNDED_RAW_TX",
            "signTransaction",
            "sendRawTransaction",
            "refreshSenderFundedSettlementProfile",
            "profile.nextNonce",
            "txNonce",
            "rawTransaction",
            "maxGasCostNative",
        ),
    )
    require(
        ROOT / "src/components/BleeRuntime.tsx",
        (
            "registerPlugin<MeshPlugin>('BleeMesh')",
            "ledgerChanged",
            "pendingEnvelopes",
            "verifyAuthorization",
            "acceptEnvelope",
            "refreshSenderFundedSettlementProfile",
        ),
    )
    require(ROOT / "src/components/BleeApp.tsx", ("Blee 2.1", "formatLedgerTimestamp"))

    activities = list((ROOT / "android/app/src/main/java").rglob("MainActivity.java"))
    if len(activities) != 1:
        raise SystemExit(f"VERIFY ERROR: expected one MainActivity.java, found {len(activities)}")
    activity = activities[0]
    require(activity, ("registerPlugin(BleeMeshPlugin.class)", "BleeMeshService.start(this)"))

    for name, markers in {
        "BleeDeviceIdentity.java": ("AndroidKeyStore", "SHA256withECDSA"),
        "BleeMeshDb.java": ("PAYMENT_ENVELOPE", "DELIVERY_ACK", "SETTLEMENT_RECEIPT", "pendingEnvelopes", "acceptVerifiedEnvelope"),
        "BleeMeshService.java": (
            "START_STICKY",
            "BluetoothLeScanner",
            "BluetoothLeAdvertiser",
            "registerDefaultNetworkCallback",
            "attemptSenderFundedSettlement",
            "eth_sendRawTransaction",
            "SENDER_FUNDED_RAW_TX",
            "TRUSTED_CHAIN_ID = 5042002L",
            "settlementRetryAfter.put(paymentId, Long.MAX_VALUE)",
        ),
        "BleeMeshPlugin.java": (
            "BleeMesh",
            "ledgerChanged",
            "pendingEnvelopes",
            "acceptEnvelope",
            "broadcastMode",
            "senderPaysGas",
            "relayPaysGas",
        ),
        "BleeBootReceiver.java": ("BOOT_COMPLETED", "BleeMeshService.start"),
    }.items():
        require(activity.parent / name, markers)

    manifest = ROOT / "android/app/src/main/AndroidManifest.xml"
    require(
        manifest,
        (
            "android.permission.BLUETOOTH_SCAN",
            "android.permission.BLUETOOTH_CONNECT",
            "android.permission.BLUETOOTH_ADVERTISE",
            "android.permission.POST_NOTIFICATIONS",
            "android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE",
            "android.permission.RECEIVE_BOOT_COMPLETED",
            "BleeMeshService",
            "BleeBootReceiver",
        ),
    )

    generated = "\n".join(path.read_text(errors="replace") for path in activity.parent.glob("Blee*.java"))
    web = (ROOT / "src/components/BleeRuntime.tsx").read_text(errors="replace") + "\n" + (ROOT / "src/lib/payments.ts").read_text(errors="replace")
    if "__BLEE_APP_PACKAGE__" in generated:
        raise SystemExit("VERIFY ERROR: unresolved Android package placeholder")

    banned = (
        "attemptSponsoredSettlement",
        "SPONSORED_AUTO_RELAY",
        "mesh.relay.endpoint",
        "configureRelay",
        "NEXT_PUBLIC_BLEE_RELAY_ENDPOINT",
    )
    found = [marker for marker in banned if marker in generated or marker in web]
    if found:
        raise SystemExit(f"VERIFY ERROR: obsolete sponsored-relay implementation remains: {found}")

    print("============================================================")
    print("VERIFIED: Blee 2.1 Mesh v2 source wiring")
    print("- SQLite/WAL immutable event ledger + durable mesh queues")
    print("- Native foreground BLE mesh service + reboot recovery")
    print("- Persistent dedup + bounded store-and-forward courier path")
    print("- Offline notification + viem-verified financial acceptance")
    print("- Crash-safe local EOA nonce reservation")
    print("- Sender-funded EIP-1559 raw transaction prepared by Phone A")
    print("- Any online mesh phone can broadcast; relay phone pays zero gas")
    print("- Arc receipt is gossiped back through the BLE mesh")
    print("============================================================")


if __name__ == "__main__":
    main()
