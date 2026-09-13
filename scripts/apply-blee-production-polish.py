#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Blee production polish: missing {label} anchor")
    return text.replace(old, new, 1)


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        raise SystemExit(f"Blee production polish: expected one {name}, found {len(hits)}")
    return hits[0]


def patch_db() -> None:
    path = locate("BleeMeshDb.java")
    text = path.read_text()
    if "BLEE_PRODUCTION_PROFILE_IDENTITY_V1" in text:
        return

    anchor = "    synchronized String getKv(String key) {"
    helper = r'''    // BLEE_PRODUCTION_PROFILE_IDENTITY_V1
    synchronized String localAvatar() {
        String wallet = activeWallet();
        if (wallet != null) {
            try (Cursor c = db().query(
                "peer_identities", new String[] { "avatar" },
                "wallet_address=?", new String[] { wallet }, null, null, null, "1"
            )) {
                if (c.moveToFirst()) {
                    String candidate = cleanAvatar(c.getString(0));
                    if (candidate != null) return candidate;
                }
            } catch (Throwable ignored) {}
        }

        String[] preferred = new String[] {
            "profile.avatar", "profile.photo", "profile.picture", "profile.image",
            "avatar", "photo", "profile.avatarDataUrl"
        };
        for (String key : preferred) {
            String candidate = cleanAvatar(getKv(key));
            if (candidate != null) return candidate;
        }

        try (Cursor c = db().rawQuery(
            "SELECT key,value FROM kv WHERE lower(key) LIKE '%avatar%' OR lower(key) LIKE '%photo%' OR lower(key) LIKE '%picture%' OR lower(key) LIKE '%image%' ORDER BY updated_at DESC LIMIT 24",
            null
        )) {
            while (c.moveToNext()) {
                String key = c.getString(0) == null ? "" : c.getString(0).toLowerCase(Locale.ROOT);
                if (key.contains("vault") || key.contains("key") || key.contains("network") || key.contains("logo")) continue;
                String candidate = cleanAvatar(c.getString(1));
                if (candidate != null) return candidate;
            }
        } catch (Throwable ignored) {}
        return null;
    }

    private static String cleanAvatar(String raw) {
        if (raw == null) return null;
        String value = raw.trim();
        if (value.isEmpty() || value.length() > 350_000) return null;
        try {
            JSONObject object = new JSONObject(value);
            for (String key : new String[] { "avatar", "photo", "picture", "image", "avatarUrl", "photoUrl" }) {
                String candidate = object.optString(key, "").trim();
                if (!candidate.isEmpty() && candidate.length() <= 350_000) return candidate;
            }
        } catch (Throwable ignored) {}
        if (value.startsWith("\"") && value.endsWith("\"") && value.length() >= 2) {
            value = value.substring(1, value.length() - 1).trim();
        }
        if (value.startsWith("data:image/") || value.startsWith("https://") || value.startsWith("http://")) return value;
        return null;
    }

    synchronized void upsertPeerIdentity(String wallet, String displayName, String avatar, String deviceId, String source) {
        if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) return;
        try {
            String normalized = wallet.toLowerCase(Locale.ROOT);
            String cleanName = displayName == null ? "" : displayName.trim();
            if (cleanName.length() > 64) cleanName = cleanName.substring(0, 64);
            String cleanAvatar = cleanAvatar(avatar);
            JSONObject payload = new JSONObject();
            payload.put("wallet", normalized);
            payload.put("displayName", cleanName);
            if (cleanAvatar != null) payload.put("avatar", cleanAvatar);
            if (deviceId != null) payload.put("deviceId", deviceId);
            if (source != null) payload.put("source", source);

            ContentValues cv = new ContentValues();
            cv.put("wallet_address", normalized);
            cv.put("display_name", cleanName);
            if (cleanAvatar != null) cv.put("avatar", cleanAvatar);
            else cv.putNull("avatar");
            cv.put("device_id", deviceId == null ? "" : deviceId);
            cv.put("updated_at", System.currentTimeMillis());
            cv.put("payload", payload.toString());
            db().insertWithOnConflict("peer_identities", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
        } catch (Throwable ignored) {}
    }

'''
    text = once(text, anchor, helper + anchor, "profile identity DB helper")
    path.write_text(text)


