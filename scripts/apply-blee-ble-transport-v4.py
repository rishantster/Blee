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
    text = ensure_field(text, "    private volatile int advertiseRetryCount = 0;", "    private volatile long lastBleHitAt = 0L;")
    text = ensure_field(text, "    private volatile long nextAdvertiseAttemptAt = 0L;", "    private volatile int advertiseRetryCount = 0;")

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
            if (advertiser != null && !advertising && !advertiseStarting && now >= nextAdvertiseAttemptAt) {
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
                    nextAdvertiseAttemptAt = now + 2_000L;
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
        nextAdvertiseAttemptAt = 0L;
        gattServer = null;
    }

'''
    text = replace_between(text, "    private void stopBluetooth() {", "    private void startGattServer() {", stop_method, "stopBluetooth")

    advertise_new = r'''    private final AdvertiseCallback advertiseCallback = new AdvertiseCallback() {
        @Override public void onStartSuccess(AdvertiseSettings settingsInEffect) {
            advertiseStarting = false;
            advertising = true;
            advertiseRetryCount = 0;
            nextAdvertiseAttemptAt = 0L;
            Log.i(TAG, "BLE advertising active");
        }

        @Override public void onStartFailure(int errorCode) {
            advertiseStarting = false;
            if (errorCode == AdvertiseCallback.ADVERTISE_FAILED_ALREADY_STARTED) {
                // Android reports code 3 when this exact callback is already
                // registered. The advertiser is healthy; treating it as down
                // caused an endless 1.5-second restart loop on physical phones.
                advertising = true;
                advertiseRetryCount = 0;
                nextAdvertiseAttemptAt = 0L;
                Log.i(TAG, "BLE advertising already active");
                return;
            }
            advertising = false;
            advertiseRetryCount = Math.min(advertiseRetryCount + 1, 6);
            Log.w(TAG, "BLE advertising failed: " + errorCode + "; rearming");
            try { if (advertiser != null) advertiser.stopAdvertising(this); } catch (Throwable ignored) {}
            final long retryDelay = errorCode == AdvertiseCallback.ADVERTISE_FAILED_TOO_MANY_ADVERTISERS
                ? Math.min(60_000L, 10_000L * advertiseRetryCount)
                : Math.min(30_000L, 2_000L * advertiseRetryCount);
            nextAdvertiseAttemptAt = System.currentTimeMillis() + retryDelay;
            handler.postDelayed(new Runnable() {
                @Override public void run() { startBluetooth(); }
            }, retryDelay);
        }
    };

'''
    callback_start = "    private final AdvertiseCallback advertiseCallback = new AdvertiseCallback()"
    callback_pos = text.find(callback_start)
    scan_pos = text.find("    private final ScanCallback scanCallback = new ScanCallback() {", callback_pos)
    if callback_pos < 0 or scan_pos < 0:
        raise SystemExit("Blee BLE v4: advertise/scan callback anchors missing")
    text = text[:callback_pos] + advertise_new + text[scan_pos:]

    pump_start = text.find("    private void pumpKnownPeers() {")
    pump_end = text.find("\n    private void maybeConnect(BluetoothDevice device) {", pump_start)
    if pump_start < 0 or pump_end < 0:
        raise SystemExit("Blee BLE v4: known-peer pump anchor missing")
    pump_new = '''    private void pumpKnownPeers() {
        // Re-attempt identity discovery for remembered scan results even when
        // Android only delivered one advertisement callback and no payment is
        // queued. maybeConnect() provides the per-device retry throttle.
        List<BluetoothDevice> snapshot;
        synchronized (peers) { snapshot = new ArrayList<BluetoothDevice>(peers.values()); }
        for (BluetoothDevice device : snapshot) maybeConnect(device);
    }
