#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def locate_activity() -> Path:
    hits = list(ANDROID_JAVA.rglob("MainActivity.java"))
    if len(hits) != 1:
        raise SystemExit(f"Blee transport v2: expected one MainActivity.java, found {len(hits)}")
    return hits[0]


def once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Blee transport v2: missing {label} anchor")
    return text.replace(old, new, 1)


def between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    a = text.find(start)
    if a < 0:
        raise SystemExit(f"Blee transport v2: missing {label} start")
    b = text.find(end, a)
    if b < 0:
        raise SystemExit(f"Blee transport v2: missing {label} end")
    return text[:a] + replacement + text[b:]


def patch_service(native_dir: Path) -> None:
    path = native_dir / "BleeMeshService.java"
    text = path.read_text()
    if "BLEE_TRANSPORT_CORE_V2" in text:
        return

    for marker in (
        "BLEE_BLE_TRANSPORT_V4",
        "BLEE_BLE_DIAGNOSTICS_V1",
        "BLEE_BITCHAT_ANDROID_GATT_PARITY_V1",
        "BLEE_GATT_INTEROP_V1",
        "BLEE_GATT_SERVER_READINESS_V1",
    ):
        if marker not in text:
            raise SystemExit(f"Blee transport v2: prerequisite missing: {marker}")

    if "import android.bluetooth.BluetoothGattDescriptor;" not in text:
        text = once(
            text,
            "import android.bluetooth.BluetoothGattCharacteristic;",
            "import android.bluetooth.BluetoothGattCharacteristic;\nimport android.bluetooth.BluetoothGattDescriptor;",
            "BluetoothGattDescriptor import",
        )
    if "import java.security.MessageDigest;" not in text:
        text = once(
            text,
            "import java.nio.charset.StandardCharsets;",
            "import java.nio.charset.StandardCharsets;\nimport java.security.MessageDigest;",
            "MessageDigest import",
        )

    field_anchor = "    private volatile boolean settlementScheduled = false;"
    text = once(
        text,
        field_anchor,
        field_anchor + "\n    // BLEE_TRANSPORT_CORE_V2\n    private BleTransportV2 bleTransportV2;",
        "transport field",
    )

    start_marker = "    private void startBluetooth() {"
    core = r'''    // BLEE_TRANSPORT_CORE_V2
    // One runtime owner for BLE scanning, advertising, GATT server and GATT client.
    // The older transport methods remain below only as build-time compatibility
    // material; startBluetooth/stopBluetooth route all runtime radio ownership here.
    private final class BleTransportV2 {
        private static final long SCAN_RESTART_MIN_MS = 5_000L;
        private static final long SCAN_STALE_MS = 120_000L;
        private static final long ADVERTISE_RETRY_BASE_MS = 3_000L;
        private static final long ADVERTISE_RETRY_MAX_MS = 30_000L;
        private static final long CONNECT_RETRY_MS = 6_000L;
        private static final long CONNECT_STALE_MS = 45_000L;
        private static final int RSSI_FLOOR = -96;
        private static final int PREFERRED_MTU = 247;
        private static final UUID CCCD_UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");

        private BluetoothManager manager;
        private BluetoothAdapter localAdapter;
        private BluetoothLeScanner localScanner;
        private BluetoothLeAdvertiser localAdvertiser;
        private BluetoothGattServer localServer;
        private BluetoothGattCharacteristic serverWriteCharacteristic;

        private boolean started = false;
        private boolean scanActive = false;
        private boolean advertiseActive = false;
        private boolean advertiseStartingV2 = false;
        private boolean serverReadyV2 = false;
        private long lastScanStartV2 = 0L;
        private long lastScanResultV2 = 0L;
        private long advertiseSuppressedUntilV2 = 0L;
        private int advertiseRetryV2 = 0;
        private int advertiserSlotFailuresV2 = 0;
        private long lastMaintenanceV2 = 0L;

        private final byte[] localPeerId = stablePeerId();
        private final Map<String, Long> lastAttempt = Collections.synchronizedMap(new HashMap<String, Long>());
        private final Map<BluetoothGatt, ClientLink> clientLinks = Collections.synchronizedMap(new HashMap<BluetoothGatt, ClientLink>());
        private final Map<String, BluetoothGatt> addressLinks = Collections.synchronizedMap(new HashMap<String, BluetoothGatt>());

        private long scanStartsV2 = 0L;
        private long rawScanResultsV2 = 0L;
        private long bleAdvertisementsV2 = 0L;
        private long advertiseStartsV2 = 0L;
        private long advertiseSuccessesV2 = 0L;
        private long advertiseFailuresV2 = 0L;
        private long gattAttemptsV2 = 0L;
        private long gattConnectionsV2 = 0L;
        private long servicesDiscoveredV2 = 0L;
        private long identityReadsV2 = 0L;
        private long identityFailuresV2 = 0L;
        private long serverConnectionsV2 = 0L;
        private long gattCallbacksV2 = 0L;
        private long lastSeenAtV2 = 0L;
        private int lastRssiV2 = 0;
        private String lastTransportIdV2 = "";
        private String lastWalletV2 = "";
        private String lastPhaseV2 = "created";
        private String lastErrorV2 = "";
        private String lastAdvertiseErrorV2 = "";
        private String lastGattErrorV2 = "";
        private String lastServerPeerV2 = "";
        private int lastServerStatusV2 = 0;
        private int lastServerStateV2 = BluetoothProfile.STATE_DISCONNECTED;
        private boolean lastScanConnectableV2 = true;
        private int lastAddressTypeV2 = -1;
        private int lastDeviceTypeV2 = -1;
        private int lastNativeGattStatusV2 = -1;
        private int lastNativeGattStateV2 = -1;
        private String lastConnectStrategyV2 = "direct_scan_result";

        private final class ClientLink {
            final BluetoothDevice device;
            final String address;
            final int rssi;
            final byte[] peerId;
            final long startedAt;
            int mtu = 23;
            String messageId = null;
            List<byte[]> frames = Collections.emptyList();
            int nextFrame = 0;
            boolean connected = false;

            ClientLink(BluetoothDevice device, int rssi, byte[] peerId) {
                this.device = device;
                this.address = device.getAddress();
                this.rssi = rssi;
                this.peerId = peerId;
                this.startedAt = System.currentTimeMillis();
            }
        }

        void start() {
            if (!bluetoothPermissionsGranted()) {
                lastPhaseV2 = "permissions_missing";
                syncLegacyState();
                return;
            }
            manager = (BluetoothManager) getSystemService(Context.BLUETOOTH_SERVICE);
            localAdapter = manager == null ? null : manager.getAdapter();
            if (localAdapter == null || !localAdapter.isEnabled()) {
                lastPhaseV2 = "bluetooth_disabled";
                syncLegacyState();
                return;
            }
            localScanner = localAdapter.getBluetoothLeScanner();
            localAdvertiser = localAdapter.getBluetoothLeAdvertiser();
            started = true;
            if (localServer == null && System.currentTimeMillis() >= advertiseSuppressedUntilV2) setupServer();
            startScan();
            syncLegacyState();
        }

        void stop() {
            started = false;
            try { if (localScanner != null && scanActive) localScanner.stopScan(coreScanCallback); } catch (Throwable ignored) {}
            scanActive = false;
            try { if (localAdvertiser != null && (advertiseActive || advertiseStartingV2)) localAdvertiser.stopAdvertising(coreAdvertiseCallback); } catch (Throwable ignored) {}
            advertiseActive = false;
            advertiseStartingV2 = false;

            List<BluetoothGatt> links;
            synchronized (clientLinks) { links = new ArrayList<BluetoothGatt>(clientLinks.keySet()); }
            for (BluetoothGatt gatt : links) closeClient(gatt, false, "transport_stop");

            try { if (localServer != null) localServer.close(); } catch (Throwable ignored) {}
            localServer = null;
            serverWriteCharacteristic = null;
            serverReadyV2 = false;
            lastPhaseV2 = "stopped";
            syncLegacyState();
        }

        void maintain() {
            long now = System.currentTimeMillis();
            if (now - lastMaintenanceV2 < 1_000L) return;
            lastMaintenanceV2 = now;

            if (!started) {
                start();
                return;
            }
            if (localAdapter == null || !localAdapter.isEnabled()) {
                stop();
                return;
            }

            if (!scanActive) startScan();
            else if (lastScanResultV2 > 0L && now - lastScanResultV2 > SCAN_STALE_MS && now - lastScanStartV2 > SCAN_STALE_MS) {
                restartScan("watchdog_stale");
            }

            if (localServer == null && now >= advertiseSuppressedUntilV2) setupServer();
            if (serverReadyV2 && !advertiseActive && !advertiseStartingV2 && now >= advertiseSuppressedUntilV2) startAdvertising();

            List<BluetoothGatt> links;
            synchronized (clientLinks) { links = new ArrayList<BluetoothGatt>(clientLinks.keySet()); }
            for (BluetoothGatt gatt : links) {
                ClientLink link = clientLinks.get(gatt);
                if (link != null && !link.connected && now - link.startedAt > CONNECT_STALE_MS) {
                    lastGattErrorV2 = "No Android connection callback for " + CONNECT_STALE_MS + "ms";
                    lastErrorV2 = lastGattErrorV2;
                    lastPhaseV2 = "connect_watchdog";
                    closeClient(gatt, true, "connect_watchdog");
                }
            }
            syncLegacyState();
        }

        private void setupServer() {
            if (!started || manager == null || localServer != null) return;
            try {
                localServer = manager.openGattServer(BleeMeshService.this, coreServerCallback);
                if (localServer == null) {
                    lastPhaseV2 = "server_open_failed";
                    return;
                }
                serverReadyV2 = false;
                BluetoothGattService service = new BluetoothGattService(SERVICE_UUID, BluetoothGattService.SERVICE_TYPE_PRIMARY);

                serverWriteCharacteristic = new BluetoothGattCharacteristic(
                    WRITE_UUID,
                    BluetoothGattCharacteristic.PROPERTY_WRITE
                        | BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE
                        | BluetoothGattCharacteristic.PROPERTY_NOTIFY,
                    BluetoothGattCharacteristic.PERMISSION_WRITE
                );
                BluetoothGattDescriptor cccd = new BluetoothGattDescriptor(
                    CCCD_UUID,
                    BluetoothGattDescriptor.PERMISSION_READ | BluetoothGattDescriptor.PERMISSION_WRITE
                );
                serverWriteCharacteristic.addDescriptor(cccd);
                service.addCharacteristic(serverWriteCharacteristic);

                BluetoothGattCharacteristic identity = new BluetoothGattCharacteristic(
                    IDENTITY_UUID,
                    BluetoothGattCharacteristic.PROPERTY_READ | BluetoothGattCharacteristic.PROPERTY_WRITE,
                    BluetoothGattCharacteristic.PERMISSION_READ | BluetoothGattCharacteristic.PERMISSION_WRITE
                );
                service.addCharacteristic(identity);

                boolean accepted = localServer.addService(service);
                lastPhaseV2 = accepted ? "server_service_registering" : "server_service_rejected";
                if (!accepted) {
                    try { localServer.close(); } catch (Throwable ignored) {}
                    localServer = null;
                }
            } catch (Throwable error) {
                lastPhaseV2 = "server_exception";
                lastErrorV2 = message(error);
                try { if (localServer != null) localServer.close(); } catch (Throwable ignored) {}
                localServer = null;
                serverReadyV2 = false;
            }
            syncLegacyState();
        }

        private void startAdvertising() {
            if (!started || !serverReadyV2 || advertiseActive || advertiseStartingV2) return;
            if (localAdvertiser == null) {
                lastAdvertiseErrorV2 = "advertiser_unavailable";
                return;
            }
            long now = System.currentTimeMillis();
            if (now < advertiseSuppressedUntilV2) return;
            try {
                AdvertiseSettings settings = new AdvertiseSettings.Builder()
                    .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_BALANCED)
                    .setTxPowerLevel(AdvertiseSettings.ADVERTISE_TX_POWER_MEDIUM)
                    .setConnectable(true)
                    .setTimeout(0)
                    .build();
                AdvertiseData data = new AdvertiseData.Builder()
                    .addServiceUuid(new ParcelUuid(SERVICE_UUID))
                    .setIncludeTxPowerLevel(false)
                    .setIncludeDeviceName(false)
                    .build();
                AdvertiseData response = new AdvertiseData.Builder()
                    .addServiceData(new ParcelUuid(SERVICE_UUID), localPeerId)
                    .setIncludeTxPowerLevel(false)
                    .setIncludeDeviceName(false)
                    .build();
                advertiseStartingV2 = true;
                advertiseStartsV2++;
                lastPhaseV2 = "advertise_start_requested";
                localAdvertiser.startAdvertising(settings, data, response, coreAdvertiseCallback);
            } catch (Throwable error) {
                advertiseStartingV2 = false;
                advertiseActive = false;
                lastAdvertiseErrorV2 = message(error);
                lastErrorV2 = lastAdvertiseErrorV2;
                scheduleAdvertiseRetry("exception");
            }
            syncLegacyState();
        }

        private void scheduleAdvertiseRetry(String reason) {
            advertiseRetryV2 = Math.min(10, advertiseRetryV2 + 1);
            long delay = Math.min(ADVERTISE_RETRY_MAX_MS, ADVERTISE_RETRY_BASE_MS * advertiseRetryV2);
            advertiseSuppressedUntilV2 = System.currentTimeMillis() + delay;
            lastPhaseV2 = "advertise_backoff_" + reason;
            handler.postDelayed(() -> {
                if (!started) return;
                if (localServer == null) setupServer();
                if (serverReadyV2) startAdvertising();
            }, delay);
        }

        private void suspendPeripheralRole(long delayMs) {
            try { if (localAdvertiser != null) localAdvertiser.stopAdvertising(coreAdvertiseCallback); } catch (Throwable ignored) {}
            advertiseActive = false;
            advertiseStartingV2 = false;
            serverReadyV2 = false;
            try { if (localServer != null) localServer.close(); } catch (Throwable ignored) {}
            localServer = null;
            serverWriteCharacteristic = null;
            advertiseSuppressedUntilV2 = System.currentTimeMillis() + delayMs;
            lastPhaseV2 = "scanner_first";
            syncLegacyState();
        }

        private void startScan() {
            if (!started || localScanner == null || scanActive) return;
            long now = System.currentTimeMillis();
            if (lastScanStartV2 > 0L && now - lastScanStartV2 < SCAN_RESTART_MIN_MS) {
                long wait = SCAN_RESTART_MIN_MS - (now - lastScanStartV2);
                handler.postDelayed(() -> { if (started && !scanActive) startScan(); }, wait);
                return;
            }
            try {
                ScanFilter filter = new ScanFilter.Builder().setServiceUuid(new ParcelUuid(SERVICE_UUID)).build();
                ScanSettings.Builder settings = new ScanSettings.Builder()
                    .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
                    .setReportDelay(0L);
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    settings.setCallbackType(ScanSettings.CALLBACK_TYPE_ALL_MATCHES)
                        .setMatchMode(ScanSettings.MATCH_MODE_AGGRESSIVE)
                        .setNumOfMatches(ScanSettings.MATCH_NUM_MAX_ADVERTISEMENT);
                }
                scanStartsV2++;
                lastScanStartV2 = now;
                localScanner.startScan(Collections.singletonList(filter), settings.build(), coreScanCallback);
                scanActive = true;
                lastPhaseV2 = "scan_active";
                lastErrorV2 = "";
            } catch (Throwable error) {
                scanActive = false;
                lastPhaseV2 = "scan_exception";
                lastErrorV2 = message(error);
                handler.postDelayed(() -> startScan(), SCAN_RESTART_MIN_MS);
            }
            syncLegacyState();
        }

        private void restartScan(String reason) {
            try { if (localScanner != null && scanActive) localScanner.stopScan(coreScanCallback); } catch (Throwable ignored) {}
            scanActive = false;
            lastPhaseV2 = "scan_restart_" + reason;
            handler.postDelayed(() -> startScan(), 750L);
            syncLegacyState();
        }

        private void handleScan(ScanResult result) {
            if (!started || result == null || result.getDevice() == null) return;
            rawScanResultsV2++;
            lastScanResultV2 = System.currentTimeMillis();
            lastSeenAtV2 = lastScanResultV2;
            lastRssiV2 = result.getRssi();
            BluetoothDevice device = result.getDevice();
            String address;
            try { address = device.getAddress(); } catch (Throwable ignored) { return; }
            lastTransportIdV2 = address;
            lastDeviceTypeV2 = device.getType();
            if (Build.VERSION.SDK_INT >= 35) {
                try { lastAddressTypeV2 = device.getAddressType(); } catch (Throwable ignored) {}
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                try { lastScanConnectableV2 = result.isConnectable(); } catch (Throwable ignored) { lastScanConnectableV2 = true; }
            } else lastScanConnectableV2 = true;

            if (!containsService(result)) return;
            bleAdvertisementsV2++;
            lastPhaseV2 = "blee_advertisement_seen";

            byte[] remotePeerId = peerId(result);
            if (samePeer(remotePeerId, localPeerId)) {
                lastPhaseV2 = "self_advertisement_ignored";
                return;
            }
            if (!lastScanConnectableV2) {
                lastGattErrorV2 = "Android marked advertisement non-connectable";
                return;
            }
            if (result.getRssi() < RSSI_FLOOR) return;

            peers.put(address, device);
            peerSeen.put(address, System.currentTimeMillis());
            peerRssi.put(address, result.getRssi());

            String knownWallet = peerWallets.get(address);
            if (knownWallet != null) publishResolvedPeer(address, knownWallet, peerDisplayNames.get(address), result.getRssi(), System.currentTimeMillis());

            if (!addressLinks.isEmpty()) return;
            String attemptKey = remotePeerId == null ? address : hex(remotePeerId);
            long now = System.currentTimeMillis();
            Long previous = lastAttempt.get(attemptKey);
            if (previous != null && now - previous < CONNECT_RETRY_MS) return;

            // Deterministic role choice prevents two healthy dual-role phones from
            // racing central-to-central. If our advertiser is down we must be the
            // client, so scanner-first mode always initiates.
            if (advertiseActive && remotePeerId != null && compare(localPeerId, remotePeerId) > 0) return;

            lastAttempt.put(attemptKey, now);
            connectFromScan(device, result.getRssi(), remotePeerId);
        }

        private void connectFromScan(BluetoothDevice device, int rssi, byte[] peerId) {
            if (device == null || !addressLinks.isEmpty()) return;
            String address;
            try { address = device.getAddress(); } catch (Throwable ignored) { return; }
            try {
                gattAttemptsV2++;
                lastConnectStrategyV2 = "direct_scan_result";
                lastPhaseV2 = "gatt_connect_attempt";
                lastGattErrorV2 = "";
                BluetoothGatt gatt = device.connectGatt(BleeMeshService.this, false, coreClientCallback, BluetoothDevice.TRANSPORT_LE);
                if (gatt == null) {
                    lastGattErrorV2 = "connectGatt returned null";
                    lastErrorV2 = lastGattErrorV2;
                    return;
                }
                ClientLink link = new ClientLink(device, rssi, peerId);
                clientLinks.put(gatt, link);
                addressLinks.put(address, gatt);
            } catch (Throwable error) {
                lastGattErrorV2 = message(error);
                lastErrorV2 = lastGattErrorV2;
                lastPhaseV2 = "gatt_connect_exception";
            }
            syncLegacyState();
        }

        private void afterConnected(BluetoothGatt gatt) {
            ClientLink link = clientLinks.get(gatt);
            if (link == null) return;
            link.connected = true;
            gattConnectionsV2++;
            lastPhaseV2 = "gatt_connected";
            lastGattErrorV2 = "";
            lastErrorV2 = "";
            try { gatt.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH); } catch (Throwable ignored) {}
            handler.postDelayed(() -> {
                if (!clientLinks.containsKey(gatt)) return;
                boolean requested = false;
                try { requested = gatt.requestMtu(PREFERRED_MTU); } catch (Throwable ignored) {}
                if (!requested) discoverServices(gatt);
            }, 200L);
        }

        private void discoverServices(BluetoothGatt gatt) {
            try {
                if (!gatt.discoverServices()) {
                    lastGattErrorV2 = "discoverServices rejected";
                    closeClient(gatt, true, "discover_rejected");
                }
            } catch (Throwable error) {
                lastGattErrorV2 = message(error);
                closeClient(gatt, true, "discover_exception");
            }
        }

        private void afterServices(BluetoothGatt gatt, int status) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                lastGattErrorV2 = "service discovery status=" + status;
                closeClient(gatt, true, "discover_status");
                return;
            }
            servicesDiscoveredV2++;
            lastPhaseV2 = "blee_service_discovered";
            BluetoothGattService service = gatt.getService(SERVICE_UUID);
            BluetoothGattCharacteristic identity = service == null ? null : service.getCharacteristic(IDENTITY_UUID);
            if (identity == null) {
                lastGattErrorV2 = "identity characteristic missing";
                identityFailuresV2++;
                closeClient(gatt, true, "identity_missing");
                return;
            }
            try {
                if (!gatt.readCharacteristic(identity)) {
                    lastGattErrorV2 = "identity read rejected";
                    identityFailuresV2++;
                    closeClient(gatt, true, "identity_read_rejected");
                }
            } catch (Throwable error) {
                lastGattErrorV2 = message(error);
                identityFailuresV2++;
                closeClient(gatt, true, "identity_read_exception");
            }
        }

        private void handleIdentity(BluetoothGatt gatt, byte[] value, int status) {
            if (status != BluetoothGatt.GATT_SUCCESS || value == null) {
                identityFailuresV2++;
                lastGattErrorV2 = "identity read status=" + status;
                closeClient(gatt, true, "identity_read_status");
                return;
            }
            boolean resolved = handleIdentityRead(gatt, value);
            if (!resolved) {
                identityFailuresV2++;
                lastGattErrorV2 = "identity payload invalid";
                closeClient(gatt, true, "identity_invalid");
                return;
            }
            identityReadsV2++;
            ClientLink link = clientLinks.get(gatt);
            if (link != null) {
                String wallet = peerWallets.get(link.address);
                if (wallet != null) lastWalletV2 = wallet;
            }
            writeOwnIdentity(gatt);
        }

        private void writeOwnIdentity(BluetoothGatt gatt) {
            byte[] payload = localIdentityPayload();
            BluetoothGattService service = gatt.getService(SERVICE_UUID);
            BluetoothGattCharacteristic identity = service == null ? null : service.getCharacteristic(IDENTITY_UUID);
            if (identity == null || payload == null || payload.length != 20
                || (identity.getProperties() & BluetoothGattCharacteristic.PROPERTY_WRITE) == 0) {
                sendPacketIfAny(gatt);
                return;
            }
            try {
                identity.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
                boolean ok;
                if (Build.VERSION.SDK_INT >= 33) ok = gatt.writeCharacteristic(identity, payload, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == 0;
                else { identity.setValue(payload); ok = gatt.writeCharacteristic(identity); }
                if (!ok) sendPacketIfAny(gatt);
            } catch (Throwable ignored) { sendPacketIfAny(gatt); }
        }

        private void sendPacketIfAny(BluetoothGatt gatt) {
            ClientLink link = clientLinks.get(gatt);
            if (link == null) return;
            List<String> packets = db.duePacketsForPeer(System.currentTimeMillis(), link.address, 1);
            if (packets.isEmpty()) {
                handler.postDelayed(() -> closeClient(gatt, false, "identity_complete"), 900L);
                return;
            }
            String raw = packets.get(0);
            try {
                JSONObject packet = new JSONObject(raw);
                String messageId = packet.optString("messageId", "");
                if (messageId.isEmpty()) throw new IllegalStateException("messageId missing");
                List<byte[]> frames = makeFrames(messageId, raw, link.mtu);
                if (frames.isEmpty()) throw new IllegalStateException("MTU too small for Blee frame");
                link.messageId = messageId;
                link.frames = frames;
                link.nextFrame = 0;
                writeNextFrame(gatt);
            } catch (Throwable error) {
                lastGattErrorV2 = message(error);
                closeClient(gatt, true, "packet_prepare_failed");
            }
        }

        private List<byte[]> makeFrames(String messageId, String raw, int mtu) {
            String encoded = Base64.encodeToString(raw.getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP);
            int safeMtu = Math.max(23, mtu);
            int headerReserve = ("B2|" + messageId + "|2147483647|2147483647|").getBytes(StandardCharsets.UTF_8).length;
            int chunk = safeMtu - 3 - headerReserve;
            if (chunk < 1) return Collections.emptyList();
            int total = (encoded.length() + chunk - 1) / chunk;
            if (total <= 0 || total > 512) return Collections.emptyList();
            List<byte[]> frames = new ArrayList<byte[]>();
            for (int i = 0; i < total; i++) {
                int start = i * chunk;
                int end = Math.min(encoded.length(), start + chunk);
                String frame = "B2|" + messageId + "|" + i + "|" + total + "|" + encoded.substring(start, end);
                frames.add(frame.getBytes(StandardCharsets.UTF_8));
            }
            return frames;
        }

        private void writeNextFrame(BluetoothGatt gatt) {
            ClientLink link = clientLinks.get(gatt);
            if (link == null) return;
            if (link.nextFrame >= link.frames.size()) {
                if (link.messageId != null) db.recordPeerDelivery(link.messageId, link.address);
                closeClient(gatt, false, "packet_delivered");
                return;
            }
            BluetoothGattService service = gatt.getService(SERVICE_UUID);
            BluetoothGattCharacteristic write = service == null ? null : service.getCharacteristic(WRITE_UUID);
            if (write == null) {
                lastGattErrorV2 = "write characteristic missing";
                closeClient(gatt, true, "write_missing");
                return;
            }
            byte[] value = link.frames.get(link.nextFrame);
            try {
                write.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
                boolean ok;
                if (Build.VERSION.SDK_INT >= 33) ok = gatt.writeCharacteristic(write, value, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == 0;
                else { write.setValue(value); ok = gatt.writeCharacteristic(write); }
                if (!ok) {
                    lastGattErrorV2 = "frame write rejected";
                    closeClient(gatt, true, "write_rejected");
                    return;
                }
                link.nextFrame++;
            } catch (Throwable error) {
                lastGattErrorV2 = message(error);
                closeClient(gatt, true, "write_exception");
            }
        }

        private void closeClient(BluetoothGatt gatt, boolean failed, String reason) {
            if (gatt == null) return;
            ClientLink link = clientLinks.remove(gatt);
            if (link != null) addressLinks.remove(link.address);
            try { gatt.disconnect(); } catch (Throwable ignored) {}
            handler.postDelayed(() -> { try { gatt.close(); } catch (Throwable ignored) {} }, 350L);
            if (failed) {
                lastPhaseV2 = "gatt_failed_" + reason;
                if (lastGattErrorV2 == null || lastGattErrorV2.isEmpty()) lastGattErrorV2 = reason;
                lastErrorV2 = lastGattErrorV2;
            } else {
                lastPhaseV2 = reason;
            }
            syncLegacyState();
        }

        private final AdvertiseCallback coreAdvertiseCallback = new AdvertiseCallback() {
            @Override public void onStartSuccess(AdvertiseSettings settingsInEffect) {
                advertiseStartingV2 = false;
                advertiseActive = true;
                advertiseRetryV2 = 0;
                advertiserSlotFailuresV2 = 0;
                advertiseSuppressedUntilV2 = 0L;
                advertiseSuccessesV2++;
                lastAdvertiseErrorV2 = "";
                lastErrorV2 = "";
                lastPhaseV2 = "advertising_active";
                syncLegacyState();
            }

            @Override public void onStartFailure(int errorCode) {
                advertiseStartingV2 = false;
                advertiseActive = false;
                advertiseFailuresV2++;
                lastAdvertiseErrorV2 = "advertise_error_" + errorCode;
                lastErrorV2 = lastAdvertiseErrorV2;
                if (errorCode == AdvertiseCallback.ADVERTISE_FAILED_ALREADY_STARTED) {
                    advertiseActive = true;
                    advertiseRetryV2 = 0;
                    lastPhaseV2 = "advertising_already_active";
                    syncLegacyState();
                    return;
                }
                if (errorCode == AdvertiseCallback.ADVERTISE_FAILED_TOO_MANY_ADVERTISERS) {
                    advertiserSlotFailuresV2++;
                    suspendPeripheralRole(Math.min(60_000L, 15_000L * advertiserSlotFailuresV2));
                    return;
                }
                scheduleAdvertiseRetry("error_" + errorCode);
                syncLegacyState();
            }
        };

        private final ScanCallback coreScanCallback = new ScanCallback() {
            @Override public void onScanResult(int callbackType, ScanResult result) { handleScan(result); }
            @Override public void onBatchScanResults(List<ScanResult> results) {
                if (results == null) return;
                for (ScanResult result : results) handleScan(result);
            }
            @Override public void onScanFailed(int errorCode) {
                scanActive = false;
                lastPhaseV2 = "scan_failed";
                lastErrorV2 = "scan_error_" + errorCode;
                long delay = errorCode == 6 ? 10_000L : (errorCode == 5 ? 9_000L : 3_000L);
                handler.postDelayed(() -> startScan(), delay);
                syncLegacyState();
            }
        };

        private final BluetoothGattCallback coreClientCallback = new BluetoothGattCallback() {
            @Override public void onConnectionStateChange(BluetoothGatt gatt, int status, int newState) {
                handler.post(() -> {
                    gattCallbacksV2++;
                    lastNativeGattStatusV2 = status;
                    lastNativeGattStateV2 = newState;
                    ClientLink link = clientLinks.get(gatt);
                    if (link == null) {
                        try { gatt.close(); } catch (Throwable ignored) {}
                        return;
                    }
                    if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                        afterConnected(gatt);
                        return;
                    }
                    if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                        if (status != BluetoothGatt.GATT_SUCCESS) lastGattErrorV2 = "disconnect status=" + status;
                        closeClient(gatt, status != BluetoothGatt.GATT_SUCCESS, "disconnected");
                        return;
                    }
                    if (status != BluetoothGatt.GATT_SUCCESS) {
                        lastGattErrorV2 = "connection status=" + status;
                        closeClient(gatt, true, "connection_status");
                    }
                });
            }

            @Override public void onMtuChanged(BluetoothGatt gatt, int mtu, int status) {
                handler.post(() -> {
                    ClientLink link = clientLinks.get(gatt);
                    if (link == null) return;
                    if (status == BluetoothGatt.GATT_SUCCESS && mtu >= 23) link.mtu = mtu;
                    discoverServices(gatt);
                });
            }

            @Override public void onServicesDiscovered(BluetoothGatt gatt, int status) {
                handler.post(() -> afterServices(gatt, status));
            }

            @Override public void onCharacteristicRead(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
                byte[] value = characteristic == null ? null : characteristic.getValue();
                if (characteristic != null && IDENTITY_UUID.equals(characteristic.getUuid())) handler.post(() -> handleIdentity(gatt, value, status));
            }

            @Override public void onCharacteristicRead(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, byte[] value, int status) {
                if (characteristic != null && IDENTITY_UUID.equals(characteristic.getUuid())) handler.post(() -> handleIdentity(gatt, value, status));
            }

            @Override public void onCharacteristicWrite(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
                handler.post(() -> {
                    if (characteristic == null) return;
                    if (IDENTITY_UUID.equals(characteristic.getUuid())) {
                        sendPacketIfAny(gatt);
                        return;
                    }
                    if (WRITE_UUID.equals(characteristic.getUuid())) {
                        if (status != BluetoothGatt.GATT_SUCCESS) {
                            lastGattErrorV2 = "frame write status=" + status;
                            closeClient(gatt, true, "write_status");
                        } else writeNextFrame(gatt);
                    }
                });
            }
        };

        private final BluetoothGattServerCallback coreServerCallback = new BluetoothGattServerCallback() {
            @Override public void onServiceAdded(int status, BluetoothGattService service) {
                handler.post(() -> {
                    if (!started || service == null || !SERVICE_UUID.equals(service.getUuid())) return;
                    if (status == BluetoothGatt.GATT_SUCCESS) {
                        serverReadyV2 = true;
                        lastPhaseV2 = "gatt_server_ready";
                        handler.postDelayed(() -> startAdvertising(), 300L);
                    } else {
                        serverReadyV2 = false;
                        lastErrorV2 = "gatt_server_service_" + status;
                        try { if (localServer != null) localServer.close(); } catch (Throwable ignored) {}
                        localServer = null;
                        handler.postDelayed(() -> setupServer(), 1_000L);
                    }
                    syncLegacyState();
                });
            }

            @Override public void onConnectionStateChange(BluetoothDevice device, int status, int newState) {
                handler.post(() -> {
                    lastServerStatusV2 = status;
                    lastServerStateV2 = newState;
                    try { lastServerPeerV2 = device == null ? "" : device.getAddress(); } catch (Throwable ignored) { lastServerPeerV2 = ""; }
                    if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                        serverConnectionsV2++;
                        lastPhaseV2 = "gatt_server_connected";
                    }
                    syncLegacyState();
                });
            }

            @Override public void onCharacteristicReadRequest(BluetoothDevice device, int requestId, int offset, BluetoothGattCharacteristic characteristic) {
                if (localServer == null || characteristic == null || !IDENTITY_UUID.equals(characteristic.getUuid())) {
                    try { if (localServer != null) localServer.sendResponse(device, requestId, BluetoothGatt.GATT_FAILURE, offset, null); } catch (Throwable ignored) {}
                    return;
                }
                try {
                    byte[] identity = localIdentityPayload();
                    if (identity == null || offset < 0 || offset > identity.length) {
                        localServer.sendResponse(device, requestId, BluetoothGatt.GATT_FAILURE, offset, null);
                        return;
                    }
                    byte[] slice = Arrays.copyOfRange(identity, offset, identity.length);
                    localServer.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, offset, slice);
                } catch (Throwable ignored) {
                    try { localServer.sendResponse(device, requestId, BluetoothGatt.GATT_FAILURE, offset, null); } catch (Throwable ignored2) {}
                }
            }

            @Override public void onCharacteristicWriteRequest(
                BluetoothDevice device, int requestId, BluetoothGattCharacteristic characteristic,
                boolean preparedWrite, boolean responseNeeded, int offset, byte[] value
            ) {
                int status = BluetoothGatt.GATT_FAILURE;
                try {
                    if (characteristic != null && IDENTITY_UUID.equals(characteristic.getUuid()) && value != null) {
                        String wallet = walletFromBytes(value);
                        if (wallet != null && device != null) {
                            String address = device.getAddress();
                            int rssi = peerRssi.containsKey(address) ? peerRssi.get(address) : 0;
                            publishResolvedPeer(address, wallet, "", rssi, System.currentTimeMillis());
                            lastWalletV2 = wallet;
                            identityReadsV2++;
                            status = BluetoothGatt.GATT_SUCCESS;
                        }
                    } else if (characteristic != null && WRITE_UUID.equals(characteristic.getUuid()) && value != null) {
                        status = acceptFrame(device, new String(value, StandardCharsets.UTF_8))
                            ? BluetoothGatt.GATT_SUCCESS : BluetoothGatt.GATT_FAILURE;
                    }
                } catch (Throwable ignored) {}
                if (responseNeeded && localServer != null) {
                    try { localServer.sendResponse(device, requestId, status, 0, null); } catch (Throwable ignored) {}
                }
            }

            @Override public void onDescriptorWriteRequest(
                BluetoothDevice device, int requestId, BluetoothGattDescriptor descriptor,
                boolean preparedWrite, boolean responseNeeded, int offset, byte[] value
            ) {
                if (responseNeeded && localServer != null) {
                    try { localServer.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, 0, null); } catch (Throwable ignored) {}
                }
            }
        };

        private boolean containsService(ScanResult result) {
            try {
                if (result == null || result.getScanRecord() == null) return false;
                List<ParcelUuid> uuids = result.getScanRecord().getServiceUuids();
                if (uuids == null) return false;
                ParcelUuid expected = new ParcelUuid(SERVICE_UUID);
                for (ParcelUuid uuid : uuids) if (expected.equals(uuid)) return true;
            } catch (Throwable ignored) {}
            return false;
        }

        private byte[] peerId(ScanResult result) {
            try {
                if (result == null || result.getScanRecord() == null) return null;
                byte[] data = result.getScanRecord().getServiceData(new ParcelUuid(SERVICE_UUID));
                if (data == null || data.length < 8) return null;
                return Arrays.copyOf(data, 8);
            } catch (Throwable ignored) { return null; }
        }

        private byte[] stablePeerId() {
            try {
                MessageDigest digest = MessageDigest.getInstance("SHA-256");
                byte[] hash = digest.digest((deviceId == null ? "blee" : deviceId).getBytes(StandardCharsets.UTF_8));
                return Arrays.copyOf(hash, 8);
            } catch (Throwable ignored) {
                long value = (deviceId == null ? "blee" : deviceId).hashCode() & 0xffffffffL;
                return new byte[] {0,0,0,0,(byte)(value>>>24),(byte)(value>>>16),(byte)(value>>>8),(byte)value};
            }
        }

        private boolean samePeer(byte[] a, byte[] b) { return a != null && b != null && Arrays.equals(a, b); }

        private int compare(byte[] a, byte[] b) {
            if (a == null || b == null) return 0;
            int n = Math.min(a.length, b.length);
            for (int i = 0; i < n; i++) {
                int x = a[i] & 0xff, y = b[i] & 0xff;
                if (x != y) return x < y ? -1 : 1;
            }
            return Integer.compare(a.length, b.length);
        }

        private String hex(byte[] value) {
            if (value == null) return "";
            StringBuilder out = new StringBuilder();
            for (byte b : value) out.append(String.format(Locale.ROOT, "%02x", b & 0xff));
            return out.toString();
        }

        private String message(Throwable error) {
            if (error == null) return "unknown";
            String value = error.getMessage();
            return value == null || value.isEmpty() ? error.toString() : value;
        }

        private String radioMode() {
            if (!addressLinks.isEmpty()) return "gatt_session";
            if (scanActive && advertiseActive) return "dual_role";
            if (scanActive && !advertiseActive && System.currentTimeMillis() < advertiseSuppressedUntilV2) return "scanner_first";
            if (scanActive) return "scanner_only";
            if (advertiseActive) return "advertiser_only";
            return "idle";
        }

        private void syncLegacyState() {
            BleeMeshService.this.scanning = scanActive;
            BleeMeshService.this.advertising = advertiseActive;
            BleeMeshService.this.advertiseStarting = advertiseStartingV2;
            BleeMeshService.this.gattServerReady = serverReadyV2;
        }

        JSONObject snapshot() {
            JSONObject out = new JSONObject();
            try {
                out.put("transportEngine", "ble_core_v2");
                out.put("scannerAvailable", localScanner != null);
                out.put("advertiserAvailable", localAdvertiser != null);
                out.put("scannerActive", scanActive);
                out.put("advertiserActive", advertiseActive);
                out.put("advertiserStarting", advertiseStartingV2);
                out.put("gattServerActive", localServer != null);
                out.put("gattServerReady", serverReadyV2);
                out.put("radioMode", radioMode());
                out.put("advertiserResourceFailures", advertiserSlotFailuresV2);
                out.put("scanStarts", scanStartsV2);
                out.put("rawScanResults", rawScanResultsV2);
                out.put("bleeAdvertisements", bleAdvertisementsV2);
                out.put("advertiseStarts", advertiseStartsV2);
                out.put("advertiseSuccesses", advertiseSuccessesV2);
                out.put("advertiseFailures", advertiseFailuresV2);
                out.put("gattAttempts", gattAttemptsV2);
                out.put("gattConnected", gattConnectionsV2);
                out.put("servicesDiscovered", servicesDiscoveredV2);
                out.put("identityReads", identityReadsV2);
                out.put("identityFailures", identityFailuresV2);
                out.put("serverConnections", serverConnectionsV2);
                out.put("gattConnectionCallbacks", gattCallbacksV2);
                out.put("lastSeenAt", lastSeenAtV2);
                out.put("lastRssi", lastRssiV2);
                out.put("lastTransportId", lastTransportIdV2);
                out.put("lastWallet", lastWalletV2);
                out.put("lastPhase", lastPhaseV2);
                out.put("lastError", lastErrorV2);
                out.put("lastAdvertiseError", lastAdvertiseErrorV2);
                out.put("lastGattError", lastGattErrorV2);
                out.put("lastServerPeer", lastServerPeerV2);
                out.put("lastServerStatus", lastServerStatusV2);
                out.put("lastServerState", lastServerStateV2);
                out.put("lastScanConnectable", lastScanConnectableV2);
                out.put("lastAddressType", lastAddressTypeV2);
                out.put("lastDeviceType", lastDeviceTypeV2);
                out.put("lastNativeGattStatus", lastNativeGattStatusV2);
                out.put("lastNativeGattState", lastNativeGattStateV2);
                out.put("lastConnectStrategy", lastConnectStrategyV2);
                out.put("gattScanPaused", false);
            } catch (Throwable ignored) {}
            return out;
        }
    }

'''
    text = once(text, start_marker, core + start_marker, "transport core insertion")

    start_replacement = r'''    private void startBluetooth() {
        if (!bluetoothPermissionsGranted()) return;
        if (bleTransportV2 == null) bleTransportV2 = new BleTransportV2();
        bleTransportV2.start();
    }

'''
    text = between(text, "    private void startBluetooth() {", "    private void stopBluetooth() {", start_replacement, "startBluetooth")

    stop_replacement = r'''    private void stopBluetooth() {
        if (bleTransportV2 != null) bleTransportV2.stop();
        scanning = false;
        advertising = false;
        advertiseStarting = false;
        gattServerReady = false;
    }

'''
    text = between(text, "    private void stopBluetooth() {", "    private void startGattServer() {", stop_replacement, "stopBluetooth")

    if "maintainBleReliability();" not in text:
        raise SystemExit("Blee transport v2: legacy maintenance anchor missing")
    text = text.replace("maintainBleReliability();", "if (bleTransportV2 != null) bleTransportV2.maintain();", 1)

    diag_anchor = '''            String ownWallet = service.db == null ? null : service.db.activeWallet();
            out.put("localWalletResolved", ownWallet != null && ownWallet.matches("^0x[0-9a-fA-F]{40}$"));'''
    diag_new = diag_anchor + r'''
            if (service.bleTransportV2 != null) {
                JSONObject transport = service.bleTransportV2.snapshot();
                java.util.Iterator<String> transportKeys = transport.keys();
                while (transportKeys.hasNext()) {
                    String key = transportKeys.next();
                    out.put(key, transport.opt(key));
                }
            }'''
    text = once(text, diag_anchor, diag_new, "diagnostics overlay")

    path.write_text(text)


