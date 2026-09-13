#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee nearby speed/profile v2: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def main() -> None:
    path = locate("BleeMeshService.java")
    text = path.read_text()
    if "BLEE_NEARBY_SPEED_PROFILE_V2" in text:
        print("VERIFIED: nearby fast path/profile sync already installed")
        return
    if "BLEE_ADAPTIVE_NEARBY_V3" not in text or "BLEE_NEARBY_STABILITY_V1" not in text:
        fail("adaptive + stability stages must run first")

    replacements = {
        "private static final long BLE_GRACE_MS = 15_000L;": "private static final long BLE_GRACE_MS = 3_000L;",
        "private static final int GATT_TIMEOUT_THRESHOLD = 2;": "private static final int GATT_TIMEOUT_THRESHOLD = 1;",
        "now - lastNearbyPumpAt >= 2_000L": "now - lastNearbyPumpAt >= 250L",
        "private static final long NEARBY_HEARTBEAT_MS = 5_000L;": "private static final long NEARBY_HEARTBEAT_MS = 1_000L;",
        "private static final long NEARBY_IDLE_REARM_MS = 30_000L;": "private static final long NEARBY_IDLE_REARM_MS = 12_000L;",
        "private static final long NEARBY_REARM_COOLDOWN_MS = 15_000L;": "private static final long NEARBY_REARM_COOLDOWN_MS = 6_000L;",
    }
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new, 1)
        elif new not in text:
            fail(f"missing tuning anchor: {old}")

    field_anchor = "        private static final long NEARBY_REARM_COOLDOWN_MS = 6_000L;"
    fields = field_anchor + '''\n        // BLEE_NEARBY_SPEED_PROFILE_V2\n        private static final long PROFILE_SYNC_CHECK_MS = 750L;\n        private long lastProfileSyncCheckAt = 0L;\n        private String lastProfileFingerprint = \"\";'''
    if field_anchor not in text:
        fail("rearm field anchor missing")
    text = text.replace(field_anchor, fields, 1)

    maintain_anchor = '''                if (fallbackActive && connectionsClient != null) {\n                    if (!nearbyAdvertising) startNearbyAdvertising();'''
    maintain_new = '''                if (fallbackActive && connectionsClient != null) {\n                    if (now - lastProfileSyncCheckAt >= PROFILE_SYNC_CHECK_MS) {\n                        lastProfileSyncCheckAt = now;\n                        syncNearbyProfileIfChanged();\n                    }\n                    if (!nearbyAdvertising) startNearbyAdvertising();'''
    if maintain_anchor not in text:
        fail("fallback maintain anchor missing")
    text = text.replace(maintain_anchor, maintain_new, 1)

    helper_anchor = "        private void restartNearbyPresence(String reason) {"
    helper = r'''        private String currentProfileFingerprint() {
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

'''
    if helper_anchor not in text:
        fail("profile helper anchor missing")
    text = text.replace(helper_anchor, helper + helper_anchor, 1)

    identity_anchor = '''                    publishResolvedPeer(transportId, wallet, displayName, 0, System.currentTimeMillis());\n                    pumpNearbyPacket(endpointId);'''
    identity_new = '''                    publishResolvedPeer(transportId, wallet, displayName, 0, System.currentTimeMillis());\n                    notifyLedgerChanged("", "PEER_IDENTITY_UPDATED");\n                    pumpNearbyPacket(endpointId);'''
    if identity_anchor in text:
        text = text.replace(identity_anchor, identity_new, 1)
    elif 'notifyLedgerChanged("", "PEER_IDENTITY_UPDATED")' not in text:
        fail("identity wakeup anchor missing")

    path.write_text(text)

    generated = path.read_text()
    for marker in (
        "BLEE_NEARBY_SPEED_PROFILE_V2",
        "BLE_GRACE_MS = 3_000L",
        "GATT_TIMEOUT_THRESHOLD = 1",
        "PROFILE_SYNC_CHECK_MS = 750L",
        "syncNearbyProfileIfChanged",
        "PEER_IDENTITY_UPDATED",
        "NEARBY_HEARTBEAT_MS = 1_000L",
    ):
        if marker not in generated:
            fail(f"missing generated marker {marker}")
    print("VERIFIED: nearby fallback/discovery is fast and profile changes re-sync while connected")


if __name__ == "__main__":
    main()
