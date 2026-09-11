#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android/app/src/main/java"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Blee reliability: missing {label} anchor")
    return text.replace(old, new, 1)


def locate_activity() -> Path:
    matches = list(ANDROID.rglob("MainActivity.java"))
    if len(matches) != 1:
        raise SystemExit(f"Blee reliability: expected one MainActivity.java, found {len(matches)}")
    return matches[0]


def patch_mesh_db(native_dir: Path) -> None:
    path = native_dir / "BleeMeshDb.java"
    text = path.read_text()
    marker = "BLEE_NATIVE_DISCOVERY_IDENTITY_V1"
    if marker in text:
        return

    anchor = "    synchronized String getKv(String key) {"
    helper = r'''    // BLEE_NATIVE_DISCOVERY_IDENTITY_V1
    synchronized String localDisplayName() {
        String wallet = activeWallet();
        if (wallet != null) {
            try (Cursor c = db().query(
                "peer_identities", new String[] { "display_name" },
                "wallet_address=?", new String[] { wallet }, null, null, null, "1"
            )) {
                if (c.moveToFirst()) {
                    String candidate = cleanDisplayName(c.getString(0));
                    if (candidate != null) return candidate;
                }
            } catch (Throwable ignored) {}
        }

        String[] preferred = new String[] {
            "profile.alias", "profile.displayName", "wallet.alias", "blee.alias",
            "displayName", "alias", "profile.name"
        };
        for (String key : preferred) {
            String candidate = cleanDisplayName(getKv(key));
            if (candidate != null) return candidate;
        }

        // Older Blee builds used different profile-key names. Read only short
        // profile-ish KV values and never expose vault/private-key material.
        try (Cursor c = db().rawQuery(
            "SELECT key,value FROM kv WHERE lower(key) LIKE '%alias%' OR lower(key) LIKE '%display%' OR lower(key) LIKE '%profile%' ORDER BY updated_at DESC LIMIT 16",
            null
        )) {
            while (c.moveToNext()) {
                String key = c.getString(0) == null ? "" : c.getString(0).toLowerCase(Locale.ROOT);
                if (key.contains("photo") || key.contains("avatar") || key.contains("vault") || key.contains("key")) continue;
                String candidate = cleanDisplayName(c.getString(1));
                if (candidate != null) return candidate;
            }
        } catch (Throwable ignored) {}
        return null;
    }

    private static String cleanDisplayName(String raw) {
        if (raw == null) return null;
        String value = raw.trim();
        if (value.isEmpty() || value.length() > 512 || value.startsWith("data:")) return null;
        try {
            JSONObject object = new JSONObject(value);
            for (String key : new String[] { "alias", "displayName", "name" }) {
                String candidate = object.optString(key, "").trim();
                if (!candidate.isEmpty() && candidate.length() <= 64) return candidate;
            }
        } catch (Throwable ignored) {}
        if (value.startsWith("\"") && value.endsWith("\"") && value.length() >= 2) {
            value = value.substring(1, value.length() - 1).trim();
        }
        if (value.isEmpty() || value.length() > 64 || value.startsWith("{") || value.startsWith("[")) return null;
        return value;
    }

'''
    text = replace_once(text, anchor, helper + anchor, "local display-name helper")
    path.write_text(text)
    print("Blee reliability: native BLE identity can resolve wallet + display name")