def patch_runtime() -> None:
    path = ROOT / "src/components/BleeRuntime.tsx"
    if not path.is_file():
        raise SystemExit("Blee transport v2: generated runtime missing")
    text = path.read_text()
    if "BLEE_TRANSPORT_CORE_V2_DIAGNOSTICS" in text:
        return
    marker = "  ['radioMode', 'Radio mode'],"
    if marker not in text:
        raise SystemExit("Blee transport v2: runtime diagnostics row anchor missing")
    text = text.replace(
        marker,
        "  // BLEE_TRANSPORT_CORE_V2_DIAGNOSTICS\n  ['transportEngine', 'Transport engine'],\n" + marker,
        1,
    )
    path.write_text(text)


def verify(native_dir: Path) -> None:
    service = (native_dir / "BleeMeshService.java").read_text()
    runtime = (ROOT / "src/components/BleeRuntime.tsx").read_text()
    required = (
        "BLEE_TRANSPORT_CORE_V2",
        "class BleTransportV2",
        "direct_scan_result",
        "setServiceUuid(new ParcelUuid(SERVICE_UUID))",
        "addServiceData(new ParcelUuid(SERVICE_UUID), localPeerId)",
        "PROPERTY_WRITE_NO_RESPONSE",
        "CCCD_UUID",
        "connectGatt(BleeMeshService.this, false, coreClientCallback, BluetoothDevice.TRANSPORT_LE)",
        "requestMtu(PREFERRED_MTU)",
        "duePacketsForPeer",
        "recordPeerDelivery",
        "acceptFrame(device",
        "bleTransportV2.maintain()",
        "transportEngine",
    )
    missing = [m for m in required if m not in service]
    if missing:
        raise SystemExit(f"Blee transport v2 verification failed: {missing}")
    start_block = service[service.index("private void startBluetooth()"):service.index("private void stopBluetooth()")]
    if "bleTransportV2.start()" not in start_block or "startGattServer()" in start_block:
        raise SystemExit("Blee transport v2: legacy BLE owner still controls startBluetooth")
    if "BLEE_TRANSPORT_CORE_V2_DIAGNOSTICS" not in runtime:
        raise SystemExit("Blee transport v2: runtime diagnostics marker missing")
    print("Blee transport core v2 installed and verified")


def main() -> None:
    native_dir = locate_activity().parent
    patch_service(native_dir)
    patch_runtime()
    verify(native_dir)


if __name__ == "__main__":
    main()
