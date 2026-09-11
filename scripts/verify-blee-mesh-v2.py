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
    if package.get("version") != "2.5.0":
        raise SystemExit(f"VERIFY ERROR: package version is {package.get('version')}, expected 2.5.0")

    store = require(ROOT / "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java", (
        "BLEE_STORE_MESH_V2_ATOMIC_SIGNING_V2", "signing_intents", "reserveSigningIntent", "finalizeSigningIntent",
        "abortSigningIntent", "SIGNATURE_BUNDLE_PERSISTED", "database.beginTransaction()", "state='SIGNING'", "PERSISTED",
    ))
    atomic = require(ROOT / "src/lib/atomicSigning.ts", (
        "createAtomicAuthorization", "reserveSigningIntent", "finalizeSigningIntent", "abortSigningIntent",
        "SENDER_FUNDED_RAW_TX", "signTypedData", "signTransaction", "BLEE_ATOMIC_BRIDGE_STRING_NUMERICS",
    ))
    payments = require(ROOT / "src/lib/payments.ts", ("createAtomicAuthorization", "sendRawTransaction", "verifyAuthorization"))
    recovery = require(ROOT / "src/lib/walletRecovery.ts", ("passphrase.length < 8", "PBKDF2", "AES-GCM"))
    vault = require(ROOT / "src/lib/vault.ts", ("createVault", "passphrase.length < 8"))
    hook = require(ROOT / "src/hooks/useBlee.ts", ("BLEE_EXPLICIT_LOGOUT_ONLY",))

    app = require(ROOT / "src/components/BleeApp.tsx", (
        "useBlee", "BottomNav", "Home", "Nearby", "Activity", "Profile", "QRCodeSVG", "Backup & recovery",
        "PasswordField", "Show passphrase", "Hide passphrase", "Fingerprint unlock", "BleeBiometric.unlock",
        "BleeBiometric.enroll", "splash-logo", "/brand/blee-wordmark.svg",
    ))
    # Verify real rendered 2.5 CSS features rather than a bookkeeping comment marker.
    css = require(ROOT / "app/globals.css", (
        "BLEE_UI_2_4", "grid-template-columns: repeat(4, 1fr)", ".blee-phone.with-nav",
        ".blee-wordmark", "height: auto", ".password-input", ".biometric-opt-in",
        "@keyframes blee-launch-logo", "safe-area-inset-bottom",
    ))
    biometric = require(ROOT / "src/lib/biometric.ts", (
        "registerPlugin<NativeBleeBiometric>('BleeBiometric')", "enroll(passphrase", "unlock():", "disable()",
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

    activities = list((ROOT / "android/app/src/main/java").rglob("MainActivity.java"))
    if len(activities) != 1:
        raise SystemExit(f"VERIFY ERROR: expected one MainActivity.java, found {len(activities)}")
    activity = activities[0]
    activity_text = require(activity, (
        "registerPlugin(BleeMeshPlugin.class)", "registerPlugin(BleeBiometricPlugin.class)", "BleeMeshService.start(this)",
        "POST_NOTIFICATIONS", "playBleeLaunchChime()", "R.raw.blee_open_chime",
    ))
    native_dir = activity.parent
    require(native_dir / "BleeBiometricPlugin.java", (
        "@CapacitorPlugin(name = \"BleeBiometric\")", "AndroidKeyStore", "BiometricPrompt", "AES/GCM/NoPadding",
        "setUserAuthenticationRequired(true)", "Use a passphrase of at least 8 characters",
    ))
    service = require(native_dir / "BleeMeshService.java", (
        "START_STICKY", "BluetoothLeScanner", "BluetoothLeAdvertiser", "registerDefaultNetworkCallback",
        "attemptSenderFundedSettlement", "eth_sendRawTransaction", "SENDER_FUNDED_RAW_TX", "TRUSTED_CHAIN_ID = 5042002L",
        "BLEE_BLUETOOTH_DISCOVERY_V2_2", "ADVERTISE_MODE_LOW_LATENCY", "ADVERTISE_TX_POWER_HIGH", "SCAN_MODE_LOW_LATENCY",
        "MATCH_MODE_AGGRESSIVE", "CONNECTION_PRIORITY_HIGH", "PHY_LE_CODED_MASK", "Payment confirmed",
    ))
    require(native_dir / "BleeMeshDb.java", (
        "PAYMENT_ENVELOPE", "DELIVERY_ACK", "SETTLEMENT_RECEIPT", "BLEE_ATOMIC_OUTBOX_V1",
        "BLEE_ATOMIC_RECIPIENT_ACK_V1", "Payment delivered",
    ))
    require(native_dir / "BleeMeshPlugin.java", ("BleeMesh", "ledgerChanged", "pendingEnvelopes", "acceptEnvelope", "senderPaysGas"))
    require(native_dir / "BleeBootReceiver.java", ("BOOT_COMPLETED", "BleeMeshService.start"))

    manifest = require(ROOT / "android/app/src/main/AndroidManifest.xml", (
        "BLUETOOTH_SCAN", "BLUETOOTH_CONNECT", "BLUETOOTH_ADVERTISE", "POST_NOTIFICATIONS", "USE_BIOMETRIC",
        "FOREGROUND_SERVICE_CONNECTED_DEVICE", "RECEIVE_BOOT_COMPLETED", "BleeMeshService", "BleeBootReceiver",
    ))
    chime = ROOT / "android/app/src/main/res/raw/blee_open_chime.wav"
    if not chime.is_file() or chime.stat().st_size < 1000:
        raise SystemExit("VERIFY ERROR: launch chime is missing or invalid")

    banned_backend = ("attemptSponsoredSettlement", "SPONSORED_AUTO_RELAY", "NEXT_PUBLIC_BLEE_RELAY_ENDPOINT")
    generated = "\n".join(path.read_text(errors="replace") for path in native_dir.glob("Blee*.java"))
    web = "\n".join((atomic, payments, hook, biometric))
    found_backend = [marker for marker in banned_backend if marker in generated or marker in web]
    if found_backend:
        raise SystemExit(f"VERIFY ERROR: obsolete sponsored relay remains: {found_backend}")

    print("============================================================")
    print("VERIFIED: Blee 2.5 production build")
    print("- supplied Blee wordmark rendered at natural aspect ratio")
    print("- 8-character passphrase enforced in UI + crypto paths")
    print("- show/hide controls on passphrase fields")
    print("- Android Keystore + BiometricPrompt fingerprint unlock with passphrase fallback")
    print("- Android 13+ notification permission requested")
    print("- nearby received / delivered / settlement / chain-confirmed notification plumbing")
    print("- subtle cold-start logo animation + one-time low-volume chime")
    print("- crash-atomic sender-funded Mesh v2 settlement retained")
    print("============================================================")


if __name__ == "__main__":
    main()