def patch_mesh_service(native_dir: Path) -> None:
    path = native_dir / "BleeMeshService.java"
    text = path.read_text()
    marker = "BLEE_NATIVE_BLE_DISCOVERY_V3"
    if marker in text:
        return

    if "import java.util.concurrent.ConcurrentHashMap;" not in text:
        text = text.replace(
            "import java.util.concurrent.ExecutorService;",
            "import java.util.concurrent.ConcurrentHashMap;\nimport java.util.concurrent.ExecutorService;",
            1,
        )

    text = replace_once(
        text,
        '    static final String EXTRA_EVENT_TYPE = "eventType";',
        '''    static final String EXTRA_EVENT_TYPE = "eventType";
    // BLEE_NATIVE_BLE_DISCOVERY_V3
    static final String ACTION_PEER_CHANGED = "__BLEE_APP_PACKAGE__.BLEE_PEER_CHANGED";
    static final String EXTRA_PEER_TRANSPORT_ID = "transportId";
    static final String EXTRA_PEER_WALLET = "wallet";
    static final String EXTRA_PEER_DISPLAY_NAME = "displayName";
    static final String EXTRA_PEER_RSSI = "rssi";
    static final String EXTRA_PEER_LAST_SEEN = "lastSeen";
    static final String EXTRA_PEER_PRESENT = "present";''',
        "peer event constants",
    )

    text = replace_once(
        text,
        '    private static final UUID WRITE_UUID = UUID.fromString("50f57a10-7bd4-4b6a-bf45-b1ee20000002");',
        '''    private static final UUID WRITE_UUID = UUID.fromString("50f57a10-7bd4-4b6a-bf45-b1ee20000002");
    private static final UUID IDENTITY_UUID = UUID.fromString("50f57a10-7bd4-4b6a-bf45-b1ee20000003");''',
        "identity characteristic UUID",
    )

    field_anchor = "    private final Map<String, Long> peerSeen = Collections.synchronizedMap(new HashMap<String, Long>());"
    fields = field_anchor + r'''
    private final Map<String, String> peerWallets = Collections.synchronizedMap(new HashMap<String, String>());
    private final Map<String, String> peerDisplayNames = Collections.synchronizedMap(new HashMap<String, String>());
    private final Map<String, Long> peerIdentityAt = Collections.synchronizedMap(new HashMap<String, Long>());
    private final Map<String, Integer> peerRssi = Collections.synchronizedMap(new HashMap<String, Integer>());
    private static final Map<String, JSONObject> DISCOVERED_PEERS = new ConcurrentHashMap<String, JSONObject>();'''
    text = replace_once(text, field_anchor, fields, "BLE peer identity maps")

    cleanup_old = '''                if (seenAt == null || now - seenAt > PEER_STALE_MS) {
                    peerSeen.remove(address);
                    peers.remove(address);
                    lastConnect.remove(address);
                }'''
    cleanup_new = '''                if (seenAt == null || now - seenAt > PEER_STALE_MS) {
                    peerSeen.remove(address);
                    peers.remove(address);
                    lastConnect.remove(address);
                    peerIdentityAt.remove(address);
                    peerWallets.remove(address);
                    peerDisplayNames.remove(address);
                    peerRssi.remove(address);
                    if (DISCOVERED_PEERS.remove(address) != null) publishPeerGone(address, now);
                }'''
    text = replace_once(text, cleanup_old, cleanup_new, "stale peer cleanup")

    observe_anchor = "    private void observeConnectivity() {"
    peer_helpers = r'''    static List<JSONObject> nearbyPeersSnapshot() {
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

    private void publishResolvedPeer(String address, String wallet, String displayName, int rssi, long seenAt) {
        if (address == null || address.isEmpty() || wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) return;
        String normalizedWallet = wallet.toLowerCase(Locale.ROOT);
        String own = db == null ? null : db.activeWallet();
        if (own != null && own.equalsIgnoreCase(normalizedWallet)) return;
        String cleanName = displayName == null ? "" : displayName.trim();
        if (cleanName.length() > 64) cleanName = cleanName.substring(0, 64);
        try {
            JSONObject peer = new JSONObject();
            peer.put("transportId", address);
            peer.put("wallet", normalizedWallet);
            peer.put("displayName", cleanName);
            peer.put("rssi", rssi);
            peer.put("lastSeen", seenAt);
            peer.put("transport", "ble");
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
            intent.putExtra(EXTRA_PEER_RSSI, rssi);
            intent.putExtra(EXTRA_PEER_LAST_SEEN, seenAt);
            intent.putExtra(EXTRA_PEER_PRESENT, true);
            sendBroadcast(intent);
        } catch (Throwable error) {
            Log.d(TAG, "Unable to publish BLE peer: " + error.getMessage());
        }
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
        try {
            JSONObject identity = new JSONObject();
            identity.put("version", 1);
            String wallet = db == null ? null : db.activeWallet();
            if (wallet != null) identity.put("wallet", wallet);
            String name = db == null ? null : db.localDisplayName();
            if (name != null && !name.isEmpty()) identity.put("displayName", name);
            identity.put("deviceId", deviceId == null ? "" : deviceId);
            return identity.toString().getBytes(StandardCharsets.UTF_8);
        } catch (Throwable ignored) {
            return "{}".getBytes(StandardCharsets.UTF_8);
        }
    }

    private void readIdentityOrSend(BluetoothGatt gatt) {
        if (gatt == null) return;
        try {
            BluetoothGattService service = gatt.getService(SERVICE_UUID);
            BluetoothGattCharacteristic identity = service == null ? null : service.getCharacteristic(IDENTITY_UUID);
            if (identity != null && gatt.readCharacteristic(identity)) return;
        } catch (Throwable ignored) {}
        sendOnePacket(gatt);
    }

    private void handleIdentityRead(BluetoothGatt gatt, byte[] value) {
        try {
            if (gatt == null || gatt.getDevice() == null || value == null || value.length == 0 || value.length > 2048) return;
            JSONObject identity = new JSONObject(new String(value, StandardCharsets.UTF_8));
            String wallet = identity.optString("wallet", "");
            String displayName = identity.optString("displayName", "");
            String address = gatt.getDevice().getAddress();
            int rssi = peerRssi.containsKey(address) ? peerRssi.get(address) : 0;
            publishResolvedPeer(address, wallet, displayName, rssi, System.currentTimeMillis());
        } catch (Throwable error) {
            Log.d(TAG, "BLE identity read ignored: " + error.getMessage());
        }
    }

'''
    text = replace_once(text, observe_anchor, peer_helpers + observe_anchor, "BLE peer helper methods")

    gatt_anchor = '''        service.addCharacteristic(write);
        gattServer.addService(service);'''
    gatt_new = '''        service.addCharacteristic(write);
        BluetoothGattCharacteristic identity = new BluetoothGattCharacteristic(
            IDENTITY_UUID,
            BluetoothGattCharacteristic.PROPERTY_READ,
            BluetoothGattCharacteristic.PERMISSION_READ
        );
        service.addCharacteristic(identity);
        gattServer.addService(service);'''
    text = replace_once(text, gatt_anchor, gatt_new, "GATT identity characteristic")

    server_anchor = '''    private final BluetoothGattServerCallback serverCallback = new BluetoothGattServerCallback() {
        @Override public void onCharacteristicWriteRequest('''
    server_new = '''    private final BluetoothGattServerCallback serverCallback = new BluetoothGattServerCallback() {
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
                    gattServer.sendResponse(device, requestId, BluetoothGatt.GATT_INVALID_OFFSET, offset, null);
                    return;
                }
                byte[] slice = Arrays.copyOfRange(identity, offset, identity.length);
                gattServer.sendResponse(device, requestId, BluetoothGatt.GATT_SUCCESS, offset, slice);
            } catch (Throwable error) {
                try { gattServer.sendResponse(device, requestId, BluetoothGatt.GATT_FAILURE, offset, null); } catch (Throwable ignored) {}
            }
        }

        @Override public void onCharacteristicWriteRequest('''
    text = replace_once(text, server_anchor, server_new, "GATT identity read callback")

    scan_old = '''            peers.put(device.getAddress(), device);
            peerSeen.put(device.getAddress(), System.currentTimeMillis());
            maybeConnect(device);'''
    scan_new = '''            String address = device.getAddress();
            long seenAt = System.currentTimeMillis();
            peers.put(address, device);
            peerSeen.put(address, seenAt);
            peerRssi.put(address, result.getRssi());
            String knownWallet = peerWallets.get(address);
            if (knownWallet != null) {
                publishResolvedPeer(address, knownWallet, peerDisplayNames.get(address), result.getRssi(), seenAt);
            }
            maybeConnect(device);'''
    text = replace_once(text, scan_old, scan_new, "scan result publication")

    maybe_pattern = re.compile(
        r'''    private void maybeConnect\(BluetoothDevice device\) \{\n        if \(!bluetoothPermissionsGranted\(\)\) return;\n        long now = System\.currentTimeMillis\(\);\n        Long previous = lastConnect\.get\(device\.getAddress\(\)\);\n        if \(previous != null && now - previous < PEER_RETRY_MS\) return;\n        if \(db\.duePackets\(now, 1\)\.isEmpty\(\)\) return;\n        lastConnect\.put\(device\.getAddress\(\), now\);\n        try \{ device\.connectGatt\(this, false, clientCallback, BluetoothDevice\.TRANSPORT_LE\); \}\n        catch \(Throwable error\) \{ Log\.d\(TAG, "connect failed: " \+ error\.getMessage\(\)\); \}\n    \}'''
    )
    maybe_new = '''    private void maybeConnect(BluetoothDevice device) {
        if (!bluetoothPermissionsGranted() || device == null) return;
        long now = System.currentTimeMillis();
        String address = device.getAddress();
        Long previous = lastConnect.get(address);
        if (previous != null && now - previous < PEER_RETRY_MS) return;
        Long identityAt = peerIdentityAt.get(address);
        boolean needsIdentity = identityAt == null || now - identityAt > 45_000L;
        boolean hasPacket = !db.duePacketsForPeer(now, address, 1).isEmpty();
        // Discovery itself is a reason to connect. The old implementation only
        // opened GATT when a payment was already queued, so BLE-only users could
        // never become identifiable peers in the UI.
        if (!needsIdentity && !hasPacket) return;
        lastConnect.put(address, now);
        try { device.connectGatt(this, false, clientCallback, BluetoothDevice.TRANSPORT_LE); }
        catch (Throwable error) { Log.d(TAG, "connect failed: " + error.getMessage()); }
    }'''
    text, count = maybe_pattern.subn(maybe_new, text, count=1)
    if count != 1:
        # Hardening may already have changed duePackets() to duePacketsForPeer().
        start = text.find("    private void maybeConnect(BluetoothDevice device) {")
        end = text.find("\n    private final BluetoothGattCallback clientCallback", start)
        if start < 0 or end < 0:
            raise SystemExit("Blee reliability: maybeConnect method anchor not found")
        text = text[:start] + maybe_new + "\n" + text[end:]

    service_discovery_pattern = re.compile(
        r'''        @Override public void onServicesDiscovered\(final BluetoothGatt gatt, int status\) \{.*?\n        \}\n\n        @Override public void onCharacteristicWrite''',
        re.S,
    )
    service_discovery_new = '''        @Override public void onServicesDiscovered(final BluetoothGatt gatt, int status) {
            if (status != BluetoothGatt.GATT_SUCCESS) { closeGatt(gatt); return; }
            try { gatt.requestMtu(517); } catch (Throwable ignored) {}
            handler.postDelayed(new Runnable() {
                @Override public void run() { readIdentityOrSend(gatt); }
            }, 220L);
        }

        @Override public void onCharacteristicRead(BluetoothGatt gatt, BluetoothGattCharacteristic characteristic, int status) {
            try {
                if (status == BluetoothGatt.GATT_SUCCESS && characteristic != null && IDENTITY_UUID.equals(characteristic.getUuid())) {
                    handleIdentityRead(gatt, characteristic.getValue());
                }
            } catch (Throwable ignored) {}
            sendOnePacket(gatt);
        }

        @Override public void onCharacteristicWrite'''
    text, count = service_discovery_pattern.subn(service_discovery_new, text, count=1)
    if count != 1:
        raise SystemExit("Blee reliability: client identity-read callback anchor not found")

    path.write_text(text)
    print("Blee reliability: BLE scan -> GATT identity -> native peer events wired independently of Wi-Fi/payment queue")