def patch_service() -> None:
    path = locate("BleeMeshService.java")
    text = path.read_text()
    if "BLEE_PRODUCTION_EVENT_PATH_V1" in text:
        return
    if "BLEE_ADAPTIVE_NEARBY_V3" not in text:
        raise SystemExit("Blee production polish: Adaptive V3 must be installed first")

    text = once(
        text,
        '    static final String EXTRA_PEER_DISPLAY_NAME = "displayName";',
        '''    static final String EXTRA_PEER_DISPLAY_NAME = "displayName";
    // BLEE_PRODUCTION_EVENT_PATH_V1
    static final String EXTRA_PEER_AVATAR = "avatar";''',
        "peer avatar constant",
    )

    text = once(
        text,
        '    private final Map<String, String> peerDisplayNames = Collections.synchronizedMap(new HashMap<String, String>());',
        '''    private final Map<String, String> peerDisplayNames = Collections.synchronizedMap(new HashMap<String, String>());
    private final Map<String, String> peerAvatars = Collections.synchronizedMap(new HashMap<String, String>());''',
        "peer avatar cache",
    )

    text = text.replace(
        "                    peerDisplayNames.remove(address);\n                    peerRssi.remove(address);",
        "                    peerDisplayNames.remove(address);\n                    peerAvatars.remove(address);\n                    peerRssi.remove(address);",
        1,
    )

    old_publish = '''            peer.put("displayName", cleanName);
            peer.put("rssi", rssi);'''
    new_publish = '''            peer.put("displayName", cleanName);
            String avatar = peerAvatars.get(address);
            if (avatar != null && !avatar.isEmpty()) peer.put("avatar", avatar);
            peer.put("rssi", rssi);'''
    text = once(text, old_publish, new_publish, "peer snapshot avatar")

    old_cache = '''            peerWallets.put(address, normalizedWallet);
            peerDisplayNames.put(address, cleanName);
            peerIdentityAt.put(address, seenAt);'''
    new_cache = '''            peerWallets.put(address, normalizedWallet);
            peerDisplayNames.put(address, cleanName);
            peerIdentityAt.put(address, seenAt);
            if (db != null) db.upsertPeerIdentity(normalizedWallet, cleanName, avatar, address, address.startsWith("nc:") ? "nearby" : "ble");'''
    text = once(text, old_cache, new_cache, "peer identity persistence")

    text = once(
        text,
        '''            intent.putExtra(EXTRA_PEER_DISPLAY_NAME, cleanName);
            intent.putExtra(EXTRA_PEER_RSSI, rssi);''',
        '''            intent.putExtra(EXTRA_PEER_DISPLAY_NAME, cleanName);
            if (avatar != null && !avatar.isEmpty()) intent.putExtra(EXTRA_PEER_AVATAR, avatar);
            intent.putExtra(EXTRA_PEER_RSSI, rssi);''',
        "peer avatar broadcast",
    )

    # Core BLE identity remains deliberately compact. Carry an avatar only when
    # it is tiny enough for a characteristic read; Adaptive Nearby carries the
    # full profile image separately below.
    local_identity_anchor = '''            String name = db == null ? null : db.localDisplayName();
            if (name != null && !name.isEmpty()) identity.put("displayName", name);
            return identity.toString().getBytes(StandardCharsets.UTF_8);'''
    if local_identity_anchor in text:
        local_identity_new = '''            String name = db == null ? null : db.localDisplayName();
            if (name != null && !name.isEmpty()) identity.put("displayName", name);
            String avatar = db == null ? null : db.localAvatar();
            if (avatar != null && avatar.length() <= 1200) identity.put("avatar", avatar);
            return identity.toString().getBytes(StandardCharsets.UTF_8);'''
        text = text.replace(local_identity_anchor, local_identity_new, 1)

    identity_read_anchor = '''            String displayName = identity.optString("displayName", "");
            String address = gatt.getDevice().getAddress();'''
    if identity_read_anchor in text:
        identity_read_new = '''            String displayName = identity.optString("displayName", "");
            String avatar = identity.optString("avatar", "");
            String address = gatt.getDevice().getAddress();
            if (!avatar.isEmpty()) peerAvatars.put(address, avatar);'''
        text = text.replace(identity_read_anchor, identity_read_new, 1)

    # Nearby identity must not derive from the 20-byte raw BLE wallet identity.
    # Build the complete application profile directly from durable local state.
    old_nearby_identity = '''            try {
                JSONObject identity = new JSONObject(new String(localIdentityPayload(), StandardCharsets.UTF_8));
                identity.put("kind", "blee_identity_v3");
                identity.put("peerId", hexBytes(localPeerIdBytes()));
                connectionsClient.sendPayload(endpointId, Payload.fromBytes(identity.toString().getBytes(StandardCharsets.UTF_8)));
            } catch (Throwable error) {'''
    new_nearby_identity = '''            try {
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
            } catch (Throwable error) {'''
    text = once(text, old_nearby_identity, new_nearby_identity, "Nearby full-profile identity")

    old_nearby_receive = '''                    String wallet = envelope.optString("wallet", "");
                    String displayName = envelope.optString("displayName", "");
                    String peerHex = envelope.optString("peerId", "");'''
    new_nearby_receive = '''                    String wallet = envelope.optString("wallet", "");
                    String displayName = envelope.optString("displayName", "");
                    String avatar = envelope.optString("avatar", "");
                    String peerHex = envelope.optString("peerId", "");'''
    text = once(text, old_nearby_receive, new_nearby_receive, "Nearby avatar receive")

    old_publish_nearby = '''                    endpointTransportIds.put(endpointId, transportId);
                    publishResolvedPeer(transportId, wallet, displayName, 0, System.currentTimeMillis());
                    pumpNearbyPacket(endpointId);'''
    new_publish_nearby = '''                    endpointTransportIds.put(endpointId, transportId);
                    if (!avatar.isEmpty()) peerAvatars.put(transportId, avatar);
                    publishResolvedPeer(transportId, wallet, displayName, 0, System.currentTimeMillis());
                    pumpNearbyPacket(endpointId);'''
    text = once(text, old_publish_nearby, new_publish_nearby, "Nearby profile publish")

    # PAYMENT_ENVELOPE receipt is not yet a ledger mutation, but the WebView must
    # wake immediately so it can verify the sender authorization and project the
    # pending/on-hold amount without waiting for another periodic event.
    old_packet_receive = '''                    BleeMeshDb.ProcessResult result = db.receive(raw, deviceId, publicKey);
                    if (result.accepted && result.ledgerChanged) notifyLedgerChanged(result.paymentId, result.type);
                    if (result.notificationTitle != null) paymentNotification(result.notificationTitle, result.notificationBody, result.paymentId);'''
    new_packet_receive = '''                    BleeMeshDb.ProcessResult result = db.receive(raw, deviceId, publicKey);
                    if (result.accepted && (result.ledgerChanged || "PAYMENT_ENVELOPE".equals(result.type))) {
                        notifyLedgerChanged(result.paymentId, result.ledgerChanged ? result.type : "PAYMENT_ENVELOPE_RECEIVED");
                    }
                    if (result.notificationTitle != null) paymentNotification(result.notificationTitle, result.notificationBody, result.paymentId);'''
    text = once(text, old_packet_receive, new_packet_receive, "immediate payment-envelope wakeup")

    path.write_text(text)


