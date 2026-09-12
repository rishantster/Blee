#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def locate_activity() -> Path:
    matches = list(ANDROID_JAVA.rglob("MainActivity.java"))
    if len(matches) != 1:
        raise SystemExit(f"Blee BLE diagnostics: expected one MainActivity.java, found {len(matches)}")
    return matches[0]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Blee BLE diagnostics: missing {label} anchor")
    return text.replace(old, new, 1)


def patch_service(native_dir: Path) -> None:
    path = native_dir / "BleeMeshService.java"
    text = path.read_text()
    if "BLEE_BLE_DIAGNOSTICS_V1" in text:
        return
    if "BLEE_BLE_TRANSPORT_V4" not in text:
        raise SystemExit("Blee BLE diagnostics: BLE transport v4 must run first")

    text = replace_once(
        text,
        "    // BLEE_BLE_TRANSPORT_V4",
        '''    // BLEE_BLE_TRANSPORT_V4
    // BLEE_BLE_DIAGNOSTICS_V1
    private static final String ACTION_DIAGNOSTIC_REARM = "__BLEE_DIAGNOSTIC_REARM__";
    private static volatile BleeMeshService INSTANCE = null;
    private volatile long diagScanStarts = 0L;
    private volatile long diagRawScanResults = 0L;
    private volatile long diagBleeAdvertisements = 0L;
    private volatile long diagAdvertiseStarts = 0L;
    private volatile long diagAdvertiseSuccesses = 0L;
    private volatile long diagAdvertiseFailures = 0L;
    private volatile long diagGattAttempts = 0L;
    private volatile long diagGattConnected = 0L;
    private volatile long diagServicesDiscovered = 0L;
    private volatile long diagIdentityReads = 0L;
    private volatile long diagIdentityFailures = 0L;
    private volatile long diagLastSeenAt = 0L;
    private volatile int diagLastRssi = 0;
    private volatile String diagLastTransportId = "";
    private volatile String diagLastWallet = "";
    private volatile String diagLastPhase = "created";
    private volatile String diagLastError = "";''',
        "diagnostics fields",
    )

    start_anchor = "    public static void start(Context context) {"
    diagnostics_methods = r'''    static JSONObject diagnosticsSnapshot(Context context) {
        JSONObject out = new JSONObject();
        try {
            BluetoothManager manager = (BluetoothManager) context.getSystemService(Context.BLUETOOTH_SERVICE);
            BluetoothAdapter localAdapter = manager == null ? null : manager.getAdapter();
            boolean scanPermission = Build.VERSION.SDK_INT < Build.VERSION_CODES.S
                || context.checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) == PackageManager.PERMISSION_GRANTED;
            boolean connectPermission = Build.VERSION.SDK_INT < Build.VERSION_CODES.S
                || context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED;
            boolean advertisePermission = Build.VERSION.SDK_INT < Build.VERSION_CODES.S
                || context.checkSelfPermission(Manifest.permission.BLUETOOTH_ADVERTISE) == PackageManager.PERMISSION_GRANTED;

            out.put("serviceRunning", running);
            out.put("sdk", Build.VERSION.SDK_INT);
            out.put("manufacturer", Build.MANUFACTURER == null ? "" : Build.MANUFACTURER);
            out.put("model", Build.MODEL == null ? "" : Build.MODEL);
            out.put("adapterPresent", localAdapter != null);
            out.put("bluetoothEnabled", localAdapter != null && localAdapter.isEnabled());
            out.put("scanPermission", scanPermission);
            out.put("connectPermission", connectPermission);
            out.put("advertisePermission", advertisePermission);
            out.put("multipleAdvertisementSupported", localAdapter != null && localAdapter.isMultipleAdvertisementSupported());

            BleeMeshService service = INSTANCE;
            if (service == null) {
                out.put("scannerActive", false);
                out.put("advertiserActive", false);
                out.put("advertiserStarting", false);
                out.put("gattServerActive", false);
                out.put("resolvedPeerCount", DISCOVERED_PEERS.size());
                out.put("lastPhase", "service_not_attached");
                return out;
            }

            out.put("scannerAvailable", service.scanner != null);
            out.put("advertiserAvailable", service.advertiser != null);
            out.put("scannerActive", service.scanning);
            out.put("advertiserActive", service.advertising);
            out.put("advertiserStarting", service.advertiseStarting);
            out.put("gattServerActive", service.gattServer != null);
            out.put("scanStarts", service.diagScanStarts);
            out.put("rawScanResults", service.diagRawScanResults);
            out.put("bleeAdvertisements", service.diagBleeAdvertisements);
            out.put("advertiseStarts", service.diagAdvertiseStarts);
            out.put("advertiseSuccesses", service.diagAdvertiseSuccesses);
            out.put("advertiseFailures", service.diagAdvertiseFailures);
            out.put("gattAttempts", service.diagGattAttempts);
            out.put("gattConnected", service.diagGattConnected);
            out.put("servicesDiscovered", service.diagServicesDiscovered);
            out.put("identityReads", service.diagIdentityReads);
            out.put("identityFailures", service.diagIdentityFailures);
            out.put("resolvedPeerCount", DISCOVERED_PEERS.size());
            out.put("lastSeenAt", service.diagLastSeenAt);
            out.put("lastRssi", service.diagLastRssi);
            out.put("lastTransportId", service.diagLastTransportId);
            out.put("lastWallet", service.diagLastWallet);
            out.put("lastPhase", service.diagLastPhase);
            out.put("lastError", service.diagLastError);
            out.put("lastBleHitAt", service.lastBleHitAt);
            out.put("lastScanStartAt", service.lastScanStartAt);
            out.put("lastAdvertiseAttemptAt", service.lastAdvertiseAttemptAt);
            String ownWallet = service.db == null ? null : service.db.activeWallet();
            out.put("localWalletResolved", ownWallet != null && ownWallet.matches("^0x[0-9a-fA-F]{40}$"));
        } catch (Throwable error) {
            try { out.put("snapshotError", error.getMessage() == null ? error.toString() : error.getMessage()); }
            catch (Throwable ignored) {}
        }
        return out;
    }

    static void requestBluetoothRearm(Context context) {
        Intent intent = new Intent(context, BleeMeshService.class);
        intent.setAction(ACTION_DIAGNOSTIC_REARM);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(intent);
        else context.startService(intent);
    }

'''
    text = replace_once(text, start_anchor, diagnostics_methods + start_anchor, "service start method")

    text = replace_once(
        text,
        "        super.onCreate();\n        running = true;",
        "        super.onCreate();\n        INSTANCE = this;\n        diagLastPhase = \"service_created\";\n        running = true;",
        "service onCreate",
    )
    text = replace_once(
        text,
        "        running = false;\n        handler.removeCallbacksAndMessages(null);",
        "        running = false;\n        if (INSTANCE == this) INSTANCE = null;\n        handler.removeCallbacksAndMessages(null);",
        "service onDestroy",
    )

    old_on_start = "    @Override public int onStartCommand(Intent intent, int flags, int startId) { return START_STICKY; }"
    new_on_start = '''    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_DIAGNOSTIC_REARM.equals(intent.getAction())) {
            diagLastPhase = "manual_rearm";
            diagLastError = "";
            stopBluetooth();
            handler.postDelayed(new Runnable() {
                @Override public void run() { startBluetooth(); }
            }, 250L);
        }
        return START_STICKY;
    }'''
    text = replace_once(text, old_on_start, new_on_start, "diagnostic rearm command")

    text = replace_once(
        text,
        "                    advertiser.startAdvertising(settings, data, advertiseCallback);",
        "                    diagAdvertiseStarts++;\n                    diagLastPhase = \"advertise_start_requested\";\n                    advertiser.startAdvertising(settings, data, advertiseCallback);",
        "advertising start",
    )
    text = replace_once(
        text,
        "            advertiseStarting = false;\n            advertising = true;\n            advertiseRetryCount = 0;\n            nextAdvertiseAttemptAt = 0L;\n            Log.i(TAG, \"BLE advertising active\");\n            handler.post(new Runnable() { @Override public void run() { startBluetooth(); } });",
        "            advertiseStarting = false;\n            advertising = true;\n            advertiseRetryCount = 0;\n            nextAdvertiseAttemptAt = 0L;\n            diagAdvertiseSuccesses++;\n            diagLastPhase = \"advertising_active\";\n            diagLastError = \"\";\n            Log.i(TAG, \"BLE advertising active\");\n            handler.post(new Runnable() { @Override public void run() { startBluetooth(); } });",
        "advertising success",
    )
    text = replace_once(
        text,
        "            advertising = false;\n            advertiseRetryCount = Math.min(advertiseRetryCount + 1, 6);\n            Log.w(TAG, \"BLE advertising failed: \" + errorCode + \"; rearming\");",
        "            advertising = false;\n            advertiseRetryCount = Math.min(advertiseRetryCount + 1, 6);\n            diagAdvertiseFailures++;\n            diagLastPhase = \"advertising_failed\";\n            diagLastError = \"advertise_error_\" + errorCode;\n            Log.w(TAG, \"BLE advertising failed: \" + errorCode + \"; rearming\");",
        "advertising failure",
    )
    text = replace_once(
        text,
        "                    scanner.startScan(Collections.<ScanFilter>emptyList(), settings, scanCallback);\n                    scanning = true;",
        "                    diagScanStarts++;\n                    diagLastPhase = \"scan_start_requested\";\n                    scanner.startScan(Collections.<ScanFilter>emptyList(), settings, scanCallback);\n                    scanning = true;",
        "scan start",
    )

    scan_anchor = '''        @Override public void onScanResult(int callbackType, ScanResult result) {
            if (result == null || result.getDevice() == null) return;
            if (!isBleeAdvertisement(result)) return;
            lastBleHitAt = System.currentTimeMillis();'''
    scan_replacement = '''        @Override public void onScanResult(int callbackType, ScanResult result) {
            if (result == null || result.getDevice() == null) return;
            diagRawScanResults++;
            diagLastSeenAt = System.currentTimeMillis();
            diagLastRssi = result.getRssi();
            try { diagLastTransportId = result.getDevice().getAddress(); } catch (Throwable ignored) {}
            diagLastPhase = "scan_result";
            if (!isBleeAdvertisement(result)) return;
            diagBleeAdvertisements++;
            diagLastPhase = "blee_advertisement_seen";
            lastBleHitAt = System.currentTimeMillis();'''
    text = replace_once(text, scan_anchor, scan_replacement, "scan result instrumentation")

    text = replace_once(
        text,
        '            Log.w(TAG, "BLE scan failed: " + errorCode + "; rearming");',
        '            diagLastPhase = "scan_failed";\n            diagLastError = "scan_error_" + errorCode;\n            Log.w(TAG, "BLE scan failed: " + errorCode + "; rearming");',
        "scan failure instrumentation",
    )

    text = replace_once(
        text,
        "        lastConnect.put(address, now);\n        try { device.connectGatt(this, false, clientCallback, BluetoothDevice.TRANSPORT_LE); }",
        "        lastConnect.put(address, now);\n        diagGattAttempts++;\n        diagLastPhase = \"gatt_connect_attempt\";\n        try { device.connectGatt(this, false, clientCallback, BluetoothDevice.TRANSPORT_LE); }",
        "GATT attempt instrumentation",
    )
    text = replace_once(
        text,
        "            if (newState == BluetoothProfile.STATE_CONNECTED) {",
        "            if (newState == BluetoothProfile.STATE_CONNECTED) {\n                diagGattConnected++;\n                diagLastPhase = \"gatt_connected\";\n                diagLastError = \"\";",
        "GATT connected instrumentation",
    )
    text = replace_once(
        text,
        "        @Override public void onServicesDiscovered(final BluetoothGatt gatt, int status) {\n            if (status != BluetoothGatt.GATT_SUCCESS) { closeGatt(gatt); return; }",
        "        @Override public void onServicesDiscovered(final BluetoothGatt gatt, int status) {\n            if (status != BluetoothGatt.GATT_SUCCESS) { diagLastPhase = \"service_discovery_failed\"; diagLastError = \"gatt_service_\" + status; closeGatt(gatt); return; }\n            diagServicesDiscovered++;\n            diagLastPhase = \"blee_service_discovered\";",
        "service discovery instrumentation",
    )

    bad_identity = '''            if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) {
                Log.w(TAG, "BLE identity read returned no wallet (bytes=" + value.length + ")");
                return false;
            }'''
    bad_identity_new = '''            if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) {
                diagIdentityFailures++;
                diagLastPhase = "identity_invalid";
                diagLastError = "identity_bytes_" + value.length;
                Log.w(TAG, "BLE identity read returned no wallet (bytes=" + value.length + ")");
                return false;
            }'''
    text = replace_once(text, bad_identity, bad_identity_new, "identity failure instrumentation")
    text = replace_once(
        text,
        "            publishResolvedPeer(address, wallet, displayName, rssi, System.currentTimeMillis());\n            Log.i(TAG, \"BLE peer resolved \" + wallet.substring(0, 8) + \"… via \" + address);",
        "            publishResolvedPeer(address, wallet, displayName, rssi, System.currentTimeMillis());\n            diagIdentityReads++;\n            diagLastWallet = wallet;\n            diagLastPhase = \"peer_resolved\";\n            diagLastError = \"\";\n            Log.i(TAG, \"BLE peer resolved \" + wallet.substring(0, 8) + \"… via \" + address);",
        "identity success instrumentation",
    )

    path.write_text(text)
    print("Blee BLE diagnostics: native scan/advertise/GATT/identity telemetry installed")


