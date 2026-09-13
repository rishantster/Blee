package com.blee.nearby;

import android.Manifest;
import android.bluetooth.*;
import android.bluetooth.le.*;
import android.content.Context;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelUuid;
import android.util.Base64;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.io.ByteArrayOutputStream;
import java.net.DatagramPacket;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.MulticastSocket;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.Collections;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

@CapacitorPlugin(
    name = "BleeNearby",
    permissions = {
        @Permission(alias = "bluetooth", strings = {
            Manifest.permission.BLUETOOTH_SCAN,
            Manifest.permission.BLUETOOTH_CONNECT,
            Manifest.permission.BLUETOOTH_ADVERTISE
        }),
        @Permission(alias = "locationLegacy", strings = { Manifest.permission.ACCESS_FINE_LOCATION })
    }
)
public class BleeNearbyPlugin extends Plugin {
    private static final UUID SERVICE_UUID = UUID.fromString("a7c00001-6d3b-4c4e-9c6e-2e73b6c5d001");
    private static final UUID CHAR_UUID = UUID.fromString("a7c00002-6d3b-4c4e-9c6e-2e73b6c5d001");
    private static final UUID CCCD_UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");

    private static final int LAN_PORT = 42424;
    private static final String LAN_GROUP = "239.255.77.77";
    private static final long LAN_STALE_MS = 12_000L;

    private static final byte MAGIC_A = 0x41;
    private static final byte MAGIC_D = 0x44;
    private static final byte MAGIC_B = 0x42;
    private static final int BLE_HEADER = 7;

    private BluetoothManager manager;
    private BluetoothAdapter adapter;
    private BluetoothLeScanner scanner;
    private BluetoothLeAdvertiser advertiser;
    private BluetoothGattServer server;
    private BluetoothGattCharacteristic serverCharacteristic;

    private final Map<String, BluetoothGatt> gatts = new ConcurrentHashMap<>();
    private final Map<String, BluetoothGattCharacteristic> remoteCharacteristics = new ConcurrentHashMap<>();
    private final Map<String, Integer> rssiById = new ConcurrentHashMap<>();
    private final Map<String, Integer> mtuById = new ConcurrentHashMap<>();
    private final Map<String, ArrayDeque<byte[]>> writeQueues = new ConcurrentHashMap<>();
    private final Set<String> writeBusy = ConcurrentHashMap.newKeySet();
    private final Map<String, BleAssembly> bleAssemblies = new ConcurrentHashMap<>();
    private final AtomicInteger bleMessageId = new AtomicInteger(1);
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private final String nodeId = UUID.randomUUID().toString();
    private MulticastSocket lanSocket;
    private InetAddress lanGroup;
    private Thread lanThread;
    private ScheduledExecutorService lanScheduler;
    private WifiManager.MulticastLock multicastLock;
    private final Map<String, InetSocketAddress> lanPeers = new ConcurrentHashMap<>();
    private final Map<String, Long> lanLastSeen = new ConcurrentHashMap<>();
    private final Object lanSendLock = new Object();

    private volatile boolean started = false;
    private volatile boolean scanStarted = false;
    private volatile boolean advertiseStarted = false;
    private volatile boolean lanStarted = false;

    private static class BleAssembly {
        final byte[][] parts;
        final long createdAt = System.currentTimeMillis();
        int count = 0;
        BleAssembly(int total) { parts = new byte[total][]; }
    }

    // BLEE_MESH_SERVICE_SOLE_BLE_OWNER_V1
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

    @PluginMethod
    public void stopMesh(PluginCall call) {
        started = false;
        try {
            if (scanner != null && scanStarted) scanner.stopScan(scanCallback);
            if (advertiser != null && advertiseStarted) advertiser.stopAdvertising(advertiseCallback);
            scanStarted = false;
            advertiseStarted = false;

            for (BluetoothGatt gatt : gatts.values()) {
                try { gatt.disconnect(); } catch (Exception ignored) {}
                try { gatt.close(); } catch (Exception ignored) {}
            }
            gatts.clear();
            remoteCharacteristics.clear();
            rssiById.clear();
            mtuById.clear();
            writeQueues.clear();
            writeBusy.clear();
            bleAssemblies.clear();

            if (server != null) {
                try { server.close(); } catch (Exception ignored) {}
                server = null;
            }

            stopLan();
            emitState("stopped");
            call.resolve();
        } catch (SecurityException e) {
            call.reject("Bluetooth permission error", e);
        }
    }