def patch_plugin() -> None:
    path = locate("BleeMeshPlugin.java")
    text = path.read_text()
    if "BLEE_PRODUCTION_PEER_EVENT_V1" in text:
        return

    text = once(
        text,
        '''                    event.put("displayName", intent.getStringExtra(BleeMeshService.EXTRA_PEER_DISPLAY_NAME));
                    event.put("rssi", intent.getIntExtra(BleeMeshService.EXTRA_PEER_RSSI, 0));''',
        '''                    event.put("displayName", intent.getStringExtra(BleeMeshService.EXTRA_PEER_DISPLAY_NAME));
                    event.put("avatar", intent.getStringExtra(BleeMeshService.EXTRA_PEER_AVATAR));
                    // BLEE_PRODUCTION_PEER_EVENT_V1
                    event.put("rssi", intent.getIntExtra(BleeMeshService.EXTRA_PEER_RSSI, 0));''',
        "peer avatar event bridge",
    )

    text = once(
        text,
        '''                peer.put("displayName", item.optString("displayName", ""));
                peer.put("rssi", item.optInt("rssi", 0));''',
        '''                peer.put("displayName", item.optString("displayName", ""));
                peer.put("avatar", item.optString("avatar", ""));
                peer.put("rssi", item.optInt("rssi", 0));''',
        "peer avatar snapshot bridge",
    )
    path.write_text(text)


