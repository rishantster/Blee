#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"
FRAGMENT = ROOT / "mesh-v2/android/BleeBleReliability.javafrag"


def locate_activity():
    hits = list(ANDROID_JAVA.rglob("MainActivity.java"))
    if len(hits) != 1:
        raise SystemExit(f"BLE reliability: expected one MainActivity.java, found {len(hits)}")
    return hits[0]


def once(text, old, new, label):
    if old not in text:
        raise SystemExit(f"BLE reliability: missing {label} anchor")
    return text.replace(old, new, 1)


def patch_service(native_dir):
    path = native_dir / "BleeMeshService.java"
    text = path.read_text()
    if "BLEE_RADIO_ARBITRATION_V2" in text:
        return
    if "BLEE_BITCHAT_STYLE_BLE_RELIABILITY_V1" in text:
        raise SystemExit("BLE reliability: stale generated Android service; rerun the canonical build from a clean android directory")
    if "BLEE_BLE_TRANSPORT_V4" not in text or "BLEE_BLE_DIAGNOSTICS_V1" not in text:
        raise SystemExit("BLE reliability: transport v4 + diagnostics must run first")
    if not FRAGMENT.is_file():
        raise SystemExit("BLE reliability: Java reliability fragment is missing")

    fragment = FRAGMENT.read_text().rstrip() + "\n\n"
    marker = "    // BLEE_BLE_DIAGNOSTICS_V1\n"
    text = once(text, marker, marker + fragment, "diagnostics")

    text = once(
        text,
        '    private volatile String diagLastGattError = "";\n',
        '''    private volatile String diagLastGattError = "";
    // BLEE_GATT_SERVER_READINESS_V1
    private volatile boolean gattServerReady = false;
    private volatile long diagServerConnections = 0L;
    private volatile String diagLastServerPeer = "";
    private volatile int diagLastServerStatus = 0;
    private volatile int diagLastServerState = BluetoothProfile.STATE_DISCONNECTED;
''',
        "GATT server readiness fields",
    )

    # The fragment owns candidate admission now; remove the earlier direct-connect implementation.
    start = text.find("    private void maybeConnect(BluetoothDevice device) {", text.find("BLEE_BLE_DIAGNOSTICS_V1"))
    start = text.find("    private void maybeConnect(BluetoothDevice device) {", start + 1)
    end = text.find("\n    private final BluetoothGattCallback clientCallback", start)
    if start < 0 or end < 0:
        raise SystemExit("BLE reliability: legacy maybeConnect/client callback anchors missing")
    text = text[:start] + text[end:]

    loop = "                if (!scanning || !advertising) startBluetooth();"
    text = once(text, loop, loop + "\n                maintainBleReliability();", "service loop")

    text = once(
        text,
        "            if (advertiser != null && !advertising && !advertiseStarting && now >= nextAdvertiseAttemptAt) {",
        "            if (advertiser != null && gattServerReady && !advertising && !advertiseStarting && now >= nextAdvertiseAttemptAt && now >= advertisingSuppressedUntil) {",
        "advertiser suppression/readiness gate",
    )

    text = once(
        text,
        "                    advertiser.startAdvertising(settings, data, advertiseCallback);",
        '''                    AdvertiseData scanResponse = new AdvertiseData.Builder()
                        .addServiceData(new ParcelUuid(SERVICE_UUID), localRoleTokenPayload())
                        .build();
                    advertiser.startAdvertising(settings, data, scanResponse, advertiseCallback);''',
        "role-token scan response",
    )

    # Keep scanning alive while a direct GATT connection is being established.
    # The real Bitchat Android client calls connectGatt() directly from a fresh
    # scan result and does not tear the scanner down first. This also lets Blee
    # continue receiving fresh rotating BLE transport addresses while a previous
    # connection attempt is pending.

    success = '''            diagAdvertiseSuccesses++;
            diagLastPhase = "advertising_active";
            diagLastError = "";'''
    text = once(text, success, success + "\n            onAdvertiseStarted();", "advertiser recovery success")

    failure = '''            diagAdvertiseFailures++;
            diagLastPhase = "advertising_failed";
            diagLastError = "advertise_error_" + errorCode;'''
    text = once(text, failure, failure + "\n            onAdvertiseFailed(errorCode);", "advertiser recovery failure")

    scan_seen = '''            diagBleeAdvertisements++;
            diagLastPhase = "blee_advertisement_seen";'''
    text = once(text, scan_seen, scan_seen + "\n            rememberPeerRoleToken(result);", "peer role token")

    # The server object existing is not enough. Android's addService() is
    # asynchronous; only advertise after onServiceAdded(GATT_SUCCESS), exactly
    # like Bitchat's server-first sequencing.
    text = once(
        text,
        "        gattServer = bluetoothManager.openGattServer(this, serverCallback);",
        "        gattServerReady = false;\n        gattServer = bluetoothManager.openGattServer(this, serverCallback);",
        "GATT server open readiness reset",
    )

    snapshot = '            out.put("lastAdvertiseAttemptAt", service.lastAdvertiseAttemptAt);'
    text = once(
        text,
        snapshot,
        snapshot + '''
            out.put("radioMode", service.bleRadioMode());
            out.put("advertiserResourceFailures", service.advertiserResourceFailures);
            out.put("advertisingSuppressedUntil", service.advertisingSuppressedUntil);
            out.put("lastAdvertiseError", service.diagLastAdvertiseError);
            out.put("lastGattError", service.diagLastGattError);
            out.put("gattScanPaused", service.gattScanPaused);
            out.put("gattServerReady", service.gattServerReady);
            out.put("serverConnections", service.diagServerConnections);
            out.put("lastServerPeer", service.diagLastServerPeer);
            out.put("lastServerStatus", service.diagLastServerStatus);
            out.put("lastServerState", service.diagLastServerState);''',
        "radio diagnostics",
    )

    cs = text.find("        @Override public void onConnectionStateChange(BluetoothGatt gatt, int status, int newState) {")
    ce = text.find("\n        @Override public void onServicesDiscovered", cs)
    if cs < 0 or ce < 0:
        raise SystemExit("BLE reliability: connection callback anchor missing")
    callback = '''        @Override public void onConnectionStateChange(final BluetoothGatt gatt, final int status, final int newState) {
            handler.post(() -> handleClientConnectionState(gatt, status, newState));
        }
'''
    text = text[:cs] + callback + text[ce:]

    service_failure = '''            if (status != BluetoothGatt.GATT_SUCCESS) { diagLastPhase = "service_discovery_failed"; diagLastError = "gatt_service_" + status; closeGatt(gatt); return; }'''
    text = once(
        text, service_failure,
        '''            if (status != BluetoothGatt.GATT_SUCCESS) { diagLastPhase = "service_discovery_failed"; diagLastError = "gatt_service_" + status; failGatt(gatt, "service discovery status=" + status); return; }''',
        "service discovery failure backoff",
    )

    progress = '''            diagServicesDiscovered++;
            diagLastPhase = "blee_service_discovered";'''
    text = once(text, progress, progress + "\n            touchGatt(gatt);", "service discovery progress")
    text = once(text,
        '''        @Override public void onCharacteristicRead(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
            boolean identityResolved = false;''',
        '''        @Override public void onCharacteristicRead(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
            touchGatt(gatt);
            boolean identityResolved = false;''', "legacy read")
    text = once(text,
        '''        @Override public void onCharacteristicRead(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, byte[] value, int status) {
            boolean identityResolved = false;''',
        '''        @Override public void onCharacteristicRead(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, byte[] value, int status) {
            touchGatt(gatt);
            boolean identityResolved = false;''', "modern read")
    identity_failure = "            if (identityResolved) writeLocalIdentity(gatt);\n            else closeGatt(gatt);"
    if text.count(identity_failure) < 2:
        raise SystemExit("BLE reliability: identity failure anchors missing")
    text = text.replace(
        identity_failure,
        "            if (identityResolved) writeLocalIdentity(gatt);\n            else failGatt(gatt, \"identity read failed\");",
        2,
    )
    text = once(text,
        '''        @Override public void onMtuChanged(BluetoothGatt gatt, int mtu, int status) {
            if (status == BluetoothGatt.GATT_SUCCESS && mtu >= 23) sendOnePacket(gatt, mtu);''',
        '''        @Override public void onMtuChanged(BluetoothGatt gatt, int mtu, int status) {
            touchGatt(gatt);
            if (status == BluetoothGatt.GATT_SUCCESS && mtu >= 23) sendOnePacket(gatt, mtu);''', "MTU")
    text = once(text,
        '''        @Override public void onCharacteristicWrite(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
            if (characteristic != null && IDENTITY_UUID.equals(characteristic.getUuid())) {''',
        '''        @Override public void onCharacteristicWrite(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
            touchGatt(gatt);
            if (characteristic != null && IDENTITY_UUID.equals(characteristic.getUuid())) {''', "write progress")

    close_start = text.find("    private void closeGatt(BluetoothGatt gatt) {")
    close_end = text.find("\n    private final BluetoothGattServerCallback serverCallback", close_start)
    if close_start < 0 or close_end < 0:
        raise SystemExit("BLE reliability: closeGatt anchor missing")
    text = text[:close_start] + '''    private void closeGatt(BluetoothGatt gatt) {
        finishGatt(gatt, false, "completed");
    }
''' + text[close_end:]

    server_anchor = "    private final BluetoothGattServerCallback serverCallback = new BluetoothGattServerCallback() {"
    server_callbacks = '''    private final BluetoothGattServerCallback serverCallback = new BluetoothGattServerCallback() {
        @Override public void onServiceAdded(final int status, final BluetoothGattService service) {
            handler.post(() -> {
                if (service == null || !SERVICE_UUID.equals(service.getUuid())) return;
                if (status == BluetoothGatt.GATT_SUCCESS && gattServer != null) {
                    gattServerReady = true;
                    diagLastPhase = "gatt_server_ready";
                    diagLastError = "";
                    startBluetooth();
                    return;
                }
                gattServerReady = false;
                diagLastPhase = "gatt_server_service_failed";
                diagLastError = "gatt_server_service_" + status;
                try { if (gattServer != null) gattServer.close(); } catch (Throwable ignored) {}
                gattServer = null;
                handler.postDelayed(() -> startBluetooth(), 1_000L);
            });
        }

        @Override public void onConnectionStateChange(final BluetoothDevice device, final int status, final int newState) {
            handler.post(() -> {
                diagLastServerStatus = status;
                diagLastServerState = newState;
                try { diagLastServerPeer = device == null ? "" : device.getAddress(); } catch (Throwable ignored) { diagLastServerPeer = ""; }
                if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                    diagServerConnections++;
                    diagLastPhase = "gatt_server_connected";
                }
            });
        }'''
    text = once(text, server_anchor, server_callbacks, "GATT server readiness callbacks")

    stop = "        try { if (gattServer != null) gattServer.close(); } catch (Throwable ignored) {}"
    text = once(text, stop, "        gattServerReady = false;\n" + stop + "\n        resetClientGattConnections();", "stopBluetooth")
    reset = "        nextAdvertiseAttemptAt = 0L;"
    text = once(text, reset, reset + "\n        resetAdvertiserRecovery();", "advertiser recovery reset")
    path.write_text(text)


