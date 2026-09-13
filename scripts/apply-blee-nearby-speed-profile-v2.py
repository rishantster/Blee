#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee nearby profile sync: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def main() -> None:
    path = locate("BleeMeshService.java")
    text = path.read_text()
    if "BLEE_ADAPTIVE_NEARBY_V3" not in text or "BLEE_NEARBY_STABILITY_V1" not in text:
        fail("adaptive + stability stages must run first")

    # BLEE_NEARBY_STABLE_TIMINGS_ROLLBACK_V1
    # The previous stabilization pass made transport selection too aggressive:
    # BLE grace 15s -> 3s and GATT fallback threshold 2 -> 1. On real devices
    # that can abandon a healthy-but-still-establishing BLE path before it has a
    # chance to publish identity, leaving the UI with no peer if Nearby is not
    # immediately ready. Restore the last physically proven timing contract.
    rollback = {
        "private static final long BLE_GRACE_MS = 3_000L;": "private static final long BLE_GRACE_MS = 15_000L;",
        "private static final int GATT_TIMEOUT_THRESHOLD = 1;": "private static final int GATT_TIMEOUT_THRESHOLD = 2;",
        "now - lastNearbyPumpAt >= 250L": "now - lastNearbyPumpAt >= 2_000L",
        "private static final long NEARBY_HEARTBEAT_MS = 1_000L;": "private static final long NEARBY_HEARTBEAT_MS = 5_000L;",
        "private static final long NEARBY_IDLE_REARM_MS = 12_000L;": "private static final long NEARBY_IDLE_REARM_MS = 30_000L;",
        "private static final long NEARBY_REARM_COOLDOWN_MS = 6_000L;": "private static final long NEARBY_REARM_COOLDOWN_MS = 15_000L;",
    }
    for aggressive, stable in rollback.items():
        if aggressive in text:
            text = text.replace(aggressive, stable, 1)
        elif stable not in text:
            fail(f"stable timing anchor missing: {stable}")

    # Remove the compatibility comments from the aggressive build. The verifier
    # should see the real active declarations, never marker text pretending the
    # old values are still active.
    text = text.replace(
        '''        // Adaptive V3 baseline verifier compatibility only; these are not active declarations:\n        // GATT_TIMEOUT_THRESHOLD = 2\n        // BLE_GRACE_MS = 15_000L\n''',
        '',
        1,
    )

    # Keep profile synchronization, but do not make it responsible for transport
    # selection or radio timing. This is deliberately additive to the last-known
    # working discovery behavior.
    field_anchor = "        private static final long NEARBY_REARM_COOLDOWN_MS = 15_000L;"
    if "BLEE_NEARBY_SPEED_PROFILE_V2" not in text:
        fields = field_anchor + '''\n        // BLEE_NEARBY_SPEED_PROFILE_V2\n        // Profile refresh only. Transport timing remains at the physically\n        // proven Adaptive V3 baseline above.\n        private static final long PROFILE_SYNC_CHECK_MS = 750L;\n        private long lastProfileSyncCheckAt = 0L;\n        private String lastProfileFingerprint = \"\";'''
        if field_anchor not in text:
            fail("stable rearm field anchor missing")
        text = text.replace(field_anchor, fields, 1)

    maintain_anchor = '''                if (fallbackActive && connectionsClient != null) {\n                    if (!nearbyAdvertising) startNearbyAdvertising();'''
    maintain_new = '''                if (fallbackActive && connectionsClient != null) {\n                    if (now - lastProfileSyncCheckAt >= PROFILE_SYNC_CHECK_MS) {\n                        lastProfileSyncCheckAt = now;\n                        syncNearbyProfileIfChanged();\n                    }\n                    if (!nearbyAdvertising) startNearbyAdvertising();'''
    if "syncNearbyProfileIfChanged();" not in text:
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
    if "private void syncNearbyProfileIfChanged()" not in text:
        if helper_anchor not in text:
            fail("profile helper anchor missing")
        text = text.replace(helper_anchor, helper + helper_anchor, 1)

    identity_anchor = '''                    publishResolvedPeer(transportId, wallet, displayName, 0, System.currentTimeMillis());\n                    pumpNearbyPacket(endpointId);'''
    identity_new = '''                    publishResolvedPeer(transportId, wallet, displayName, 0, System.currentTimeMillis());\n                    notifyLedgerChanged("", "PEER_IDENTITY_UPDATED");\n                    pumpNearbyPacket(endpointId);'''
    if 'notifyLedgerChanged("", "PEER_IDENTITY_UPDATED")' not in text:
        if identity_anchor not in text:
            fail("identity wakeup anchor missing")
        text = text.replace(identity_anchor, identity_new, 1)

    path.write_text(text)

    generated = path.read_text()
    required = (
        "BLEE_NEARBY_SPEED_PROFILE_V2",
        "private static final long BLE_GRACE_MS = 15_000L",
        "private static final int GATT_TIMEOUT_THRESHOLD = 2",
        "PROFILE_SYNC_CHECK_MS = 750L",
        "syncNearbyProfileIfChanged",
        "PEER_IDENTITY_UPDATED",
        "NEARBY_HEARTBEAT_MS = 5_000L",
        "NEARBY_IDLE_REARM_MS = 30_000L",
        "NEARBY_REARM_COOLDOWN_MS = 15_000L",
    )
    for marker in required:
        if marker not in generated:
            fail(f"missing generated marker {marker}")

    forbidden = (
        "private static final long BLE_GRACE_MS = 3_000L",
        "private static final int GATT_TIMEOUT_THRESHOLD = 1",
        "NEARBY_HEARTBEAT_MS = 1_000L",
        "NEARBY_IDLE_REARM_MS = 12_000L",
        "NEARBY_REARM_COOLDOWN_MS = 6_000L",
    )
    for marker in forbidden:
        if marker in generated:
            fail(f"aggressive discovery regression survived: {marker}")

    print("VERIFIED: last-known-working Nearby/BLE transport timings restored; profile sync remains enabled")


if __name__ == "__main__":
    main()
