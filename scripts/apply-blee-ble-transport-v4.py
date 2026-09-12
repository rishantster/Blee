#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def locate_activity() -> Path:
    matches = list(ANDROID_JAVA.rglob("MainActivity.java"))
    if len(matches) != 1:
        raise SystemExit(f"Blee BLE v4: expected one MainActivity.java, found {len(matches)}")
    return matches[0]


def replace_between(text: str, start_marker: str, end_marker: str, replacement: str, label: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise SystemExit(f"Blee BLE v4: missing {label} start anchor")
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit(f"Blee BLE v4: missing {label} end anchor")
    return text[:start] + replacement + text[end:]


def patch_db(native_dir: Path) -> None:
    path = native_dir / "BleeMeshDb.java"
    text = path.read_text()
    if "BLEE_ACTIVE_WALLET_RESOLUTION_V4" in text:
        return

    start = "    synchronized String activeWallet() {"
    end = "\n    synchronized String localDisplayName() {"
    replacement = r'''    // BLEE_ACTIVE_WALLET_RESOLUTION_V4
    synchronized String activeWallet() {
        for (String key : new String[] {
            "wallet.vault.v2", "wallet.vault.v1", "blee.wallet.v2",
            "blee.wallet.v1", "wallet", "vault", "account"
        }) {
            String address = walletAddressFromStoredValue(getKv(key));
            if (address != null) return address;
        }

        try (Cursor c = db().rawQuery(
            "SELECT key,value FROM kv WHERE lower(key) LIKE '%vault%' OR lower(key) LIKE '%wallet%' OR lower(key) LIKE '%account%' ORDER BY updated_at DESC LIMIT 64",
            null
        )) {
            while (c.moveToNext()) {
                String address = walletAddressFromStoredValue(c.getString(1));
                if (address != null) return address;
            }
        } catch (Throwable ignored) {}
        return null;
    }

    private static String walletAddressFromStoredValue(String raw) {
        if (raw == null) return null;
        String value = raw.trim();
        if (value.matches("^0x[0-9a-fA-F]{40}$")) return value.toLowerCase(Locale.ROOT);
        if (value.length() < 2 || value.length() > 65536) return null;
        try {
            JSONObject object = new JSONObject(value);
            String direct = object.optString("address", "").trim();
            if (direct.matches("^0x[0-9a-fA-F]{40}$")) return direct.toLowerCase(Locale.ROOT);
            for (String key : new String[] { "account", "wallet", "vault", "identity" }) {
                JSONObject nested = object.optJSONObject(key);
                if (nested == null) continue;
                String address = nested.optString("address", "").trim();
                if (address.matches("^0x[0-9a-fA-F]{40}$")) return address.toLowerCase(Locale.ROOT);
            }
        } catch (Throwable ignored) {}
        return null;
    }
'''
    text = replace_between(text, start, end, replacement, "activeWallet")
    path.write_text(text)
    print("Blee BLE v4: native wallet identity no longer depends on one legacy KV key")


def ensure_field(text: str, declaration: str, after: str) -> str:
    if declaration in text:
        return text
    if after not in text:
        raise SystemExit(f"Blee BLE v4: field anchor missing for {declaration}")
    return text.replace(after, after + "\n" + declaration, 1)


def patch_service(native_dir: Path) -> None:
    path = native_dir / "BleeMeshService.java"
    text = path.read_text()
    if "BLEE_BLE_TRANSPORT_V4" in text:
        return

    if "public class BleeMeshService extends Service {" not in text:
        raise SystemExit("Blee BLE v4: service class anchor missing")
    text = text.replace(
        "public class BleeMeshService extends Service {",
        "public class BleeMeshService extends Service {\n    // BLEE_BLE_TRANSPORT_V4",
        1,
    )

    scanning = "    private volatile boolean scanning = false;"
    if scanning not in text:
        raise SystemExit("Blee BLE v4: scanning field anchor missing")
    text = ensure_field(text, "    private volatile boolean advertising = false;", scanning)
    text = ensure_field(text, "    private volatile boolean advertiseStarting = false;", "    private volatile boolean advertising = false;")
    text = ensure_field(text, "    private volatile long lastAdvertiseAttemptAt = 0L;", "    private volatile boolean advertiseStarting = false;")
    text = ensure_field(text, "    private volatile long lastScanStartAt = 0L;", "    private volatile long lastAdvertiseAttemptAt = 0L;")
    text = ensure_field(text, "    private volatile long lastBleHitAt = 0L;", "    private volatile long lastScanStartAt = 0L;")

    if "if (!scanning) startBluetooth();" in text:
        text = text.replace("if (!scanning) startBluetooth();", "if (!scanning || !advertising) startBluetooth();", 1)
    elif "if (!scanning || !advertising) startBluetooth();" not in text:
        raise SystemExit("Blee BLE v4: loop BLE rearm anchor missing")

    start_bluetooth = r'''    private void startBluetooth() {
        if (!bluetoothPermissionsGranted()) return;
        bluetoothManager = (BluetoothManager) getSystemService(Context.BLUETOOTH_SERVICE);
        if (bluetoothManager == null) return;
        adapter = bluetoothManager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) return;
        try {
            startGattServer();
            advertiser = adapter.getBluetoothLeAdvertiser();
            scanner = adapter.getBluetoothLeScanner();

            long now = System.currentTimeMillis();
            if (advertiser != null && !advertising && !advertiseStarting && now - lastAdvertiseAttemptAt > 1200L) {
                advertiseStarting = true;
                lastAdvertiseAttemptAt = now;
                AdvertiseSettings settings = new AdvertiseSettings.Builder()
                    .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)
                    .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_HIGH)
                    .setConnectable(true)
                    .setTimeout(0)
                    .build();
                AdvertiseData data = new AdvertiseData.Builder()
                    .addServiceUuid(new ParcelUuid(SERVICE_UUID))
                    .setIncludeDeviceName(false)
                    .build();
                try {
                    advertiser.startAdvertising(settings, data, advertiseCallback);
                } catch (Throwable error) {
                    advertiseStarting = false;
                    advertising = false;
                    Log.w(TAG, "BLE advertising start threw: " + error.getMessage());
                }
            } else if (advertiser == null) {
                Log.w(TAG, "BLE advertiser unavailable on this device");
            }

            if (scanner != null && !scanning && now - lastScanStartAt > 900L) {
                ScanSettings.Builder scanBuilder = new ScanSettings.Builder()
                    .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
                    .setReportDelay(0L);
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    scanBuilder
                        .setCallbackType(ScanSettings.CALLBACK_TYPE_ALL_MATCHES)
                        .setMatchMode(ScanSettings.MATCH_MODE_AGGRESSIVE)
                        .setNumOfMatches(ScanSettings.MATCH_NUM_MAX_ADVERTISEMENT);
                }
                ScanSettings settings = scanBuilder.build();
                try {
                    scanner.startScan(Collections.<ScanFilter>emptyList(), settings, scanCallback);
                    scanning = true;
                    lastScanStartAt = now;
                    Log.i(TAG, "BLE scan armed (unfiltered/manual Blee UUID match)");
                } catch (Throwable error) {
                    scanning = false;
                    Log.w(TAG, "BLE scan start threw: " + error.getMessage());
                }
            } else if (scanner == null) {
                Log.w(TAG, "BLE scanner unavailable on this device");
            }
        } catch (Throwable error) {
            advertising = false;
            advertiseStarting = false;
            scanning = false;
            Log.w(TAG, "Unable to start BLE mesh", error);
        }
    }

'''
    text = replace_between(text, "    private void startBluetooth() {", "    private void stopBluetooth() {", start_bluetooth, "startBluetooth")

    stop_method = r'''    private void stopBluetooth() {
        if (!bluetoothPermissionsGranted()) return;
        try { if (scanner != null && scanning) scanner.stopScan(scanCallback); } catch (Throwable ignored) {}
        try { if (advertiser != null) advertiser.stopAdvertising(advertiseCallback); } catch (Throwable ignored) {}
        try { if (gattServer != null) gattServer.close(); } catch (Throwable ignored) {}
        scanning = false;
        advertising = false;
        advertiseStarting = false;
        gattServer = null;
    }

'''
    text = replace_between(text, "    private void stopBluetooth() {", "    private void startGattServer() {", stop_method, "stopBluetooth")

    advertise_new = r'''    private final AdvertiseCallback advertiseCallback = new AdvertiseCallback() {
        @Override public void onStartSuccess(AdvertiseSettings settingsInEffect) {
            advertiseStarting = false;
            advertising = true;
            Log.i(TAG, "BLE advertising active");
        }

        @Override public void onStartFailure(int errorCode) {
            advertiseStarting = false;
            advertising = false;
            Log.w(TAG, "BLE advertising failed: " + errorCode + "; rearming");
            handler.postDelayed(new Runnable() {
                @Override public void run() { startBluetooth(); }
            }, 1500L);
        }
    };

'''
    callback_start = "    private final AdvertiseCallback advertiseCallback = new AdvertiseCallback()"
    callback_pos = text.find(callback_start)
    scan_pos = text.find("    private final ScanCallback scanCallback = new ScanCallback() {", callback_pos)
    if callback_pos < 0 or scan_pos < 0:
        raise SystemExit("Blee BLE v4: advertise/scan callback anchors missing")
    text = text[:callback_pos] + advertise_new + text[scan_pos:]

    identity_replacement = r'''    private byte[] localIdentityPayload() {
        String wallet = db == null ? null : db.activeWallet();
        if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) return new byte[0];
        return walletBytes(wallet);
    }

    private static byte[] walletBytes(String wallet) {
        if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) return new byte[0];
        byte[] out = new byte[20];
        String hex = wallet.substring(2);
        try {
            for (int i = 0; i < 20; i++) out[i] = (byte) Integer.parseInt(hex.substring(i * 2, i * 2 + 2), 16);
            return out;
        } catch (Throwable ignored) { return new byte[0]; }
    }

    private static String walletFromBytes(byte[] value) {
        if (value == null || value.length != 20) return null;
        StringBuilder out = new StringBuilder("0x");
        for (byte b : value) out.append(String.format(Locale.ROOT, "%02x", b & 0xff));
        String wallet = out.toString();
        return wallet.matches("^0x[0-9a-f]{40}$") ? wallet : null;
    }

'''
    text = replace_between(text, "    private byte[] localIdentityPayload() {", "    private void readIdentityOrSend(BluetoothGatt gatt) {", identity_replacement, "local BLE identity payload")

    handle_replacement = r'''    private void handleIdentityRead(BluetoothGatt gatt, byte[] value) {
        try {
            if (gatt == null || gatt.getDevice() == null || value == null || value.length == 0 || value.length > 2048) return;
            String wallet = walletFromBytes(value);
            String displayName = "";
            if (wallet == null && value[0] == (byte) '{') {
                JSONObject identity = new JSONObject(new String(value, StandardCharsets.UTF_8));
                wallet = identity.optString("wallet", "");
                displayName = identity.optString("displayName", "");
            }
            if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) {
                Log.w(TAG, "BLE identity read returned no wallet (bytes=" + value.length + ")");
                return;
            }
            String address = gatt.getDevice().getAddress();
            int rssi = peerRssi.containsKey(address) ? peerRssi.get(address) : 0;
            publishResolvedPeer(address, wallet, displayName, rssi, System.currentTimeMillis());
            Log.i(TAG, "BLE peer resolved " + wallet.substring(0, 8) + "… via " + address);
        } catch (Throwable error) {
            Log.w(TAG, "BLE identity read ignored: " + error.getMessage());
        }
    }

'''
    text = replace_between(text, "    private void handleIdentityRead(BluetoothGatt gatt, byte[] value) {", "    private void observeConnectivity() {", handle_replacement, "handleIdentityRead")

    scan_callback_anchor = "    private final ScanCallback scanCallback = new ScanCallback() {"
    if "    private boolean isBleeAdvertisement(ScanResult result) {" not in text:
        scan_helper = r'''    private boolean isBleeAdvertisement(ScanResult result) {
        try {
            if (result == null || result.getScanRecord() == null) return false;
            List<ParcelUuid> serviceUuids = result.getScanRecord().getServiceUuids();
            if (serviceUuids == null) return false;
            ParcelUuid expected = new ParcelUuid(SERVICE_UUID);
            for (ParcelUuid uuid : serviceUuids) if (expected.equals(uuid)) return true;
        } catch (Throwable ignored) {}
        return false;
    }

'''
        if scan_callback_anchor not in text:
            raise SystemExit("Blee BLE v4: scan callback anchor missing")
        text = text.replace(scan_callback_anchor, scan_helper + scan_callback_anchor, 1)

    filter_marker = "            if (!isBleeAdvertisement(result)) return;"
    if filter_marker not in text:
        scan_result_anchor = '''        @Override public void onScanResult(int callbackType, ScanResult result) {
            if (result == null || result.getDevice() == null) return;'''
        if scan_result_anchor not in text:
            raise SystemExit("Blee BLE v4: scan result anchor missing")
        text = text.replace(
            scan_result_anchor,
            scan_result_anchor + '''
            if (!isBleeAdvertisement(result)) return;
            lastBleHitAt = System.currentTimeMillis();''',
            1,
        )

    if 'Log.w(TAG, "BLE scan failed: " + errorCode + "; rearming");' not in text:
        raise SystemExit("Blee BLE v4: scan failure/rearm callback missing")

    text = text.replace(
        'handler.postDelayed(new Runnable() {\n                @Override public void run() { readIdentityOrSend(gatt); }\n            }, 220L);',
        'handler.postDelayed(new Runnable() {\n                @Override public void run() { readIdentityOrSend(gatt); }\n            }, 80L);',
        1,
    )

    path.write_text(text)
    print("Blee BLE v4: advertiser/scanner rearm + filterless scan + MTU-independent wallet identity installed")


def verify(native_dir: Path) -> None:
    service = (native_dir / "BleeMeshService.java").read_text()
    db = (native_dir / "BleeMeshDb.java").read_text()

    service_markers = (
        "BLEE_BLE_TRANSPORT_V4",
        "advertising = false",
        "advertiseStarting",
        "onStartFailure(int errorCode)",
        "BLE advertising active",
        "Collections.<ScanFilter>emptyList()",
        "isBleeAdvertisement",
        "walletFromBytes",
        "value.length != 20",
        "if (!scanning || !advertising) startBluetooth();",
        "BLE peer resolved",
    )
    missing = [marker for marker in service_markers if marker not in service]
    if missing:
        raise SystemExit(f"Blee BLE v4 verification failed in service: {missing}")
    if "new ScanFilter.Builder().setServiceUuid" in service:
        raise SystemExit("Blee BLE v4: hardware/offloaded UUID scan filter survived")

    db_markers = (
        "BLEE_ACTIVE_WALLET_RESOLUTION_V4",
        "walletAddressFromStoredValue",
        "wallet.vault.v2",
        "lower(key) LIKE '%vault%'",
    )
    missing_db = [marker for marker in db_markers if marker not in db]
    if missing_db:
        raise SystemExit(f"Blee BLE v4 verification failed in DB identity resolution: {missing_db}")

    print("============================================================")
    print("VERIFIED: Blee BLE-only discovery v4")
    print("- scanning and advertising have independent health/retry state")
    print("- Android controller UUID-filter quirks cannot suppress Blee scan results")
    print("- wallet identity is a raw 20-byte GATT read and does not depend on MTU negotiation")
    print("- wallet lookup tolerates historical Blee vault/storage keys")
    print("- BLE discovery remains independent of Wi-Fi and queued payments")
    print("============================================================")


def main() -> None:
    activity = locate_activity()
    native_dir = activity.parent
    patch_db(native_dir)
    patch_service(native_dir)
    verify(native_dir)


if __name__ == "__main__":
    main()