    @PluginMethod
    public void send(PluginCall call) {
        String text = call.getString("data");
        if (text == null) {
            call.reject("Missing data");
            return;
        }
        if (!started) {
            call.reject("Nearby transport is not running");
            return;
        }

        byte[] bytes = text.getBytes(StandardCharsets.UTF_8);
        int recipients = 0;

        for (String id : remoteCharacteristics.keySet()) {
            if (enqueueBleMessage(id, bytes)) recipients++;
        }

        recipients += sendLanData(bytes);

        JSObject ret = new JSObject();
        ret.put("recipients", recipients);
        call.resolve(ret);
    }

    @PluginMethod
    public void getPeers(PluginCall call) {
        JSArray peers = new JSArray();
        for (Map.Entry<String, Integer> e : rssiById.entrySet()) {
            JSObject p = new JSObject();
            p.put("id", e.getKey());
            p.put("rssi", e.getValue());
            p.put("transport", "ble");
            peers.put(p);
        }
        for (String id : lanPeers.keySet()) {
            JSObject p = new JSObject();
            p.put("id", id);
            p.put("transport", "lan");
            peers.put(p);
        }
        JSObject ret = new JSObject();
        ret.put("peers", peers);
        call.resolve(ret);
    }

    private void emitState(String value) {
        JSObject s = new JSObject();
        s.put("state", value);
        notifyListeners("state", s);
    }

    private void emitPeerSeen(String id, Integer rssi, String transport) {
        JSObject p = new JSObject();
        p.put("id", id);
        if (rssi != null) p.put("rssi", rssi);
        p.put("transport", transport);
        notifyListeners("peerSeen", p);
    }

    private void emitPacket(String peerId, byte[] value) {
        if (value == null) return;
        JSObject event = new JSObject();
        event.put("peerId", peerId);
        event.put("data", new String(value, StandardCharsets.UTF_8));
        notifyListeners("packet", event);
    }

    // ---------------- LAN / same-Wi-Fi transport ----------------

    private void startLan() {
        try {
            WifiManager wifi = (WifiManager) getContext().getApplicationContext().getSystemService(Context.WIFI_SERVICE);
            if (wifi != null) {
                multicastLock = wifi.createMulticastLock("blee-nearby");
                multicastLock.setReferenceCounted(false);
                multicastLock.acquire();
            }

            lanGroup = InetAddress.getByName(LAN_GROUP);
            MulticastSocket socket = new MulticastSocket(null);
            socket.setReuseAddress(true);
            socket.setBroadcast(true);
            socket.bind(new InetSocketAddress(LAN_PORT));
            socket.setTimeToLive(1);
            socket.joinGroup(lanGroup);
            lanSocket = socket;
            lanStarted = true;

            lanThread = new Thread(this::lanReceiveLoop, "Blee-LAN-RX");
            lanThread.setDaemon(true);
            lanThread.start();

            lanScheduler = Executors.newSingleThreadScheduledExecutor();
            lanScheduler.scheduleAtFixedRate(() -> {
                if (!started || !lanStarted) return;
                sendLanBeacon();
                pruneLanPeers();
            }, 0, 1500, TimeUnit.MILLISECONDS);
        } catch (Exception e) {
            lanStarted = false;
            emitState("lan_unavailable_" + e.getClass().getSimpleName());
        }
    }

    private void stopLan() {
        lanStarted = false;
        if (lanScheduler != null) {
            lanScheduler.shutdownNow();
            lanScheduler = null;
        }
        if (lanSocket != null) {
            try { if (lanGroup != null) lanSocket.leaveGroup(lanGroup); } catch (Exception ignored) {}
            try { lanSocket.close(); } catch (Exception ignored) {}
            lanSocket = null;
        }
        if (multicastLock != null) {
            try { if (multicastLock.isHeld()) multicastLock.release(); } catch (Exception ignored) {}
            multicastLock = null;
        }
        lanPeers.clear();
        lanLastSeen.clear();
    }

    private void lanReceiveLoop() {
        byte[] buffer = new byte[8192];
        while (started && lanStarted) {
            try {
                DatagramPacket packet = new DatagramPacket(buffer, buffer.length);
                lanSocket.receive(packet);
                String message = new String(packet.getData(), packet.getOffset(), packet.getLength(), StandardCharsets.UTF_8);
                handleLanMessage(message, packet.getAddress());
            } catch (Exception e) {
                if (started && lanStarted) emitState("lan_receive_error");
                break;
            }
        }
    }

