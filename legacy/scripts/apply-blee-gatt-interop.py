#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def locate_activity() -> Path:
    hits = list(ANDROID_JAVA.rglob("MainActivity.java"))
    if len(hits) != 1:
        raise SystemExit(f"Blee GATT interop: expected one MainActivity.java, found {len(hits)}")
    return hits[0]


def once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Blee GATT interop: missing {label} anchor")
    return text.replace(old, new, 1)


def replace_between(text: str, start_marker: str, end_marker: str, replacement: str, label: str) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise SystemExit(f"Blee GATT interop: missing {label} start anchor")
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit(f"Blee GATT interop: missing {label} end anchor")
    return text[:start] + replacement + text[end:]


def patch_service(native_dir: Path) -> None:
    path = native_dir / "BleeMeshService.java"
    text = path.read_text()
    if "BLEE_GATT_INTEROP_V1" in text:
        return
    for marker in (
        "BLEE_BITCHAT_ANDROID_GATT_PARITY_V1",
        "BLEE_GATT_SERVER_READINESS_V1",
        "BLEE_RADIO_ARBITRATION_V2",
    ):
        if marker not in text:
            raise SystemExit(f"Blee GATT interop: prerequisite missing: {marker}")

    fields_anchor = "    private volatile int diagLastServerState = BluetoothProfile.STATE_DISCONNECTED;"
    fields = fields_anchor + r'''
    // BLEE_GATT_INTEROP_V1
    private volatile boolean diagLastScanConnectable = true;
    private volatile int diagLastAddressType = -1;
    private volatile int diagLastDeviceType = -1;
    private volatile long diagGattConnectionCallbacks = 0L;
    private volatile int diagLastNativeGattStatus = -1;
    private volatile int diagLastNativeGattState = -1;
    private volatile String diagLastConnectStrategy = "";
    private final Map<String, Boolean> gattAutoConnectMode = Collections.synchronizedMap(new HashMap<String, Boolean>());'''
    text = once(text, fields_anchor, fields, "interop diagnostic fields")

    # A phone whose controller cannot allocate an advertiser slot cannot be a
    # useful peripheral. Keep it as a pure scanner/central until the advertiser
    # suppression window expires. This frees scarce OEM controller resources.
    text = once(
        text,
        "            startGattServer();",
        "            if (System.currentTimeMillis() >= advertisingSuppressedUntil) startGattServer();",
        "scanner-first GATT-server gate",
    )

    helper_anchor = "    private void maybeConnect(BluetoothDevice device) {"
    helpers = r'''    private void observeGattScanResult(ScanResult result) {
        try {
            if (result == null || result.getDevice() == null) return;
            diagLastScanConnectable = Build.VERSION.SDK_INT < Build.VERSION_CODES.O || result.isConnectable();
            diagLastDeviceType = result.getDevice().getType();
            if (Build.VERSION.SDK_INT >= 35) diagLastAddressType = result.getDevice().getAddressType();
        } catch (Throwable ignored) {}
    }

    private boolean connectImmediatelyFromScan(ScanResult result) {
        if (result == null || result.getDevice() == null || db == null) return false;
        observeGattScanResult(result);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !result.isConnectable()) {
            diagLastPhase = "blee_advertisement_not_connectable";
            diagLastGattError = "Android marked the Blee advertisement non-connectable";
            diagLastError = diagLastGattError;
            return true;
        }

        BluetoothDevice device = result.getDevice();
        String address;
        try { address = device.getAddress(); } catch (Throwable ignored) { return false; }
        long now = System.currentTimeMillis();
        if (!clientGatts.isEmpty() || !bleLinkStates.isEmpty()) return false;
        if (bleLastGlobalConnectAt > 0L && now - bleLastGlobalConnectAt < BLE_CONNECT_RATE_MS) return false;

        long cool = bleCooldownUntil.containsKey(address) ? bleCooldownUntil.get(address) : 0L;
        long settle = bleDisconnectUntil.containsKey(address) ? bleDisconnectUntil.get(address) : 0L;
        if (now < cool || now < settle) return false;

        Long identityAt = peerIdentityAt.get(address);
        boolean needsIdentity = identityAt == null || now - identityAt > 45_000L;
        boolean hasPacket = !db.duePacketsForPeer(now, address, 1).isEmpty();
        if (!needsIdentity && !hasPacket) return true;

        BleCandidate candidate = new BleCandidate(device, address, result.getRssi(), now, needsIdentity, hasPacket);
        Integer remoteToken = peerRoleTokens.get(address);
        // When both phones are healthy dual-role peers and the scan response did
        // not contain the role token, retain the existing randomized scheduler to
        // avoid symmetric central/central racing. Scanner-first phones must not
        // wait: they have no usable peripheral role and should connect immediately.
        if (advertising && remoteToken == null) return false;
        if (!shouldInitiateCandidate(candidate)) return true;

        bleCandidates.remove(address);
        bleLinkStates.put(address, "CONNECTING");
        bleLastGlobalConnectAt = now;
        openGattConnection(candidate);
        return true;
    }

    private void suspendPeripheralForScannerFirst() {
        gattServerReady = false;
        try { if (advertiser != null) advertiser.stopAdvertising(advertiseCallback); } catch (Throwable ignored) {}
        try { if (gattServer != null) gattServer.close(); } catch (Throwable ignored) {}
        gattServer = null;
        advertising = false;
        advertiseStarting = false;
        diagLastPhase = "scanner_first_peripheral_suspended";
    }

'''
    text = once(text, helper_anchor, helpers + helper_anchor, "interop helper insertion")

    advertise_tail = '''        try { if (advertiser != null) advertiser.stopAdvertising(advertiseCallback); } catch (Throwable ignored) {}
    }

    private void resetAdvertiserRecovery()'''
    advertise_tail_new = '''        try { if (advertiser != null) advertiser.stopAdvertising(advertiseCallback); } catch (Throwable ignored) {}
        suspendPeripheralForScannerFirst();
    }

    private void resetAdvertiserRecovery()'''
    text = once(text, advertise_tail, advertise_tail_new, "scanner-first peripheral suspension")

    connect_method = r'''    private BluetoothGatt connectGattReliable(BluetoothDevice device) {
        // BLEE_SAFE_GATT_BOOTSTRAP_1M_V1
        if (device == null) return null;
        String address = "";
        try { address = device.getAddress(); } catch (Throwable ignored) {}
        int failures = bleFailures.containsKey(address) ? bleFailures.get(address) : 0;
        // Direct LE is the first choice and matches Bitchat/Android guidance.
        // If a vendor stack accepts the direct request but never establishes it,
        // retry the next fresh advertisement through Android's background
        // auto-connect path. Alternate thereafter instead of getting stuck in
        // one broken controller strategy forever.
        boolean autoConnect = failures > 0 && (failures % 2 == 1);
        gattAutoConnectMode.put(address, autoConnect);
        diagLastConnectStrategy = autoConnect ? "auto_connect_le" : "direct_le";
        return device.connectGatt(this, autoConnect, clientCallback, BluetoothDevice.TRANSPORT_LE);
    }

'''
    text = replace_between(
        text,
        "    private BluetoothGatt connectGattReliable(BluetoothDevice device) {",
        "    private void pauseScanForGatt() {",
        connect_method,
        "adaptive connectGatt strategy",
    )

    timeout_method = r'''    private void scheduleGattConnectTimeout(final BluetoothGatt gatt, final String address) {
        final boolean autoConnect = Boolean.TRUE.equals(gattAutoConnectMode.get(address));
        final long timeoutMs = autoConnect ? 25_000L : 15_000L;
        handler.postDelayed(() -> {
            if (clientGatts.get(address) != gatt) return;
            if (!"CONNECTING".equals(bleLinkStates.get(address))) return;
            diagLastPhase = "gatt_connect_timeout";
            diagLastGattError = "No Android GATT callback for " + timeoutMs + "ms using " + diagLastConnectStrategy;
            diagLastError = diagLastGattError;
            failGatt(gatt, "GATT connect timeout");
        }, timeoutMs);
    }

'''
    text = replace_between(
        text,
        "    private void scheduleGattConnectTimeout(final BluetoothGatt gatt, final String address) {",
        "    private void handleClientConnectionState(BluetoothGatt gatt, int status, int newState) {",
        timeout_method,
        "GATT connect timeout",
    )

    state_anchor = '''        String address = gatt.getDevice().getAddress();
        BluetoothGatt tracked = clientGatts.get(address);'''
    state_new = '''        String address = gatt.getDevice().getAddress();
        diagGattConnectionCallbacks++;
        diagLastNativeGattStatus = status;
        diagLastNativeGattState = newState;
        BluetoothGatt tracked = clientGatts.get(address);'''
    text = once(text, state_anchor, state_new, "native GATT callback telemetry")

    finish_anchor = "            clientGatts.remove(address); gattProgressAt.remove(address); gattWatchdogDueAt.remove(address); SendState.clear(gatt);"
    finish_new = finish_anchor + "\n            gattAutoConnectMode.remove(address);"
    text = once(text, finish_anchor, finish_new, "GATT strategy cleanup")

    # Connect directly from the live ScanResult before the address-type cache can
    # go stale. This is the important parity fix with Bitchat Android.
    scan_start = text.find("    private final ScanCallback scanCallback = new ScanCallback() {")
    scan_end = text.find("\n    private void pumpKnownPeers() {", scan_start)
    if scan_start < 0 or scan_end < 0:
        raise SystemExit("Blee GATT interop: scan callback boundaries missing")
    scan_block = text[scan_start:scan_end]
    needle = "            maybeConnect(device);"
    if needle not in scan_block:
        raise SystemExit("Blee GATT interop: scan callback maybeConnect anchor missing")
    scan_block = scan_block.replace(needle, "            if (!connectImmediatelyFromScan(result)) maybeConnect(device);", 1)
    text = text[:scan_start] + scan_block + text[scan_end:]

    snapshot_anchor = '            out.put("lastServerState", service.diagLastServerState);'
    snapshot_new = snapshot_anchor + r'''
            out.put("lastScanConnectable", service.diagLastScanConnectable);
            out.put("lastAddressType", service.diagLastAddressType);
            out.put("lastDeviceType", service.diagLastDeviceType);
            out.put("gattConnectionCallbacks", service.diagGattConnectionCallbacks);
            out.put("lastNativeGattStatus", service.diagLastNativeGattStatus);
            out.put("lastNativeGattState", service.diagLastNativeGattState);
            out.put("lastConnectStrategy", service.diagLastConnectStrategy);'''
    text = once(text, snapshot_anchor, snapshot_new, "interop diagnostics snapshot")

    path.write_text(text)


