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
    if package.get("version") != "2.2.0":
        raise SystemExit(f"VERIFY ERROR: package version is {package.get('version')}, expected 2.2.0")

    require(
        ROOT / "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java",
        (
            "BLEE_STORE_MESH_V2_ATOMIC_SIGNING_V2",
            "readLong(PluginCall call, String key)",
            "signing_intents",
            "reserveSigningIntent",
            "finalizeSigningIntent",
            "abortSigningIntent",
            "SIGNATURE_BUNDLE_PERSISTED",
            "database.beginTransaction()",
            "state='SIGNING'",
            "PERSISTED",
            "setWriteAheadLoggingEnabled(true)",
        ),
    )
    require(
        ROOT / "src/lib/atomicSigning.ts",
        (
            "createAtomicAuthorization",
            "refreshAtomicSigningProfile",
            "reserveSigningIntent",
            "finalizeSigningIntent",
            "abortSigningIntent",
            "SIGNING_SESSION_ID",
            "SENDER_FUNDED_RAW_TX",
            "bundleHash",
            "signTypedData",
            "signTransaction",
            "BLEE_ATOMIC_BRIDGE_STRING_NUMERICS",
            "chainId: String(arcTestnet.id)",
        ),
    )
    require(
        ROOT / "src/lib/payments.ts",
        (
            "createAtomicAuthorization",
            "refreshAtomicSigningProfile",
            "sendRawTransaction",
            "verifyAuthorization",
        ),
    )
    require(
        ROOT / "src/lib/walletRecovery.ts",
        (
            "passphrase.length < 8",
            "at least 8 characters",
        ),
    )
    require(ROOT / "src/hooks/useBlee.ts", ("BLEE_PERSISTENT_SESSION",))
    require(ROOT / "app/globals.css", ("BLEE_PREMIUM_MONOCHROME_2_2", "--blee-bg", "premium monochrome"))
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
    require(ROOT / "src/components/BleeApp.tsx", ("Blee 2.2", "formatLedgerTimestamp"))

    activities = list((ROOT / "android/app/src/main/java").rglob("MainActivity.java"))
    if len(activities) != 1:
        raise SystemExit(f"VERIFY ERROR: expected one MainActivity.java, found {len(activities)}")
    activity = activities[0]
    require(activity, ("registerPlugin(BleeMeshPlugin.class)", "BleeMeshService.start(this)"))

    for name, markers in {
        "BleeDeviceIdentity.java": ("AndroidKeyStore", "SHA256withECDSA"),
        "BleeMeshDb.java": (
            "PAYMENT_ENVELOPE",
            "DELIVERY_ACK",
            "SETTLEMENT_RECEIPT",
            "pendingEnvelopes",
            "acceptVerifiedEnvelope",
        ),
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
            "BLEE_BLUETOOTH_DISCOVERY_V2_2",
            "ADVERTISE_MODE_LOW_LATENCY",
            "ADVERTISE_TX_POWER_HIGH",
            "SCAN_MODE_LOW_LATENCY",
            "MATCH_MODE_AGGRESSIVE",
            "onScanFailed",
            "CONNECTION_PRIORITY_HIGH",
            "PHY_LE_CODED_MASK",
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
    web = "\n".join(
        (ROOT / rel).read_text(errors="replace")
        for rel in (
            "src/components/BleeRuntime.tsx",
            "src/lib/payments.ts",
            "src/lib/atomicSigning.ts",
            "src/hooks/useBlee.ts",
        )
    )
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

    wallet = (ROOT / "src/lib/walletRecovery.ts").read_text(errors="replace")
    if "passphrase.length < 12" in wallet or "at least 12 characters" in wallet:
        raise SystemExit("VERIFY ERROR: old 12-character wallet passphrase rule remains")

    print("============================================================")
    print("VERIFIED: Blee 2.2 Mesh v2 source wiring")
    print("- SQLite/WAL immutable event ledger + durable mesh queues")
    print("- DB-backed authorization + EOA nonce reservation before signing")
    print("- Capacitor numeric bridge hardened for chainId/expiry/nonce")
    print("- Exact authorization/raw-tx bundle committed before caller receives it")
    print("- Sender-funded raw transaction can be broadcast by any online mesh phone")
    print("- Persistent in-process session policy; explicit logout remains authoritative")
    print("- 8-character minimum wallet passphrase")
    print("- BLE low-latency scan/high-power advertise + all supported LE PHY preference")
    print("- Premium monochrome UI design system + centered brand treatment")
    print("============================================================")


if __name__ == "__main__":
    main()