def patch_runtime_diagnostics():
    path = ROOT / "src/components/BleeRuntime.tsx"
    if not path.is_file():
        raise SystemExit("BLE reliability: generated BleeRuntime.tsx is missing")
    text = path.read_text()
    if "BLEE_RADIO_ARBITRATION_DIAGNOSTICS_V2" in text:
        return

    old = '''  if (numberValue(d.advertiseFailures) > 0 && !bool(d.advertiserActive)) {
    return `BLE advertising is failing (${String(d.lastError || 'unknown error')}).`;
  }
  if (!bool(d.advertiserActive)) return 'Blee is not currently advertising over Bluetooth.';
  if (!bool(d.scannerActive)) return 'Blee is not currently scanning over Bluetooth.';
  if (numberValue(d.rawScanResults) === 0) return 'Scanner is active, but this phone has not seen any BLE advertisements yet.';
  if (numberValue(d.bleeAdvertisements) === 0) return 'Bluetooth scanning works, but no Blee advertisement has been detected.';
  if (numberValue(d.gattAttempts) === 0) return 'A Blee advertisement was seen, but a GATT connection was not attempted.';
  if (numberValue(d.gattConnected) === 0) return 'Blee sees the other phone, but the BLE GATT connection is failing.';'''
    new = '''  // BLEE_RADIO_ARBITRATION_DIAGNOSTICS_V2
  const radioMode = String(d.radioMode || '');
  const advertiserSlotBusy = String(d.lastAdvertiseError || '') === 'advertise_error_2'
    || numberValue(d.advertiserResourceFailures) > 0;
  if (!bool(d.scannerActive) && !bool(d.gattScanPaused)) return 'Blee is not currently scanning over Bluetooth.';
  if (numberValue(d.rawScanResults) === 0) return 'Scanner is active, but this phone has not seen any BLE advertisements yet.';
  if (numberValue(d.bleeAdvertisements) === 0) {
    return advertiserSlotBusy && radioMode === 'scanner_first'
      ? 'This phone has no free advertiser slot, so Blee switched to scanner-first mode and is waiting to see the other phone.'
      : 'Bluetooth scanning works, but no Blee advertisement has been detected.';
  }
  if (numberValue(d.gattAttempts) === 0) return 'A Blee advertisement was seen. Blee is coordinating which phone should open the GATT link.';
  if (numberValue(d.gattConnected) === 0) {
    const detail = String(d.lastGattError || '').trim();
    return detail
      ? `Blee sees the other phone, but the GATT handshake is retrying (${detail}).`
      : 'Blee sees the other phone, but the GATT handshake has not completed yet.';
  }'''
    text = once(text, old, new, "runtime diagnostic summary")

    rows = "  ['advertiserActive', 'Advertiser active'],\n  ['gattServerActive', 'GATT server active'],"
    replacement = """  ['advertiserActive', 'Advertiser active'],
  ['radioMode', 'Radio mode'],
  ['advertiserResourceFailures', 'Advertiser slot failures'],
  ['gattScanPaused', 'Scan paused for GATT'],
  ['gattServerActive', 'GATT server active'],
  ['gattServerReady', 'Blee GATT service ready'],
  ['serverConnections', 'Incoming GATT connections'],"""
    text = once(text, rows, replacement, "runtime diagnostic rows")
    errors = "  ['lastPhase', 'Last BLE phase'],\n  ['lastError', 'Last BLE error'],"
    error_replacement = """  ['lastPhase', 'Last BLE phase'],
  ['lastServerPeer', 'Last incoming BLE device'],
  ['lastServerStatus', 'Last incoming GATT status'],
  ['lastServerState', 'Last incoming GATT state'],
  ['lastAdvertiseError', 'Last advertise error'],
  ['lastGattError', 'Last GATT error'],
  ['lastError', 'Last BLE error'],"""
    text = once(text, errors, error_replacement, "runtime diagnostic errors")
    path.write_text(text)


