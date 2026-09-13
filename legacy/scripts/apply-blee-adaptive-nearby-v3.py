#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android/app/src/main"
ANDROID_JAVA = ANDROID / "java"


def once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Blee adaptive v3: missing {label} anchor")
    return text.replace(old, new, 1)


def locate_activity() -> Path:
    hits = list(ANDROID_JAVA.rglob("MainActivity.java"))
    if len(hits) != 1:
        raise SystemExit(f"Blee adaptive v3: expected one MainActivity.java, found {len(hits)}")
    return hits[0]


def patch_gradle() -> None:
    path = ROOT / "android/app/build.gradle"
    if not path.is_file():
        raise SystemExit("Blee adaptive v3: android/app/build.gradle missing")
    text = path.read_text()
    dep = "implementation 'com.google.android.gms:play-services-nearby:19.5.0'"
    if dep in text:
        return
    match = re.search(r"(?m)^dependencies\s*\{", text)
    if not match:
        raise SystemExit("Blee adaptive v3: Gradle dependencies block missing")
    pos = match.end()
    text = text[:pos] + "\n    // BLEE_ADAPTIVE_NEARBY_V3\n    " + dep + text[pos:]
    path.write_text(text)


def patch_manifest() -> None:
    path = ANDROID / "AndroidManifest.xml"
    if not path.is_file():
        raise SystemExit("Blee adaptive v3: AndroidManifest.xml missing")
    text = path.read_text()
    marker = "<application"
    pos = text.find(marker)
    if pos < 0:
        raise SystemExit("Blee adaptive v3: application manifest anchor missing")
    permissions = (
        ('android.permission.ACCESS_WIFI_STATE', ''),
        ('android.permission.CHANGE_WIFI_STATE', ''),
        ('android.permission.NEARBY_WIFI_DEVICES', ' android:usesPermissionFlags="neverForLocation"'),
    )
    additions = []
    for name, extra in permissions:
        if f'android:name="{name}"' not in text:
            additions.append(f'    <uses-permission android:name="{name}"{extra} />\n')
    if additions:
        text = text[:pos] + ''.join(additions) + text[pos:]
    if "BLEE_ADAPTIVE_NEARBY_V3" not in text:
        text = text.replace("<manifest", "<!-- BLEE_ADAPTIVE_NEARBY_V3 -->\n<manifest", 1)
    path.write_text(text)


def patch_activity(activity: Path) -> None:
    text = activity.read_text()
    if "BLEE_ADAPTIVE_NEARBY_PERMISSION_V3" in text:
        return
    anchor = '''            if (checkSelfPermission(Manifest.permission.BLUETOOTH_ADVERTISE) != PackageManager.PERMISSION_GRANTED) {
                missing.add(Manifest.permission.BLUETOOTH_ADVERTISE);
            }'''
    addition = anchor + '''
            // BLEE_ADAPTIVE_NEARBY_PERMISSION_V3
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && checkSelfPermission(Manifest.permission.NEARBY_WIFI_DEVICES) != PackageManager.PERMISSION_GRANTED) {
                missing.add(Manifest.permission.NEARBY_WIFI_DEVICES);
            }'''
    text = once(text, anchor, addition, "Nearby Wi-Fi runtime permission")
    activity.write_text(text)


def add_imports(text: str) -> str:
    imports = (
        "import com.google.android.gms.nearby.Nearby;",
        "import com.google.android.gms.nearby.connection.AdvertisingOptions;",
        "import com.google.android.gms.nearby.connection.ConnectionInfo;",
        "import com.google.android.gms.nearby.connection.ConnectionLifecycleCallback;",
        "import com.google.android.gms.nearby.connection.ConnectionOptions;",
        "import com.google.android.gms.nearby.connection.ConnectionResolution;",
        "import com.google.android.gms.nearby.connection.ConnectionsClient;",
        "import com.google.android.gms.nearby.connection.ConnectionsStatusCodes;",
        "import com.google.android.gms.nearby.connection.DiscoveredEndpointInfo;",
        "import com.google.android.gms.nearby.connection.DiscoveryOptions;",
        "import com.google.android.gms.nearby.connection.EndpointDiscoveryCallback;",
        "import com.google.android.gms.nearby.connection.Payload;",
        "import com.google.android.gms.nearby.connection.PayloadCallback;",
        "import com.google.android.gms.nearby.connection.PayloadTransferUpdate;",
        "import com.google.android.gms.nearby.connection.Strategy;",
    )
    anchor = "import org.json.JSONArray;"
    if anchor not in text:
        raise SystemExit("Blee adaptive v3: Java import anchor missing")
    missing = [line for line in imports if line not in text]
    if missing:
        text = text.replace(anchor, "\n".join(missing) + "\n\n" + anchor, 1)
    if "import java.util.HashSet;" not in text:
        text = text.replace("import java.util.HashMap;", "import java.util.HashMap;\nimport java.util.HashSet;\nimport java.util.Set;", 1)
    return text