def patch_plugin(native_dir: Path) -> None:
    path = native_dir / "BleeMeshPlugin.java"
    text = path.read_text()
    if "BLEE_BLE_DIAGNOSTICS_PLUGIN_V1" in text:
        return

    anchor = "    @PluginMethod\n    public void nearbyPeers(PluginCall call) {"
    methods = r'''    // BLEE_BLE_DIAGNOSTICS_PLUGIN_V1
    @PluginMethod
    public void diagnostics(PluginCall call) {
        try {
            org.json.JSONObject snapshot = BleeMeshService.diagnosticsSnapshot(getContext());
            JSObject result = new JSObject();
            java.util.Iterator<String> keys = snapshot.keys();
            while (keys.hasNext()) {
                String key = keys.next();
                result.put(key, snapshot.opt(key));
            }
            call.resolve(result);
        } catch (Exception error) {
            call.reject("Unable to read BLE diagnostics", error);
        }
    }

    @PluginMethod
    public void rearmBluetooth(PluginCall call) {
        try {
            BleeMeshService.requestBluetoothRearm(getContext());
            JSObject result = new JSObject();
            result.put("requested", true);
            call.resolve(result);
        } catch (Exception error) {
            call.reject("Unable to restart Bluetooth discovery", error);
        }
    }

'''
    text = replace_once(text, anchor, methods + anchor, "plugin nearbyPeers method")
    path.write_text(text)
    print("Blee BLE diagnostics: Capacitor diagnostics + manual rearm methods installed")