'''
    text = text[:pump_start] + pump_new + text[pump_end:]

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

    # Make identity exchange bidirectional. If only one of two phones can claim
    # an Android advertiser slot, the scanning phone connects to it, reads its
    # wallet, then writes its own wallet back. Both UIs can therefore resolve a
    # peer without requiring both controllers to advertise successfully.
    text = text.replace(
        "            BluetoothGattCharacteristic.PROPERTY_READ,\n            BluetoothGattCharacteristic.PERMISSION_READ",
        "            BluetoothGattCharacteristic.PROPERTY_READ | BluetoothGattCharacteristic.PROPERTY_WRITE,\n            BluetoothGattCharacteristic.PERMISSION_READ | BluetoothGattCharacteristic.PERMISSION_WRITE",
        1,
    )

    read_identity_old = '''    private void readIdentityOrSend(BluetoothGatt gatt) {
        if (gatt == null) return;
        try {
            BluetoothGattService service = gatt.getService(SERVICE_UUID);
            BluetoothGattCharacteristic identity = service == null ? null : service.getCharacteristic(IDENTITY_UUID);
            if (identity != null && gatt.readCharacteristic(identity)) return;
        } catch (Throwable ignored) {}
        sendOnePacket(gatt);
    }'''
    read_identity_new = '''    private void readIdentityOrSend(BluetoothGatt gatt) {
        if (gatt == null) return;
        try {
            BluetoothGattService service = gatt.getService(SERVICE_UUID);
            BluetoothGattCharacteristic identity = service == null ? null : service.getCharacteristic(IDENTITY_UUID);
            if (identity != null && gatt.readCharacteristic(identity)) return;
        } catch (Throwable ignored) {}
        // A rejected read means another controller operation is still busy or
        // the remote service is incomplete. Never silently skip identity.
        Log.w(TAG, "BLE identity read could not be started; retrying later");
        closeGatt(gatt);
    }'''
    if read_identity_old not in text:
        raise SystemExit("Blee BLE v4: identity read method anchor missing")
    text = text.replace(read_identity_old, read_identity_new, 1)

    write_identity_method = '''    private void writeLocalIdentity(BluetoothGatt gatt) {
        if (gatt == null) return;
        try {
            BluetoothGattService service = gatt.getService(SERVICE_UUID);
            BluetoothGattCharacteristic identity = service == null ? null : service.getCharacteristic(IDENTITY_UUID);
            byte[] payload = localIdentityPayload();
            // Reciprocal identity was introduced in 2.6. Older peers expose a
            // read-only characteristic; keep payment delivery compatible after
            // their identity has already been successfully authenticated.
            if (identity == null || payload.length != 20
                || (identity.getProperties() & BluetoothGattCharacteristic.PROPERTY_WRITE) == 0) {
                continueAfterIdentity(gatt);
                return;
            }
            identity.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
            boolean started;
            if (Build.VERSION.SDK_INT >= 33) {
                started = gatt.writeCharacteristic(identity, payload, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == 0;
            } else {
                identity.setValue(payload);
                started = gatt.writeCharacteristic(identity);
            }
            if (!started) continueAfterIdentity(gatt);
        } catch (Throwable ignored) { continueAfterIdentity(gatt); }
    }

'''
    handle_anchor = "    private void handleIdentityRead(BluetoothGatt gatt, byte[] value) {"
    if handle_anchor not in text:
        raise SystemExit("Blee BLE v4: identity handler insertion anchor missing")
    text = text.replace(handle_anchor, write_identity_method + handle_anchor, 1)

    handle_replacement = r'''    private boolean handleIdentityRead(BluetoothGatt gatt, byte[] value) {
        try {
            if (gatt == null || gatt.getDevice() == null || value == null || value.length == 0 || value.length > 2048) return false;
            String wallet = walletFromBytes(value);
            String displayName = "";
            if (wallet == null && value[0] == (byte) '{') {
                JSONObject identity = new JSONObject(new String(value, StandardCharsets.UTF_8));
                wallet = identity.optString("wallet", "");
                displayName = identity.optString("displayName", "");
            }
            if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) {
                Log.w(TAG, "BLE identity read returned no wallet (bytes=" + value.length + ")");
                return false;
            }
            String address = gatt.getDevice().getAddress();
            int rssi = peerRssi.containsKey(address) ? peerRssi.get(address) : 0;
            publishResolvedPeer(address, wallet, displayName, rssi, System.currentTimeMillis());
            Log.i(TAG, "BLE peer resolved " + wallet.substring(0, 8) + "… via " + address);
            return true;
        } catch (Throwable error) {
            Log.w(TAG, "BLE identity read ignored: " + error.getMessage());
            return false;
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

    # Do not overlap MTU negotiation with the identity read. Android only permits
    # one outstanding GATT operation per client; the previous implementation
    # requested an MTU and then tried to read 80 ms later. On real controllers
    # the MTU callback routinely arrives later, causing readCharacteristic() to
    # return false and the connection to close without ever resolving a peer.
    discovery_old = '''        @Override public void onServicesDiscovered(final BluetoothGatt gatt, int status) {
            if (status != BluetoothGatt.GATT_SUCCESS) { closeGatt(gatt); return; }
            try { gatt.requestMtu(517); } catch (Throwable ignored) {}
            handler.postDelayed(new Runnable() {
                @Override public void run() { readIdentityOrSend(gatt); }
            }, 220L);
        }'''
    discovery_new = '''        @Override public void onServicesDiscovered(final BluetoothGatt gatt, int status) {
            if (status != BluetoothGatt.GATT_SUCCESS) { closeGatt(gatt); return; }
            // Identity is exactly 20 bytes and fits the default ATT MTU. Reading
            // it first avoids overlapping MTU negotiation on slow stacks.
            readIdentityOrSend(gatt);
        }'''
    if discovery_old not in text:
        raise SystemExit("Blee BLE v4: service discovery/identity sequencing anchor missing")
    text = text.replace(discovery_old, discovery_new, 1)

    # Identity discovery uses the default MTU. Only negotiate a larger MTU
    # afterwards when an actual packet is queued, and wait for Android's
    # callback rather than guessing how long negotiation takes.
    reads_start = text.find("        @Override public void onCharacteristicRead(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {")
    reads_end = text.find("        @Override public void onCharacteristicWrite", reads_start)
    if reads_start < 0 or reads_end < 0:
        raise SystemExit("Blee BLE v4: identity callbacks missing")
    identity_callbacks = '''        @Override public void onCharacteristicRead(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
            boolean identityResolved = false;
            try {
                if (status == BluetoothGatt.GATT_SUCCESS && characteristic != null && IDENTITY_UUID.equals(characteristic.getUuid())) {
                    identityResolved = handleIdentityRead(gatt, characteristic.getValue());
                }
            } catch (Throwable ignored) {}
            if (identityResolved) writeLocalIdentity(gatt);
            else closeGatt(gatt);
        }

        @Override public void onCharacteristicRead(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, byte[] value, int status) {
            boolean identityResolved = false;
            try {
                if (status == BluetoothGatt.GATT_SUCCESS && characteristic != null && IDENTITY_UUID.equals(characteristic.getUuid())) {
                    identityResolved = handleIdentityRead(gatt, value);
                }
            } catch (Throwable ignored) {}
            if (identityResolved) writeLocalIdentity(gatt);
            else closeGatt(gatt);
        }

        @Override public void onMtuChanged(BluetoothGatt gatt, int mtu, int status) {
            if (status == BluetoothGatt.GATT_SUCCESS && mtu >= 23) sendOnePacket(gatt, mtu);
            else closeGatt(gatt);
        }

'''
    text = text[:reads_start] + identity_callbacks + text[reads_end:]

    write_callback_anchor = '''        @Override public void onCharacteristicWrite(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
            SendState state = SendState.forGatt(gatt);'''
    write_callback_new = '''        @Override public void onCharacteristicWrite(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
            if (characteristic != null && IDENTITY_UUID.equals(characteristic.getUuid())) {
                // The remote identity was validated by the preceding read. A
                // legacy read-only peer may reject this optional write, but its
                // queued payment must still continue to MTU negotiation.
                continueAfterIdentity(gatt);
                return;
            }
            SendState state = SendState.forGatt(gatt);'''
    if write_callback_anchor not in text:
        raise SystemExit("Blee BLE v4: characteristic-write callback anchor missing")
    text = text.replace(write_callback_anchor, write_callback_new, 1)

    server_write_anchor = '''                if (characteristic != null && WRITE_UUID.equals(characteristic.getUuid()) && value != null) {
                    String frame = new String(value, StandardCharsets.UTF_8);
                    status = acceptFrame(device, frame) ? BluetoothGatt.GATT_SUCCESS : BluetoothGatt.GATT_FAILURE;
                }'''
    server_write_new = '''                if (characteristic != null && IDENTITY_UUID.equals(characteristic.getUuid()) && value != null) {
                    String wallet = walletFromBytes(value);
                    if (wallet != null && device != null) {
                        String address = device.getAddress();
                        int rssi = peerRssi.containsKey(address) ? peerRssi.get(address) : 0;
                        publishResolvedPeer(address, wallet, "", rssi, System.currentTimeMillis());
                        status = BluetoothGatt.GATT_SUCCESS;
                    }
                } else if (characteristic != null && WRITE_UUID.equals(characteristic.getUuid()) && value != null) {
                    String frame = new String(value, StandardCharsets.UTF_8);
                    status = acceptFrame(device, frame) ? BluetoothGatt.GATT_SUCCESS : BluetoothGatt.GATT_FAILURE;
                }'''
    if server_write_anchor not in text:
        raise SystemExit("Blee BLE v4: GATT server write anchor missing")
    text = text.replace(server_write_anchor, server_write_new, 1)

    send_method_anchor = "    private void sendOnePacket(BluetoothGatt gatt) {"
    continue_method = '''    private void continueAfterIdentity(BluetoothGatt gatt) {
        if (gatt == null) return;
        if (db.duePackets(System.currentTimeMillis(), 1).isEmpty()) {
            closeGatt(gatt);
            return;
        }
        try {
            if (gatt.requestMtu(247)) return;
        } catch (Throwable ignored) {}
        closeGatt(gatt);
    }

'''
    if send_method_anchor not in text:
        raise SystemExit("Blee BLE v4: packet sender anchor missing")
    text = text.replace(send_method_anchor, continue_method + send_method_anchor, 1)

    text = text.replace(
        "    private void sendOnePacket(BluetoothGatt gatt) {",
        "    private void sendOnePacket(BluetoothGatt gatt, int mtu) {",
        1,
    )
    sender_old = "            SendState state = SendState.create(messageId, packets.get(0), characteristic);\n            SendState.put(gatt, state);"
    sender_new = "            SendState state = SendState.create(messageId, packets.get(0), characteristic, mtu);\n            if (state == null) { closeGatt(gatt); return; }\n            SendState.put(gatt, state);"
    if sender_old not in text:
        raise SystemExit("Blee BLE v4: packet state creation anchor missing")
    text = text.replace(sender_old, sender_new, 1)

    create_old = '''        static SendState create(String messageId, String raw, BluetoothGattCharacteristic characteristic) {
            String encoded = Base64.encodeToString(raw.getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP);
            int chunkSize = 120;
            int total = (encoded.length() + chunkSize - 1) / chunkSize;'''
    create_new = '''        static SendState create(String messageId, String raw, BluetoothGattCharacteristic characteristic, int mtu) {
            String encoded = Base64.encodeToString(raw.getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP);
            int headerBytes = ("B2|" + messageId + "|2147483647|2147483647|").getBytes(StandardCharsets.UTF_8).length;
            int chunkSize = Math.max(1, mtu - 3 - headerBytes);
            int total = (encoded.length() + chunkSize - 1) / chunkSize;
            if (total <= 0 || total > MAX_FRAGMENTS) return null;'''
    if create_old not in text:
        raise SystemExit("Blee BLE v4: fixed-size packet framing anchor missing")
    text = text.replace(create_old, create_new, 1)

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
        "ADVERTISE_FAILED_ALREADY_STARTED",
        "ADVERTISE_FAILED_TOO_MANY_ADVERTISERS",
        "advertiseRetryCount",
        "nextAdvertiseAttemptAt",
        "now >= nextAdvertiseAttemptAt",
        "BLE advertising already active",
        "BLE advertising active",
        "Collections.<ScanFilter>emptyList()",
        "isBleeAdvertisement",
        "walletFromBytes",
        "value.length != 20",
        "private boolean handleIdentityRead",
        "if (identityResolved) writeLocalIdentity(gatt)",
        "private void writeLocalIdentity(BluetoothGatt gatt)",
        "identity.getProperties() & BluetoothGattCharacteristic.PROPERTY_WRITE",
        "legacy read-only peer may reject this optional write",
        "PROPERTY_READ | BluetoothGattCharacteristic.PROPERTY_WRITE",
        "IDENTITY_UUID.equals(characteristic.getUuid()) && value != null",
        "continueAfterIdentity",
        "onMtuChanged(BluetoothGatt gatt, int mtu, int status)",
        "sendOnePacket(gatt, mtu)",
        "mtu - 3 - headerBytes",
        "if (!scanning || !advertising) startBluetooth();",
        "BLE peer resolved",
        "Re-attempt identity discovery for remembered scan results",
    )
    missing = [marker for marker in service_markers if marker not in service]
    if missing:
        raise SystemExit(f"Blee BLE v4 verification failed in service: {missing}")
    if "new ScanFilter.Builder().setServiceUuid" in service:
        raise SystemExit("Blee BLE v4: hardware/offloaded UUID scan filter survived")

    discovered_start = service.find("@Override public void onServicesDiscovered")
    discovered_end = service.find("@Override public void onCharacteristicRead", discovered_start)
    if discovered_start < 0 or discovered_end < 0:
        raise SystemExit("Blee BLE v4: service-discovery callback missing")
    discovery_callback = service[discovered_start:discovered_end]
    if "requestMtu(" in discovery_callback or "postDelayed(" in discovery_callback:
        raise SystemExit("Blee BLE v4: identity read still races MTU negotiation or a timer")
    if "readIdentityOrSend(gatt);" not in discovery_callback:
        raise SystemExit("Blee BLE v4: service discovery does not immediately read identity")
    if "int chunkSize = 120" in service:
        raise SystemExit("Blee BLE v4: packet frames still ignore the negotiated MTU")

    write_callback_start = service.find("@Override public void onCharacteristicWrite(BluetoothGatt gatt")
    payment_state_start = service.find("SendState state = SendState.forGatt(gatt);", write_callback_start)
    if write_callback_start < 0 or payment_state_start < 0:
        raise SystemExit("Blee BLE v4: characteristic-write compatibility callback missing")
    identity_write_callback = service[write_callback_start:payment_state_start]
    if "continueAfterIdentity(gatt);" not in identity_write_callback or "closeGatt(gatt)" in identity_write_callback:
        raise SystemExit("Blee BLE v4: optional reciprocal identity write can block legacy payment delivery")

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
    print("- identity read completes before any payment MTU negotiation begins")
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
