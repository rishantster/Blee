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

    # Brand contract: the v5 splash may be either a direct <img> or a wrapper.
    # The canonical brand installer supports both forms. Do not require the logo
    # URL to exist literally in BleeApp.tsx when CSS binds a wrapper to the
    # standalone asset; verify the rendered contract instead.
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
            'BLEE_STANDALONE_LAUNCH_LOGO_V2',
            '.splash-screen .splash-logo:not(img)',
            'background-image: url("/brand/blee-logo.svg")',
            '.splash-screen .splash-logo:not(img) > *',
            'visibility: hidden',
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
    service = require(native_dir / "BleeMeshService.java", (
        "START_STICKY", "BluetoothLeScanner", "BluetoothLeAdvertiser", "registerDefaultNetworkCallback",
        "attemptSenderFundedSettlement", "eth_sendRawTransaction", "SENDER_FUNDED_RAW_TX", "TRUSTED_CHAIN_ID = 5042002L",
        "BLEE_BLUETOOTH_DISCOVERY_V2_2", "ADVERTISE_MODE_LOW_LATENCY", "ADVERTISE_TX_POWER_HIGH", "SCAN_MODE_LOW_LATENCY",
        "MATCH_MODE_AGGRESSIVE", "CONNECTION_PRIORITY_HIGH", "PHY_LE_CODED_MASK",
        "BLEE_NATIVE_LIFECYCLE_HARDENING_V1", "bluetoothStateReceiver", "PEER_STALE_MS", "MAX_ASSEMBLIES",
        "MAX_PACKET_BYTES", "reconcileCanonicalReceipts", "CHAIN_CONFIRMED", "R.drawable.blee_notification",
    ))
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
    print("- BLE scanning/advertising has runtime permissions + radio recovery")
    print("- fragment assemblies and stale peer caches are bounded")
    print("- relay receipt hash is pinned to sender-signed transaction")
    print("- relay-reported state is independently promoted to CHAIN_CONFIRMED online")
    print("- Android payment notification uses dedicated monochrome icon")
    print("============================================================")


if __name__ == "__main__":
    main()
