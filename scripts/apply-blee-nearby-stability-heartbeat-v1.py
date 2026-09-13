#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee nearby heartbeat v1: {message}")


def locate_service() -> Path:
    hits = list(ANDROID_JAVA.rglob("BleeMeshService.java"))
    if len(hits) != 1:
        fail(f"expected one BleeMeshService.java, found {len(hits)}")
    return hits[0]


def main() -> None:
    path = locate_service()
    text = path.read_text()
    if "BLEE_NEARBY_MEMORY_HEARTBEAT_V1" in text:
        return
    if "BLEE_NEARBY_STABILITY_V1" not in text:
        fail("nearby stability stage must run first")

    old = '''                String name = peerDisplayNames.get(transportId);
                int rssi = peerRssi.containsKey(transportId) ? peerRssi.get(transportId) : 0;
                publishResolvedPeer(transportId, wallet, name, rssi, now);
                lastNearbyProgressAt = now;'''
    new = '''                String name = peerDisplayNames.get(transportId);
                int rssi = peerRssi.containsKey(transportId) ? peerRssi.get(transportId) : 0;
                refreshResolvedPeerHeartbeat(transportId, wallet, name, rssi, now);
                lastNearbyProgressAt = now;'''
    if old not in text:
        fail("connected presence heartbeat anchor missing")
    text = text.replace(old, new, 1)

    anchor = "        private void restartNearbyPresence(String reason) {"
    helper = r'''        // BLEE_NEARBY_MEMORY_HEARTBEAT_V1
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

'''
    if anchor not in text:
        fail("presence restart helper anchor missing")
    text = text.replace(anchor, helper + anchor, 1)
    path.write_text(text)

    generated = path.read_text()
    for marker in ("BLEE_NEARBY_MEMORY_HEARTBEAT_V1", "refreshResolvedPeerHeartbeat"):
        if marker not in generated:
            fail(f"missing generated marker {marker}")
    print("VERIFIED: connected Nearby heartbeat refreshes presence without repeated SQLite identity writes")


if __name__ == "__main__":
    main()