    private void handleLanMessage(String message, InetAddress address) {
        if (message == null || message.length() < 3) return;
        String[] parts = message.split("\\|", 3);
        if (parts.length < 2) return;
        String kind = parts[0];
        String remoteNode = parts[1];
        if (remoteNode.equals(nodeId)) return;

        String peerId = "lan:" + remoteNode;
        boolean first = !lanPeers.containsKey(peerId);
        lanPeers.put(peerId, new InetSocketAddress(address, LAN_PORT));
        lanLastSeen.put(peerId, System.currentTimeMillis());
        if (first) emitPeerSeen(peerId, null, "lan");

        if ("D".equals(kind) && parts.length == 3) {
            try {
                byte[] payload = Base64.decode(parts[2], Base64.NO_WRAP);
                emitPacket(peerId, payload);
            } catch (Exception ignored) {}
        }
    }

    private void sendLanBeacon() {
        String message = "H|" + nodeId;
        byte[] bytes = message.getBytes(StandardCharsets.UTF_8);
        try {
            synchronized (lanSendLock) {
                if (lanSocket == null) return;
                lanSocket.send(new DatagramPacket(bytes, bytes.length, lanGroup, LAN_PORT));
                try {
                    InetAddress broadcast = InetAddress.getByName("255.255.255.255");
                    lanSocket.send(new DatagramPacket(bytes, bytes.length, broadcast, LAN_PORT));
                } catch (Exception ignored) {}
            }
        } catch (Exception ignored) {}
    }

    private int sendLanData(byte[] payload) {
        if (!lanStarted || lanSocket == null || lanPeers.isEmpty()) return 0;
        String encoded = Base64.encodeToString(payload, Base64.NO_WRAP);
        byte[] bytes = ("D|" + nodeId + "|" + encoded).getBytes(StandardCharsets.UTF_8);
        int sent = 0;
        for (Map.Entry<String, InetSocketAddress> entry : lanPeers.entrySet()) {
            Long last = lanLastSeen.get(entry.getKey());
            if (last == null || System.currentTimeMillis() - last > LAN_STALE_MS) continue;
            try {
                synchronized (lanSendLock) {
                    lanSocket.send(new DatagramPacket(bytes, bytes.length, entry.getValue()));
                }
                sent++;
            } catch (Exception ignored) {}
        }
        return sent;
    }

    private void pruneLanPeers() {
        long now = System.currentTimeMillis();
        for (Map.Entry<String, Long> e : lanLastSeen.entrySet()) {
            if (now - e.getValue() > LAN_STALE_MS) {
                lanLastSeen.remove(e.getKey());
                lanPeers.remove(e.getKey());
            }
        }
    }

    // ---------------- BLE transport ----------------

    private void startScanning() throws SecurityException {
        ScanFilter filter = new ScanFilter.Builder().setServiceUuid(new ParcelUuid(SERVICE_UUID)).build();
        ScanSettings settings = new ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .setCallbackType(ScanSettings.CALLBACK_TYPE_ALL_MATCHES)
            .build();
        scanner.startScan(Collections.singletonList(filter), settings, scanCallback);
        scanStarted = true;
    }

