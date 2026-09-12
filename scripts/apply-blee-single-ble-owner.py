#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/blee-nearby/android/src/main/java/com/blee/nearby/BleeNearbyPlugin.java"


def main() -> None:
    text = PLUGIN.read_text()
    marker = "BLEE_MESH_SERVICE_SOLE_BLE_OWNER_V1"
    if marker in text:
        verify(text)
        return

    start = text.find("    @PluginMethod\n    public void startMesh(PluginCall call) {")
    end = text.find("\n    @PluginMethod\n    public void stopMesh", start)
    if start < 0 or end < 0:
        raise SystemExit("Blee single-owner: legacy transport start anchors missing")

    replacement = '''    // BLEE_MESH_SERVICE_SOLE_BLE_OWNER_V1
    // BleeMeshService owns Android BLE scanning, advertising and GATT. This
    // legacy Capacitor transport is LAN-only; starting its second advertiser
    // consumed the phone's only peripheral slot and produced advertise_error_2.
    @PluginMethod
    public void startMesh(PluginCall call) {
        startInternal(call);
    }

    private void startInternal(PluginCall call) {
        if (started) {
            JSObject ret = new JSObject();
            ret.put("started", true);
            ret.put("lan", lanStarted);
            ret.put("ble", false);
            call.resolve(ret);
            return;
        }
        try {
            started = true;
            emitState("starting_lan");
            startLan();

            JSObject ret = new JSObject();
            ret.put("started", true);
            ret.put("lan", lanStarted);
            ret.put("ble", false);
            call.resolve(ret);
            emitState(lanStarted ? "running_lan" : "lan_unavailable");
        } catch (Exception error) {
            started = false;
            stopLan();
            call.reject("Nearby LAN fallback failed to start: " + error.getMessage(), error);
        }
    }
'''
    text = text[:start] + replacement + text[end:]
    PLUGIN.write_text(text)
    verify(text)
    print("Blee transport ownership: Mesh v2 is the sole BLE advertiser; legacy Nearby is LAN-only")


def verify(text: str) -> None:
    start = text.find("// BLEE_MESH_SERVICE_SOLE_BLE_OWNER_V1")
    end = text.find("@PluginMethod\n    public void stopMesh", start)
    section = text[start:end]
    required = ('ret.put("ble", false)', 'startLan()', 'running_lan')
    missing = [value for value in required if value not in section]
    if missing:
        raise SystemExit(f"Blee single-owner verification failed: {missing}")
    forbidden = ("startScanning()", "startServer()", "getBluetoothLeAdvertiser()")
    survived = [value for value in forbidden if value in section]
    if survived:
        raise SystemExit(f"Blee single-owner: legacy BLE startup survived: {survived}")


if __name__ == "__main__":
    main()