def patch_runtime() -> None:
    path = ROOT / "src/components/BleeRuntime.tsx"
    if not path.is_file():
        raise SystemExit("Blee GATT interop: generated BleeRuntime.tsx missing")
    text = path.read_text()
    if "BLEE_GATT_INTEROP_DIAGNOSTICS_V1" in text:
        return

    diagnosis_old = '''  if (numberValue(d.gattAttempts) === 0) return 'A Blee advertisement was seen. Blee is coordinating which phone should open the GATT link.';
  if (numberValue(d.gattConnected) === 0) {
    const detail = String(d.lastGattError || '').trim();
    return detail
      ? `Blee sees the other phone, but the GATT handshake is retrying (${detail}).`
      : 'Blee sees the other phone, but the GATT handshake has not completed yet.';
  }'''
    diagnosis_new = '''  // BLEE_GATT_INTEROP_DIAGNOSTICS_V1
  if (d.lastScanConnectable === false) return 'Blee sees the other phone, but Android reports its BLE advertisement as non-connectable.';
  if (numberValue(d.gattAttempts) === 0) return 'A Blee advertisement was seen. Blee is coordinating which phone should open the GATT link.';
  if (numberValue(d.gattConnected) === 0) {
    if (numberValue(d.gattConnectionCallbacks) === 0) {
      return `Android accepted the ${String(d.lastConnectStrategy || 'BLE')} connection request but has not returned a GATT callback yet.`;
    }
    const detail = String(d.lastGattError || '').trim();
    return detail
      ? `Blee sees the other phone, but the GATT handshake is retrying (${detail}).`
      : `Android returned GATT status ${String(d.lastNativeGattStatus)} / state ${String(d.lastNativeGattState)}.`;
  }'''
    text = once(text, diagnosis_old, diagnosis_new, "interop diagnosis")

    rows_anchor = "  ['serverConnections', 'Incoming GATT connections'],"
    rows_new = rows_anchor + """
  ['lastScanConnectable', 'Last Blee advertisement connectable'],
  ['lastAddressType', 'Last BLE address type'],
  ['lastDeviceType', 'Last BLE device type'],
  ['lastConnectStrategy', 'GATT connection strategy'],
  ['gattConnectionCallbacks', 'Android GATT callbacks'],
  ['lastNativeGattStatus', 'Last native GATT status'],
  ['lastNativeGattState', 'Last native GATT state'],"""
    text = once(text, rows_anchor, rows_new, "interop diagnostic rows")
    path.write_text(text)


