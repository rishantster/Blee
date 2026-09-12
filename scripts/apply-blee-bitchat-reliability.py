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
    if "BLEE_BITCHAT_STYLE_BLE_RELIABILITY_V1" in text:
        return
    if "BLEE_BLE_TRANSPORT_V4" not in text or "BLEE_BLE_DIAGNOSTICS_V1" not in text:
        raise SystemExit("BLE reliability: transport v4 + diagnostics must run first")
    if not FRAGMENT.is_file():
        raise SystemExit("BLE reliability: Java reliability fragment is missing")

    fragment = FRAGMENT.read_text().rstrip() + "\n\n"
    marker = "    // BLEE_BLE_DIAGNOSTICS_V1\n"
    text = once(text, marker, marker + fragment, "diagnostics")

    # The fragment owns candidate admission now; remove the earlier direct-connect implementation.
    start = text.find("    private void maybeConnect(BluetoothDevice device) {", text.find("BLEE_BLE_DIAGNOSTICS_V1"))
    # First occurrence is our injected method. Find the legacy occurrence after the fragment.
    start = text.find("    private void maybeConnect(BluetoothDevice device) {", start + 1)
    end = text.find("\n    private final BluetoothGattCallback clientCallback", start)
    if start < 0 or end < 0:
        raise SystemExit("BLE reliability: legacy maybeConnect/client callback anchors missing")
    text = text[:start] + text[end:]

    loop = "                if (!scanning || !advertising) startBluetooth();"
    text = once(text, loop, loop + "\n                maintainBleReliability();", "service loop")

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

    stop = "        try { if (gattServer != null) gattServer.close(); } catch (Throwable ignored) {}"
    text = once(text, stop, stop + "\n        resetClientGattConnections();", "stopBluetooth")
    path.write_text(text)


def verify(native_dir):
    text = (native_dir / "BleeMeshService.java").read_text()
    required = (
        "BLEE_BITCHAT_STYLE_BLE_RELIABILITY_V1",
        "BLE_MAX_CLIENT_LINKS = 1",
        "bleCandidateScore",
        "gatt_stall_timeout",
        "scan_watchdog_restart",
        "requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH)",
        "maintainBleReliability();",
        "resetClientGattConnections",
        "touchGatt(gatt)",
    )
    missing = [item for item in required if item not in text]
    if missing:
        raise SystemExit(f"BLE reliability verification failed: {missing}")
    if text.count("private void maybeConnect(BluetoothDevice device)") != 1:
        raise SystemExit("BLE reliability verification failed: maybeConnect is not single-owner")
    print("Blee Bitchat-style BLE reliability installed and verified")


def main():
    native_dir = locate_activity().parent
    patch_service(native_dir)
    verify(native_dir)


if __name__ == "__main__":
    main()