def patch_service(native_dir: Path) -> None:
    path = native_dir / "BleeMeshService.java"
    text = path.read_text()
    if "BLEE_ADAPTIVE_NEARBY_V3" in text:
        return
    if "BLEE_TRANSPORT_CORE_V2" not in text or "class BleTransportV2" not in text:
        raise SystemExit("Blee adaptive v3: Transport Core V2 must run first")
    text = add_imports(text)

    text = once(
        text,
        "    private BleTransportV2 bleTransportV2;",
        '''    private BleTransportV2 bleTransportV2;
    // BLEE_ADAPTIVE_NEARBY_V3
    private AdaptiveNearbyV3 adaptiveNearbyV3;''',
        "adaptive transport field",
    )

    core_anchor = '''    // BLEE_TRANSPORT_CORE_V2
    // One runtime owner for BLE scanning, advertising, GATT server and GATT client.'''
    adaptive = r'''    // BLEE_ADAPTIVE_NEARBY_V3
    // Raw BLE remains the first-choice transport. If Android's native GATT layer
    // cannot establish a link (notably status 147 / GATT_CONNECTION_TIMEOUT),
    // Blee switches both discovery and payload delivery to Nearby Connections.
    // Nearby Connections can select Bluetooth/Wi-Fi radios locally; it does not
    // change Blee's payment authorization or settlement semantics.
    private final class AdaptiveNearbyV3 {
        private static final String NEARBY_SERVICE_ID = "com.blee.payments.nearby.v3";
        private static final long BLE_GRACE_MS = 15_000L;
        private static final long DUAL_SCAN_ON_MS = 8_000L;
        private static final long DUAL_SCAN_OFF_MS = 2_000L;
        private static final int GATT_TIMEOUT_THRESHOLD = 2;
        private static final int MAX_NEARBY_PACKET_BYTES = 900_000;

        private boolean active = false;
        private boolean fallbackActive = false;
        private boolean fallbackStarting = false;
        private boolean nearbyAdvertising = false;
        private boolean nearbyDiscovering = false;
        private long startedAt = 0L;
        private long dualCycleStartedAt = 0L;
        private long lastNearbyPumpAt = 0L;
        private int gatt147Count = 0;
        private int endpointsFound = 0;
        private int nearbyConnections = 0;
        private String fallbackReason = "";
        private String lastNearbyError = "";
        private String lastNearbyStatus = "idle";

        private ConnectionsClient connectionsClient;
        private final Set<String> connectedEndpoints = Collections.synchronizedSet(new HashSet<String>());
        private final Map<String, byte[]> endpointPeerIds = Collections.synchronizedMap(new HashMap<String, byte[]>());
        private final Map<String, String> endpointTransportIds = Collections.synchronizedMap(new HashMap<String, String>());
        private final Map<Long, NearbyPending> pendingPayloads = Collections.synchronizedMap(new HashMap<Long, NearbyPending>());

        private final class NearbyPending {
            final String messageId;
            final String transportId;
            NearbyPending(String messageId, String transportId) {
                this.messageId = messageId;
                this.transportId = transportId;
            }
        }

        void start() {
            if (active) return;
            active = true;
            startedAt = System.currentTimeMillis();
            dualCycleStartedAt = startedAt;
            fallbackActive = false;
            fallbackStarting = false;
            lastNearbyStatus = "ble_primary";
            if (bleTransportV2 == null) bleTransportV2 = new BleTransportV2();
            bleTransportV2.start();
        }

        void stop() {
            active = false;
            stopNearby();
            if (bleTransportV2 != null) bleTransportV2.stop();
            fallbackActive = false;
            fallbackStarting = false;
            lastNearbyStatus = "stopped";
        }

        void maintain() {
            if (!active) return;
            long now = System.currentTimeMillis();
            if (fallbackActive || fallbackStarting) {
                if (fallbackActive && now - lastNearbyPumpAt >= 2_000L) {
                    lastNearbyPumpAt = now;
                    pumpNearbyPackets();
                }
                return;
            }

            boolean unresolved = nearbyPeersSnapshot().isEmpty();
            if (gatt147Count >= GATT_TIMEOUT_THRESHOLD) {
                activateNearby("gatt_timeout_147");
                return;
            }
            if (unresolved && startedAt > 0L && now - startedAt >= BLE_GRACE_MS) {
                activateNearby("ble_peer_unresolved");
                return;
            }

            if (bleTransportV2 == null) bleTransportV2 = new BleTransportV2();
            // Match Bitchat Android's balanced duty-cycle idea: when this phone
            // is simultaneously a peripheral and scanner, preserve a clean radio
            // window for inbound links instead of scanning at full duty forever.
            if (bleTransportV2.advertiseActive) {
                long period = DUAL_SCAN_ON_MS + DUAL_SCAN_OFF_MS;
                long phase = (now - dualCycleStartedAt) % period;
                boolean scanWindow = phase < DUAL_SCAN_ON_MS;
                bleTransportV2.setAdaptiveScanEnabled(scanWindow);
                if (scanWindow) bleTransportV2.maintain();
            } else {
                bleTransportV2.setAdaptiveScanEnabled(true);
                bleTransportV2.maintain();
            }
        }

        void onGattFailure(int status) {
            if (status == 147) {
                gatt147Count++;
                if (gatt147Count >= GATT_TIMEOUT_THRESHOLD) activateNearby("gatt_timeout_147");
            }
        }

        private boolean nearbyPermissionsGranted() {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && checkSelfPermission(Manifest.permission.NEARBY_WIFI_DEVICES) != PackageManager.PERMISSION_GRANTED) return false;
            return bluetoothPermissionsGranted();
        }

        private void activateNearby(String reason) {
            if (!active || fallbackActive || fallbackStarting) return;
            if (!nearbyPermissionsGranted()) {
                fallbackReason = reason;
                lastNearbyStatus = "permission_required";
                lastNearbyError = "Nearby devices permission is required";
                return;
            }
            fallbackStarting = true;
            fallbackReason = reason;
            lastNearbyStatus = "nearby_starting";
            if (bleTransportV2 != null) bleTransportV2.stop();
            try {
                connectionsClient = Nearby.getConnectionsClient(BleeMeshService.this);
                connectionsClient.stopAdvertising();
                connectionsClient.stopDiscovery();
                connectionsClient.stopAllEndpoints();
                connectedEndpoints.clear();
                endpointPeerIds.clear();
                endpointTransportIds.clear();
                pendingPayloads.clear();
                startNearbyAdvertising();
                startNearbyDiscovery();
            } catch (Throwable error) {
                fallbackStarting = false;
                fallbackActive = false;
                lastNearbyStatus = "nearby_unavailable";
                lastNearbyError = message(error);
                handler.postDelayed(() -> resumeBlePrimary("nearby_start_exception"), 5_000L);
            }
        }

        private void startNearbyAdvertising() {
            if (connectionsClient == null) return;
            AdvertisingOptions options = new AdvertisingOptions.Builder()
                .setStrategy(Strategy.P2P_CLUSTER)
                .setLowPower(false)
                .build();
            connectionsClient.startAdvertising(localPeerIdBytes(), NEARBY_SERVICE_ID, nearbyLifecycleCallback, options)
                .addOnSuccessListener(unused -> {
                    nearbyAdvertising = true;
                    fallbackActive = true;
                    fallbackStarting = false;
                    lastNearbyStatus = "nearby_active";
                    lastNearbyError = "";
                })
                .addOnFailureListener(error -> {
                    nearbyAdvertising = false;
                    lastNearbyError = message(error);
                    maybeNearbyStartFailed();
                });
        }

        private void startNearbyDiscovery() {
            if (connectionsClient == null) return;
            DiscoveryOptions options = new DiscoveryOptions.Builder()
                .setStrategy(Strategy.P2P_CLUSTER)
                .setLowPower(false)
                .build();
            connectionsClient.startDiscovery(NEARBY_SERVICE_ID, nearbyDiscoveryCallback, options)
                .addOnSuccessListener(unused -> {
                    nearbyDiscovering = true;
                    fallbackActive = true;
                    fallbackStarting = false;
                    lastNearbyStatus = "nearby_active";
                    lastNearbyError = "";
                })
                .addOnFailureListener(error -> {
                    nearbyDiscovering = false;
                    lastNearbyError = message(error);
                    maybeNearbyStartFailed();
                });
        }

        private void maybeNearbyStartFailed() {
            handler.postDelayed(() -> {
                if (!active || fallbackActive || nearbyAdvertising || nearbyDiscovering) return;
                fallbackStarting = false;
                lastNearbyStatus = "nearby_start_failed";
                resumeBlePrimary("nearby_start_failed");
            }, 1_200L);
        }

        private void resumeBlePrimary(String reason) {
            if (!active) return;
            stopNearby();
            fallbackActive = false;
            fallbackStarting = false;
            startedAt = System.currentTimeMillis();
            dualCycleStartedAt = startedAt;
            gatt147Count = 0;
            fallbackReason = reason;
            lastNearbyStatus = "ble_primary";
            if (bleTransportV2 == null) bleTransportV2 = new BleTransportV2();
            bleTransportV2.start();
        }

        private void stopNearby() {
            if (connectionsClient != null) {
                try { connectionsClient.stopAdvertising(); } catch (Throwable ignored) {}
                try { connectionsClient.stopDiscovery(); } catch (Throwable ignored) {}
                try { connectionsClient.stopAllEndpoints(); } catch (Throwable ignored) {}
            }
            nearbyAdvertising = false;
            nearbyDiscovering = false;
            connectedEndpoints.clear();
            endpointPeerIds.clear();
            endpointTransportIds.clear();
            pendingPayloads.clear();
        }

        private byte[] localPeerIdBytes() {
            if (bleTransportV2 != null && bleTransportV2.localPeerId != null) return Arrays.copyOf(bleTransportV2.localPeerId, bleTransportV2.localPeerId.length);
            try {
                MessageDigest digest = MessageDigest.getInstance("SHA-256");
                return Arrays.copyOf(digest.digest((deviceId == null ? "blee" : deviceId).getBytes(StandardCharsets.UTF_8)), 8);
            } catch (Throwable ignored) {
                return new byte[] {0,0,0,0,0,0,0,1};
            }
        }

        private byte[] normalizePeerInfo(byte[] value) {
            if (value == null || value.length < 8) return null;
            return Arrays.copyOf(value, 8);
        }

        private String nearbyTransportId(byte[] peerId, String endpointId) {
            if (peerId != null && peerId.length >= 8) return "nc:" + hexBytes(Arrays.copyOf(peerId, 8));
            return "nc:endpoint:" + (endpointId == null ? "unknown" : endpointId);
        }

        private String hexBytes(byte[] value) {
            if (value == null) return "";
            StringBuilder out = new StringBuilder();
            for (byte b : value) out.append(String.format(Locale.ROOT, "%02x", b & 0xff));
            return out.toString();
        }

        private int comparePeerIds(byte[] a, byte[] b) {
            if (a == null || b == null) return 0;
            int n = Math.min(a.length, b.length);
            for (int i = 0; i < n; i++) {
                int x = a[i] & 0xff, y = b[i] & 0xff;
                if (x != y) return x < y ? -1 : 1;
            }
            return Integer.compare(a.length, b.length);
        }

        private final EndpointDiscoveryCallback nearbyDiscoveryCallback = new EndpointDiscoveryCallback() {
            @Override public void onEndpointFound(String endpointId, DiscoveredEndpointInfo info) {
                endpointsFound++;
                byte[] remote = normalizePeerInfo(info == null ? null : info.getEndpointInfo());
                if (remote != null && Arrays.equals(remote, localPeerIdBytes())) return;
                if (remote != null) {
                    endpointPeerIds.put(endpointId, remote);
                    endpointTransportIds.put(endpointId, nearbyTransportId(remote, endpointId));
                }
                if (connectionsClient == null || connectedEndpoints.contains(endpointId)) return;
                // Deterministic tie-break prevents both endpoints requesting each
                // other simultaneously when both advertise and discover.
                if (remote != null && comparePeerIds(localPeerIdBytes(), remote) > 0) return;
                ConnectionOptions options = new ConnectionOptions.Builder().setLowPower(false).build();
                connectionsClient.requestConnection(localPeerIdBytes(), endpointId, nearbyLifecycleCallback, options)
                    .addOnFailureListener(error -> {
                        lastNearbyStatus = "nearby_request_failed";
                        lastNearbyError = message(error);
                    });
            }

            @Override public void onEndpointLost(String endpointId) {
                if (!connectedEndpoints.contains(endpointId)) {
                    endpointPeerIds.remove(endpointId);
                    endpointTransportIds.remove(endpointId);
                }
            }
        };

        private final ConnectionLifecycleCallback nearbyLifecycleCallback = new ConnectionLifecycleCallback() {
            @Override public void onConnectionInitiated(String endpointId, ConnectionInfo info) {
                byte[] remote = normalizePeerInfo(info == null ? null : info.getEndpointInfo());
                if (remote != null) {
                    endpointPeerIds.put(endpointId, remote);
                    endpointTransportIds.put(endpointId, nearbyTransportId(remote, endpointId));
                }
                if (connectionsClient != null) {
                    connectionsClient.acceptConnection(endpointId, nearbyPayloadCallback)
                        .addOnFailureListener(error -> {
                            lastNearbyStatus = "nearby_accept_failed";
                            lastNearbyError = message(error);
                        });
                }
            }

            @Override public void onConnectionResult(String endpointId, ConnectionResolution result) {
                int status = result == null || result.getStatus() == null
                    ? ConnectionsStatusCodes.STATUS_ERROR : result.getStatus().getStatusCode();
                if (status == ConnectionsStatusCodes.STATUS_OK) {
                    connectedEndpoints.add(endpointId);
                    nearbyConnections++;
                    lastNearbyStatus = "nearby_connected";
                    lastNearbyError = "";
                    try { if (connectionsClient != null) connectionsClient.stopDiscovery(); } catch (Throwable ignored) {}
                    nearbyDiscovering = false;
                    sendNearbyIdentity(endpointId);
                    handler.postDelayed(() -> pumpNearbyPacket(endpointId), 250L);
                } else {
                    lastNearbyStatus = "nearby_connection_failed_" + status;
                    lastNearbyError = "Nearby connection status=" + status;
                }
            }

            @Override public void onDisconnected(String endpointId) {
                connectedEndpoints.remove(endpointId);
                endpointPeerIds.remove(endpointId);
                endpointTransportIds.remove(endpointId);
                lastNearbyStatus = "nearby_disconnected";
                if (active && fallbackActive) {
                    handler.postDelayed(() -> {
                        if (!active || !fallbackActive || connectionsClient == null) return;
                        if (!nearbyDiscovering) startNearbyDiscovery();
                        if (!nearbyAdvertising) startNearbyAdvertising();
                    }, 750L);
                }
            }
        };

        private final PayloadCallback nearbyPayloadCallback = new PayloadCallback() {
            @Override public void onPayloadReceived(String endpointId, Payload payload) {
                if (payload == null || payload.getType() != Payload.Type.BYTES) return;
                byte[] bytes = payload.asBytes();
                if (bytes == null || bytes.length == 0 || bytes.length > MAX_NEARBY_PACKET_BYTES) return;
                handleNearbyBytes(endpointId, bytes);
            }

            @Override public void onPayloadTransferUpdate(String endpointId, PayloadTransferUpdate update) {
                if (update == null) return;
                if (update.getStatus() == PayloadTransferUpdate.Status.SUCCESS) {
                    NearbyPending pending = pendingPayloads.remove(update.getPayloadId());
                    if (pending != null) db.recordPeerDelivery(pending.messageId, pending.transportId);
                } else if (update.getStatus() == PayloadTransferUpdate.Status.FAILURE
                    || update.getStatus() == PayloadTransferUpdate.Status.CANCELED) {
                    NearbyPending pending = pendingPayloads.remove(update.getPayloadId());
                    if (pending != null) db.recordAttempt(pending.messageId);
                }
            }
        };

        private void sendNearbyIdentity(String endpointId) {
            if (connectionsClient == null || !connectedEndpoints.contains(endpointId)) return;
            try {
                JSONObject identity = new JSONObject(new String(localIdentityPayload(), StandardCharsets.UTF_8));
                identity.put("kind", "blee_identity_v3");
                identity.put("peerId", hexBytes(localPeerIdBytes()));
                connectionsClient.sendPayload(endpointId, Payload.fromBytes(identity.toString().getBytes(StandardCharsets.UTF_8)));
            } catch (Throwable error) {
                lastNearbyError = message(error);
            }
        }

        private void handleNearbyBytes(String endpointId, byte[] bytes) {
            try {
                JSONObject envelope = new JSONObject(new String(bytes, StandardCharsets.UTF_8));
                String kind = envelope.optString("kind", "");
                if ("blee_identity_v3".equals(kind)) {
                    String wallet = envelope.optString("wallet", "");
                    String displayName = envelope.optString("displayName", "");
                    String peerHex = envelope.optString("peerId", "");
                    byte[] remote = endpointPeerIds.get(endpointId);
                    String transportId = remote == null ? endpointTransportIds.get(endpointId) : nearbyTransportId(remote, endpointId);
                    if ((transportId == null || transportId.isEmpty()) && peerHex.matches("^[0-9a-fA-F]{16}$")) transportId = "nc:" + peerHex.toLowerCase(Locale.ROOT);
                    if (transportId == null || transportId.isEmpty()) transportId = "nc:endpoint:" + endpointId;
                    endpointTransportIds.put(endpointId, transportId);
                    publishResolvedPeer(transportId, wallet, displayName, 0, System.currentTimeMillis());
                    pumpNearbyPacket(endpointId);
                    return;
                }
                if ("blee_packet_v3".equals(kind)) {
                    String raw = envelope.optString("raw", "");
                    if (raw.isEmpty() || raw.length() > MAX_NEARBY_PACKET_BYTES) return;
                    BleeMeshDb.ProcessResult result = db.receive(raw, deviceId, publicKey);
                    if (result.accepted && result.ledgerChanged) notifyLedgerChanged(result.paymentId, result.type);
                    if (result.notificationTitle != null) paymentNotification(result.notificationTitle, result.notificationBody, result.paymentId);
                    if (result.accepted) scheduleSenderFundedSettlement();
                }
            } catch (Throwable error) {
                lastNearbyError = message(error);
            }
        }

        private void pumpNearbyPackets() {
            List<String> endpoints;
            synchronized (connectedEndpoints) { endpoints = new ArrayList<String>(connectedEndpoints); }
            for (String endpointId : endpoints) pumpNearbyPacket(endpointId);
        }

        private void pumpNearbyPacket(String endpointId) {
            if (connectionsClient == null || !connectedEndpoints.contains(endpointId) || db == null) return;
            String transportId = endpointTransportIds.get(endpointId);
            if (transportId == null || transportId.isEmpty()) return;
            List<String> packets = db.duePacketsForPeer(System.currentTimeMillis(), transportId, 1);
            if (packets.isEmpty()) return;
            try {
                String raw = packets.get(0);
                JSONObject packet = new JSONObject(raw);
                String messageId = packet.optString("messageId", "");
                if (messageId.isEmpty()) return;
                JSONObject envelope = new JSONObject();
                envelope.put("kind", "blee_packet_v3");
                envelope.put("raw", raw);
                byte[] bytes = envelope.toString().getBytes(StandardCharsets.UTF_8);
                if (bytes.length > MAX_NEARBY_PACKET_BYTES) {
                    lastNearbyError = "Nearby packet exceeds byte payload limit";
                    return;
                }
                Payload payload = Payload.fromBytes(bytes);
                pendingPayloads.put(payload.getId(), new NearbyPending(messageId, transportId));
                connectionsClient.sendPayload(endpointId, payload)
                    .addOnFailureListener(error -> {
                        NearbyPending pending = pendingPayloads.remove(payload.getId());
                        if (pending != null) db.recordAttempt(pending.messageId);
                        lastNearbyError = message(error);
                    });
            } catch (Throwable error) {
                lastNearbyError = message(error);
            }
        }

        String mode() {
            if (fallbackStarting) return "nearby_starting";
            if (fallbackActive && !connectedEndpoints.isEmpty()) return "nearby_connected";
            if (fallbackActive) return "nearby_active";
            return "ble_primary";
        }

        JSONObject snapshot() {
            JSONObject out = new JSONObject();
            try {
                out.put("transportEngine", "adaptive_v3");
                out.put("fallbackMode", mode());
                out.put("fallbackReason", fallbackReason);
                out.put("gatt147Count", gatt147Count);
                out.put("nearbyAdvertising", nearbyAdvertising);
                out.put("nearbyDiscovering", nearbyDiscovering);
                out.put("nearbyEndpointsFound", endpointsFound);
                out.put("nearbyConnections", nearbyConnections);
                out.put("nearbyConnectedNow", connectedEndpoints.size());
                out.put("lastNearbyStatus", lastNearbyStatus);
                out.put("lastNearbyError", lastNearbyError);
            } catch (Throwable ignored) {}
            return out;
        }
    }

'''
    text = once(text, core_anchor, adaptive + core_anchor, "adaptive transport class")

    # Give dual-role devices a Bitchat-like balanced scan and explicit scan-off
    # window. Scanner-first devices still use low latency because they have no
    # peripheral role to protect.
    scan_anchor = '''                ScanSettings.Builder settings = new ScanSettings.Builder()
                    .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
                    .setReportDelay(0L);'''
    scan_new = '''                int adaptiveScanMode = advertiseActive
                    ? ScanSettings.SCAN_MODE_BALANCED
                    : ScanSettings.SCAN_MODE_LOW_LATENCY;
                ScanSettings.Builder settings = new ScanSettings.Builder()
                    .setScanMode(adaptiveScanMode)
                    .setReportDelay(0L);'''
    text = once(text, scan_anchor, scan_new, "adaptive BLE scan mode")

    scan_method_anchor = '''        private void startScan() {'''
    scan_control = r'''        private void setAdaptiveScanEnabled(boolean enabled) {
            if (!started || localScanner == null) return;
            if (enabled) {
                if (!scanActive) startScan();
                return;
            }
            if (scanActive) {
                try { localScanner.stopScan(coreScanCallback); } catch (Throwable ignored) {}
                scanActive = false;
                lastPhaseV2 = "adaptive_scan_window_off";
                syncLegacyState();
            }
        }

'''
    text = once(text, scan_method_anchor, scan_control + scan_method_anchor, "adaptive scan window control")

    # A Nearby transport identity is stable even though it is not a BLE MAC.
    text = once(
        text,
        '            peer.put("transport", "ble");',
        '            peer.put("transport", address.startsWith("nc:") ? "nearby" : "ble");',
        "peer transport classification",
    )

    disconnected_anchor = '''                    if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                        if (status != BluetoothGatt.GATT_SUCCESS) lastGattErrorV2 = "disconnect status=" + status;
                        closeClient(gatt, status != BluetoothGatt.GATT_SUCCESS, "disconnected");
                        return;
                    }'''
    disconnected_new = '''                    if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                        if (status != BluetoothGatt.GATT_SUCCESS) lastGattErrorV2 = "disconnect status=" + status;
                        if (status != BluetoothGatt.GATT_SUCCESS && adaptiveNearbyV3 != null) adaptiveNearbyV3.onGattFailure(status);
                        closeClient(gatt, status != BluetoothGatt.GATT_SUCCESS, "disconnected");
                        return;
                    }'''
    text = once(text, disconnected_anchor, disconnected_new, "GATT 147 adaptive fallback hook")

    start_old = '''    private void startBluetooth() {
        if (!bluetoothPermissionsGranted()) return;
        if (bleTransportV2 == null) bleTransportV2 = new BleTransportV2();
        bleTransportV2.start();
    }'''
    start_new = '''    private void startBluetooth() {
        if (!bluetoothPermissionsGranted()) return;
        if (adaptiveNearbyV3 == null) adaptiveNearbyV3 = new AdaptiveNearbyV3();
        adaptiveNearbyV3.start();
    }'''
    text = once(text, start_old, start_new, "adaptive start owner")

    stop_old = '''    private void stopBluetooth() {
        if (bleTransportV2 != null) bleTransportV2.stop();
        scanning = false;
        advertising = false;
        advertiseStarting = false;
        gattServerReady = false;
    }'''
    stop_new = '''    private void stopBluetooth() {
        if (adaptiveNearbyV3 != null) adaptiveNearbyV3.stop();
        else if (bleTransportV2 != null) bleTransportV2.stop();
        scanning = false;
        advertising = false;
        advertiseStarting = false;
        gattServerReady = false;
    }'''
    text = once(text, stop_old, stop_new, "adaptive stop owner")

    text = once(
        text,
        "if (bleTransportV2 != null) bleTransportV2.maintain();",
        "if (adaptiveNearbyV3 != null) adaptiveNearbyV3.maintain(); else if (bleTransportV2 != null) bleTransportV2.maintain();",
        "adaptive maintenance owner",
    )

    # Core diagnostics remain useful underneath the supervisor. Overlay adaptive
    # state last so transportEngine/fallback fields reflect the live owner.
    diag_anchor = '''                out.put("transportEngine", "ble_core_v2");'''
    diag_new = '''                out.put("transportEngine", "ble_core_v2");
                if (adaptiveNearbyV3 != null) {
                    JSONObject adaptive = adaptiveNearbyV3.snapshot();
                    java.util.Iterator<String> adaptiveKeys = adaptive.keys();
                    while (adaptiveKeys.hasNext()) {
                        String adaptiveKey = adaptiveKeys.next();
                        out.put(adaptiveKey, adaptive.opt(adaptiveKey));
                    }
                }'''
    text = once(text, diag_anchor, diag_new, "adaptive diagnostics overlay")

    path.write_text(text)


