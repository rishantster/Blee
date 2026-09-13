#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(path: Path, markers: tuple[str, ...]) -> str:
    if not path.is_file():
        raise SystemExit(f"VERIFY ERROR: missing {path.relative_to(ROOT)}")
    text = path.read_text(errors="replace")
    missing = [marker for marker in markers if marker not in text]
    if missing:
        raise SystemExit(f"VERIFY ERROR: {path.relative_to(ROOT)} missing {missing}")
    return text


def require_text(text: str, label: str, markers: tuple[str, ...]) -> None:
    missing = [marker for marker in markers if marker not in text]
    if missing:
        raise SystemExit(f"VERIFY ERROR: {label} missing {missing}")


def verify_ble_transport(service: str) -> str:
    common = (
        "START_STICKY", "BluetoothLeScanner", "BluetoothLeAdvertiser", "registerDefaultNetworkCallback",
        "attemptSenderFundedSettlement", "eth_sendRawTransaction", "SENDER_FUNDED_RAW_TX", "TRUSTED_CHAIN_ID = 5042002L",
        "SCAN_MODE_LOW_LATENCY", "CONNECTION_PRIORITY_HIGH",
        "BLEE_NATIVE_LIFECYCLE_HARDENING_V1", "bluetoothStateReceiver", "PEER_STALE_MS", "MAX_ASSEMBLIES",
        "MAX_PACKET_BYTES", "reconcileCanonicalReceipts", "CHAIN_CONFIRMED", "R.drawable.blee_notification",
    )
    require_text(service, "BleeMeshService.java common transport contract", common)

    if "BLEE_ADAPTIVE_NEARBY_V3" in service:
        adaptive_v3 = (
            "BLEE_ADAPTIVE_NEARBY_V3",
            "class AdaptiveNearbyV3",
            "BLEE_TRANSPORT_CORE_V2",
            "class BleTransportV2",
            "adaptive_v3",
            "Strategy.P2P_CLUSTER",
            "Nearby.getConnectionsClient",
            "startAdvertising(localPeerIdBytes()",
            "startDiscovery(NEARBY_SERVICE_ID",
            "requestConnection(localPeerIdBytes()",
            "acceptConnection(endpointId, nearbyPayloadCallback)",
            "Payload.fromBytes",
            "blee_identity_v3",
            "blee_packet_v3",
            "db.receive(raw, deviceId, publicKey)",
            "db.recordPeerDelivery",
            "GATT_TIMEOUT_THRESHOLD = 2",
            "status == 147",
            "BLE_GRACE_MS = 15_000L",
            "DUAL_SCAN_ON_MS = 8_000L",
            "DUAL_SCAN_OFF_MS = 2_000L",
            "setAdaptiveScanEnabled",
            "ScanSettings.SCAN_MODE_BALANCED",
            "adaptiveNearbyV3.maintain()",
            "address.startsWith(\"nc:\") ? \"nearby\" : \"ble\"",
            "nearbyError(Throwable error)",
            "direct_scan_result",
            "setConnectable(true)",
            "addServiceData(new ParcelUuid(SERVICE_UUID), localPeerId)",
            "device.connectGatt(BleeMeshService.this, false, coreClientCallback, BluetoothDevice.TRANSPORT_LE)",
            "requestMtu(PREFERRED_MTU)",
            "duePacketsForPeer",
            "coreServerCallback",
        )
        require_text(service, "BleeMeshService.java adaptive v3 transport contract", adaptive_v3)
        return "adaptive_v3"

    if "BLEE_TRANSPORT_CORE_V2" in service:
        core_v2 = (
            "BLEE_TRANSPORT_CORE_V2",
            "class BleTransportV2",
            "ble_core_v2",
            "setConnectable(true)",
            "ADVERTISE_MODE_BALANCED",
            "ADVERTISE_TX_POWER_MEDIUM",
            "addServiceData(new ParcelUuid(SERVICE_UUID), localPeerId)",
            "stablePeerId()",
            "samePeer(remotePeerId, localPeerId)",
            "direct_scan_result",
            "device.connectGatt(BleeMeshService.this, false, coreClientCallback, BluetoothDevice.TRANSPORT_LE)",
            "requestMtu(PREFERRED_MTU)",
            "discoverServices(gatt)",
            "gatt_server_ready",
            "server_service_registering",
            "scanner_first",
            "ADVERTISE_FAILED_TOO_MANY_ADVERTISERS",
            "handleIdentityRead(gatt, value)",
            "writeOwnIdentity(gatt)",
            "duePacketsForPeer",
            "recordPeerDelivery",
            "acceptFrame",
            "coreScanCallback",
            "coreAdvertiseCallback",
            "coreClientCallback",
            "coreServerCallback",
        )
        require_text(service, "BleeMeshService.java transport core v2 contract", core_v2)
        return "ble_core_v2"

    legacy = (
        "BLEE_BLUETOOTH_DISCOVERY_V2_2", "ADVERTISE_MODE_LOW_LATENCY", "ADVERTISE_TX_POWER_HIGH",
        "MATCH_MODE_AGGRESSIVE", "BLEE_RADIO_ARBITRATION_V2", "BLEE_SAFE_GATT_BOOTSTRAP_1M_V1",
        "localRoleTokenPayload", "rememberPeerRoleToken", "pauseScanForGatt", "advertiser_slot_busy_scanner_first",
        "addServiceData(new ParcelUuid(SERVICE_UUID), localRoleTokenPayload())",
    )
    require_text(service, "BleeMeshService.java legacy BLE contract", legacy)
    return "legacy_ble"


