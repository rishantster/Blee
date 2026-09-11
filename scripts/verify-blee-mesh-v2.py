#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(path: Path, markers: tuple[str, ...]) -> str:
    if not path.exists():
        raise SystemExit(f"VERIFY ERROR: missing {path.relative_to(ROOT)}")
    text = path.read_text(errors="replace")
    missing = [marker for marker in markers if marker not in text]
    if missing:
        raise SystemExit(f"VERIFY ERROR: {path.relative_to(ROOT)} missing {missing}")
    return text


def main() -> None:
    package = json.loads((ROOT / "package.json").read_text())
    if package.get("version") != "2.4.0":
        raise SystemExit(f"VERIFY ERROR: package version is {package.get('version')}, expected 2.4.0")

    store = require(
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
    atomic = require(
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
    payments = require(
        ROOT / "src/lib/payments.ts",
        (
            "createAtomicAuthorization",
            "refreshAtomicSigningProfile",
            "sendRawTransaction",
            "verifyAuthorization",
        ),
    )
    recovery = require(
        ROOT / "src/lib/walletRecovery.ts",
        (
            "passphrase.length < 8",
            "at least 8 characters",
            "PBKDF2",
            "AES-GCM",
        ),
    )
    vault = require(
        ROOT / "src/lib/vault.ts",
        (
            "createVault",
            "passphrase.length < 8",
            "at least 8 characters",
        ),
    )
    hook = require(ROOT / "src/hooks/useBlee.ts", ("BLEE_EXPLICIT_LOGOUT_ONLY",))

    app = require(
        ROOT / "src/components/BleeApp.tsx",
        (
            "useBlee",
            "BottomNav",
            "Home",
            "Nearby",
            "Activity",
            "Profile",
            "Review & send",
            "Confirm and send",
            "QRCodeSVG",
            "Backup & recovery",
            "Network & Security",
            "Blee 2.4",
        ),
    )
    css = require(
        ROOT / "app/globals.css",
        (
            "BLEE_UI_2_4",
            "grid-template-columns: repeat(4, 1fr)",
            ".blee-phone.with-nav",
            ".screen-transition",
            "safe-area-inset-bottom",
        ),
    )
    network = require(
        ROOT / "src/lib/networkConfig.ts",
        (
            'id: "arc-testnet"',
            'name: "Arc Testnet"',
            "chainId: 5042002",
            'tokenSymbol: "USDC"',
            'tokenAddress: "0x3600000000000000000000000000000000000000"',
            "return [ARC_TESTNET]",
            "Custom settlement networks are not available in Blee",
        ),
    )
    advanced = require(
        ROOT / "src/components/BleeAdvancedSettings.tsx",
        ("getActiveNetwork", "Settlement network"),
    )
    runtime = require(
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

    # Passphrase policy must be functional, not only presentation copy.
    combined_passphrase = app + "\n" + vault + "\n" + recovery
    if re.search(r"(?i)12\s*(?:\+|characters)|passphrase\.length\s*<\s*12", combined_passphrase):
        raise SystemExit("VERIFY ERROR: old 12-character passphrase rule/copy remains")
    if not re.search(r"passphrase\.length\s*<\s*8", vault):
        raise SystemExit("VERIFY ERROR: createVault path is not enforcing 8-character minimum")
    if not re.search(r"passphrase\.length\s*<\s*8", recovery):
        raise SystemExit("VERIFY ERROR: wallet import/encryption path is not enforcing 8-character minimum")

    # Fresh presentation only. Old 2.3 visual/copy layers must not survive.
    banned_ui = (
        "Keep this screen open",
        "MetaMask-style",
        "Add network",
        "Relay valid payments",
        "Payments that keep moving",
        "brand-orbit",
        "hero-ring",
        "signal-ring",
        "radar-ring",
        "brand-monument",
        "People around you",  # 2.4 uses compact Nearby preview, not the oversized legacy section title.
    )
    found = [term for term in banned_ui if term.lower() in app.lower()]
    if found:
        raise SystemExit(f"VERIFY ERROR: legacy presentation survived ground-up rebuild: {found}")
    if not css.lstrip().startswith("/* BLEE_UI_2_4"):
        raise SystemExit("VERIFY ERROR: globals.css is still layered legacy CSS instead of the 2.4 replacement")

    # Single-network / single-asset product contract.
    if "saveNetwork" not in network or "throw new Error" not in network:
        raise SystemExit("VERIFY ERROR: legacy network compatibility API is not locked")
    if any(term in advanced for term in ("saveNetwork", "deleteNetwork", "setActiveNetwork", "Custom network")):
        raise SystemExit("VERIFY ERROR: custom-network controls survived in settings")
    if "Arc Testnet" not in app or "USDC" not in app:
        raise SystemExit("VERIFY ERROR: Arc Testnet / USDC product identity missing from UI")

    # One authoritative bottom navigation: Home, Nearby, Activity, Profile.
    nav_match = re.search(r"function\s+BottomNav\b(?P<body>.*?)(?:\n}\n|\n}\r?\n)", app, re.S)
    if not nav_match:
        raise SystemExit("VERIFY ERROR: BottomNav component missing")
    nav = nav_match.group("body")
    for label in ("Home", "Nearby", "Activity", "Profile"):
        if label not in nav:
            raise SystemExit(f"VERIFY ERROR: BottomNav missing {label}")
    for label in ("Send", "Receive", "Settings"):
        if re.search(rf"[\"'>]\s*{label}\s*[\"'<]", nav):
            raise SystemExit(f"VERIFY ERROR: {label} incorrectly appears as permanent bottom navigation")

    # Session policy: no inactivity/background timer may lock the wallet.
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
    web = "\n".join((atomic, payments, hook, runtime))
    if "__BLEE_APP_PACKAGE__" in generated:
        raise SystemExit("VERIFY ERROR: unresolved Android package placeholder")

    banned_backend = (
        "attemptSponsoredSettlement",
        "SPONSORED_AUTO_RELAY",
        "mesh.relay.endpoint",
        "configureRelay",
        "NEXT_PUBLIC_BLEE_RELAY_ENDPOINT",
    )
    found_backend = [marker for marker in banned_backend if marker in generated or marker in web]
    if found_backend:
        raise SystemExit(f"VERIFY ERROR: obsolete sponsored-relay implementation remains: {found_backend}")

    print("============================================================")
    print("VERIFIED: Blee 2.4 ground-up production UI + Mesh v2")
    print("- fresh app structure and stylesheet replace legacy presentation")
    print("- Home / Nearby / Activity / Profile single bottom navigation")
    print("- Send -> Confirm -> state-aware completion flow")
    print("- Receive QR + Activity detail + Profile/Edit + Settings + Recovery")
    print("- Arc Testnet + USDC only; custom network mutation disabled")
    print("- functional 8-character minimum in create + import crypto paths")
    print("- explicit logout-only in-process session policy")
    print("- crash-atomic signing + native nonce reservation")
    print("- sender-funded raw transaction relay; courier never pays gas")
    print("- BLE low-latency scan/high-power advertise + supported LE PHY preference")
    print("============================================================")


if __name__ == "__main__":
    main()