def verify(native_dir: Path) -> None:
    service = (native_dir / "BleeMeshService.java").read_text()
    runtime = (ROOT / "src/components/BleeRuntime.tsx").read_text()
    required = (
        "BLEE_GATT_INTEROP_V1",
        "connectImmediatelyFromScan",
        "result.isConnectable()",
        "getAddressType()",
        "scanner_first_peripheral_suspended",
        "auto_connect_le",
        "direct_le",
        "gattConnectionCallbacks",
        "lastNativeGattStatus",
        "lastConnectStrategy",
    )
    missing = [x for x in required if x not in service]
    if missing:
        raise SystemExit(f"Blee GATT interop verification failed: {missing}")
    scan_start = service.find("private final ScanCallback scanCallback")
    scan_end = service.find("private void pumpKnownPeers", scan_start)
    if scan_start < 0 or scan_end < 0 or "connectImmediatelyFromScan(result)" not in service[scan_start:scan_end]:
        raise SystemExit("Blee GATT interop verification failed: live ScanResult is not the primary connect path")
    if "BLEE_GATT_INTEROP_DIAGNOSTICS_V1" not in runtime:
        raise SystemExit("Blee GATT interop verification failed: UI telemetry missing")
    print("Blee Android GATT interop recovery installed and verified")


def main() -> None:
    native_dir = locate_activity().parent
    patch_service(native_dir)
    patch_runtime()
    verify(native_dir)


if __name__ == "__main__":
    main()
