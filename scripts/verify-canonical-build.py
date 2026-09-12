#!/usr/bin/env python3
from pathlib import Path
import hashlib
import re

ROOT = Path(__file__).resolve().parents[1]


def require_file(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"Missing canonical Blee file: {rel}")
    return path.read_text(errors="replace")


def require_all(rel: str, markers: tuple[str, ...]) -> str:
    text = require_file(rel)
    missing = [m for m in markers if m not in text]
    if missing:
        raise SystemExit(f"Canonical Blee verification failed for {rel}: {missing}")
    return text


build = require_all(
    "build-blee.command",
    (
        "CANONICAL_BLEE_BUILDER_V2",
        'FINAL_APK="$ROOT/dist/Blee.apk"',
        "command -v sdkmanager",
        'if [ "$(uname -s)" != "Darwin" ]',
        "--exclude 'ARCHITECTURE.md'",
        "--exclude 'UI_ARCHITECTURE.md'",
        "--exclude 'scripts/apply-blee-*.py'",
        "--exclude 'scripts/verify-*.py'",
        'apply-blee-original-brand.py',
        'apply-blee-launcher-1.4.py',
        'verify-blee-original-brand.py',
        'apply-blee-final-hardening.py --web',
        'apply-blee-final-hardening.py --android',
        'apply-blee-final-hardening-2.py',
        'apply-blee-runtime-reliability.py',
        'apply-blee-ble-transport-v4.py',
        'apply-blee-ble-diagnostics.py',
        'verify-blee-mesh-v2.py',
        'verify-canonical-build.py',
        'rm -f "$ROOT/dist"/*.apk',
    ),
)

architecture = require_file("ARCHITECTURE.md")
if "dist/Blee.apk" not in architecture:
    raise SystemExit("Canonical architecture does not declare dist/Blee.apk")
if "source-of-truth" not in architecture or "main" not in architecture:
    raise SystemExit("Canonical architecture does not declare main as source of truth")
if not any(
    phrase in architecture
    for phrase in (
        "Phone C never pays A's gas",
        "must never spend its owner's funds",
        "courier only broadcasts",
    )
):
    raise SystemExit("Canonical architecture does not preserve the courier-never-pays invariant")

ui = require_file("UI_ARCHITECTURE.md")
if "Fingerprint unlock is optional" not in ui:
    raise SystemExit("UI contract is missing optional fingerprint unlock")
if "fingerprint hardware" not in ui.lower() or "enrolled" not in ui.lower():
    raise SystemExit("UI contract is missing fingerprint capability gating")
if "dist/Blee.apk" not in ui:
    raise SystemExit("UI contract does not pin the canonical APK name")
if "standalone Blee logo" not in ui or "cold-launch" not in ui:
    raise SystemExit("UI contract does not pin the standalone Blee launch identity")

logo = ROOT / "brand-assets/blee-logo.svg"
if not logo.is_file():
    raise SystemExit("Canonical standalone Blee logo is missing")
logo_hash = hashlib.sha256(logo.read_bytes()).hexdigest()
if logo_hash != "87812e386ba533b4e4dc6ea52c0fda6c60dee996d2428eaa13203a99b7b313e6":
    raise SystemExit(f"Canonical standalone Blee logo changed unexpectedly: {logo_hash}")