    private void startAdvertising() throws SecurityException {
        if (advertiser == null || advertiseStarted || !started) return;
        AdvertiseSettings settings = new AdvertiseSettings.Builder()
            .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)
            .setConnectable(true)
            .setTimeout(0)
            .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_HIGH)
            .build();
        AdvertiseData data = new AdvertiseData.Builder()
            .setIncludeDeviceName(false)
            .addServiceUuid(new ParcelUuid(SERVICE_UUID))
            .build();
        advertiser.startAdvertising(settings, data, advertiseCallback);
    }

    private void startServer() throws SecurityException {
        server = manager.openGattServer(getContext(), serverCallback);
        if (server == null) {
            emitState("gatt_server_unavailable");
            return;
        }

        BluetoothGattService service = new BluetoothGattService(SERVICE_UUID, BluetoothGattService.SERVICE_TYPE_PRIMARY);
        serverCharacteristic = new BluetoothGattCharacteristic(
            CHAR_UUID,
            BluetoothGattCharacteristic.PROPERTY_WRITE | BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE | BluetoothGattCharacteristic.PROPERTY_NOTIFY,
            BluetoothGattCharacteristic.PERMISSION_WRITE
        );
        BluetoothGattDescriptor descriptor = new BluetoothGattDescriptor(
            CCCD_UUID,
            BluetoothGattDescriptor.PERMISSION_READ | BluetoothGattDescriptor.PERMISSION_WRITE
        );
        serverCharacteristic.addDescriptor(descriptor);
        service.addCharacteristic(serverCharacteristic);
        if (!server.addService(service)) emitState("gatt_service_add_failed");
    }

    private final ScanCallback scanCallback = new ScanCallback() {
        @Override
        public void onScanResult(int callbackType, ScanResult result) {
            if (!started) return;
            BluetoothDevice device = result.getDevice();
            String id = device.getAddress();
            rssiById.put(id, result.getRssi());
            emitPeerSeen(id, result.getRssi(), "ble");

            if (!gatts.containsKey(id)) {
                try {
                    BluetoothGatt gatt = device.connectGatt(getContext(), false, clientCallback, BluetoothDevice.TRANSPORT_LE);
                    if (gatt != null) gatts.put(id, gatt);
                } catch (SecurityException ignored) {}
            }
        }

        @Override
        public void onScanFailed(int errorCode) {
            scanStarted = false;
            emitState("ble_scan_error_" + errorCode);
        }
    };

    private final AdvertiseCallback advertiseCallback = new AdvertiseCallback() {
        @Override
        public void onStartSuccess(AdvertiseSettings settingsInEffect) {
            advertiseStarted = true;
            emitState(lanStarted ? "running_lan_ble" : "running_ble");
        }

        @Override
        public void onStartFailure(int errorCode) {
            advertiseStarted = false;
            emitState("ble_advertise_error_" + errorCode + (lanStarted ? "_lan_active" : ""));
        }
    };

    private final BluetoothGattCallback clientCallback = new BluetoothGattCallback() {
        @Override
        public void onConnectionStateChange(BluetoothGatt gatt, int status, int newState) {
            String id = gatt.getDevice().getAddress();
            try {
                if (newState == BluetoothProfile.STATE_CONNECTED) {
                    boolean requested = false;
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) requested = gatt.requestMtu(247);
                    if (!requested) gatt.discoverServices();
                    mainHandler.postDelayed(() -> {
                        try {
                            if (started && !remoteCharacteristics.containsKey(id)) gatt.discoverServices();
                        } catch (SecurityException ignored) {}
                    }, 1200);
                } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                    remoteCharacteristics.remove(id);
                    gatts.remove(id);
                    mtuById.remove(id);
                    writeQueues.remove(id);
                    writeBusy.remove(id);
                    try { gatt.close(); } catch (Exception ignored) {}
                }
            } catch (SecurityException ignored) {}
        }

        @Override
        public void onMtuChanged(BluetoothGatt gatt, int mtu, int status) {
            String id = gatt.getDevice().getAddress();
            if (status == BluetoothGatt.GATT_SUCCESS && mtu >= 23) mtuById.put(id, mtu);
            try { gatt.discoverServices(); } catch (SecurityException ignored) {}
        }

        @Override
        public void onServicesDiscovered(BluetoothGatt gatt, int status) {
            if (status != BluetoothGatt.GATT_SUCCESS) return;
            BluetoothGattService service = gatt.getService(SERVICE_UUID);
            if (service == null) return;
            BluetoothGattCharacteristic c = service.getCharacteristic(CHAR_UUID);
            if (c == null) return;

            String id = gatt.getDevice().getAddress();
            remoteCharacteristics.put(id, c);
            emitPeerSeen(id, rssiById.get(id), "ble");

            try {
                gatt.setCharacteristicNotification(c, true);
                BluetoothGattDescriptor d = c.getDescriptor(CCCD_UUID);
                if (d != null) {
                    if (Build.VERSION.SDK_INT >= 33) {
                        gatt.writeDescriptor(d, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
                    } else {
                        d.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
                        gatt.writeDescriptor(d);
                    }
                }
            } catch (SecurityException ignored) {}
        }

        @Override
        public void onCharacteristicWrite(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
            String id = gatt.getDevice().getAddress();
            writeBusy.remove(id);
            writeNext(id);
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, byte[] value) {
            handleBleChunk(gatt.getDevice().getAddress(), value);
        }

        @Override
        public void onCharacteristicChanged(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic) {
            handleBleChunk(gatt.getDevice().getAddress(), characteristic.getValue());
        }
    };

    private final BluetoothGattServerCallback serverCallback = new BluetoothGattServerCallback() {
        @Override
        public void onServiceAdded(int status, BluetoothGattService service) {
            if (status == BluetoothGatt.GATT_SUCCESS && SERVICE_UUID.equals(service.getUuid())) {
                try { startAdvertising(); } catch (SecurityException e) { emitState("ble_advertise_permission_error"); }
            } else {
                emitState("gatt_service_error_" + status);
            }
        }

        @Override
        public void onDescriptorWriteRequest(BluetoothDevice device, int requestId, BluetoothGattDescriptor descriptor,
                                             boolean preparedWrite, boolean responseNeeded, int offset, byte[] value) {
            try {
                if (responseNeeded && server != null) server.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, 0, null);
            } catch (SecurityException ignored) {}
        }

        @Override
        public void onCharacteristicWriteRequest(BluetoothDevice device, int requestId, BluetoothGattCharacteristic characteristic,
                                                 boolean preparedWrite, boolean responseNeeded, int offset, byte[] value) {
            if (CHAR_UUID.equals(characteristic.getUuid())) handleBleChunk(device.getAddress(), value);
            try {
                if (responseNeeded && server != null) server.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, 0, null);
            } catch (SecurityException ignored) {}
        }
    };

    private boolean enqueueBleMessage(String id, byte[] payload) {
        BluetoothGatt gatt = gatts.get(id);
        BluetoothGattCharacteristic c = remoteCharacteristics.get(id);
        if (gatt == null || c == null) return false;

        int mtu = mtuById.containsKey(id) ? mtuById.get(id) : 23;
        int payloadPerChunk = Math.max(8, Math.min(160, mtu - 10));
        int total = Math.max(1, (payload.length + payloadPerChunk - 1) / payloadPerChunk);
        if (total > 255) return false;

        int messageId = bleMessageId.getAndIncrement() & 0xffff;
        ArrayDeque<byte[]> queue = writeQueues.computeIfAbsent(id, k -> new ArrayDeque<>());
        synchronized (queue) {
            for (int seq = 0; seq < total; seq++) {
                int from = seq * payloadPerChunk;
                int to = Math.min(payload.length, from + payloadPerChunk);
                byte[] chunk = new byte[BLE_HEADER + (to - from)];
                chunk[0] = MAGIC_A;
                chunk[1] = MAGIC_D;
                chunk[2] = MAGIC_B;
                chunk[3] = (byte) ((messageId >> 8) & 0xff);
                chunk[4] = (byte) (messageId & 0xff);
                chunk[5] = (byte) seq;
                chunk[6] = (byte) total;
                System.arraycopy(payload, from, chunk, BLE_HEADER, to - from);
                queue.add(chunk);
            }
        }
        writeNext(id);
        return true;
    }

    private void writeNext(String id) {
        if (writeBusy.contains(id)) return;
        BluetoothGatt gatt = gatts.get(id);
        BluetoothGattCharacteristic c = remoteCharacteristics.get(id);
        ArrayDeque<byte[]> queue = writeQueues.get(id);
        if (gatt == null || c == null || queue == null) return;

        byte[] bytes;
        synchronized (queue) { bytes = queue.poll(); }
        if (bytes == null) return;

        writeBusy.add(id);
        boolean success = false;
        try {
            if (Build.VERSION.SDK_INT >= 33) {
                int result = gatt.writeCharacteristic(c, bytes, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
                success = result == BluetoothStatusCodes.SUCCESS;
            } else {
                c.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
                c.setValue(bytes);
                success = gatt.writeCharacteristic(c);
            }
        } catch (SecurityException ignored) {}

        if (!success) {
            writeBusy.remove(id);
            mainHandler.postDelayed(() -> writeNext(id), 35);
        }
    }

    private void handleBleChunk(String peerId, byte[] value) {
        if (value == null || value.length == 0) return;
        if (value.length < BLE_HEADER || value[0] != MAGIC_A || value[1] != MAGIC_D || value[2] != MAGIC_B) {
            emitPacket(peerId, value);
            return;
        }

        int messageId = ((value[3] & 0xff) << 8) | (value[4] & 0xff);
        int seq = value[5] & 0xff;
        int total = value[6] & 0xff;
        if (total <= 0 || seq >= total) return;

        String key = peerId + ":" + messageId;
        BleAssembly assembly = bleAssemblies.computeIfAbsent(key, k -> new BleAssembly(total));
        if (assembly.parts.length != total) {
            bleAssemblies.remove(key);
            return;
        }

        if (assembly.parts[seq] == null) {
            assembly.parts[seq] = Arrays.copyOfRange(value, BLE_HEADER, value.length);
            assembly.count++;
        }

        if (assembly.count == total) {
            try {
                ByteArrayOutputStream out = new ByteArrayOutputStream();
                for (byte[] part : assembly.parts) {
                    if (part == null) return;
                    out.write(part, 0, part.length);
                }
                bleAssemblies.remove(key);
                emitPacket(peerId, out.toByteArray());
            } catch (Exception ignored) {
                bleAssemblies.remove(key);
            }
        }

        long now = System.currentTimeMillis();
        for (Map.Entry<String, BleAssembly> e : bleAssemblies.entrySet()) {
            if (now - e.getValue().createdAt > 30_000L) bleAssemblies.remove(e.getKey());
        }
    }
}