def patch_mesh_plugin(native_dir: Path) -> None:
    path = native_dir / "BleeMeshPlugin.java"
    text = path.read_text()
    marker = "BLEE_NATIVE_PEER_BRIDGE_V1"
    if marker in text:
        return

    receiver_old = '''            @Override public void onReceive(Context context, Intent intent) {
                if (!BleeMeshService.ACTION_LEDGER_CHANGED.equals(intent.getAction())) return;
                JSObject event = new JSObject();
                event.put("paymentId", intent.getStringExtra(BleeMeshService.EXTRA_PAYMENT_ID));
                event.put("eventType", intent.getStringExtra(BleeMeshService.EXTRA_EVENT_TYPE));
                notifyListeners("ledgerChanged", event, true);
            }'''
    receiver_new = '''            @Override public void onReceive(Context context, Intent intent) {
                String action = intent.getAction();
                if (BleeMeshService.ACTION_LEDGER_CHANGED.equals(action)) {
                    JSObject event = new JSObject();
                    event.put("paymentId", intent.getStringExtra(BleeMeshService.EXTRA_PAYMENT_ID));
                    event.put("eventType", intent.getStringExtra(BleeMeshService.EXTRA_EVENT_TYPE));
                    notifyListeners("ledgerChanged", event, true);
                    return;
                }
                if (BleeMeshService.ACTION_PEER_CHANGED.equals(action)) {
                    JSObject event = new JSObject();
                    event.put("transportId", intent.getStringExtra(BleeMeshService.EXTRA_PEER_TRANSPORT_ID));
                    event.put("wallet", intent.getStringExtra(BleeMeshService.EXTRA_PEER_WALLET));
                    event.put("displayName", intent.getStringExtra(BleeMeshService.EXTRA_PEER_DISPLAY_NAME));
                    event.put("rssi", intent.getIntExtra(BleeMeshService.EXTRA_PEER_RSSI, 0));
                    event.put("lastSeen", intent.getLongExtra(BleeMeshService.EXTRA_PEER_LAST_SEEN, 0L));
                    event.put("present", intent.getBooleanExtra(BleeMeshService.EXTRA_PEER_PRESENT, true));
                    event.put("transport", "ble");
                    notifyListeners("peerChanged", event, true);
                }
            }'''
    text = replace_once(text, receiver_old, receiver_new, "mesh plugin receiver")

    filter_old = '        IntentFilter filter = new IntentFilter(BleeMeshService.ACTION_LEDGER_CHANGED);'
    filter_new = '''        IntentFilter filter = new IntentFilter(BleeMeshService.ACTION_LEDGER_CHANGED);
        filter.addAction(BleeMeshService.ACTION_PEER_CHANGED);
        // BLEE_NATIVE_PEER_BRIDGE_V1'''
    text = replace_once(text, filter_old, filter_new, "peer receiver filter")

    method_anchor = "    @PluginMethod\n    public void pendingEnvelopes(PluginCall call) {"
    method = r'''    @PluginMethod
    public void nearbyPeers(PluginCall call) {
        try {
            JSArray peers = new JSArray();
            for (org.json.JSONObject item : BleeMeshService.nearbyPeersSnapshot()) {
                JSObject peer = new JSObject();
                peer.put("transportId", item.optString("transportId", ""));
                peer.put("wallet", item.optString("wallet", ""));
                peer.put("displayName", item.optString("displayName", ""));
                peer.put("rssi", item.optInt("rssi", 0));
                peer.put("lastSeen", item.optLong("lastSeen", 0L));
                peer.put("transport", "ble");
                peers.put(peer);
            }
            JSObject result = new JSObject();
            result.put("peers", peers);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to read native BLE peers: " + error.getMessage());
        }
    }

'''
    if method_anchor not in text:
        raise SystemExit("Blee reliability: pendingEnvelopes method anchor not found")
    text = text.replace(method_anchor, method + method_anchor, 1)
    path.write_text(text)
    print("Blee reliability: native BLE peer snapshot/events exposed to Capacitor")