def patch_runtime() -> None:
    path = ROOT / "src/components/BleeRuntime.tsx"
    if not path.is_file():
        raise SystemExit("Blee adaptive v3: generated BleeRuntime.tsx missing")
    text = path.read_text()
    if "BLEE_ADAPTIVE_NEARBY_V3_DIAGNOSTICS" in text:
        return

    diagnosis_anchor = "  const radioMode = String(d.radioMode || '');"
    diagnosis_new = '''  // BLEE_ADAPTIVE_NEARBY_V3_DIAGNOSTICS
  const fallbackMode = String(d.fallbackMode || 'ble_primary');
  if (fallbackMode === 'nearby_connected') return 'Offline fallback connected. Blee is using the local Nearby transport because raw GATT could not establish reliably.';
  if (fallbackMode === 'nearby_active' || fallbackMode === 'nearby_starting') {
    const detail = String(d.lastNearbyError || '').trim();
    return detail
      ? `Raw BLE could not establish a stable link. Offline fallback is retrying (${detail}).`
      : 'Raw BLE could not establish a stable link. Blee switched to the offline Nearby transport.';
  }
  if (fallbackMode === 'permission_required') return 'Blee needs Nearby devices permission before it can use the offline fallback transport.';
  const radioMode = String(d.radioMode || '');'''
    text = once(text, diagnosis_anchor, diagnosis_new, "adaptive diagnostic summary")

    row_anchor = "  ['transportEngine', 'Transport engine'],"
    row_new = '''  ['transportEngine', 'Transport engine'],
  ['fallbackMode', 'Adaptive fallback'],
  ['fallbackReason', 'Fallback reason'],
  ['gatt147Count', 'GATT 147 timeouts'],
  ['nearbyAdvertising', 'Nearby fallback advertising'],
  ['nearbyDiscovering', 'Nearby fallback discovery'],
  ['nearbyEndpointsFound', 'Nearby endpoints found'],
  ['nearbyConnections', 'Nearby connections'],
  ['nearbyConnectedNow', 'Nearby connected now'],
  ['lastNearbyStatus', 'Last Nearby status'],
  ['lastNearbyError', 'Last Nearby error'],'''
    text = once(text, row_anchor, row_new, "adaptive diagnostic rows")
    path.write_text(text)