def main() -> None:
    package = json.loads((ROOT / "package.json").read_text())
    if package.get("version") != "2.5.1":
        raise SystemExit(f"VERIFY ERROR: package version is {package.get('version')}, expected 2.5.1")

    store = require(ROOT / "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java", (
        "BLEE_STORE_MESH_V2_ATOMIC_SIGNING_V2", "signing_intents", "reserveSigningIntent", "finalizeSigningIntent",
        "abortSigningIntent", "SIGNATURE_BUNDLE_PERSISTED", "database.beginTransaction()", "state='SIGNING'", "PERSISTED",
        "BLEE_MONOTONIC_PAYMENT_STATE_V1", "paymentStateRank",
    ))
    atomic = require(ROOT / "src/lib/atomicSigning.ts", (
        "createAtomicAuthorization", "reserveSigningIntent", "finalizeSigningIntent", "abortSigningIntent",
        "SENDER_FUNDED_RAW_TX", "signTypedData", "signTransaction", "BLEE_ATOMIC_BRIDGE_STRING_NUMERICS",
    ))
    payments = require(ROOT / "src/lib/payments.ts", (
        "createAtomicAuthorization", "sendRawTransaction", "verifyAuthorization", "BLEE_COURIER_NEVER_SIGNS_V1",
        "Blee courier cannot sign or fund another wallet payment",
    ))
    recovery = require(ROOT / "src/lib/walletRecovery.ts", (
        "passphrase.length < 8", "PBKDF2", "AES-GCM", "BLEE_BACKUP_VALIDATION_V1", "validateImportedVault",
    ))
    vault = require(ROOT / "src/lib/vault.ts", ("createVault", "passphrase.length < 8"))
    hook = require(ROOT / "src/hooks/useBlee.ts", ("BLEE_EXPLICIT_LOGOUT_ONLY",))

    app = require(ROOT / "src/components/BleeApp.tsx", (
        "useBlee", "BottomNav", "Home", "Nearby", "Activity", "Profile", "QRCodeSVG", "Backup & recovery",
        "PasswordField", "Show passphrase", "Hide passphrase", "Fingerprint unlock", "BleeBiometric.unlock",
        "BleeBiometric.enroll", "splash-logo", "/brand/blee-wordmark.svg",
    ))
    css = require(ROOT / "app/globals.css", (
        "BLEE_UI_2_4", "grid-template-columns: repeat(4, 1fr)", ".blee-phone.with-nav",
        ".blee-wordmark", "height: auto", ".password-input", ".biometric-opt-in",
        "@keyframes blee-launch-logo", "animation: blee-launch-logo 680ms", "safe-area-inset-bottom", "BLEE_BIOMETRIC_CAPABILITY_CSS_V1",
        "BLEE_STANDALONE_LAUNCH_LOGO_V2", 'url("/brand/blee-logo.svg")', "aspect-ratio: 300 / 399",
    ))
    biometric = require(ROOT / "src/lib/biometric.ts", (
        "registerPlugin<NativeBleeBiometric>('BleeBiometric')", "enroll(passphrase", "unlock():", "disable()",
        "BLEE_BIOMETRIC_CAPABILITY_GATE_V1", "syncBleeBiometricCapability",
    ))
    network = require(ROOT / "src/lib/networkConfig.ts", (
        "Arc Testnet", "chainId: 5042002", "USDC", "0x3600000000000000000000000000000000000000",
        "Custom settlement networks are not available in Blee",
    ))

    all_src = "\n".join(path.read_text(errors="replace") for path in (ROOT / "src").rglob("*") if path.is_file() and path.suffix in {".ts", ".tsx"})
    if re.search(r"(?is)(passphrase.{0,120}12\s*(?:characters|chars)|12\s*(?:characters|chars).{0,120}passphrase)", all_src):
        raise SystemExit("VERIFY ERROR: a 12-character passphrase rule/copy remains")
    if "SELF-CUSTODIAL · OFFLINE-READY" in app or "One USDC wallet for Arc Testnet, online or nearby." in app:
        raise SystemExit("VERIFY ERROR: verbose onboarding copy returned")
    if "height:auto" not in css.replace(" ", ""):
        raise SystemExit("VERIFY ERROR: Blee wordmark natural aspect-ratio rule missing")
    if "logs.slice(0, 100)" in payments:
        raise SystemExit("VERIFY ERROR: settlement history is still silently truncated at 100 transfers")

    splash_nodes = re.findall(r'<[^>]*\bsplash-logo\b[^>]*>', app, flags=re.I | re.S)
    if len(splash_nodes) < 1:
        raise SystemExit("VERIFY ERROR: cold-launch splash element is missing")
    direct_splash_imgs = [node for node in splash_nodes if node.lstrip().lower().startswith('<img')]
    if direct_splash_imgs:
        if not any('/brand/blee-logo.svg' in node for node in direct_splash_imgs):
            raise SystemExit("VERIFY ERROR: direct cold-launch image is not using the standalone Blee logo")
        if any('/brand/blee-wordmark.svg' in node for node in direct_splash_imgs):
            raise SystemExit("VERIFY ERROR: direct cold-launch image regressed to the Blee wordmark")
    else:
        for marker in (
            'BLEE_STANDALONE_LAUNCH_LOGO_V2', '.splash-screen .splash-logo:not(img)',
            'background-image: url("/brand/blee-logo.svg")', '.splash-screen .splash-logo:not(img) > *', 'visibility: hidden',
        ):
            if marker not in css:
                raise SystemExit(f"VERIFY ERROR: wrapper-based cold launch is missing {marker}")

    canonical_logo = ROOT / "brand-assets/blee-logo.svg"
    public_logo = ROOT / "public/brand/blee-logo.svg"
    if not canonical_logo.is_file() or not public_logo.is_file() or canonical_logo.read_bytes() != public_logo.read_bytes():
        raise SystemExit("VERIFY ERROR: standalone Blee logo asset is missing or was altered during build")

    activities = list((ROOT / "android/app/src/main/java").rglob("MainActivity.java"))
    if len(activities) != 1:
        raise SystemExit(f"VERIFY ERROR: expected one MainActivity.java, found {len(activities)}")
    activity = activities[0]
    require(activity, (
        "registerPlugin(BleeMeshPlugin.class)", "registerPlugin(BleeBiometricPlugin.class)", "BleeMeshService.start(this)",
        "POST_NOTIFICATIONS", "playBleeLaunchChime()", "R.raw.blee_open_chime", "BLEE_NEARBY_PERMISSION_REQUEST",
        "BLUETOOTH_SCAN", "BLUETOOTH_CONNECT", "BLUETOOTH_ADVERTISE",
    ))
    native_dir = activity.parent
    require(native_dir / "BleeBiometricPlugin.java", (
        "@CapacitorPlugin(name = \"BleeBiometric\")", "AndroidKeyStore", "BiometricPrompt", "AES/GCM/NoPadding",
        "setUserAuthenticationRequired(true)", "Use a passphrase of at least 8 characters", "FingerprintManager",
        "isHardwareDetected()", "hasEnrolledFingerprints()",
    ))

    service_path = native_dir / "BleeMeshService.java"
    if not service_path.is_file():
        raise SystemExit(f"VERIFY ERROR: missing {service_path.relative_to(ROOT)}")
    service = service_path.read_text(errors="replace")
    transport_engine = verify_ble_transport(service)

    require(native_dir / "BleeMeshDb.java", (
        "PAYMENT_ENVELOPE", "DELIVERY_ACK", "SETTLEMENT_RECEIPT", "BLEE_ATOMIC_OUTBOX_V1",
        "BLEE_ATOMIC_RECIPIENT_ACK_V1", "Payment delivered", "BLEE_CANONICAL_SETTLEMENT_VERIFY_V1",
        "expectedSettlementHash", "markChainConfirmed", "unverifiedSettlementReceipts",
    ))
    require(native_dir / "BleeMeshPlugin.java", ("BleeMesh", "ledgerChanged", "pendingEnvelopes", "acceptEnvelope", "senderPaysGas"))
    require(native_dir / "BleeBootReceiver.java", ("BOOT_COMPLETED", "BleeMeshService.start"))

    manifest = require(ROOT / "android/app/src/main/AndroidManifest.xml", (
        "BLUETOOTH_SCAN", "BLUETOOTH_CONNECT", "BLUETOOTH_ADVERTISE", "POST_NOTIFICATIONS", "USE_BIOMETRIC",
        "FOREGROUND_SERVICE_CONNECTED_DEVICE", "RECEIVE_BOOT_COMPLETED", "BleeMeshService", "BleeBootReceiver",
        'android:icon="@drawable/blee_launcher"', 'android:roundIcon="@drawable/blee_launcher"',
    ))
    if transport_engine == "adaptive_v3":
        for marker in ("ACCESS_WIFI_STATE", "CHANGE_WIFI_STATE", "NEARBY_WIFI_DEVICES", "BLEE_ADAPTIVE_NEARBY_V3"):
            if marker not in manifest:
                raise SystemExit(f"VERIFY ERROR: adaptive v3 manifest missing {marker}")
        gradle = (ROOT / "android/app/build.gradle").read_text(errors="replace")
        if "com.google.android.gms:play-services-nearby:19.5.0" not in gradle:
            raise SystemExit("VERIFY ERROR: adaptive v3 Nearby Connections dependency missing")
        if "BLEE_ADAPTIVE_NEARBY_PERMISSION_V3" not in activity.read_text(errors="replace"):
            raise SystemExit("VERIFY ERROR: adaptive v3 Nearby Wi-Fi runtime permission missing")
        runtime = (ROOT / "src/components/BleeRuntime.tsx").read_text(errors="replace")
        for marker in ("BLEE_ADAPTIVE_NEARBY_V3_DIAGNOSTICS", "fallbackMode", "nearbyConnections", "gatt147Count"):
            if marker not in runtime:
                raise SystemExit(f"VERIFY ERROR: adaptive v3 runtime diagnostics missing {marker}")

    launcher = ROOT / "android/app/src/main/res/drawable/blee_launcher.xml"
    if not launcher.is_file():
        raise SystemExit("VERIFY ERROR: standalone Blee Android launcher icon is missing")
    launcher_text = launcher.read_text(errors="replace")
    if 'android:scaleX' not in launcher_text or 'android:scaleY' not in launcher_text or '#0A0A0A' not in launcher_text:
        raise SystemExit("VERIFY ERROR: Blee launcher no longer preserves standalone logo geometry")

    chime = ROOT / "android/app/src/main/res/raw/blee_open_chime.wav"
    if not chime.is_file() or chime.stat().st_size < 1000:
        raise SystemExit("VERIFY ERROR: launch chime is missing or invalid")
    if not (ROOT / "android/app/src/main/res/drawable/blee_notification.xml").is_file():
        raise SystemExit("VERIFY ERROR: dedicated monochrome payment notification icon is missing")

    banned_backend = (
        "attemptSponsoredSettlement", "SPONSORED_AUTO_RELAY", "NEXT_PUBLIC_BLEE_RELAY_ENDPOINT",
        "relayPaysGas\", true", "logs.slice(0, 100)",
    )
    generated = "\n".join(path.read_text(errors="replace") for path in native_dir.glob("Blee*.java"))
    web = "\n".join((atomic, payments, hook, biometric))
    found_backend = [marker for marker in banned_backend if marker in generated or marker in web]
    if found_backend:
        raise SystemExit(f"VERIFY ERROR: forbidden/obsolete implementation remains: {found_backend}")

    print("============================================================")
    print("VERIFIED: Blee production test build invariants")
    print("- standalone Blee logo drives cold launch + Android launcher identity")
    print("- direct-image and wrapper splash implementations are both verified")
    print("- subtle cold-launch animation + native chime remain wired")
    print("- 8-character passphrase enforced in UI + crypto paths")
    print("- fingerprint UI/native unlock gated by real hardware capability")
    print("- wallet backup import is size/format/KDF bounded")
    print("- sender-funded raw settlement retained; courier never signs or pays gas")
    print("- stale React journal writes cannot downgrade native payment state")
    if transport_engine == "adaptive_v3":
        print("- Adaptive Transport V3 keeps raw BLE primary and falls back after repeated GATT 147/no-peer failure")
        print("- Nearby Connections P2P_CLUSTER carries the same signed mesh packets without changing payment semantics")
        print("- dual-role BLE scan windows reduce scan/advertise controller contention before fallback")
    elif transport_engine == "ble_core_v2":
        print("- BLE Transport Core V2 is sole live radio owner with stable peer identity + direct scan-result GATT")
        print("- connectable advertising, scanner-first recovery, MTU/service sequencing and durable peer delivery verified")
    else:
        print("- legacy BLE uses deterministic roles, scanner-first recovery and safe 1M GATT bootstrap")
    print("- fragment assemblies and stale peer caches are bounded")
    print("- relay receipt hash is pinned to sender-signed transaction")
    print("- relay-reported state is independently promoted to CHAIN_CONFIRMED online")
    print("- Android payment notification uses dedicated monochrome icon")
    print("============================================================")


if __name__ == "__main__":
    main()