def patch_runtime() -> None:
    path = ROOT / "src/components/BleeRuntime.tsx"
    text = path.read_text()
    if "BLEE_PRODUCTION_EVENT_UI_V1" in text:
        return

    text = once(
        text,
        '''  displayName?: string | null;
  rssi?: number;''',
        '''  displayName?: string | null;
  avatar?: string | null;
  rssi?: number;''',
        "runtime peer avatar type",
    )

    # Keep diagnostics callable for internal support, but never render the debug
    # affordance in production and never run its polling loop.
    marker_anchor = "const BleeMesh = registerPlugin<MeshPlugin>('BleeMesh');"
    text = once(
        text,
        marker_anchor,
        marker_anchor + "\n\n// BLEE_PRODUCTION_EVENT_UI_V1\nconst SHOW_INTERNAL_DIAGNOSTICS = false;",
        "production diagnostics gate",
    )
    text = text.replace("if (!nativeReady || !diagnosticsOpen) return;", "if (!SHOW_INTERNAL_DIAGNOSTICS || !nativeReady || !diagnosticsOpen) return;", 1)
    text = text.replace("{nativeReady && (", "{SHOW_INTERNAL_DIAGNOSTICS && nativeReady && (", 1)
    text = text.replace("{nativeReady && diagnosticsOpen && (", "{SHOW_INTERNAL_DIAGNOSTICS && nativeReady && diagnosticsOpen && (", 1)

    # Native transport events already contain the changed peer. Apply them to the
    # JS cache immediately instead of crossing the bridge again for a full peer
    # snapshot and waiting for that promise to resolve.
    anchor = '''    const publishNativePeers = async () => {
      if (!active) return;'''
    helper = '''    const publishNativePeerEvent = (event: Record<string, unknown>) => {
      if (!active) return;
      const transportId = String(event.transportId || '');
      if (!transportId) return;
      const current = Array.isArray((window as any).__bleeMeshPeers) ? [...(window as any).__bleeMeshPeers] : [];
      const index = current.findIndex((peer: any) => String(peer?.transportId || '') === transportId);
      if (event.present === false) {
        if (index >= 0) current.splice(index, 1);
      } else {
        const next = {
          ...(index >= 0 ? current[index] : {}),
          transportId,
          wallet: event.wallet,
          displayName: event.displayName,
          avatar: event.avatar,
          rssi: event.rssi,
          lastSeen: event.lastSeen,
          transport: event.transport || 'ble',
        };
        if (index >= 0) current[index] = next;
        else current.push(next);
      }
      (window as any).__bleeMeshPeers = current;
      window.dispatchEvent(new CustomEvent('blee:native-nearby', { detail: { peers: current } }));
    };

    const publishNativePeers = async () => {
      if (!active) return;'''
    text = once(text, anchor, helper, "immediate native peer event helper")

    old_listener = '''        peerListener = await BleeMesh.addListener('peerChanged', () => {
          void publishNativePeers();
        });'''
    new_listener = '''        peerListener = await BleeMesh.addListener('peerChanged', (event) => {
          publishNativePeerEvent(event);
        });'''
    text = once(text, old_listener, new_listener, "direct peer listener")

    text = text.replace("      }, 180);", "      }, 24);", 1)
    path.write_text(text)