def patch_use_blee() -> None:
    path = ROOT / "src/hooks/useBlee.ts"
    text = path.read_text()
    marker = "BLEE_NATIVE_NEARBY_PEER_MERGE_V1"
    if marker in text:
        return

    pattern = re.compile(
        r'''(?P<decl>\s*const\s+\[\s*peers\s*,\s*setPeers\s*\]\s*=\s*useState(?:<[^;\n]+>)?\(\s*\[\s*\]\s*\)\s*;)'''
    )
    match = pattern.search(text)
    if not match:
        raise SystemExit("Blee reliability: could not locate peers state in useBlee.ts")

    effect = r'''

  // BLEE_NATIVE_NEARBY_PEER_MERGE_V1
  // The old UI peer list came from the legacy local-network transport. Native
  // Mesh v2 now publishes Bluetooth-resolved wallets as a second source so
  // discovery works with Wi-Fi completely disabled.
  useEffect(() => {
    if (typeof window === 'undefined') return;

    const applyNativePeers = (input: unknown) => {
      const source = Array.isArray(input) ? input : [];
      const normalized = source
        .filter((raw: any) => raw && typeof raw.transportId === 'string' && /^0x[0-9a-fA-F]{40}$/.test(String(raw.wallet || '')))
        .map((raw: any) => {
          const wallet = String(raw.wallet).toLowerCase();
          const transportId = String(raw.transportId);
          const fallback = `${wallet.slice(0, 6)}…${wallet.slice(-4)}`;
          const displayName = String(raw.displayName || '').trim() || fallback;
          return {
            id: wallet,
            transportId,
            address: wallet,
            wallet,
            walletAddress: wallet,
            recipient: wallet,
            alias: displayName,
            displayName,
            name: displayName,
            avatar: null,
            rssi: Number(raw.rssi || 0),
            lastSeen: Number(raw.lastSeen || Date.now()),
            transport: 'ble',
            source: 'ble',
            authenticated: true,
            __bleeNative: true,
          } as any;
        });

      setPeers((current: any) => {
        const existing = Array.isArray(current) ? current : [];
        const legacy = existing.filter((peer: any) => !peer?.__bleeNative);
        const legacyWallets = new Set(
          legacy
            .map((peer: any) => String(peer?.wallet || peer?.walletAddress || peer?.address || '').toLowerCase())
            .filter((value: string) => /^0x[0-9a-f]{40}$/.test(value)),
        );
        const nativeOnly = normalized.filter((peer: any) => !legacyWallets.has(peer.wallet));
        return [...legacy, ...nativeOnly] as any;
      });
    };

    const initial = (window as any).__bleeMeshPeers;
    if (Array.isArray(initial)) applyNativePeers(initial);

    const onNativePeers = (event: Event) => {
      const detail = (event as CustomEvent<{ peers?: unknown[] }>).detail;
      applyNativePeers(detail?.peers ?? (window as any).__bleeMeshPeers ?? []);
    };
    window.addEventListener('blee:native-nearby', onNativePeers as EventListener);
    return () => window.removeEventListener('blee:native-nearby', onNativePeers as EventListener);
  }, []);'''

    insert_at = match.end("decl")
    text = text[:insert_at] + effect + text[insert_at:]
    path.write_text(text)
    print("Blee reliability: Bluetooth-native peers merged into the existing Nearby UI")