def verify(native_dir: Path) -> None:
    service = (native_dir / "BleeMeshService.java").read_text()
    runtime = (ROOT / "src/components/BleeRuntime.tsx").read_text()
    gradle = (ROOT / "android/app/build.gradle").read_text()
    manifest = (ANDROID / "AndroidManifest.xml").read_text()
    activity = locate_activity().read_text()
    required = (
        "BLEE_ADAPTIVE_NEARBY_V3",
        "class AdaptiveNearbyV3",
        "Strategy.P2P_CLUSTER",
        "Nearby.getConnectionsClient",
        "startAdvertising(localPeerIdBytes()",
        "startDiscovery(NEARBY_SERVICE_ID",
        "requestConnection(localPeerIdBytes()",
        "acceptConnection(endpointId, nearbyPayloadCallback)",
        "Payload.fromBytes",
        "db.receive(raw, deviceId, publicKey)",
        "db.recordPeerDelivery",
        "GATT_TIMEOUT_THRESHOLD = 2",
        "status == 147",
        "DUAL_SCAN_ON_MS = 8_000L",
        "DUAL_SCAN_OFF_MS = 2_000L",
        "setAdaptiveScanEnabled",
        "ScanSettings.SCAN_MODE_BALANCED",
        "adaptiveNearbyV3.maintain()",
    )
    missing = [m for m in required if m not in service]
    if missing:
        raise SystemExit(f"Blee adaptive v3 verification failed: {missing}")
    if "play-services-nearby:19.5.0" not in gradle:
        raise SystemExit("Blee adaptive v3: Nearby Connections dependency missing")
    for marker in ("ACCESS_WIFI_STATE", "CHANGE_WIFI_STATE", "NEARBY_WIFI_DEVICES"):
        if marker not in manifest:
            raise SystemExit(f"Blee adaptive v3: manifest missing {marker}")
    if "BLEE_ADAPTIVE_NEARBY_PERMISSION_V3" not in activity or "NEARBY_WIFI_DEVICES" not in activity:
        raise SystemExit("Blee adaptive v3: runtime Nearby Wi-Fi permission wiring missing")
    if "BLEE_ADAPTIVE_NEARBY_V3_DIAGNOSTICS" not in runtime or "nearbyConnections" not in runtime:
        raise SystemExit("Blee adaptive v3: adaptive diagnostics UI missing")
    print("Blee adaptive transport v3 installed and verified")


def main() -> None:
    activity = locate_activity()
    patch_gradle()
    patch_manifest()
    patch_activity(activity)
    patch_service(activity.parent)
    patch_runtime()
    verify(activity.parent)


if __name__ == "__main__":
    main()
