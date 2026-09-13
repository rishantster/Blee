#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee nearby stability v1: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        fail(f"missing {label} anchor")
    return text.replace(old, new, 1)


def replace_java_method(text: str, signature: str, replacement: str, label: str) -> str:
    start = text.find(signature)
    if start < 0:
        fail(f"missing {label} method")
    brace = text.find("{", start)
    if brace < 0:
        fail(f"missing {label} opening brace")
    depth = 0
    end = -1
    for i in range(brace, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        fail(f"unterminated {label} method")
    return text[:start] + replacement.rstrip() + text[end:]


def patch_db() -> None:
    path = locate("BleeMeshDb.java")
    text = path.read_text()
    if "BLEE_PEER_IDENTITY_MERGE_V1" in text:
        return
    if "BLEE_PRODUCTION_PROFILE_IDENTITY_V1" not in text:
        fail("production identity stage must run first")

    signature = "    synchronized void upsertPeerIdentity(String wallet, String displayName, String avatar, String deviceId, String source)"
    replacement = r'''    // BLEE_PEER_IDENTITY_MERGE_V1
    synchronized void upsertPeerIdentity(String wallet, String displayName, String avatar, String deviceId, String source) {
        if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) return;
        try {
            String normalized = wallet.toLowerCase(Locale.ROOT);
            String cleanName = displayName == null ? "" : displayName.trim();
            if (cleanName.length() > 64) cleanName = cleanName.substring(0, 64);
            String cleanAvatarValue = cleanAvatar(avatar);

            // A later radio sighting can contain less profile data than an
            // earlier one. Preserve the richer wallet-keyed identity.
            String previousName = "";
            String previousAvatar = null;
            String previousDevice = "";
            try (Cursor c = db().query(
                "peer_identities",
                new String[] { "display_name", "avatar", "device_id" },
                "wallet_address=?", new String[] { normalized }, null, null, null, "1"
            )) {
                if (c.moveToFirst()) {
                    previousName = c.isNull(0) ? "" : c.getString(0);
                    previousAvatar = c.isNull(1) ? null : c.getString(1);
                    previousDevice = c.isNull(2) ? "" : c.getString(2);
                }
            } catch (Throwable ignored) {}

            if (cleanName.isEmpty() && previousName != null) cleanName = previousName.trim();
            if (cleanAvatarValue == null) cleanAvatarValue = cleanAvatar(previousAvatar);
            String effectiveDevice = deviceId == null || deviceId.trim().isEmpty() ? previousDevice : deviceId.trim();

            JSONObject payload = new JSONObject();
            payload.put("wallet", normalized);
            payload.put("displayName", cleanName);
            if (cleanAvatarValue != null) payload.put("avatar", cleanAvatarValue);
            if (effectiveDevice != null && !effectiveDevice.isEmpty()) payload.put("deviceId", effectiveDevice);
            if (source != null) payload.put("source", source);

            ContentValues cv = new ContentValues();
            cv.put("wallet_address", normalized);
            cv.put("display_name", cleanName);
            if (cleanAvatarValue != null) cv.put("avatar", cleanAvatarValue); else cv.putNull("avatar");
            cv.put("device_id", effectiveDevice == null ? "" : effectiveDevice);
            cv.put("updated_at", System.currentTimeMillis());
            cv.put("payload", payload.toString());
            db().insertWithOnConflict("peer_identities", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
        } catch (Throwable ignored) {}
    }

    synchronized JSONObject peerIdentity(String wallet) {
        if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) return null;
        String normalized = wallet.toLowerCase(Locale.ROOT);
        try (Cursor c = db().query(
            "peer_identities",
            new String[] { "display_name", "avatar", "device_id", "updated_at" },
            "wallet_address=?", new String[] { normalized }, null, null, null, "1"
        )) {
            if (!c.moveToFirst()) return null;
            JSONObject result = new JSONObject();
            result.put("wallet", normalized);
            if (!c.isNull(0)) result.put("displayName", c.getString(0));
            if (!c.isNull(1)) result.put("avatar", c.getString(1));
            if (!c.isNull(2)) result.put("deviceId", c.getString(2));
            result.put("updatedAt", c.getLong(3));
            return result;
        } catch (Throwable ignored) {
            return null;
        }
    }'''
    text = replace_java_method(text, signature, replacement, "peer identity upsert")
    path.write_text(text)


def patch_service() -> None:
    path = locate("BleeMeshService.java")
    text = path.read_text()
    if "BLEE_NEARBY_STABILITY_V1" in text:
        return
    if "BLEE_ADAPTIVE_NEARBY_V3" not in text or "BLEE_PRODUCTION_EVENT_PATH_V1" not in text:
        fail("adaptive v3 + production event path must run first")

    signature = "    private void publishResolvedPeer(String address, String wallet, String displayName, int rssi, long seenAt)"
    replacement = r'''    // BLEE_NEARBY_STABILITY_V1
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
    }'''
    text = replace_java_method(text, signature, replacement, "resolved peer publisher")

    text = once(
        text,
        '        private long lastNearbyPumpAt = 0L;',
        '''        private long lastNearbyPumpAt = 0L;
        private long lastNearbyProgressAt = 0L;
        private long lastNearbyHeartbeatAt = 0L;
        private long lastNearbyPresenceRestartAt = 0L;
        private static final long NEARBY_HEARTBEAT_MS = 5_000L;
        private static final long NEARBY_IDLE_REARM_MS = 30_000L;
        private static final long NEARBY_REARM_COOLDOWN_MS = 15_000L;''',
        "Nearby watchdog fields",
    )

    # A connected Nearby peer was previously allowed to age out because its
    # lastSeen timestamp was written only once during identity exchange.
    old_maintain = '''            if (fallbackActive || fallbackStarting) {
                if (fallbackActive && now - lastNearbyPumpAt >= 2_000L) {
                    lastNearbyPumpAt = now;
                    pumpNearbyPackets();
                }
                return;
            }'''
    new_maintain = '''            if (fallbackActive || fallbackStarting) {
                if (fallbackActive && now - lastNearbyPumpAt >= 2_000L) {
                    lastNearbyPumpAt = now;
                    pumpNearbyPackets();
                }
                if (fallbackActive && now - lastNearbyHeartbeatAt >= NEARBY_HEARTBEAT_MS) {
                    lastNearbyHeartbeatAt = now;
                    refreshConnectedNearbyPresence(now);
                }
                if (fallbackActive && connectionsClient != null) {
                    if (!nearbyAdvertising) startNearbyAdvertising();
                    if (!nearbyDiscovering) startNearbyDiscovery();
                    boolean noLiveEndpoint = connectedEndpoints.isEmpty();
                    boolean noPublishedPeer = nearbyPeersSnapshot().isEmpty();
                    boolean stalePresence = lastNearbyProgressAt > 0L && now - lastNearbyProgressAt >= NEARBY_IDLE_REARM_MS;
                    boolean cooldownElapsed = now - lastNearbyPresenceRestartAt >= NEARBY_REARM_COOLDOWN_MS;
                    if ((noLiveEndpoint || noPublishedPeer) && stalePresence && cooldownElapsed) restartNearbyPresence("idle_watchdog");
                }
                return;
            }'''
    text = once(text, old_maintain, new_maintain, "adaptive fallback maintain")

    # Discovery used to be stopped after the first connection, turning Nearby
    # into a one-shot pairing session. Blee must stay continuously discoverable.
    stop_discovery = '''                    try { if (connectionsClient != null) connectionsClient.stopDiscovery(); } catch (Throwable ignored) {}
                    nearbyDiscovering = false;
                    sendNearbyIdentity(endpointId);'''
    if stop_discovery in text:
        text = text.replace(
            stop_discovery,
            '''                    lastNearbyProgressAt = System.currentTimeMillis();
                    // Keep discovery running while connected: Blee is a persistent
                    // nearby presence, not a one-shot pairing session.
                    sendNearbyIdentity(endpointId);''',
            1,
        )

    text = text.replace(
        '''                    nearbyAdvertising = true;
                    fallbackActive = true;''',
        '''                    nearbyAdvertising = true;
                    lastNearbyProgressAt = System.currentTimeMillis();
                    fallbackActive = true;''',
        1,
    )
    text = text.replace(
        '''                    nearbyDiscovering = true;
                    fallbackActive = true;''',
        '''                    nearbyDiscovering = true;
                    lastNearbyProgressAt = System.currentTimeMillis();
                    fallbackActive = true;''',
        1,
    )

    anchor = "        private void stopNearby() {"
    helpers = r'''        private void refreshConnectedNearbyPresence(long now) {
            List<String> endpoints;
            synchronized (connectedEndpoints) { endpoints = new ArrayList<String>(connectedEndpoints); }
            for (String endpointId : endpoints) {
                String transportId = endpointTransportIds.get(endpointId);
                if (transportId == null || transportId.isEmpty()) continue;
                String wallet = peerWallets.get(transportId);
                if (wallet == null || wallet.isEmpty()) continue;
                String name = peerDisplayNames.get(transportId);
                int rssi = peerRssi.containsKey(transportId) ? peerRssi.get(transportId) : 0;
                publishResolvedPeer(transportId, wallet, name, rssi, now);
                lastNearbyProgressAt = now;
            }
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

'''
    text = once(text, anchor, helpers + anchor, "Nearby presence helpers")

    # When transport is explicitly stopped/rearmed, remove its public peer rows
    # too. Otherwise a newly generated endpoint can coexist with an old row.
    stop_anchor = '''        private void stopNearby() {
            if (connectionsClient != null) {'''
    stop_new = '''        private void stopNearby() {
            List<String> oldEndpoints;
            synchronized (connectedEndpoints) { oldEndpoints = new ArrayList<String>(connectedEndpoints); }
            for (String endpointId : oldEndpoints) forgetNearbyEndpoint(endpointId);
            if (connectionsClient != null) {'''
    text = once(text, stop_anchor, stop_new, "Nearby stop peer cleanup")

    endpoint_found_anchor = '''            @Override public void onEndpointFound(String endpointId, DiscoveredEndpointInfo info) {
                endpointsFound++;'''
    text = once(
        text,
        endpoint_found_anchor,
        '''            @Override public void onEndpointFound(String endpointId, DiscoveredEndpointInfo info) {
                endpointsFound++;
                lastNearbyProgressAt = System.currentTimeMillis();''',
        "Nearby endpoint progress",
    )

    endpoint_lost_pattern = re.compile(
        r'''            @Override public void onEndpointLost\(String endpointId\) \{.*?\n            \}''',
        re.S,
    )
    endpoint_lost_replacement = r'''            @Override public void onEndpointLost(String endpointId) {
                if (!connectedEndpoints.contains(endpointId)) forgetNearbyEndpoint(endpointId);
                lastNearbyProgressAt = System.currentTimeMillis();
                if (active && fallbackActive) {
                    if (!nearbyDiscovering) startNearbyDiscovery();
                    if (!nearbyAdvertising) startNearbyAdvertising();
                }
            }'''
    text, count = endpoint_lost_pattern.subn(endpoint_lost_replacement, text, count=1)
    if count != 1:
        fail("Nearby onEndpointLost callback not found")

    disconnected_pattern = re.compile(
        r'''            @Override public void onDisconnected\(String endpointId\) \{.*?\n            \}''',
        re.S,
    )
    disconnected_replacement = r'''            @Override public void onDisconnected(String endpointId) {
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
            }'''
    text, count = disconnected_pattern.subn(disconnected_replacement, text, count=1)
    if count != 1:
        fail("Nearby onDisconnected callback not found")

    # Full-profile identity arrival refreshes the presence watchdog immediately.
    identity_anchor = '''                    endpointTransportIds.put(endpointId, transportId);
                    if (!avatar.isEmpty()) peerAvatars.put(transportId, avatar);'''
    text = once(
        text,
        identity_anchor,
        '''                    endpointTransportIds.put(endpointId, transportId);
                    lastNearbyProgressAt = System.currentTimeMillis();
                    if (!avatar.isEmpty()) peerAvatars.put(transportId, avatar);''',
        "Nearby identity progress",
    )

    path.write_text(text)


def patch_runtime() -> None:
    path = ROOT / "src/components/BleeRuntime.tsx"
    text = path.read_text()
    if "BLEE_WALLET_CANONICAL_PEERS_V1" in text:
        return
    if "BLEE_PRODUCTION_EVENT_UI_V1" not in text:
        fail("production event UI must run first")

    marker = "// BLEE_PRODUCTION_EVENT_UI_V1\nconst SHOW_INTERNAL_DIAGNOSTICS = false;"
    helper = r'''// BLEE_PRODUCTION_EVENT_UI_V1
const SHOW_INTERNAL_DIAGNOSTICS = false;

// BLEE_WALLET_CANONICAL_PEERS_V1
function canonicalizeBleePeers(input: any[]) {
  const byWallet = new Map<string, any>();
  const unresolved: any[] = [];
  for (const peer of Array.isArray(input) ? input : []) {
    if (!peer) continue;
    const wallet = String(peer.wallet || '').toLowerCase();
    if (!/^0x[0-9a-f]{40}$/.test(wallet)) {
      unresolved.push(peer);
      continue;
    }
    const previous = byWallet.get(wallet);
    if (!previous) {
      byWallet.set(wallet, { ...peer, wallet });
      continue;
    }
    const previousName = String(previous.displayName || '').trim();
    const nextName = String(peer.displayName || '').trim();
    const previousAvatar = String(previous.avatar || '').trim();
    const nextAvatar = String(peer.avatar || '').trim();
    const previousSeen = Number(previous.lastSeen || 0);
    const nextSeen = Number(peer.lastSeen || 0);
    const fresher = nextSeen >= previousSeen ? peer : previous;
    byWallet.set(wallet, {
      ...previous,
      ...fresher,
      wallet,
      displayName: nextName || previousName,
      avatar: nextAvatar || previousAvatar,
      lastSeen: Math.max(previousSeen, nextSeen),
    });
  }
  return [...byWallet.values(), ...unresolved];
}'''
    text = once(text, marker, helper, "wallet canonical peer helper")

    old_event_tail = '''      (window as any).__bleeMeshPeers = current;
      window.dispatchEvent(new CustomEvent('blee:native-nearby', { detail: { peers: current } }));'''
    new_event_tail = '''      const canonical = canonicalizeBleePeers(current);
      (window as any).__bleeMeshPeers = canonical;
      window.dispatchEvent(new CustomEvent('blee:native-nearby', { detail: { peers: canonical } }));'''
    text = once(text, old_event_tail, new_event_tail, "canonical peer event publication")

    old_snapshot = '''        const snapshots = Array.isArray(peers) ? peers : [];
        (window as any).__bleeMeshPeers = snapshots;
        window.dispatchEvent(new CustomEvent('blee:native-nearby', { detail: { peers: snapshots } }));'''
    new_snapshot = '''        const snapshots = canonicalizeBleePeers(Array.isArray(peers) ? peers : []);
        (window as any).__bleeMeshPeers = snapshots;
        window.dispatchEvent(new CustomEvent('blee:native-nearby', { detail: { peers: snapshots } }));'''
    text = once(text, old_snapshot, new_snapshot, "canonical peer snapshot publication")

    path.write_text(text)


def verify() -> None:
    db = locate("BleeMeshDb.java").read_text()
    service = locate("BleeMeshService.java").read_text()
    runtime = (ROOT / "src/components/BleeRuntime.tsx").read_text()

    for marker in (
        "BLEE_PEER_IDENTITY_MERGE_V1", "peerIdentity(String wallet)",
        "previousName", "previousAvatar",
    ):
        if marker not in db:
            fail(f"DB missing {marker}")
    for marker in (
        "BLEE_NEARBY_STABILITY_V1", "duplicateTransportIds", "forgetResolvedPeer",
        "NEARBY_HEARTBEAT_MS", "refreshConnectedNearbyPresence", "restartNearbyPresence",
        "forgetNearbyEndpoint", "idle_watchdog", "Keep discovery running while connected",
    ):
        if marker not in service:
            fail(f"service missing {marker}")
    for marker in ("BLEE_WALLET_CANONICAL_PEERS_V1", "canonicalizeBleePeers", "byWallet"):
        if marker not in runtime:
            fail(f"runtime missing {marker}")
    if "connectionsClient.stopDiscovery();\n                    nearbyDiscovering = false;\n                    sendNearbyIdentity(endpointId);" in service:
        fail("Nearby still disables discovery after connection")
    print("VERIFIED: Blee nearby identity is wallet-canonical and connected presence self-heals")


def main() -> None:
    patch_db()
    patch_service()
    patch_runtime()
    verify()


if __name__ == "__main__":
    main()