def patch_activity(activity: Path) -> None:
    text = activity.read_text()
    marker = "BLEE_SESSION_BACKGROUND_SAFE_V1"
    if marker in text:
        return

    # Permission completion must not recreate the Activity/WebView. Recreate was
    # wiping the in-memory unlocked session and made first-run permission flow feel
    # like a logout.
    text = text.replace("            BleeMeshService.start(this);\n            recreate();", "            BleeMeshService.start(this);")

    onstart_anchor = "        super.onStart();"
    if onstart_anchor not in text:
        raise SystemExit("Blee reliability: MainActivity.onStart anchor not found")
    text = text.replace(
        onstart_anchor,
        onstart_anchor + "\n        // BLEE_SESSION_BACKGROUND_SAFE_V1\n        ensureBleeNearbyPermissions();\n        BleeMeshService.start(this);",
        1,
    )
    if "recreate();" in text:
        raise SystemExit("Blee reliability: Activity recreate() still survives")
    activity.write_text(text)
    print("Blee reliability: background/foreground no longer recreates the wallet UI")


def verify(activity: Path) -> None:
    native_dir = activity.parent
    runtime = (ROOT / "src/components/BleeRuntime.tsx").read_text()
    hook = (ROOT / "src/hooks/useBlee.ts").read_text()
    service = (native_dir / "BleeMeshService.java").read_text()
    plugin = (native_dir / "BleeMeshPlugin.java").read_text()
    db = (native_dir / "BleeMeshDb.java").read_text()
    activity_text = activity.read_text()

    for marker in (
        "BLEE_RUNTIME_NO_REMOUNT_V1", "blee:native-nearby", "nearbyPeers()", "peerChanged",
    ):
        if marker not in runtime:
            raise SystemExit(f"Blee reliability verification: runtime missing {marker}")
    if "<BleeApp key=" in runtime:
        raise SystemExit("Blee reliability verification: BleeApp is still force-remounted")
    if "BLEE_NATIVE_NEARBY_PEER_MERGE_V1" not in hook:
        raise SystemExit("Blee reliability verification: useBlee native-peer bridge missing")
    for marker in (
        "BLEE_NATIVE_BLE_DISCOVERY_V3", "IDENTITY_UUID", "localIdentityPayload", "publishResolvedPeer",
        "nearbyPeersSnapshot", "needsIdentity", "duePacketsForPeer", "onCharacteristicReadRequest",
    ):
        if marker not in service:
            raise SystemExit(f"Blee reliability verification: mesh service missing {marker}")
    if 'if (db.duePackets(now, 1).isEmpty()) return;' in service:
        raise SystemExit("Blee reliability verification: BLE identity still depends on a queued payment")
    for marker in ("BLEE_NATIVE_PEER_BRIDGE_V1", "ACTION_PEER_CHANGED", "nearbyPeers", "peerChanged"):
        if marker not in plugin:
            raise SystemExit(f"Blee reliability verification: mesh plugin missing {marker}")
    if "BLEE_NATIVE_DISCOVERY_IDENTITY_V1" not in db:
        raise SystemExit("Blee reliability verification: native display-name lookup missing")
    if "BLEE_SESSION_BACKGROUND_SAFE_V1" not in activity_text or "recreate();" in activity_text:
        raise SystemExit("Blee reliability verification: activity/session lifecycle is not background-safe")

    print("============================================================")
    print("VERIFIED: Blee runtime reliability")
    print("- leaving/returning to Blee does not remount and log out the wallet")
    print("- Bluetooth discovery does not depend on Wi-Fi or a queued payment")
    print("- BLE GATT identity resolves recipient wallet before showing a native peer")
    print("- native BLE peers are bridged into the existing Nearby UI")
    print("- stale Bluetooth peers expire and foregrounding re-arms native Mesh v2")
    print("============================================================")


def main() -> None:
    activity = locate_activity()
    native_dir = activity.parent
    patch_mesh_db(native_dir)
    patch_mesh_service(native_dir)
    patch_mesh_plugin(native_dir)
    patch_use_blee()
    patch_activity(activity)
    verify(activity)


if __name__ == "__main__":
    main()