def verify(native_dir: Path) -> None:
    service = (native_dir / "BleeMeshService.java").read_text()
    plugin = (native_dir / "BleeMeshPlugin.java").read_text()
    for marker in (
        "BLEE_BLE_DIAGNOSTICS_V1", "diagnosticsSnapshot", "ACTION_DIAGNOSTIC_REARM",
        "diagRawScanResults", "diagBleeAdvertisements", "diagAdvertiseSuccesses",
        "diagGattAttempts", "diagServicesDiscovered", "diagIdentityReads", "resolvedPeerCount",
    ):
        if marker not in service:
            raise SystemExit(f"Blee BLE diagnostics verification: service missing {marker}")
    for marker in ("BLEE_BLE_DIAGNOSTICS_PLUGIN_V1", "diagnostics(PluginCall", "rearmBluetooth(PluginCall"):
        if marker not in plugin:
            raise SystemExit(f"Blee BLE diagnostics verification: plugin missing {marker}")
    print("============================================================")
    print("VERIFIED: Blee on-device BLE diagnostics")
    print("- permission / adapter / scanner / advertiser state observable")
    print("- scan -> Blee advertisement -> GATT -> service -> identity counters observable")
    print("- last BLE error/phase/RSSI/device/wallet observable")
    print("- manual Bluetooth rearm available without logging out")
    print("============================================================")


def main() -> None:
    activity = locate_activity()
    native_dir = activity.parent
    patch_service(native_dir)
    patch_plugin(native_dir)
    verify(native_dir)


if __name__ == "__main__":
    main()