def patch_hook() -> None:
    path = ROOT / "src/hooks/useBlee.ts"
    if not path.is_file():
        raise SystemExit("Blee production polish: generated useBlee.ts missing")
    text = path.read_text()
    if "BLEE_PRODUCTION_NATIVE_PEER_MERGE_V1" in text:
        return
    if "BLEE_NATIVE_NEARBY_PEER_MERGE_V1" not in text:
        raise SystemExit("Blee production polish: native peer merge is missing")

    text = once(
        text,
        '''            avatar: null,
            rssi: Number(raw.rssi || 0),''',
        '''            // BLEE_PRODUCTION_NATIVE_PEER_MERGE_V1
            avatar: typeof raw.avatar === 'string' && raw.avatar ? raw.avatar : null,
            rssi: Number(raw.rssi || 0),''',
        "native peer avatar projection",
    )

    old_merge = '''      setPeers((current: any) => {
        const existing = Array.isArray(current) ? current : [];
        const legacy = existing.filter((peer: any) => !peer?.__bleeNative);
        const legacyWallets = new Set(
          legacy
            .map((peer: any) => String(peer?.wallet || peer?.walletAddress || peer?.address || '').toLowerCase())
            .filter((value: string) => /^0x[0-9a-f]{40}$/.test(value)),
        );
        const nativeOnly = normalized.filter((peer: any) => !legacyWallets.has(peer.wallet));
        return [...legacy, ...nativeOnly] as any;
      });'''
    new_merge = '''      setPeers((current: any) => {
        const existing = Array.isArray(current) ? current : [];
        const byWallet = new Map<string, any>();
        for (const peer of existing) {
          const wallet = String(peer?.wallet || peer?.walletAddress || peer?.address || '').toLowerCase();
          if (/^0x[0-9a-f]{40}$/.test(wallet)) byWallet.set(wallet, peer);
        }
        for (const peer of normalized) {
          const previous = byWallet.get(peer.wallet);
          const nativeHasName = peer.displayName && !peer.displayName.startsWith('0x');
          byWallet.set(peer.wallet, {
            ...(previous || {}),
            ...peer,
            displayName: nativeHasName ? peer.displayName : (previous?.displayName || previous?.name || peer.displayName),
            name: nativeHasName ? peer.displayName : (previous?.name || previous?.displayName || peer.name),
            alias: nativeHasName ? peer.displayName : (previous?.alias || previous?.displayName || peer.alias),
            avatar: peer.avatar || previous?.avatar || null,
          });
        }
        const nonWallet = existing.filter((peer: any) => {
          const wallet = String(peer?.wallet || peer?.walletAddress || peer?.address || '').toLowerCase();
          return !/^0x[0-9a-f]{40}$/.test(wallet);
        });
        return [...nonWallet, ...byWallet.values()] as any;
      });'''
    text = once(text, old_merge, new_merge, "peer enrichment merge")
    path.write_text(text)


def verify() -> None:
    service = locate("BleeMeshService.java").read_text()
    db = locate("BleeMeshDb.java").read_text()
    plugin = locate("BleeMeshPlugin.java").read_text()
    runtime = (ROOT / "src/components/BleeRuntime.tsx").read_text()
    hook = (ROOT / "src/hooks/useBlee.ts").read_text()

    required_service = (
        "BLEE_PRODUCTION_EVENT_PATH_V1", "EXTRA_PEER_AVATAR", "peerAvatars",
        "db.localAvatar()", 'identity.put("avatar", avatar)', "PAYMENT_ENVELOPE_RECEIVED",
        "db.upsertPeerIdentity",
    )
    missing = [m for m in required_service if m not in service]
    if missing:
        raise SystemExit(f"Blee production polish verification: service missing {missing}")
    for marker in ("BLEE_PRODUCTION_PROFILE_IDENTITY_V1", "localAvatar()", "upsertPeerIdentity"):
        if marker not in db:
            raise SystemExit(f"Blee production polish verification: DB missing {marker}")
    for marker in ("BLEE_PRODUCTION_PEER_EVENT_V1", 'event.put("avatar"', 'peer.put("avatar"'):
        if marker not in plugin:
            raise SystemExit(f"Blee production polish verification: plugin missing {marker}")
    for marker in ("BLEE_PRODUCTION_EVENT_UI_V1", "SHOW_INTERNAL_DIAGNOSTICS = false", "publishNativePeerEvent", "}, 24);"):
        if marker not in runtime:
            raise SystemExit(f"Blee production polish verification: runtime missing {marker}")
    if "SHOW_INTERNAL_DIAGNOSTICS && nativeReady" not in runtime:
        raise SystemExit("Blee production polish verification: diagnostics UI is not production-gated")
    for marker in ("BLEE_PRODUCTION_NATIVE_PEER_MERGE_V1", "peer.avatar || previous?.avatar"):
        if marker not in hook:
            raise SystemExit(f"Blee production polish verification: hook missing {marker}")

    print("============================================================")
    print("VERIFIED: Blee production event path")
    print("- visible BLE diagnostics are disabled in production")
    print("- Nearby identity sends wallet + name + avatar immediately")
    print("- resolved peer identity is persisted before activity rendering")
    print("- peerChanged updates React directly without snapshot round-trip")
    print("- received payment envelopes wake verification immediately")
    print("- ledger projection debounce reduced to 24ms")
    print("============================================================")


def main() -> None:
    patch_db()
    patch_service()
    patch_plugin()
    patch_runtime()
    patch_hook()
    verify()


if __name__ == "__main__":
    main()