require_all(
    "scripts/apply-blee-original-brand.py",
    (
        'LOGO = ROOT / "brand-assets" / "blee-logo.svg"',
        '/brand/blee-logo.svg',
        'splash-logo',
        'BLEE_STANDALONE_LAUNCH_LOGO_V2',
        'animation: blee-launch-logo 680ms',
    ),
)
require_all(
    "scripts/apply-blee-launcher-1.4.py",
    (
        'LOGO_SVG = ROOT / "brand-assets" / "blee-logo.svg"',
        'android:icon="@drawable/blee_launcher"',
        'android:roundIcon="@drawable/blee_launcher"',
    ),
)
require_all(
    "scripts/verify-blee-original-brand.py",
    (
        'source_logo = ROOT / "brand-assets" / "blee-logo.svg"',
        'BLEE_STANDALONE_LAUNCH_LOGO_V2',
        'android:icon="@drawable/blee_launcher"',
        'android:roundIcon="@drawable/blee_launcher"',
        'cold launch uses the supplied standalone Blee logo',
    ),
)
require_all(
    "scripts/apply-blee-2.5-android.py",
    (
        "bleeLaunchChimeLastPlayedAt",
        "public void onStart()",
        "Blee 2.5 Android compile guard: onStart must remain public for Capacitor BridgeActivity",
        "R.raw.blee_open_chime",
        "player.setVolume(0.24f, 0.24f)",
    ),
)
require_all(
    "scripts/apply-blee-final-hardening.py",
    (
        "BLEE_COURIER_NEVER_SIGNS_V1",
        "BLEE_MONOTONIC_PAYMENT_STATE_V1",
        "BLEE_NATIVE_LIFECYCLE_HARDENING_V1",
        "BLEE_CANONICAL_SETTLEMENT_VERIFY_V1",
    ),
)
require_all(
    "scripts/apply-blee-final-hardening-2.py",
    (
        "BLEE_OFFLINE_SETTLEMENT_PROFILE_REQUIRED_V1",
        "BLEE_BACKUP_V1_COMPAT_V1",
        "BLEE_ACK_NON_DESTRUCTIVE_V1",
        "BLEE_MESH_STATE_MACHINE_HARDENING_V2",
        "BLEE_ADVERTISER_RECOVERY_V1",
        "duePacketsForPeer",
        "recordPeerDelivery",
    ),
)
require_all(
    "scripts/apply-blee-runtime-reliability.py",
    (
        "BLEE_NATIVE_DISCOVERY_IDENTITY_V1",
        "BLEE_NATIVE_BLE_DISCOVERY_V3",
        "BLEE_NATIVE_PEER_BRIDGE_V1",
        "BLEE_NATIVE_NEARBY_PEER_MERGE_V1",
        "BLEE_SESSION_BACKGROUND_SAFE_V1",
        "IDENTITY_UUID",
        "nearbyPeers",
        "peerChanged",
        "blee:native-nearby",
    ),
)
require_all(
    "scripts/apply-blee-ble-transport-v4.py",
    (
        "BLEE_BLE_TRANSPORT_V4",
        "BLEE_ACTIVE_WALLET_RESOLUTION_V4",
        "Collections.<ScanFilter>emptyList()",
        "onStartFailure(int errorCode)",
        "ADVERTISE_FAILED_ALREADY_STARTED",
        "ADVERTISE_FAILED_TOO_MANY_ADVERTISERS",
        "advertiseRetryCount",
        "BLE advertising already active",
        "walletFromBytes",
        "identity read completes before any payment MTU negotiation begins",
        "private boolean handleIdentityRead",
        "if (identityResolved) writeLocalIdentity(gatt)",
        "private void writeLocalIdentity(BluetoothGatt gatt)",
        "PROPERTY_READ | BluetoothGattCharacteristic.PROPERTY_WRITE",
        "IDENTITY_UUID.equals(characteristic.getUuid()) && value != null",
        "continueAfterIdentity",
        "onMtuChanged(BluetoothGatt gatt, int mtu, int status)",
        "mtu - 3 - headerBytes",
        "if (!scanning || !advertising) startBluetooth();",
        "BLE peer resolved",
        "Re-attempt identity discovery for remembered scan results",
    ),
)
require_all(
    "scripts/apply-blee-ble-diagnostics.py",
    (
        "BLEE_BLE_DIAGNOSTICS_V1",
        "BLEE_BLE_DIAGNOSTICS_PLUGIN_V1",
        "diagnosticsSnapshot",
        "diagRawScanResults",
        "diagBleeAdvertisements",
        "diagGattAttempts",
        "diagIdentityReads",
        "rearmBluetooth",
    ),
)
runtime = require_all(
    "mesh-v2/web/BleeRuntime.tsx",
    (
        "BLEE_RUNTIME_NO_REMOUNT_V1",
        "nearbyPeers()",
        "peerChanged",
        "blee:native-nearby",
        "diagnostics()",
        "rearmBluetooth()",
        "BLE DIAGNOSTICS",
        "Restart Bluetooth discovery",
        "<BleeApp />",
    ),
)
if "<BleeApp key=" in runtime:
    raise SystemExit("Canonical runtime still force-remounts BleeApp on focus/ledger changes")

for rel in ("build-blee-macos.command", "build-blee-professional.command"):
    path = ROOT / rel
    if not path.exists():
        continue
    text = path.read_text(errors="replace")
    if 'exec bash "$ROOT/build-blee.command"' not in text:
        raise SystemExit(f"Legacy builder still has independent logic: {rel}")

if re.search(r"dist/Blee-[^\s\"']+\.apk", build):
    raise SystemExit("Versioned public APK naming survived in canonical builder")

print("Canonical Blee repository contract verified.")