def verify(native_dir):
    text = (native_dir / "BleeMeshService.java").read_text()
    required = (
        "BLEE_BITCHAT_STYLE_BLE_RELIABILITY_V1",
        "BLEE_RADIO_ARBITRATION_V2",
        "BLEE_BITCHAT_ANDROID_GATT_PARITY_V1",
        "BLEE_GATT_SERVER_READINESS_V1",
        "BLEE_SAFE_GATT_BOOTSTRAP_1M_V1",
        "BLE_MAX_CLIENT_LINKS = 1",
        "BLE_CONNECT_FRESHNESS_MS = 4_000L",
        "BLE_GATT_CONNECT_TIMEOUT_MS = 30_000L",
        "bleCandidateScore",
        "localRoleTokenPayload",
        "rememberPeerRoleToken",
        "advertiser_slot_busy_scanner_first",
        "gattServerReady",
        "onServiceAdded",
        "gatt_server_ready",
        "connectGattReliable",
        "device.connectGatt(this, false, clientCallback, BluetoothDevice.TRANSPORT_LE)",
        "scheduleGattConnectTimeout",
        "gatt_connect_timeout",
        "gatt_operation_timeout",
        "scan_watchdog_restart",
        "requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)",
        "maintainBleReliability();",
        "resetClientGattConnections",
        "touchGatt(gatt)",
        "addServiceData(new ParcelUuid(SERVICE_UUID), localRoleTokenPayload())",
    )
    missing = [item for item in required if item not in text]
    if missing:
        raise SystemExit(f"BLE reliability verification failed: {missing}")
    if text.count("private void maybeConnect(BluetoothDevice device)") != 1:
        raise SystemExit("BLE reliability verification failed: maybeConnect is not single-owner")
    if "connectGattWithPreferredPhy" in text:
        raise SystemExit("BLE reliability verification failed: multi-PHY negotiation returned to the initial GATT handshake")

    begin = text[text.index("private void beginGattConnection"):text.index("private void openGattConnection")]
    if "pauseScanForGatt();" in begin or "postDelayed(() -> openGattConnection" in begin:
        raise SystemExit("BLE reliability verification failed: scanner is still stopped/delayed before connectGatt")
    opening = text[text.index("private void openGattConnection"):text.index("private void scheduleGattConnectTimeout")]
    if "touchGatt(gatt)" in opening:
        raise SystemExit("BLE reliability verification failed: operation watchdog starts before STATE_CONNECTED")

    runtime = (ROOT / "src/components/BleeRuntime.tsx").read_text()
    if "BLEE_RADIO_ARBITRATION_DIAGNOSTICS_V2" not in runtime or "lastGattError" not in runtime or "gattServerReady" not in runtime:
        raise SystemExit("BLE reliability verification failed: radio-arbitration diagnostics UI missing")
    print("Blee Bitchat-style Android GATT lifecycle + server readiness installed and verified")


def main():
    native_dir = locate_activity().parent
    patch_service(native_dir)
    patch_runtime_diagnostics()
    verify(native_dir)


if __name__ == "__main__":
    main()
