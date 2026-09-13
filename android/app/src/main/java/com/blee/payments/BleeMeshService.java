package com.blee.payments;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattServer;
import android.bluetooth.BluetoothGattServerCallback;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.le.AdvertiseCallback;
import android.bluetooth.le.AdvertiseData;
import android.bluetooth.le.AdvertiseSettings;
import android.bluetooth.le.BluetoothLeAdvertiser;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.IntentFilter;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.ParcelUuid;
import android.util.Base64;
import android.util.Log;

import com.google.android.gms.nearby.Nearby;
import com.google.android.gms.nearby.connection.AdvertisingOptions;
import com.google.android.gms.nearby.connection.ConnectionInfo;
import com.google.android.gms.nearby.connection.ConnectionLifecycleCallback;
import com.google.android.gms.nearby.connection.ConnectionOptions;
import com.google.android.gms.nearby.connection.ConnectionResolution;
import com.google.android.gms.nearby.connection.ConnectionsClient;
import com.google.android.gms.nearby.connection.ConnectionsStatusCodes;
import com.google.android.gms.nearby.connection.DiscoveredEndpointInfo;
import com.google.android.gms.nearby.connection.DiscoveryOptions;
import com.google.android.gms.nearby.connection.EndpointDiscoveryCallback;
import com.google.android.gms.nearby.connection.Payload;
import com.google.android.gms.nearby.connection.PayloadCallback;
import com.google.android.gms.nearby.connection.PayloadTransferUpdate;
import com.google.android.gms.nearby.connection.Strategy;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Set;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class BleeMeshService extends Service {
    // BLEE_BLE_TRANSPORT_V4
    // BLEE_BLE_DIAGNOSTICS_V1
    // BLEE_BITCHAT_STYLE_BLE_RELIABILITY_V1
    // BLEE_RADIO_ARBITRATION_V2
    // BLEE_BITCHAT_ANDROID_GATT_PARITY_V1
    private static final int BLE_MAX_CLIENT_LINKS = 1;
    private static final int BLE_MAX_CANDIDATES = 24;
    private static final long BLE_CONNECT_RATE_MS = 650L;
    private static final long BLE_CANDIDATE_STALE_MS = 8_000L;
    private static final long BLE_CONNECT_FRESHNESS_MS = 4_000L;
    private static final long BLE_GATT_CONNECT_TIMEOUT_MS = 30_000L;
    private static final long BLE_DISCONNECT_SETTLE_MS = 1_800L;
    private static final long BLE_GATT_STALL_MS = 15_000L;
    private static final long BLE_SCAN_STALL_MS = 25_000L;
    private static final long BLE_SCAN_RESTART_COOLDOWN_MS = 60_000L;
    private final Map<String, BleCandidate> bleCandidates = Collections.synchronizedMap(new HashMap<String, BleCandidate>());
    private final Map<String, String> bleLinkStates = Collections.synchronizedMap(new HashMap<String, String>());
    private final Map<String, Integer> bleFailures = Collections.synchronizedMap(new HashMap<String, Integer>());
    private final Map<String, Long> bleCooldownUntil = Collections.synchronizedMap(new HashMap<String, Long>());
    private final Map<String, Long> bleDisconnectUntil = Collections.synchronizedMap(new HashMap<String, Long>());
    private final Map<String, Integer> peerRoleTokens = Collections.synchronizedMap(new HashMap<String, Integer>());
    private final Map<String, BluetoothGatt> clientGatts = Collections.synchronizedMap(new HashMap<String, BluetoothGatt>());
    private final Map<String, Long> gattProgressAt = Collections.synchronizedMap(new HashMap<String, Long>());
    private final Map<String, Long> gattWatchdogDueAt = Collections.synchronizedMap(new HashMap<String, Long>());
    private volatile long bleLastGlobalConnectAt = 0L;
    private volatile boolean connectionPumpScheduled = false;
    private volatile long connectionPumpDueAt = Long.MAX_VALUE;
    private volatile long lastScanWatchdogRestartAt = 0L;
    private volatile boolean bluetoothStopping = false;
    private volatile boolean gattScanPaused = false;
    private volatile int advertiserResourceFailures = 0;
    private volatile long advertisingSuppressedUntil = 0L;
    private volatile String diagLastAdvertiseError = "";
    private volatile String diagLastGattError = "";
    // BLEE_GATT_SERVER_READINESS_V1
    private volatile boolean gattServerReady = false;
    private volatile long diagServerConnections = 0L;
    private volatile String diagLastServerPeer = "";
    private volatile int diagLastServerStatus = 0;
    private volatile int diagLastServerState = BluetoothProfile.STATE_DISCONNECTED;
    // BLEE_GATT_INTEROP_V1
    private volatile boolean diagLastScanConnectable = true;
    private volatile int diagLastAddressType = -1;
    private volatile int diagLastDeviceType = -1;
    private volatile long diagGattConnectionCallbacks = 0L;
    private volatile int diagLastNativeGattStatus = -1;
    private volatile int diagLastNativeGattState = -1;
    private volatile String diagLastConnectStrategy = "";
    private final Map<String, Boolean> gattAutoConnectMode = Collections.synchronizedMap(new HashMap<String, Boolean>());

    private static final class BleCandidate {
        final BluetoothDevice device;
        final String address;
        final int rssi;
        final long seenAt;
        final boolean needsIdentity;
        final boolean hasPacket;
        BleCandidate(BluetoothDevice device, String address, int rssi, long seenAt, boolean needsIdentity, boolean hasPacket) {
            this.device = device; this.address = address; this.rssi = rssi; this.seenAt = seenAt;
            this.needsIdentity = needsIdentity; this.hasPacket = hasPacket;
        }
    }

    private int localRoleToken() {
        String seed = deviceId == null ? "blee" : deviceId;
        return seed.hashCode() & 0x7fffffff;
    }

    private byte[] localRoleTokenPayload() {
        int token = localRoleToken();
        return new byte[] {
            (byte) ((token >>> 24) & 0xff),
            (byte) ((token >>> 16) & 0xff),
            (byte) ((token >>> 8) & 0xff),
            (byte) (token & 0xff)
        };
    }

    private void rememberPeerRoleToken(ScanResult result) {
        try {
            if (result == null || result.getDevice() == null || result.getScanRecord() == null) return;
            byte[] value = result.getScanRecord().getServiceData(new ParcelUuid(SERVICE_UUID));
            if (value == null || value.length < 4) return;
            int token = ((value[0] & 0xff) << 24)
                | ((value[1] & 0xff) << 16)
                | ((value[2] & 0xff) << 8)
                | (value[3] & 0xff);
            peerRoleTokens.put(result.getDevice().getAddress(), token & 0x7fffffff);
        } catch (Throwable ignored) {}
    }

    private boolean shouldInitiateCandidate(BleCandidate candidate) {
        if (candidate == null) return false;
        Integer remoteToken = peerRoleTokens.get(candidate.address);
        int localToken = localRoleToken();
        // A controller can occasionally surface its own/stale advertisement.
        // Never try to establish a GATT link to our own stable role token.
        if (remoteToken != null && localToken == remoteToken) return false;
        if (candidate.hasPacket) return true;
        // If this phone cannot currently advertise, it cannot wait passively for
        // the peer to discover it. Scanner-first mode must own the central role.
        if (!advertising) return true;
        if (remoteToken == null) return true; // backward-compatible with older Blee builds
        return localToken < remoteToken;
    }

    private String bleRadioMode() {
        long now = System.currentTimeMillis();
        if (!clientGatts.isEmpty() || !bleLinkStates.isEmpty()) return "gatt_session";
        if (!advertising && now < advertisingSuppressedUntil) return "scanner_first";
        if (advertising && scanning) return "dual_role";
        if (scanning) return "scanner_only";
        if (advertising) return "advertiser_only";
        return "idle";
    }

    private void onAdvertiseStarted() {
        advertiserResourceFailures = 0;
        advertisingSuppressedUntil = 0L;
        diagLastAdvertiseError = "";
    }

    private void onAdvertiseFailed(int errorCode) {
        diagLastAdvertiseError = "advertise_error_" + errorCode;
        if (errorCode != AdvertiseCallback.ADVERTISE_FAILED_TOO_MANY_ADVERTISERS) return;
        advertiserResourceFailures = Math.min(6, advertiserResourceFailures + 1);
        long delay = Math.min(90_000L, 15_000L * advertiserResourceFailures);
        advertisingSuppressedUntil = System.currentTimeMillis() + delay;
        nextAdvertiseAttemptAt = Math.max(nextAdvertiseAttemptAt, advertisingSuppressedUntil);
        diagLastPhase = "advertiser_slot_busy_scanner_first";
        // Do not punish scanning when the vendor controller has no advertiser
        // slot. Continue discovering peers and act as the central/client side.
        try { if (advertiser != null) advertiser.stopAdvertising(advertiseCallback); } catch (Throwable ignored) {}
        suspendPeripheralForScannerFirst();
    }

    private void resetAdvertiserRecovery() {
        advertiserResourceFailures = 0;
        advertisingSuppressedUntil = 0L;
        diagLastAdvertiseError = "";
    }

    private void observeGattScanResult(ScanResult result) {
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

    private void maybeConnect(BluetoothDevice device) {
        if (!bluetoothPermissionsGranted() || device == null || db == null) return;
        long now = System.currentTimeMillis();
        String address;
        try { address = device.getAddress(); } catch (Throwable ignored) { return; }
        Long identityAt = peerIdentityAt.get(address);
        boolean needsIdentity = identityAt == null || now - identityAt > 45_000L;
        boolean hasPacket = !db.duePacketsForPeer(now, address, 1).isEmpty();
        if (!needsIdentity && !hasPacket) return;
        int rssi = peerRssi.containsKey(address) ? peerRssi.get(address) : -100;
        long seenAt = peerSeen.containsKey(address) ? peerSeen.get(address) : now;
        bleCandidates.put(address, new BleCandidate(device, address, rssi, seenAt, needsIdentity, hasPacket));
        pruneBleCandidates(now);
        trimBleCandidates(now);
        long admissionDelay = hasPacket ? 0L : 75L + Math.abs(address.hashCode() % 175);
        requestConnectionPump(admissionDelay);
    }

    private void pruneBleCandidates(long now) {
        synchronized (bleCandidates) {
            List<String> stale = new ArrayList<String>();
            for (Map.Entry<String, BleCandidate> entry : bleCandidates.entrySet()) {
                if (now - entry.getValue().seenAt > BLE_CANDIDATE_STALE_MS) stale.add(entry.getKey());
            }
            for (String key : stale) {
                bleCandidates.remove(key);
                peerRoleTokens.remove(key);
            }
        }
    }

    private int bleCandidateScore(BleCandidate c, long now) {
        int failures = bleFailures.containsKey(c.address) ? bleFailures.get(c.address) : 0;
        int work = c.hasPacket ? 500 : 0;
        int identity = c.needsIdentity ? 160 : 0;
        int strength = Math.max(-100, Math.min(-20, c.rssi)) + 100;
        int recency = -Math.min(300, (int) Math.max(0L, now - c.seenAt) / 100);
        return work + identity + strength * 3 + recency - failures * 45;
    }

    private void trimBleCandidates(long now) {
        synchronized (bleCandidates) {
            if (bleCandidates.size() <= BLE_MAX_CANDIDATES) return;
            List<BleCandidate> ranked = new ArrayList<BleCandidate>(bleCandidates.values());
            Collections.sort(ranked, (a, b) -> Integer.compare(bleCandidateScore(b, now), bleCandidateScore(a, now)));
            bleCandidates.clear();
            for (int i = 0; i < Math.min(BLE_MAX_CANDIDATES, ranked.size()); i++) bleCandidates.put(ranked.get(i).address, ranked.get(i));
        }
    }

    private BleCandidate nextBleCandidate(long now) {
        pruneBleCandidates(now);
        if (bleLinkStates.size() >= BLE_MAX_CLIENT_LINKS) return null;
        if (bleLastGlobalConnectAt > 0L && now - bleLastGlobalConnectAt < BLE_CONNECT_RATE_MS) return null;
        List<BleCandidate> ranked;
        synchronized (bleCandidates) { ranked = new ArrayList<BleCandidate>(bleCandidates.values()); }
        Collections.sort(ranked, (a, b) -> Integer.compare(bleCandidateScore(b, now), bleCandidateScore(a, now)));
        for (BleCandidate c : ranked) {
            if (bleLinkStates.containsKey(c.address)) continue;
            Long identityAt = peerIdentityAt.get(c.address);
            boolean stillNeedsIdentity = identityAt == null || now - identityAt > 45_000L;
            boolean stillHasPacket = db != null && !db.duePacketsForPeer(now, c.address, 1).isEmpty();
            if (!stillNeedsIdentity && !stillHasPacket) { bleCandidates.remove(c.address); continue; }
            // Match Bitchat Android's connect-from-current-scan behavior. A remembered
            // BluetoothDevice/MAC is not connection-worthy once the advertisement is old.
            if (now - c.seenAt > BLE_CONNECT_FRESHNESS_MS) { bleCandidates.remove(c.address); continue; }
            long cool = bleCooldownUntil.containsKey(c.address) ? bleCooldownUntil.get(c.address) : 0L;
            long settle = bleDisconnectUntil.containsKey(c.address) ? bleDisconnectUntil.get(c.address) : 0L;
            if (now < cool || now < settle) continue;
            BleCandidate refreshed = new BleCandidate(c.device, c.address, c.rssi, c.seenAt, stillNeedsIdentity, stillHasPacket);
            if (!shouldInitiateCandidate(refreshed)) continue;
            bleCandidates.remove(c.address);
            bleLinkStates.put(c.address, "CONNECTING");
            bleLastGlobalConnectAt = now;
            return refreshed;
        }
        return null;
    }

    private long nextBleReadyDelay(long now) {
        if (bleCandidates.isEmpty() || bleLinkStates.size() >= BLE_MAX_CLIENT_LINKS) return -1L;
        long best = Long.MAX_VALUE;
        long global = Math.max(now, bleLastGlobalConnectAt + BLE_CONNECT_RATE_MS);
        synchronized (bleCandidates) {
            for (BleCandidate c : bleCandidates.values()) {
                if (bleLinkStates.containsKey(c.address) || !shouldInitiateCandidate(c)) continue;
                if (now - c.seenAt > BLE_CONNECT_FRESHNESS_MS) continue;
                long at = global;
                if (bleCooldownUntil.containsKey(c.address)) at = Math.max(at, bleCooldownUntil.get(c.address));
                if (bleDisconnectUntil.containsKey(c.address)) at = Math.max(at, bleDisconnectUntil.get(c.address));
                best = Math.min(best, at);
            }
        }
        return best == Long.MAX_VALUE ? -1L : Math.max(0L, best - now + 25L);
    }

    private void markBleFailure(String address, long now) {
        bleLinkStates.remove(address);
        int failures = Math.min(6, (bleFailures.containsKey(address) ? bleFailures.get(address) : 0) + 1);
        bleFailures.put(address, failures);
        long base = Math.min(20_000L, 1_000L * (1L << Math.min(4, failures - 1)));
        bleCooldownUntil.put(address, now + base + Math.abs(address.hashCode() % 700));
    }

    private void requestConnectionPump(final long delayMs) {
        handler.post(() -> {
            long now = System.currentTimeMillis();
            long due = now + Math.max(0L, delayMs);
            if (connectionPumpScheduled && due >= connectionPumpDueAt - 25L) return;
            if (connectionPumpScheduled) handler.removeCallbacks(connectionPump);
            connectionPumpScheduled = true; connectionPumpDueAt = due;
            handler.postDelayed(connectionPump, Math.max(0L, due - now));
        });
    }

    private final Runnable connectionPump = new Runnable() {
        @Override public void run() {
            connectionPumpScheduled = false; connectionPumpDueAt = Long.MAX_VALUE;
            drainConnectionQueue();
        }
    };

    private void drainConnectionQueue() {
        if (bluetoothStopping || !bluetoothPermissionsGranted() || adapter == null || !adapter.isEnabled()) return;
        long now = System.currentTimeMillis();
        BleCandidate candidate = nextBleCandidate(now);
        if (candidate == null) {
            long delay = nextBleReadyDelay(now);
            if (delay >= 0L) requestConnectionPump(delay);
            return;
        }
        beginGattConnection(candidate);
    }

    private BluetoothGatt connectGattReliable(BluetoothDevice device) {
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

    private void pauseScanForGatt() {
        // gatt_radio_handoff compatibility marker. Bitchat Android keeps scanning
        // while the direct GATT link is being established; stopping the scanner
        // can invalidate useful controller state on some vendor stacks.
        gattScanPaused = false;
    }

    private void resumeRadioAfterGatt() {
        // Scanning is intentionally continuous through connection establishment.
        gattScanPaused = false;
    }

    private void beginGattConnection(final BleCandidate c) {
        if (clientGatts.containsKey(c.address)) { bleLinkStates.remove(c.address); requestConnectionPump(250L); return; }
        // BLEE_BITCHAT_ANDROID_GATT_PARITY_V1: connect directly from the fresh scan
        // result. Do not stop scanning and do not insert an artificial radio gap.
        openGattConnection(c);
    }

    private void openGattConnection(BleCandidate c) {
        final long now = System.currentTimeMillis();
        if (bluetoothStopping || adapter == null || !adapter.isEnabled()) {
            bleLinkStates.remove(c.address);
            resumeRadioAfterGatt();
            return;
        }
        lastConnect.put(c.address, now);
        diagGattAttempts++; diagLastPhase = "gatt_connect_attempt"; diagLastTransportId = c.address;
        try {
            BluetoothGatt gatt = connectGattReliable(c.device);
            if (gatt == null) {
                markBleFailure(c.address, now);
                diagLastGattError = "connectGatt returned null";
                diagLastError = diagLastGattError;
                resumeRadioAfterGatt();
                requestConnectionPump(1_000L);
                return;
            }
            clientGatts.put(c.address, gatt);
            scheduleGattConnectTimeout(gatt, c.address);
        } catch (Throwable error) {
            markBleFailure(c.address, now); diagLastPhase = "gatt_connect_exception";
            diagLastGattError = error.getMessage() == null ? error.toString() : error.getMessage();
            diagLastError = diagLastGattError;
            resumeRadioAfterGatt();
            requestConnectionPump(1_000L);
        }
    }

    private void scheduleGattConnectTimeout(final BluetoothGatt gatt, final String address) {
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

    private void handleClientConnectionState(BluetoothGatt gatt, int status, int newState) {
        if (gatt == null || gatt.getDevice() == null) return;
        String address = gatt.getDevice().getAddress();
        diagGattConnectionCallbacks++;
        diagLastNativeGattStatus = status;
        diagLastNativeGattState = newState;
        BluetoothGatt tracked = clientGatts.get(address);
        if (tracked != null && tracked != gatt) { try { gatt.close(); } catch (Throwable ignored) {} return; }
        if (tracked == null) {
            if (bluetoothStopping || !bleLinkStates.containsKey(address)) { try { gatt.close(); } catch (Throwable ignored) {} return; }
            clientGatts.put(address, gatt);
        }
        if (newState == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
            bleLinkStates.put(address, "CONNECTED"); bleFailures.remove(address); bleCooldownUntil.remove(address); bleDisconnectUntil.remove(address);
            touchGatt(gatt); diagGattConnected++; diagLastPhase = "gatt_connected"; diagLastGattError = ""; diagLastError = "";
            try { gatt.requestConnectionPriority(BluetoothGatt.CONNECTION_PRIORITY_HIGH); } catch (Throwable ignored) {}
            // Let the controller settle before service discovery. Bitchat Android
            // likewise sequences post-connect GATT work instead of firing it in
            // the same connection-state callback.
            handler.postDelayed(() -> {
                if (clientGatts.get(address) != gatt || !"CONNECTED".equals(bleLinkStates.get(address))) return;
                try { if (!gatt.discoverServices()) failGatt(gatt, "discoverServices rejected"); }
                catch (Throwable error) { failGatt(gatt, "discoverServices threw"); }
            }, 200L);
            return;
        }
        if (newState == BluetoothProfile.STATE_DISCONNECTED) {
            boolean established = "CONNECTED".equals(bleLinkStates.get(address));
            if (!established) {
                diagLastGattError = "disconnect status=" + status;
                diagLastError = diagLastGattError;
            }
            finishGatt(gatt, !established, "disconnect status=" + status); return;
        }
        if (status != BluetoothGatt.GATT_SUCCESS) failGatt(gatt, "connection status=" + status);
        else if ("CONNECTED".equals(bleLinkStates.get(address))) touchGatt(gatt);
    }

    private void touchGatt(final BluetoothGatt gatt) {
        if (gatt == null || gatt.getDevice() == null) return;
        final String address = gatt.getDevice().getAddress();
        long now = System.currentTimeMillis(); gattProgressAt.put(address, now);
        if (gattWatchdogDueAt.containsKey(address)) return;
        gattWatchdogDueAt.put(address, now + BLE_GATT_STALL_MS);
        scheduleGattWatchdog(gatt, address, BLE_GATT_STALL_MS);
    }

    private void scheduleGattWatchdog(final BluetoothGatt gatt, final String address, long delay) {
        handler.postDelayed(() -> {
            if (clientGatts.get(address) != gatt) { gattWatchdogDueAt.remove(address); return; }
            if (!"CONNECTED".equals(bleLinkStates.get(address))) { gattWatchdogDueAt.remove(address); return; }
            long now = System.currentTimeMillis(); Long progress = gattProgressAt.get(address);
            if (progress != null && now - progress < BLE_GATT_STALL_MS) {
                long next = Math.max(250L, BLE_GATT_STALL_MS - (now - progress));
                gattWatchdogDueAt.put(address, now + next); scheduleGattWatchdog(gatt, address, next); return;
            }
            gattWatchdogDueAt.remove(address); diagLastPhase = "gatt_operation_timeout";
            diagLastGattError = "No connected GATT operation progress for " + BLE_GATT_STALL_MS + "ms";
            diagLastError = diagLastGattError;
            failGatt(gatt, "GATT operation timeout");
        }, Math.max(250L, delay));
    }

    private void failGatt(BluetoothGatt gatt, String reason) {
        diagLastPhase = "gatt_failed";
        diagLastGattError = reason == null ? "GATT failure" : reason;
        diagLastError = diagLastGattError;
        finishGatt(gatt, true, reason);
    }

    private void finishGatt(BluetoothGatt gatt, boolean failed, String reason) {
        if (gatt == null) return;
        String address = ""; try { if (gatt.getDevice() != null) address = gatt.getDevice().getAddress(); } catch (Throwable ignored) {}
        boolean owned = !address.isEmpty() && clientGatts.get(address) == gatt;
        boolean established = "CONNECTED".equals(bleLinkStates.get(address));
        if (owned) {
            clientGatts.remove(address); gattProgressAt.remove(address); gattWatchdogDueAt.remove(address); SendState.clear(gatt);
            gattAutoConnectMode.remove(address);
            long now = System.currentTimeMillis();
            if (failed) markBleFailure(address, now);
            else { bleLinkStates.remove(address); if (established) bleDisconnectUntil.put(address, now + BLE_DISCONNECT_SETTLE_MS); }
        }
        try { gatt.disconnect(); } catch (Throwable ignored) {} try { gatt.close(); } catch (Throwable ignored) {}
        resumeRadioAfterGatt();
        if (!bluetoothStopping) { long delay = nextBleReadyDelay(System.currentTimeMillis()); requestConnectionPump(delay < 0L ? 250L : delay); }
    }

    private void resetClientGattConnections() {
        bluetoothStopping = true;
        List<BluetoothGatt> snapshot; synchronized (clientGatts) { snapshot = new ArrayList<BluetoothGatt>(clientGatts.values()); }
        clientGatts.clear(); gattProgressAt.clear(); gattWatchdogDueAt.clear(); bleCandidates.clear(); bleLinkStates.clear(); peerRoleTokens.clear();
        bleFailures.clear(); bleCooldownUntil.clear(); bleDisconnectUntil.clear();
        for (BluetoothGatt gatt : snapshot) { try { SendState.clear(gatt); } catch (Throwable ignored) {} try { gatt.disconnect(); } catch (Throwable ignored) {} try { gatt.close(); } catch (Throwable ignored) {} }
        gattScanPaused = false;
        bluetoothStopping = false;
    }

    private void maintainBleReliability() {
        long now = System.currentTimeMillis(); pruneBleCandidates(now);
        if (adapter == null || !adapter.isEnabled()) {
            scanning = false; advertising = false; advertiseStarting = false; scanner = null; advertiser = null;
            if (gattServer != null) { try { gattServer.close(); } catch (Throwable ignored) {} gattServer = null; }
            if (!clientGatts.isEmpty()) resetClientGattConnections(); return;
        }
        requestConnectionPump(0L);
        if (!advertising && advertisingSuppressedUntil > 0L && now >= advertisingSuppressedUntil) {
            advertisingSuppressedUntil = 0L;
            nextAdvertiseAttemptAt = 0L;
        resetAdvertiserRecovery();
            startBluetooth();
        }
        boolean noRawProgress = diagLastSeenAt <= 0L || now - diagLastSeenAt > BLE_SCAN_STALL_MS;
        boolean scanOld = scanning && lastScanStartAt > 0L && now - lastScanStartAt > BLE_SCAN_STALL_MS;
        if (scanOld && noRawProgress && now - lastScanWatchdogRestartAt > BLE_SCAN_RESTART_COOLDOWN_MS && scanner != null) {
            lastScanWatchdogRestartAt = now; diagLastPhase = "scan_watchdog_restart"; diagLastError = "";
            try { scanner.stopScan(scanCallback); } catch (Throwable ignored) {} scanning = false;
            handler.postDelayed(() -> startBluetooth(), 350L);
        }
    }

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
    private volatile String diagLastError = "";
    // BLEE_BLUETOOTH_DISCOVERY_V2_2
    static final String ACTION_LEDGER_CHANGED = "com.blee.payments.BLEE_LEDGER_CHANGED";
    // BLEE_IMMEDIATE_SENT_NOTIFICATION_V1
    static final String ACTION_LOCAL_PAYMENT_SENT = "com.blee.payments.BLEE_LOCAL_PAYMENT_SENT";
    static final String EXTRA_PAYMENT_ID = "paymentId";
    static final String EXTRA_EVENT_TYPE = "eventType";
    // BLEE_NATIVE_BLE_DISCOVERY_V3
    static final String ACTION_PEER_CHANGED = ACTION_LEDGER_CHANGED.replace("BLEE_LEDGER_CHANGED", "BLEE_PEER_CHANGED");
    static final String EXTRA_PEER_TRANSPORT_ID = "transportId";
    static final String EXTRA_PEER_WALLET = "wallet";
    static final String EXTRA_PEER_DISPLAY_NAME = "displayName";
    // BLEE_PRODUCTION_EVENT_PATH_V1
    static final String EXTRA_PEER_AVATAR = "avatar";
    static final String EXTRA_PEER_RSSI = "rssi";
    static final String EXTRA_PEER_LAST_SEEN = "lastSeen";
    static final String EXTRA_PEER_PRESENT = "present";

    private static final String TAG = "BleeMeshV2";
    private static final String CHANNEL_SERVICE = "blee_mesh_service";
    private static final String CHANNEL_PAYMENTS = "blee_payments";
    private static final int SERVICE_NOTIFICATION_ID = 24001;
    private static final UUID SERVICE_UUID = UUID.fromString("50f57a10-7bd4-4b6a-bf45-b1ee20000001");
    private static final UUID WRITE_UUID = UUID.fromString("50f57a10-7bd4-4b6a-bf45-b1ee20000002");
    private static final UUID IDENTITY_UUID = UUID.fromString("50f57a10-7bd4-4b6a-bf45-b1ee20000003");
    private static final long LOOP_MS = 4_000L;
    private static final long PEER_RETRY_MS = 8_000L;
    private static final long SETTLEMENT_RETRY_MS = 12_000L;
    // BLEE_NATIVE_LIFECYCLE_HARDENING_V1
    private static final long PEER_STALE_MS = 60_000L;
    private static final long ASSEMBLY_TTL_MS = 30_000L;
    private static final int MAX_ASSEMBLIES = 64;
    private static final int MAX_ASSEMBLIES_PER_PEER = 8;
    private static final int MAX_FRAGMENTS = 512;
    private static final int MAX_FRAME_CHARS = 512;
    private static final int MAX_PACKET_BYTES = 48 * 1024;
    private static final int MAX_ENCODED_PACKET_CHARS = 70 * 1024;

    // The APK never accepts an arbitrary RPC for automatic mesh broadcasting.
    // A mesh courier can submit sender-signed bytes only to Blee's validated rail.
    private static final long TRUSTED_CHAIN_ID = 5042002L;
    private static final String TRUSTED_RPC = "https://rpc.testnet.arc.network";

    static volatile boolean running = false;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final Map<String, BluetoothDevice> peers = Collections.synchronizedMap(new HashMap<String, BluetoothDevice>());
    private final Map<String, Long> lastConnect = Collections.synchronizedMap(new HashMap<String, Long>());
    private final Map<String, Long> peerSeen = Collections.synchronizedMap(new HashMap<String, Long>());
    private final Map<String, String> peerWallets = Collections.synchronizedMap(new HashMap<String, String>());
    private final Map<String, String> peerDisplayNames = Collections.synchronizedMap(new HashMap<String, String>());
    private final Map<String, String> peerAvatars = Collections.synchronizedMap(new HashMap<String, String>());
    private final Map<String, Long> peerIdentityAt = Collections.synchronizedMap(new HashMap<String, Long>());
    private final Map<String, Integer> peerRssi = Collections.synchronizedMap(new HashMap<String, Integer>());
    private static final Map<String, JSONObject> DISCOVERED_PEERS = new ConcurrentHashMap<String, JSONObject>();
    private final Map<String, Assembly> assemblies = Collections.synchronizedMap(new HashMap<String, Assembly>());
    private final Map<String, Long> settlementRetryAfter = Collections.synchronizedMap(new HashMap<String, Long>());

    private BleeMeshDb db;
    private String deviceId;
    private String publicKey;
    private BluetoothManager bluetoothManager;
    private BluetoothAdapter adapter;
    private BluetoothLeScanner scanner;
    private BluetoothLeAdvertiser advertiser;
    private BluetoothGattServer gattServer;
    private ConnectivityManager connectivity;
    private volatile boolean networkAvailable = false;
    private volatile boolean scanning = false;
    private volatile boolean advertising = false;
    private volatile boolean advertiseStarting = false;
    private volatile long lastAdvertiseAttemptAt = 0L;
    private volatile long lastScanStartAt = 0L;
    private volatile long lastBleHitAt = 0L;
    private volatile int advertiseRetryCount = 0;
    private volatile long nextAdvertiseAttemptAt = 0L;
    // BLEE_ADVERTISER_RECOVERY_V1
    private volatile boolean settlementScheduled = false;
    // BLEE_TRANSPORT_CORE_V2
    private BleTransportV2 bleTransportV2;
    // BLEE_ADAPTIVE_NEARBY_V3
    private AdaptiveNearbyV3 adaptiveNearbyV3;

    private final BroadcastReceiver bluetoothStateReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            if (!BluetoothAdapter.ACTION_STATE_CHANGED.equals(intent.getAction())) return;
            int state = intent.getIntExtra(BluetoothAdapter.EXTRA_STATE, BluetoothAdapter.ERROR);
            if (state == BluetoothAdapter.STATE_OFF || state == BluetoothAdapter.STATE_TURNING_OFF) {
                scanning = false;
                stopBluetooth();
                peers.clear();
                peerSeen.clear();
                lastConnect.clear();
            } else if (state == BluetoothAdapter.STATE_ON) {
                scanning = false;
                handler.postDelayed(() -> startBluetooth(), 350L);
            }
        }
    };

    static JSONObject diagnosticsSnapshot(Context context) {
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
            out.put("lastServerState", service.diagLastServerState);
            out.put("lastScanConnectable", service.diagLastScanConnectable);
            out.put("lastAddressType", service.diagLastAddressType);
            out.put("lastDeviceType", service.diagLastDeviceType);
            out.put("gattConnectionCallbacks", service.diagGattConnectionCallbacks);
            out.put("lastNativeGattStatus", service.diagLastNativeGattStatus);
            out.put("lastNativeGattState", service.diagLastNativeGattState);
            out.put("lastConnectStrategy", service.diagLastConnectStrategy);
            String ownWallet = service.db == null ? null : service.db.activeWallet();
            out.put("localWalletResolved", ownWallet != null && ownWallet.matches("^0x[0-9a-fA-F]{40}$"));
            if (service.bleTransportV2 != null) {
                JSONObject transport = service.bleTransportV2.snapshot();
                java.util.Iterator<String> transportKeys = transport.keys();
                while (transportKeys.hasNext()) {
                    String key = transportKeys.next();
                    out.put(key, transport.opt(key));
                }
            }
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

    public static void start(Context context) {
        Intent intent = new Intent(context, BleeMeshService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(intent);
        else context.startService(intent);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        INSTANCE = this;
        diagLastPhase = "service_created";
        running = true;
        db = new BleeMeshDb(this);
        deviceId = BleeDeviceIdentity.deviceId(this);
        try { publicKey = BleeDeviceIdentity.publicKey(); }
        catch (Throwable error) { publicKey = ""; }
        createNotificationChannels();
        startForeground(SERVICE_NOTIFICATION_ID, serviceNotification("Nearby payments active"));
        IntentFilter bluetoothFilter = new IntentFilter(BluetoothAdapter.ACTION_STATE_CHANGED);
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(bluetoothStateReceiver, bluetoothFilter, Context.RECEIVER_NOT_EXPORTED);
        else registerReceiver(bluetoothStateReceiver, bluetoothFilter);
        observeConnectivity();
        startBluetooth();
        handler.post(loop);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        // BLEE_SENT_NOTIFICATION_ONSTART_COMPAT_V1
        if (intent != null && ACTION_LOCAL_PAYMENT_SENT.equals(intent.getAction())) {
            BleePaymentNotifier.sent(
                this,
                intent.getStringExtra("paymentId"),
                intent.getStringExtra("amount"),
                intent.getStringExtra("counterparty")
            );
        }

        if (intent != null && ACTION_DIAGNOSTIC_REARM.equals(intent.getAction())) {
            diagLastPhase = "manual_rearm";
            diagLastError = "";
            stopBluetooth();
            handler.postDelayed(new Runnable() {
                @Override public void run() { startBluetooth(); }
            }, 250L);
        }
        return START_STICKY;
    }
    @Override public IBinder onBind(Intent intent) { return null; }

    @Override
    public void onDestroy() {
        running = false;
        if (INSTANCE == this) INSTANCE = null;
        handler.removeCallbacksAndMessages(null);
        try { unregisterReceiver(bluetoothStateReceiver); } catch (Throwable ignored) {}
        stopBluetooth();
        if (connectivity != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            try { connectivity.unregisterNetworkCallback(networkCallback); } catch (Throwable ignored) {}
        }
        io.shutdownNow();
        if (db != null) db.close();
        super.onDestroy();
    }

    private final Runnable loop = new Runnable() {
        @Override public void run() {
            try {
                long loopNow = System.currentTimeMillis();
                cleanupEphemeralState(loopNow);
                db.bootstrapOutgoing(deviceId, publicKey);
                if (!scanning || !advertising) startBluetooth();
                if (adaptiveNearbyV3 != null) adaptiveNearbyV3.maintain(); else if (bleTransportV2 != null) bleTransportV2.maintain();
                pumpKnownPeers();
                scheduleSenderFundedSettlement();
            } catch (Throwable error) {
                Log.w(TAG, "mesh loop", error);
            } finally {
                handler.postDelayed(this, LOOP_MS);
            }
        }
    };

    private void cleanupEphemeralState(long now) {
        synchronized (peerSeen) {
            for (String address : new ArrayList<String>(peerSeen.keySet())) {
                Long seenAt = peerSeen.get(address);
                if (seenAt == null || now - seenAt > PEER_STALE_MS) {
                    peerSeen.remove(address);
                    peers.remove(address);
                    lastConnect.remove(address);
                    peerIdentityAt.remove(address);
                    peerWallets.remove(address);
                    peerDisplayNames.remove(address);
                    peerAvatars.remove(address);
                    peerRssi.remove(address);
                    if (DISCOVERED_PEERS.remove(address) != null) publishPeerGone(address, now);
                }
            }
        }
        synchronized (assemblies) {
            for (String key : new ArrayList<String>(assemblies.keySet())) {
                Assembly assembly = assemblies.get(key);
                if (assembly == null || now - assembly.createdAt > ASSEMBLY_TTL_MS) assemblies.remove(key);
            }
        }
    }

    private int assembliesForPeer(String address) {
        int count = 0;
        String prefix = address + ":";
        synchronized (assemblies) {
            for (String key : assemblies.keySet()) if (key.startsWith(prefix)) count++;
        }
        return count;
    }

    static List<JSONObject> nearbyPeersSnapshot() {
        long now = System.currentTimeMillis();
        List<JSONObject> result = new ArrayList<JSONObject>();
        for (JSONObject peer : DISCOVERED_PEERS.values()) {
            try {
                long seenAt = peer.optLong("lastSeen", 0L);
                if (seenAt <= 0L || now - seenAt > PEER_STALE_MS) continue;
                result.add(new JSONObject(peer.toString()));
            } catch (Throwable ignored) {}
        }
        return result;
    }

    // BLEE_NEARBY_STABILITY_V1
    private void publishResolvedPeer(String address, String wallet, String displayName, int rssi, long seenAt) {
        if (address == null || address.isEmpty() || wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) return;
        String normalizedWallet = wallet.toLowerCase(Locale.ROOT);
        String own = db == null ? null : db.activeWallet();
        if (own != null && own.equalsIgnoreCase(normalizedWallet)) return;

        String cleanName = displayName == null ? "" : displayName.trim();
        if (cleanName.length() > 64) cleanName = cleanName.substring(0, 64);
        String avatar = peerAvatars.get(address);

        if (db != null) {
            JSONObject known = db.peerIdentity(normalizedWallet);
            if (known != null) {
                if (cleanName.isEmpty()) cleanName = known.optString("displayName", "").trim();
                if (avatar == null || avatar.isEmpty()) avatar = known.optString("avatar", "");
            }
        }

        try {
            // A person is keyed by wallet. BLE MAC addresses and Nearby endpoint
            // IDs are routing details and must never create duplicate people.
            List<String> duplicateTransportIds = new ArrayList<String>();
            for (Map.Entry<String, JSONObject> entry : DISCOVERED_PEERS.entrySet()) {
                String otherId = entry.getKey();
                JSONObject other = entry.getValue();
                if (otherId.equals(address) || other == null) continue;
                if (!normalizedWallet.equalsIgnoreCase(other.optString("wallet", ""))) continue;
                if (cleanName.isEmpty()) cleanName = other.optString("displayName", "").trim();
                if (avatar == null || avatar.isEmpty()) avatar = other.optString("avatar", "");
                duplicateTransportIds.add(otherId);
            }
            for (String duplicateId : duplicateTransportIds) {
                DISCOVERED_PEERS.remove(duplicateId);
                publishPeerGone(duplicateId, seenAt);
            }

            if (db != null) db.upsertPeerIdentity(normalizedWallet, cleanName, avatar, address, address.startsWith("nc:") ? "nearby" : "ble");
            if (avatar != null && !avatar.isEmpty()) peerAvatars.put(address, avatar);

            JSONObject peer = new JSONObject();
            peer.put("transportId", address);
            peer.put("wallet", normalizedWallet);
            peer.put("displayName", cleanName);
            if (avatar != null && !avatar.isEmpty()) peer.put("avatar", avatar);
            peer.put("rssi", rssi);
            peer.put("lastSeen", seenAt);
            peer.put("transport", address.startsWith("nc:") ? "nearby" : "ble");
            DISCOVERED_PEERS.put(address, peer);
            peerWallets.put(address, normalizedWallet);
            peerDisplayNames.put(address, cleanName);
            peerIdentityAt.put(address, seenAt);
            peerRssi.put(address, rssi);

            Intent intent = new Intent(ACTION_PEER_CHANGED);
            intent.setPackage(getPackageName());
            intent.putExtra(EXTRA_PEER_TRANSPORT_ID, address);
            intent.putExtra(EXTRA_PEER_WALLET, normalizedWallet);
            intent.putExtra(EXTRA_PEER_DISPLAY_NAME, cleanName);
            if (avatar != null && !avatar.isEmpty()) intent.putExtra(EXTRA_PEER_AVATAR, avatar);
            intent.putExtra(EXTRA_PEER_RSSI, rssi);
            intent.putExtra(EXTRA_PEER_LAST_SEEN, seenAt);
            intent.putExtra(EXTRA_PEER_PRESENT, true);
            sendBroadcast(intent);
        } catch (Throwable error) {
            Log.d(TAG, "Unable to publish canonical Blee peer: " + error.getMessage());
        }
    }

    private void forgetResolvedPeer(String transportId, long at) {
        if (transportId == null || transportId.isEmpty()) return;
        DISCOVERED_PEERS.remove(transportId);
        peerIdentityAt.remove(transportId);
        peerWallets.remove(transportId);
        peerDisplayNames.remove(transportId);
        peerAvatars.remove(transportId);
        peerRssi.remove(transportId);
        publishPeerGone(transportId, at);
    }

    private void publishPeerGone(String address, long at) {
        try {
            Intent intent = new Intent(ACTION_PEER_CHANGED);
            intent.setPackage(getPackageName());
            intent.putExtra(EXTRA_PEER_TRANSPORT_ID, address == null ? "" : address);
            intent.putExtra(EXTRA_PEER_LAST_SEEN, at);
            intent.putExtra(EXTRA_PEER_PRESENT, false);
            sendBroadcast(intent);
        } catch (Throwable ignored) {}
    }

    private byte[] localIdentityPayload() {
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

    private void readIdentityOrSend(BluetoothGatt gatt) {
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
    }

    private void writeLocalIdentity(BluetoothGatt gatt) {
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

    private boolean handleIdentityRead(BluetoothGatt gatt, byte[] value) {
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
                diagIdentityFailures++;
                diagLastPhase = "identity_invalid";
                diagLastError = "identity_bytes_" + value.length;
                Log.w(TAG, "BLE identity read returned no wallet (bytes=" + value.length + ")");
                return false;
            }
            String address = gatt.getDevice().getAddress();
            int rssi = peerRssi.containsKey(address) ? peerRssi.get(address) : 0;
            publishResolvedPeer(address, wallet, displayName, rssi, System.currentTimeMillis());
            diagIdentityReads++;
            diagLastWallet = wallet;
            diagLastPhase = "peer_resolved";
            diagLastError = "";
            Log.i(TAG, "BLE peer resolved " + wallet.substring(0, 8) + "… via " + address);
            return true;
        } catch (Throwable error) {
            Log.w(TAG, "BLE identity read ignored: " + error.getMessage());
            return false;
        }
    }

    private void observeConnectivity() {
        connectivity = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
        if (connectivity == null) return;
        try {
            Network active = connectivity.getActiveNetwork();
            networkAvailable = hasInternet(active);
        } catch (Throwable ignored) {}
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            try { connectivity.registerDefaultNetworkCallback(networkCallback); } catch (Throwable ignored) {}
        }
    }

    private final ConnectivityManager.NetworkCallback networkCallback = new ConnectivityManager.NetworkCallback() {
        @Override public void onAvailable(Network network) {
            networkAvailable = hasInternet(network);
            scheduleSenderFundedSettlement();
        }
        @Override public void onLost(Network network) {
            try {
                Network active = connectivity == null ? null : connectivity.getActiveNetwork();
                networkAvailable = hasInternet(active);
            } catch (Throwable ignored) { networkAvailable = false; }
        }
        @Override public void onCapabilitiesChanged(Network network, NetworkCapabilities capabilities) {
            networkAvailable = capabilities != null
                && capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                && capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED);
            scheduleSenderFundedSettlement();
        }
    };

    private boolean hasInternet(Network network) {
        if (network == null || connectivity == null) return false;
        NetworkCapabilities c = connectivity.getNetworkCapabilities(network);
        return c != null
            && c.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            && c.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED);
    }

    private void scheduleSenderFundedSettlement() {
        if (!networkAvailable || settlementScheduled || io.isShutdown()) return;
        settlementScheduled = true;
        io.execute(new Runnable() {
            @Override public void run() {
                try { attemptSenderFundedSettlement(); }
                finally { settlementScheduled = false; }
            }
        });
    }

    /**
     * Phone C never signs and never pays gas. It only forwards a sender-signed
     * EIP-1559 raw transaction with eth_sendRawTransaction, then gossips the
     * resulting chain receipt back into the nearby mesh.
     */
    private void attemptSenderFundedSettlement() {
        if (!networkAvailable) return;
        long now = System.currentTimeMillis();
        List<String> candidates = db.settlementCandidates(now, 512);
        for (String raw : candidates) {
            try {
                JSONObject packet = new JSONObject(raw);
                String paymentId = packet.optString("paymentId", "");
                if (paymentId.isEmpty()) continue;
                Long retryAt = settlementRetryAfter.get(paymentId);
                if (retryAt != null && retryAt > now) continue;

                JSONObject payment = new JSONObject(packet.optString("payload", "{}"));
                JSONObject auth = payment.optJSONObject("authorization");
                if (auth == null) auth = payment.optJSONObject("auth");
                if (auth == null) continue;
                JSONObject broadcast = auth.optJSONObject("broadcast");
                if (broadcast == null || !"SENDER_FUNDED_RAW_TX".equals(broadcast.optString("mode", ""))) continue;
                if (broadcast.optLong("chainId", -1L) != TRUSTED_CHAIN_ID) continue;

                String rawTx = broadcast.optString("rawTransaction", "");
                String expectedHash = broadcast.optString("txHash", "");
                if (!isHex(rawTx, 4, 262144) || !isTxHash(expectedHash)) continue;

                JSONObject receipt = transactionReceipt(expectedHash);
                if (receipt == null) {
                    try {
                        String returnedHash = sendRawTransaction(rawTx);
                        if (returnedHash != null && isTxHash(returnedHash) && !returnedHash.equalsIgnoreCase(expectedHash)) {
                            throw new IllegalStateException("RPC returned a different transaction hash");
                        }
                    } catch (Throwable broadcastError) {
                        String message = broadcastError.getMessage() == null ? "broadcast failed" : broadcastError.getMessage();
                        String lower = message.toLowerCase();
                        boolean possiblyAlreadySubmitted = lower.contains("already known")
                            || lower.contains("known transaction")
                            || lower.contains("already imported")
                            || lower.contains("nonce too low");
                        if (!possiblyAlreadySubmitted) {
                            settlementRetryAfter.put(paymentId, now + SETTLEMENT_RETRY_MS);
                            db.markSettlementAttempt(paymentId, false, message);
                            continue;
                        }
                    }
                    try { Thread.sleep(650L); } catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
                    receipt = transactionReceipt(expectedHash);
                }

                if (receipt == null) {
                    settlementRetryAfter.put(paymentId, now + SETTLEMENT_RETRY_MS);
                    db.markSettlementAttempt(paymentId, false, "sender-funded transaction pending");
                    continue;
                }

                String status = receipt.optString("status", "");
                if (!"0x1".equalsIgnoreCase(status)) {
                    settlementRetryAfter.put(paymentId, now + 30_000L);
                    db.markSettlementAttempt(paymentId, false, "sender-funded transaction reverted");
                    continue;
                }

                JSONObject evidence = new JSONObject();
                evidence.put("txHash", expectedHash);
                evidence.put("chainId", TRUSTED_CHAIN_ID);
                evidence.put("blockNumber", receipt.optString("blockNumber", ""));
                evidence.put("status", status);
                evidence.put("settlementMode", "SENDER_FUNDED_RAW_TX");
                evidence.put("gasPaidBy", auth.optString("from", "sender"));
                evidence.put("reportedAt", System.currentTimeMillis());
                db.recordSettlementReceipt(packet, evidence, deviceId, publicKey);
                db.markSettlementAttempt(paymentId, true, null);
                settlementRetryAfter.put(paymentId, Long.MAX_VALUE);
                notifyLedgerChanged(paymentId, "SETTLEMENT_RECEIPT");
            } catch (Throwable error) {
                Log.d(TAG, "sender-funded settlement candidate skipped: " + error.getMessage());
            }
        }
        reconcileCanonicalReceipts();
    }

    private void reconcileCanonicalReceipts() {
        if (!networkAvailable) return;
        for (String raw : db.unverifiedSettlementReceipts(64)) {
            try {
                JSONObject item = new JSONObject(raw);
                String paymentId = item.optString("paymentId", "");
                String txHash = item.optString("txHash", "");
                if (paymentId.isEmpty() || !isTxHash(txHash)) continue;
                JSONObject receipt = transactionReceipt(txHash);
                if (receipt == null || !"0x1".equalsIgnoreCase(receipt.optString("status", ""))) continue;
                receipt.put("verifiedBy", deviceId);
                if (db.markChainConfirmed(paymentId, txHash, receipt, System.currentTimeMillis())) {
                    notifyLedgerChanged(paymentId, "CHAIN_CONFIRMED");
                    paymentNotification("Payment confirmed", "Your Blee payment is confirmed on Arc Testnet.", paymentId);
                }
            } catch (Throwable error) {
                Log.d(TAG, "chain confirmation reconciliation skipped: " + error.getMessage());
            }
        }
    }

    private String sendRawTransaction(String rawTx) throws Exception {
        Object result = rpc("eth_sendRawTransaction", new JSONArray().put(rawTx));
        return result instanceof String ? (String) result : null;
    }

    private JSONObject transactionReceipt(String txHash) throws Exception {
        Object result = rpc("eth_getTransactionReceipt", new JSONArray().put(txHash));
        return result instanceof JSONObject ? (JSONObject) result : null;
    }

    private Object rpc(String method, JSONArray params) throws Exception {
        URL url = new URL(TRUSTED_RPC);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        connection.setRequestMethod("POST");
        connection.setConnectTimeout(7000);
        connection.setReadTimeout(12000);
        connection.setDoOutput(true);
        connection.setRequestProperty("Content-Type", "application/json");
        connection.setRequestProperty("Accept", "application/json");

        JSONObject body = new JSONObject();
        body.put("jsonrpc", "2.0");
        body.put("id", 1);
        body.put("method", method);
        body.put("params", params);
        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
        connection.setFixedLengthStreamingMode(bytes.length);
        try (OutputStream out = connection.getOutputStream()) { out.write(bytes); }

        int code = connection.getResponseCode();
        InputStream stream = code >= 200 && code < 300 ? connection.getInputStream() : connection.getErrorStream();
        StringBuilder text = new StringBuilder();
        if (stream != null) {
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) text.append(line);
            }
        }
        connection.disconnect();
        if (code < 200 || code >= 300) throw new IllegalStateException("Arc RPC HTTP " + code + ": " + text);

        JSONObject response = new JSONObject(text.toString());
        JSONObject error = response.optJSONObject("error");
        if (error != null) throw new IllegalStateException(error.optString("message", error.toString()));
        Object result = response.opt("result");
        return result == JSONObject.NULL ? null : result;
    }

    private static boolean isTxHash(String value) {
        return value != null && value.matches("^0x[0-9a-fA-F]{64}$");
    }

    private static boolean isHex(String value, int minChars, int maxChars) {
        return value != null
            && value.length() >= minChars
            && value.length() <= maxChars
            && value.matches("^0x[0-9a-fA-F]+$")
            && ((value.length() - 2) % 2 == 0);
    }

    private boolean bluetoothPermissionsGranted() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return true;
        return checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) == PackageManager.PERMISSION_GRANTED
            && checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED
            && checkSelfPermission(Manifest.permission.BLUETOOTH_ADVERTISE) == PackageManager.PERMISSION_GRANTED;
    }

    // BLEE_ADAPTIVE_NEARBY_V3
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
        private long lastNearbyProgressAt = 0L;
        private long lastNearbyHeartbeatAt = 0L;
        private long lastNearbyPresenceRestartAt = 0L;
        private static final long NEARBY_HEARTBEAT_MS = 5_000L;
        private static final long NEARBY_IDLE_REARM_MS = 30_000L;
        private static final long NEARBY_REARM_COOLDOWN_MS = 15_000L;
        // BLEE_NEARBY_SPEED_PROFILE_V2
        // Profile refresh only. Transport timing remains at the physically
        // proven Adaptive V3 baseline above.
        private static final long PROFILE_SYNC_CHECK_MS = 750L;
        private long lastProfileSyncCheckAt = 0L;
        private String lastProfileFingerprint = "";
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
                if (fallbackActive && now - lastNearbyHeartbeatAt >= NEARBY_HEARTBEAT_MS) {
                    lastNearbyHeartbeatAt = now;
                    refreshConnectedNearbyPresence(now);
                }
                if (fallbackActive && connectionsClient != null) {
                    if (now - lastProfileSyncCheckAt >= PROFILE_SYNC_CHECK_MS) {
                        lastProfileSyncCheckAt = now;
                        syncNearbyProfileIfChanged();
                    }
                    if (!nearbyAdvertising) startNearbyAdvertising();
                    if (!nearbyDiscovering) startNearbyDiscovery();
                    boolean noLiveEndpoint = connectedEndpoints.isEmpty();
                    boolean noPublishedPeer = nearbyPeersSnapshot().isEmpty();
                    boolean stalePresence = lastNearbyProgressAt > 0L && now - lastNearbyProgressAt >= NEARBY_IDLE_REARM_MS;
                    boolean cooldownElapsed = now - lastNearbyPresenceRestartAt >= NEARBY_REARM_COOLDOWN_MS;
                    if ((noLiveEndpoint || noPublishedPeer) && stalePresence && cooldownElapsed) restartNearbyPresence("idle_watchdog");
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
                lastNearbyError = nearbyError(error);
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
                    lastNearbyProgressAt = System.currentTimeMillis();
                    fallbackActive = true;
                    fallbackStarting = false;
                    lastNearbyStatus = "nearby_active";
                    lastNearbyError = "";
                })
                .addOnFailureListener(error -> {
                    nearbyAdvertising = false;
                    lastNearbyError = nearbyError(error);
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
                    lastNearbyProgressAt = System.currentTimeMillis();
                    fallbackActive = true;
                    fallbackStarting = false;
                    lastNearbyStatus = "nearby_active";
                    lastNearbyError = "";
                })
                .addOnFailureListener(error -> {
                    nearbyDiscovering = false;
                    lastNearbyError = nearbyError(error);
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

        private void refreshConnectedNearbyPresence(long now) {
            List<String> endpoints;
            synchronized (connectedEndpoints) { endpoints = new ArrayList<String>(connectedEndpoints); }
            for (String endpointId : endpoints) {
                String transportId = endpointTransportIds.get(endpointId);
                if (transportId == null || transportId.isEmpty()) continue;
                String wallet = peerWallets.get(transportId);
                if (wallet == null || wallet.isEmpty()) continue;
                String name = peerDisplayNames.get(transportId);
                int rssi = peerRssi.containsKey(transportId) ? peerRssi.get(transportId) : 0;
                refreshResolvedPeerHeartbeat(transportId, wallet, name, rssi, now);
                lastNearbyProgressAt = now;
            }
        }

        // BLEE_NEARBY_MEMORY_HEARTBEAT_V1
        private void refreshResolvedPeerHeartbeat(String transportId, String wallet, String displayName, int rssi, long seenAt) {
            if (transportId == null || transportId.isEmpty() || wallet == null || wallet.isEmpty()) return;
            try {
                JSONObject peer = DISCOVERED_PEERS.get(transportId);
                if (peer == null) {
                    publishResolvedPeer(transportId, wallet, displayName, rssi, seenAt);
                    return;
                }
                peer.put("lastSeen", seenAt);
                if (rssi != 0) peer.put("rssi", rssi);
                DISCOVERED_PEERS.put(transportId, peer);
                peerIdentityAt.put(transportId, seenAt);

                Intent intent = new Intent(ACTION_PEER_CHANGED);
                intent.setPackage(getPackageName());
                intent.putExtra(EXTRA_PEER_TRANSPORT_ID, transportId);
                intent.putExtra(EXTRA_PEER_WALLET, peer.optString("wallet", wallet));
                intent.putExtra(EXTRA_PEER_DISPLAY_NAME, peer.optString("displayName", displayName == null ? "" : displayName));
                String avatar = peer.optString("avatar", "");
                if (!avatar.isEmpty()) intent.putExtra(EXTRA_PEER_AVATAR, avatar);
                intent.putExtra(EXTRA_PEER_RSSI, peer.optInt("rssi", rssi));
                intent.putExtra(EXTRA_PEER_LAST_SEEN, seenAt);
                intent.putExtra(EXTRA_PEER_PRESENT, true);
                sendBroadcast(intent);
            } catch (Throwable error) {
                Log.d(TAG, "Nearby presence heartbeat ignored: " + error.getMessage());
            }
        }

        private String currentProfileFingerprint() {
            try {
                String wallet = db == null ? "" : db.activeWallet();
                String name = db == null ? "" : db.localDisplayName();
                String avatar = db == null ? "" : db.localAvatar();
                if (wallet == null) wallet = "";
                if (name == null) name = "";
                if (avatar == null) avatar = "";
                return Integer.toHexString((wallet + "|" + name + "|" + avatar).hashCode());
            } catch (Throwable ignored) {
                return "";
            }
        }

        private void syncNearbyProfileIfChanged() {
            if (!fallbackActive || connectionsClient == null) return;
            String fingerprint = currentProfileFingerprint();
            if (fingerprint.equals(lastProfileFingerprint)) return;
            lastProfileFingerprint = fingerprint;
            List<String> endpoints;
            synchronized (connectedEndpoints) { endpoints = new ArrayList<String>(connectedEndpoints); }
            for (String endpointId : endpoints) sendNearbyIdentity(endpointId);
        }

        private void restartNearbyPresence(String reason) {
            if (!active || connectionsClient == null) return;
            long now = System.currentTimeMillis();
            if (now - lastNearbyPresenceRestartAt < NEARBY_REARM_COOLDOWN_MS) return;
            lastNearbyPresenceRestartAt = now;
            lastNearbyProgressAt = now;
            lastNearbyStatus = "nearby_rearming_" + reason;

            // Clear ghost endpoint state only when the presence watchdog has
            // proved we have no usable published peer.
            List<String> endpoints;
            synchronized (connectedEndpoints) { endpoints = new ArrayList<String>(connectedEndpoints); }
            for (String endpointId : endpoints) forgetNearbyEndpoint(endpointId);
            try { connectionsClient.stopAllEndpoints(); } catch (Throwable ignored) {}
            try { connectionsClient.stopAdvertising(); } catch (Throwable ignored) {}
            try { connectionsClient.stopDiscovery(); } catch (Throwable ignored) {}
            nearbyAdvertising = false;
            nearbyDiscovering = false;
            handler.postDelayed(() -> {
                if (!active || !fallbackActive || connectionsClient == null) return;
                startNearbyAdvertising();
                startNearbyDiscovery();
            }, 400L);
        }

        private void forgetNearbyEndpoint(String endpointId) {
            if (endpointId == null) return;
            String transportId = endpointTransportIds.remove(endpointId);
            endpointPeerIds.remove(endpointId);
            connectedEndpoints.remove(endpointId);
            if (transportId != null) forgetResolvedPeer(transportId, System.currentTimeMillis());
        }

        private void stopNearby() {
            List<String> oldEndpoints;
            synchronized (connectedEndpoints) { oldEndpoints = new ArrayList<String>(connectedEndpoints); }
            for (String endpointId : oldEndpoints) forgetNearbyEndpoint(endpointId);
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
                lastNearbyProgressAt = System.currentTimeMillis();
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
                        lastNearbyError = nearbyError(error);
                    });
            }

            @Override public void onEndpointLost(String endpointId) {
                if (!connectedEndpoints.contains(endpointId)) forgetNearbyEndpoint(endpointId);
                lastNearbyProgressAt = System.currentTimeMillis();
                if (active && fallbackActive) {
                    if (!nearbyDiscovering) startNearbyDiscovery();
                    if (!nearbyAdvertising) startNearbyAdvertising();
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
                            lastNearbyError = nearbyError(error);
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
                    lastNearbyProgressAt = System.currentTimeMillis();
                    // Keep discovery running while connected: Blee is a persistent
                    // nearby presence, not a one-shot pairing session.
                    sendNearbyIdentity(endpointId);
                    handler.postDelayed(() -> pumpNearbyPacket(endpointId), 250L);
                } else {
                    lastNearbyStatus = "nearby_connection_failed_" + status;
                    lastNearbyError = "Nearby connection status=" + status;
                }
            }

            @Override public void onDisconnected(String endpointId) {
                forgetNearbyEndpoint(endpointId);
                lastNearbyProgressAt = System.currentTimeMillis();
                lastNearbyStatus = "nearby_disconnected";
                if (active && fallbackActive) {
                    handler.postDelayed(() -> {
                        if (!active || !fallbackActive || connectionsClient == null) return;
                        if (!nearbyDiscovering) startNearbyDiscovery();
                        if (!nearbyAdvertising) startNearbyAdvertising();
                    }, 350L);
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
                JSONObject identity = new JSONObject();
                identity.put("kind", "blee_identity_v3");
                identity.put("peerId", hexBytes(localPeerIdBytes()));
                String wallet = db == null ? null : db.activeWallet();
                if (wallet != null) identity.put("wallet", wallet);
                String displayName = db == null ? null : db.localDisplayName();
                if (displayName != null && !displayName.isEmpty()) identity.put("displayName", displayName);
                String avatar = db == null ? null : db.localAvatar();
                if (avatar != null && !avatar.isEmpty() && avatar.length() <= 300_000) identity.put("avatar", avatar);
                connectionsClient.sendPayload(endpointId, Payload.fromBytes(identity.toString().getBytes(StandardCharsets.UTF_8)));
            } catch (Throwable error) {
                lastNearbyError = nearbyError(error);
            }
        }

        private void handleNearbyBytes(String endpointId, byte[] bytes) {
            try {
                JSONObject envelope = new JSONObject(new String(bytes, StandardCharsets.UTF_8));
                String kind = envelope.optString("kind", "");
                if ("blee_identity_v3".equals(kind)) {
                    String wallet = envelope.optString("wallet", "");
                    String displayName = envelope.optString("displayName", "");
                    String avatar = envelope.optString("avatar", "");
                    String peerHex = envelope.optString("peerId", "");
                    byte[] remote = endpointPeerIds.get(endpointId);
                    String transportId = remote == null ? endpointTransportIds.get(endpointId) : nearbyTransportId(remote, endpointId);
                    if ((transportId == null || transportId.isEmpty()) && peerHex.matches("^[0-9a-fA-F]{16}$")) transportId = "nc:" + peerHex.toLowerCase(Locale.ROOT);
                    if (transportId == null || transportId.isEmpty()) transportId = "nc:endpoint:" + endpointId;
                    endpointTransportIds.put(endpointId, transportId);
                    lastNearbyProgressAt = System.currentTimeMillis();
                    if (!avatar.isEmpty()) peerAvatars.put(transportId, avatar);
                    publishResolvedPeer(transportId, wallet, displayName, 0, System.currentTimeMillis());
                    notifyLedgerChanged("", "PEER_IDENTITY_UPDATED");
                    pumpNearbyPacket(endpointId);
                    return;
                }
                if ("blee_packet_v3".equals(kind)) {
                    String raw = envelope.optString("raw", "");
                    if (raw.isEmpty() || raw.length() > MAX_NEARBY_PACKET_BYTES) return;
                    BleeMeshDb.ProcessResult result = db.receive(raw, deviceId, publicKey);
                    if (result.accepted && (result.ledgerChanged || "PAYMENT_ENVELOPE".equals(result.type))) {
                        notifyLedgerChanged(result.paymentId, result.ledgerChanged ? result.type : "PAYMENT_ENVELOPE_RECEIVED");
                    }
                    if (result.notificationTitle != null) paymentNotification(result.notificationTitle, result.notificationBody, result.paymentId);
                    if (result.accepted) scheduleSenderFundedSettlement();
                }
            } catch (Throwable error) {
                lastNearbyError = nearbyError(error);
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
                        lastNearbyError = nearbyError(error);
                    });
            } catch (Throwable error) {
                lastNearbyError = nearbyError(error);
            }
        }

        private String nearbyError(Throwable error) {
            if (error == null) return "unknown";
            String value = error.getMessage();
            return value == null || value.isEmpty() ? error.toString() : value;
        }

        String mode() {
            if ("permission_required".equals(lastNearbyStatus)) return "permission_required";
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

    // BLEE_TRANSPORT_CORE_V2
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

        private void setAdaptiveScanEnabled(boolean enabled) {
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
                int adaptiveScanMode = advertiseActive
                    ? ScanSettings.SCAN_MODE_BALANCED
                    : ScanSettings.SCAN_MODE_LOW_LATENCY;
                ScanSettings.Builder settings = new ScanSettings.Builder()
                    .setScanMode(adaptiveScanMode)
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
                        if (status != BluetoothGatt.GATT_SUCCESS && adaptiveNearbyV3 != null) adaptiveNearbyV3.onGattFailure(status);
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
                if (adaptiveNearbyV3 != null) {
                    JSONObject adaptive = adaptiveNearbyV3.snapshot();
                    java.util.Iterator<String> adaptiveKeys = adaptive.keys();
                    while (adaptiveKeys.hasNext()) {
                        String adaptiveKey = adaptiveKeys.next();
                        out.put(adaptiveKey, adaptive.opt(adaptiveKey));
                    }
                }
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

    private void startBluetooth() {
        if (!bluetoothPermissionsGranted()) return;
        if (adaptiveNearbyV3 == null) adaptiveNearbyV3 = new AdaptiveNearbyV3();
        adaptiveNearbyV3.start();
    }

    private void stopBluetooth() {
        if (adaptiveNearbyV3 != null) adaptiveNearbyV3.stop();
        else if (bleTransportV2 != null) bleTransportV2.stop();
        scanning = false;
        advertising = false;
        advertiseStarting = false;
        gattServerReady = false;
    }

    private void startGattServer() {
        if (gattServer != null || bluetoothManager == null) return;
        gattServerReady = false;
        gattServer = bluetoothManager.openGattServer(this, serverCallback);
        if (gattServer == null) return;
        BluetoothGattService service = new BluetoothGattService(SERVICE_UUID, BluetoothGattService.SERVICE_TYPE_PRIMARY);
        BluetoothGattCharacteristic write = new BluetoothGattCharacteristic(
            WRITE_UUID,
            BluetoothGattCharacteristic.PROPERTY_WRITE,
            BluetoothGattCharacteristic.PERMISSION_WRITE
        );
        service.addCharacteristic(write);
        BluetoothGattCharacteristic identity = new BluetoothGattCharacteristic(
            IDENTITY_UUID,
            BluetoothGattCharacteristic.PROPERTY_READ | BluetoothGattCharacteristic.PROPERTY_WRITE,
            BluetoothGattCharacteristic.PERMISSION_READ | BluetoothGattCharacteristic.PERMISSION_WRITE
        );
        service.addCharacteristic(identity);
        gattServer.addService(service);
    }

    private final AdvertiseCallback advertiseCallback = new AdvertiseCallback() {
        @Override public void onStartSuccess(AdvertiseSettings settingsInEffect) {
            advertiseStarting = false;
            advertising = true;
            advertiseRetryCount = 0;
            nextAdvertiseAttemptAt = 0L;
            diagAdvertiseSuccesses++;
            diagLastPhase = "advertising_active";
            diagLastError = "";
            onAdvertiseStarted();
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
            diagAdvertiseFailures++;
            diagLastPhase = "advertising_failed";
            diagLastError = "advertise_error_" + errorCode;
            onAdvertiseFailed(errorCode);
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

    private boolean isBleeAdvertisement(ScanResult result) {
        try {
            if (result == null || result.getScanRecord() == null) return false;
            List<ParcelUuid> serviceUuids = result.getScanRecord().getServiceUuids();
            if (serviceUuids == null) return false;
            ParcelUuid expected = new ParcelUuid(SERVICE_UUID);
            for (ParcelUuid uuid : serviceUuids) if (expected.equals(uuid)) return true;
        } catch (Throwable ignored) {}
        return false;
    }

    private final ScanCallback scanCallback = new ScanCallback() {
        @Override public void onScanResult(int callbackType, ScanResult result) {
            if (result == null || result.getDevice() == null) return;
            diagRawScanResults++;
            diagLastSeenAt = System.currentTimeMillis();
            diagLastRssi = result.getRssi();
            try { diagLastTransportId = result.getDevice().getAddress(); } catch (Throwable ignored) {}
            diagLastPhase = "scan_result";
            if (!isBleeAdvertisement(result)) return;
            diagBleeAdvertisements++;
            diagLastPhase = "blee_advertisement_seen";
            rememberPeerRoleToken(result);
            lastBleHitAt = System.currentTimeMillis();
            BluetoothDevice device = result.getDevice();
            String address = device.getAddress();
            long seenAt = System.currentTimeMillis();
            peers.put(address, device);
            peerSeen.put(address, seenAt);
            peerRssi.put(address, result.getRssi());
            String knownWallet = peerWallets.get(address);
            if (knownWallet != null) {
                publishResolvedPeer(address, knownWallet, peerDisplayNames.get(address), result.getRssi(), seenAt);
            }
            if (!connectImmediatelyFromScan(result)) maybeConnect(device);
        }

        @Override public void onBatchScanResults(List<ScanResult> results) {
            if (results == null) return;
            for (ScanResult result : results) onScanResult(ScanSettings.CALLBACK_TYPE_ALL_MATCHES, result);
        }

        @Override public void onScanFailed(int errorCode) {
            scanning = false;
            diagLastPhase = "scan_failed";
            diagLastError = "scan_error_" + errorCode;
            Log.w(TAG, "BLE scan failed: " + errorCode + "; rearming");
            handler.postDelayed(new Runnable() {
                @Override public void run() { startBluetooth(); }
            }, 1200L);
        }
    };

    private void pumpKnownPeers() {
        // Re-attempt identity discovery for remembered scan results even when
        // Android only delivered one advertisement callback and no payment is
        // queued. maybeConnect() provides the per-device retry throttle.
        List<BluetoothDevice> snapshot;
        synchronized (peers) { snapshot = new ArrayList<BluetoothDevice>(peers.values()); }
        for (BluetoothDevice device : snapshot) maybeConnect(device);
    }


    private final BluetoothGattCallback clientCallback = new BluetoothGattCallback() {
        @Override public void onConnectionStateChange(final BluetoothGatt gatt, final int status, final int newState) {
            handler.post(() -> handleClientConnectionState(gatt, status, newState));
        }

        @Override public void onServicesDiscovered(final BluetoothGatt gatt, int status) {
            if (status != BluetoothGatt.GATT_SUCCESS) { diagLastPhase = "service_discovery_failed"; diagLastError = "gatt_service_" + status; failGatt(gatt, "service discovery status=" + status); return; }
            diagServicesDiscovered++;
            diagLastPhase = "blee_service_discovered";
            touchGatt(gatt);
            // Identity is exactly 20 bytes and fits the default ATT MTU. Reading
            // it first avoids overlapping MTU negotiation on slow stacks.
            readIdentityOrSend(gatt);
        }

        @Override public void onCharacteristicRead(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
            touchGatt(gatt);
            boolean identityResolved = false;
            try {
                if (status == BluetoothGatt.GATT_SUCCESS && characteristic != null && IDENTITY_UUID.equals(characteristic.getUuid())) {
                    identityResolved = handleIdentityRead(gatt, characteristic.getValue());
                }
            } catch (Throwable ignored) {}
            if (identityResolved) writeLocalIdentity(gatt);
            else failGatt(gatt, "identity read failed");
        }

        @Override public void onCharacteristicRead(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, byte[] value, int status) {
            touchGatt(gatt);
            boolean identityResolved = false;
            try {
                if (status == BluetoothGatt.GATT_SUCCESS && characteristic != null && IDENTITY_UUID.equals(characteristic.getUuid())) {
                    identityResolved = handleIdentityRead(gatt, value);
                }
            } catch (Throwable ignored) {}
            if (identityResolved) writeLocalIdentity(gatt);
            else failGatt(gatt, "identity read failed");
        }

        @Override public void onMtuChanged(BluetoothGatt gatt, int mtu, int status) {
            touchGatt(gatt);
            if (status == BluetoothGatt.GATT_SUCCESS && mtu >= 23) sendOnePacket(gatt, mtu);
            else closeGatt(gatt);
        }

        @Override public void onCharacteristicWrite(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
            touchGatt(gatt);
            if (characteristic != null && IDENTITY_UUID.equals(characteristic.getUuid())) {
                // The remote identity was validated by the preceding read. A
                // legacy read-only peer may reject this optional write, but its
                // queued payment must still continue to MTU negotiation.
                continueAfterIdentity(gatt);
                return;
            }
            SendState state = SendState.forGatt(gatt);
            if (state == null) { closeGatt(gatt); return; }
            if (status != BluetoothGatt.GATT_SUCCESS) { SendState.clear(gatt); closeGatt(gatt); return; }
            if (!state.writeNext(gatt)) {
                String peerAddress = gatt.getDevice() == null ? "unknown" : gatt.getDevice().getAddress();
                db.recordPeerDelivery(state.messageId, peerAddress);
                SendState.clear(gatt);
                closeGatt(gatt);
            }
        }
    };

    private void continueAfterIdentity(BluetoothGatt gatt) {
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

    private void sendOnePacket(BluetoothGatt gatt, int mtu) {
        String peerAddress = gatt.getDevice() == null ? "unknown" : gatt.getDevice().getAddress();
        List<String> packets = db.duePacketsForPeer(System.currentTimeMillis(), peerAddress, 1);
        if (packets.isEmpty()) { closeGatt(gatt); return; }
        BluetoothGattService service = gatt.getService(SERVICE_UUID);
        BluetoothGattCharacteristic characteristic = service == null ? null : service.getCharacteristic(WRITE_UUID);
        if (characteristic == null) { closeGatt(gatt); return; }
        try {
            JSONObject packet = new JSONObject(packets.get(0));
            String messageId = packet.optString("messageId", UUID.randomUUID().toString());
            SendState state = SendState.create(messageId, packets.get(0), characteristic, mtu);
            if (state == null) { closeGatt(gatt); return; }
            SendState.put(gatt, state);
            if (!state.writeNext(gatt)) { SendState.clear(gatt); closeGatt(gatt); }
        } catch (Throwable ignored) { closeGatt(gatt); }
    }

    private void closeGatt(BluetoothGatt gatt) {
        finishGatt(gatt, false, "completed");
    }

    private final BluetoothGattServerCallback serverCallback = new BluetoothGattServerCallback() {
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
        }
        @Override public void onCharacteristicReadRequest(
            BluetoothDevice device, int requestId, int offset, BluetoothGattCharacteristic characteristic
        ) {
            if (gattServer == null || characteristic == null || !IDENTITY_UUID.equals(characteristic.getUuid())) {
                if (gattServer != null) {
                    try { gattServer.sendResponse(device, requestId, BluetoothGatt.GATT_FAILURE, offset, null); } catch (Throwable ignored) {}
                }
                return;
            }
            try {
                byte[] identity = localIdentityPayload();
                if (offset < 0 || offset > identity.length) {
                    gattServer.sendResponse(device, requestId, BluetoothGatt.GATT_FAILURE, offset, null);
                    return;
                }
                byte[] slice = Arrays.copyOfRange(identity, offset, identity.length);
                gattServer.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, offset, slice);
            } catch (Throwable error) {
                try { gattServer.sendResponse(device, requestId, BluetoothGatt.GATT_FAILURE, offset, null); } catch (Throwable ignored) {}
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
                        status = BluetoothGatt.GATT_SUCCESS;
                    }
                } else if (characteristic != null && WRITE_UUID.equals(characteristic.getUuid()) && value != null) {
                    String frame = new String(value, StandardCharsets.UTF_8);
                    status = acceptFrame(device, frame) ? BluetoothGatt.GATT_SUCCESS : BluetoothGatt.GATT_FAILURE;
                }
            } catch (Throwable ignored) {}
            if (responseNeeded && gattServer != null) {
                try { gattServer.sendResponse(device, requestId, status, 0, null); } catch (Throwable ignored) {}
            }
        }
    };

    private boolean acceptFrame(BluetoothDevice device, String frame) {
        if (!frame.startsWith("B2|")) return false;
        String[] parts = frame.split("\\|", 5);
        if (parts.length != 5) return false;
        String messageId = parts[1];
        int index;
        int total;
        try { index = Integer.parseInt(parts[2]); total = Integer.parseInt(parts[3]); }
        catch (Throwable ignored) { return false; }
        if (messageId.isEmpty() || messageId.length() > 160) return false;
        if (total <= 0 || total > MAX_FRAGMENTS || index < 0 || index >= total) return false;
        String chunk = parts[4];
        if (chunk.length() > MAX_FRAME_CHARS) return false;
        long now = System.currentTimeMillis();
        cleanupEphemeralState(now);
        String address = device.getAddress();
        String key = address + ":" + messageId;
        Assembly assembly = assemblies.get(key);
        if (assembly == null || assembly.total != total) {
            if (assemblies.size() >= MAX_ASSEMBLIES || assembliesForPeer(address) >= MAX_ASSEMBLIES_PER_PEER) return false;
            assembly = new Assembly(total, now);
            assemblies.put(key, assembly);
        }
        if (assembly.parts[index] == null) assembly.encodedChars += chunk.length();
        if (assembly.encodedChars > MAX_ENCODED_PACKET_CHARS) { assemblies.remove(key); return false; }
        assembly.parts[index] = chunk;
        if (!assembly.complete()) return true;
        assemblies.remove(key);
        try {
            StringBuilder b64 = new StringBuilder();
            for (String part : assembly.parts) b64.append(part);
            byte[] decoded = Base64.decode(b64.toString(), Base64.NO_WRAP);
            if (decoded.length == 0 || decoded.length > MAX_PACKET_BYTES) return false;
            String raw = new String(decoded, StandardCharsets.UTF_8);
            BleeMeshDb.ProcessResult result = db.receive(raw, deviceId, publicKey);
            // BLEE_PRODUCTION_RAW_PAYMENT_WAKEUP_V1
            if (result.accepted && (result.ledgerChanged || "PAYMENT_ENVELOPE".equals(result.type))) {
                notifyLedgerChanged(result.paymentId, result.ledgerChanged ? result.type : "PAYMENT_ENVELOPE_RECEIVED");
            }
            if (result.notificationTitle != null) paymentNotification(result.notificationTitle, result.notificationBody, result.paymentId);
            if (result.accepted) scheduleSenderFundedSettlement();
            return result.accepted;
        } catch (Throwable error) {
            Log.w(TAG, "packet assembly failed", error);
            return false;
        }
    }

    private void notifyLedgerChanged(String paymentId, String type) {
        // BLEE_BACKGROUND_RECEIVE_NOTIFICATION_V2
        // PAYMENT_ENVELOPE_RECEIVED is emitted by native transport immediately.
        // Wording stays at "detected" until EIP-3009 verification promotes it.
        if ("PAYMENT_ENVELOPE_RECEIVED".equals(type)) BleePaymentNotifier.detected(this, paymentId);

        if ("DELIVERY_ACK".equals(type)) BleePaymentNotifier.delivered(this, paymentId);

        Intent intent = new Intent(ACTION_LEDGER_CHANGED);
        intent.setPackage(getPackageName());
        intent.putExtra(EXTRA_PAYMENT_ID, paymentId == null ? "" : paymentId);
        intent.putExtra(EXTRA_EVENT_TYPE, type == null ? "" : type);
        sendBroadcast(intent);
    }

    private void createNotificationChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return;
        NotificationChannel service = new NotificationChannel(CHANNEL_SERVICE, "Blee nearby payments", NotificationManager.IMPORTANCE_LOW);
        service.setDescription("Keeps Blee nearby payment delivery and reconciliation active.");
        manager.createNotificationChannel(service);
        NotificationChannel payments = new NotificationChannel(CHANNEL_PAYMENTS, "Blee payments", NotificationManager.IMPORTANCE_HIGH);
        payments.setDescription("Payment received and settlement notifications.");
        manager.createNotificationChannel(payments);
    }

    private Notification serviceNotification(String text) {
        Intent launch = getPackageManager().getLaunchIntentForPackage(getPackageName());
        PendingIntent pending = launch == null ? null : PendingIntent.getActivity(this, 0, launch, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            ? new Notification.Builder(this, CHANNEL_SERVICE)
            : new Notification.Builder(this);
        builder.setContentTitle("Blee")
            .setContentText(text)
            .setSmallIcon(R.drawable.blee_notification)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(Notification.CATEGORY_SERVICE);
        if (pending != null) builder.setContentIntent(pending);
        return builder.build();
    }

    private void paymentNotification(String title, String body, String paymentId) {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return;
        NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return;
        Intent launch = getPackageManager().getLaunchIntentForPackage(getPackageName());
        if (launch != null && paymentId != null) launch.putExtra("bleePaymentId", paymentId);
        PendingIntent pending = launch == null ? null : PendingIntent.getActivity(
            this,
            paymentId == null ? 0 : paymentId.hashCode(),
            launch,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            ? new Notification.Builder(this, CHANNEL_PAYMENTS)
            : new Notification.Builder(this);
        builder.setContentTitle(title)
            .setContentText(body)
            .setSmallIcon(R.drawable.blee_notification)
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_MESSAGE);
        if (pending != null) builder.setContentIntent(pending);
        manager.notify(paymentId == null ? (int) System.currentTimeMillis() : paymentId.hashCode(), builder.build());
    }

    private static final class Assembly {
        final int total;
        final String[] parts;
        final long createdAt;
        int encodedChars = 0;
        Assembly(int total, long createdAt) { this.total = total; this.createdAt = createdAt; this.parts = new String[total]; }
        boolean complete() { for (String p : parts) if (p == null) return false; return true; }
    }

    private static final class SendState {
        private static final Map<BluetoothGatt, SendState> STATES = Collections.synchronizedMap(new HashMap<BluetoothGatt, SendState>());
        final String messageId;
        final BluetoothGattCharacteristic characteristic;
        final List<byte[]> frames;
        int next = 0;

        private SendState(String messageId, BluetoothGattCharacteristic characteristic, List<byte[]> frames) {
            this.messageId = messageId;
            this.characteristic = characteristic;
            this.frames = frames;
        }

        static SendState create(String messageId, String raw, BluetoothGattCharacteristic characteristic, int mtu) {
            String encoded = Base64.encodeToString(raw.getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP);
            int headerBytes = ("B2|" + messageId + "|2147483647|2147483647|").getBytes(StandardCharsets.UTF_8).length;
            int chunkSize = Math.max(1, mtu - 3 - headerBytes);
            int total = (encoded.length() + chunkSize - 1) / chunkSize;
            if (total <= 0 || total > MAX_FRAGMENTS) return null;
            List<byte[]> frames = new ArrayList<byte[]>();
            for (int i = 0; i < total; i++) {
                int end = Math.min(encoded.length(), (i + 1) * chunkSize);
                String frame = "B2|" + messageId + "|" + i + "|" + total + "|" + encoded.substring(i * chunkSize, end);
                frames.add(frame.getBytes(StandardCharsets.UTF_8));
            }
            return new SendState(messageId, characteristic, frames);
        }

        boolean writeNext(BluetoothGatt gatt) {
            if (next >= frames.size()) return false;
            byte[] data = frames.get(next++);
            characteristic.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
            if (Build.VERSION.SDK_INT >= 33) {
                return gatt.writeCharacteristic(characteristic, data, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == 0;
            }
            characteristic.setValue(data);
            return gatt.writeCharacteristic(characteristic);
        }

        static void put(BluetoothGatt gatt, SendState state) { STATES.put(gatt, state); }
        static SendState forGatt(BluetoothGatt gatt) { return STATES.get(gatt); }
        static void clear(BluetoothGatt gatt) { STATES.remove(gatt); }
    }
}
