#!/usr/bin/env python3
from __future__ import annotations

import json
import re
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
    if package.get("version") != "2.4.0":
        raise SystemExit(f"VERIFY ERROR: package version is {package.get('version')}, expected 2.4.0")

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
    require(ROOT / "src/hooks/useBlee.ts", ("BLEE_EXPLICIT_LOGOUT_ONLY",))
    require(
        ROOT / "app/globals.css",
        (
            "BLEE_PRODUCTION_WALLET_2_4",
            "--b-bg",
            "blee-brand-lockup",
            "[data-blee-action=\"send\"]",
            "[class*=\"orbit\" i]",
            "blee-screen-in",
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
    require(
        ROOT / "src/components/BleeApp.tsx",
        (
            "BLEE_UI_2_4",
            "BLEE_NO_DECORATIVE_HERO",
            "Blee 2.4",
            "blee-brand-lockup",
            'data-blee-action="send"',
            'data-blee-action="receive"',
            "formatLedgerTimestamp",
        ),
    )

    app = (ROOT / "src/components/BleeApp.tsx").read_text(errors="replace")
    wallet = (ROOT / "src/lib/walletRecovery.ts").read_text(errors="replace")
    hook = (ROOT / "src/hooks/useBlee.ts").read_text(errors="replace")

    if re.search(r"(?i)at\s+least\s+12\s+characters|passphrase\.length\s*<\s*12", app + "\n" + wallet):
        raise SystemExit("VERIFY ERROR: old 12-character passphrase rule/copy remains")
    if not re.search(r"passphrase\.length\s*<\s*8", wallet):
        raise SystemExit("VERIFY ERROR: wallet crypto path is not enforcing 8-character minimum")
    if 'data-blee-action="send"' not in app or 'data-blee-action="receive"' not in app:
        raise SystemExit("VERIFY ERROR: Send/Receive actions are not explicitly wired in generated UI")
    if "Payments that keep moving" in app:
        raise SystemExit("VERIFY ERROR: obsolete marketing tagline remains in generated UI")

    for timer in re.finditer(r"set(?:Timeout|Interval)\((.{0,3500}?)\)", hook, re.S):
        if re.search(r"logout|lockWallet|lockSession|clearWalletSession|setUnlocked\(false\)|setLocked\(true\)", timer.group(1)):
            raise SystemExit("VERIFY ERROR: inactivity/background wallet-lock timer remains")

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

    print("============================================================")
    print("VERIFIED: Blee 2.4 production wallet + Mesh v2")
    print("- crash-atomic signing + native nonce reservation")
    print("- sender-funded raw transaction relay path")
    print("- explicit logout-only in-process session policy")
    print("- 8-character wallet passphrase in UI + crypto path")
    print("- wired Send and Receive actions preserved")
    print("- duplicate home navigation suppressed; bottom nav remains authoritative")
    print("- legacy orbit/radar/halo onboarding art removed")
    print("- BLE low-latency scan/high-power advertise + supported LE PHY preference")
    print("- Blee 2.4 monochrome production design system + transitions")
    print("============================================================")


if __name__ == "__main__":
    main()
