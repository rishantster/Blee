#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android/app/src/main/java"


def main_activity() -> Path:
    matches = list(ANDROID.rglob("MainActivity.java"))
    if len(matches) != 1:
        raise SystemExit(f"Blee 2.2: expected one MainActivity.java, found {len(matches)}")
    return matches[0]


def patch_service(activity: Path) -> None:
    path = activity.parent / "BleeMeshService.java"
    text = path.read_text()

    text = text.replace(
        ".setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_BALANCED)",
        ".setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)",
    )
    text = text.replace(
        ".setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_MEDIUM)",
        ".setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_HIGH)",
    )

    old_settings = "ScanSettings settings = new ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_BALANCED).build();"
    new_settings = '''ScanSettings.Builder scanBuilder = new ScanSettings.Builder()
                    .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
                    .setReportDelay(0L);
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    scanBuilder
                        .setCallbackType(ScanSettings.CALLBACK_TYPE_ALL_MATCHES)
                        .setMatchMode(ScanSettings.MATCH_MODE_AGGRESSIVE)
                        .setNumOfMatches(ScanSettings.MATCH_NUM_MAX_ADVERTISEMENT);
                }
                ScanSettings settings = scanBuilder.build();'''
    if old_settings in text:
        text = text.replace(old_settings, new_settings, 1)
    elif "ScanSettings.Builder scanBuilder" not in text:
        raise SystemExit("Blee 2.2: BLE scan settings anchor not found")

    old_scan = '''    private final ScanCallback scanCallback = new ScanCallback() {
        @Override public void onScanResult(int callbackType, ScanResult result) {
            if (result == null || result.getDevice() == null) return;
            BluetoothDevice device = result.getDevice();
            peers.put(device.getAddress(), device);
            maybeConnect(device);
        }
    };'''
    new_scan = '''    private final ScanCallback scanCallback = new ScanCallback() {
        @Override public void onScanResult(int callbackType, ScanResult result) {
            if (result == null || result.getDevice() == null) return;
            BluetoothDevice device = result.getDevice();
            peers.put(device.getAddress(), device);
            maybeConnect(device);
        }

        @Override public void onBatchScanResults(List<ScanResult> results) {
            if (results == null) return;
            for (ScanResult result : results) onScanResult(ScanSettings.CALLBACK_TYPE_ALL_MATCHES, result);
        }

        @Override public void onScanFailed(int errorCode) {
            scanning = false;
            Log.w(TAG, "BLE scan failed: " + errorCode + "; rearming");
            handler.postDelayed(new Runnable() {
                @Override public void run() { startBluetooth(); }
            }, 1200L);
        }
    };'''
    if old_scan in text:
        text = text.replace(old_scan, new_scan, 1)
    elif "BLE scan failed:" not in text:
        raise SystemExit("Blee 2.2: scan callback anchor not found")

    old_connected = '''            if (newState == BluetoothProfile.STATE_CONNECTED) {
                try { gatt.discoverServices(); } catch (Throwable ignored) { closeGatt(gatt); }
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) closeGatt(gatt);'''
    new_connected = '''            if (newState == BluetoothProfile.STATE_CONNECTED) {
                try { gatt.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH); } catch (Throwable ignored) {}
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    try {
                        int phyMask = BluetoothDevice.PHY_LE_1M_MASK | BluetoothDevice.PHY_LE_2M_MASK | BluetoothDevice.PHY_LE_CODED_MASK;
                        gatt.setPreferredPhy(phyMask, phyMask, BluetoothDevice.PHY_OPTION_NO_PREFERRED);
                    } catch (Throwable ignored) {}
                }
                try { gatt.discoverServices(); } catch (Throwable ignored) { closeGatt(gatt); }
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) closeGatt(gatt);'''
    if old_connected in text:
        text = text.replace(old_connected, new_connected, 1)
    elif "PHY_LE_CODED_MASK" not in text:
        raise SystemExit("Blee 2.2: connection-state anchor not found")

    text = text.replace("gatt.requestMtu(247);", "gatt.requestMtu(517);")

    marker = "BLEE_BLUETOOTH_DISCOVERY_V2_2"
    if marker not in text:
        text = text.replace(
            "public class BleeMeshService extends Service {",
            "public class BleeMeshService extends Service {\n    // " + marker,
            1,
        )

    path.write_text(text)
    print("Blee 2.2: BLE low-latency scan/high-power advertise + multi-PHY preference applied")


def verify(activity: Path) -> None:
    service = (activity.parent / "BleeMeshService.java").read_text()
    markers = (
        "BLEE_BLUETOOTH_DISCOVERY_V2_2",
        "ADVERTISE_MODE_LOW_LATENCY",
        "ADVERTISE_TX_POWER_HIGH",
        "SCAN_MODE_LOW_LATENCY",
        "MATCH_MODE_AGGRESSIVE",
        "MATCH_NUM_MAX_ADVERTISEMENT",
        "onScanFailed",
        "CONNECTION_PRIORITY_HIGH",
        "PHY_LE_2M_MASK",
        "PHY_LE_CODED_MASK",
        "requestMtu(517)",
    )
    missing = [marker for marker in markers if marker not in service]
    if missing:
        raise SystemExit(f"Blee 2.2 Bluetooth verification failed: {missing}")
    print("Blee 2.2 Android Bluetooth discovery hardening verified.")


def main() -> None:
    activity = main_activity()
    patch_service(activity)
    verify(activity)


if __name__ == "__main__":
    main()
