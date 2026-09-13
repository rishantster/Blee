#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee relay cleanup: {message}")


def locate() -> Path:
    hits = list(ANDROID_JAVA.rglob("BleeRelayStore.java"))
    if len(hits) != 1:
        fail(f"expected one BleeRelayStore.java, found {len(hits)}")
    return hits[0]


def main() -> None:
    path = locate()
    text = path.read_text()
    marker = "BLEE_RELAY_TERMINAL_CLEANUP_V1"
    if marker in text:
        return
    if "BLEE_GLOBAL_STORE_FORWARD_RELAY_V1" not in text:
        fail("relay store stage must run first")

    reject_anchor = '''        db().insertWithOnConflict("relay_envelopes", null, row, SQLiteDatabase.CONFLICT_IGNORE);
        db().delete("mesh_outbox", "message_id=?", new String[] { messageId });
    }

    synchronized List<RelayCandidate> broadcastCandidates'''
    reject_new = '''        db().insertWithOnConflict("relay_envelopes", null, row, SQLiteDatabase.CONFLICT_IGNORE);
        db().delete("mesh_outbox", "message_id=?", new String[] { messageId });
        // BLEE_RELAY_TERMINAL_CLEANUP_V1
        // Invalid cryptographic candidates are not useful to the wallet or relay
        // after rejection; do not retain attacker-controlled payloads indefinitely.
        db().delete("mesh_inbox", "message_id=?", new String[] { messageId });
    }

    synchronized List<RelayCandidate> broadcastCandidates'''
    if reject_anchor not in text:
        fail("rejectCandidate cleanup anchor missing")
    text = text.replace(reject_anchor, reject_new, 1)

    invalid_anchor = '''    synchronized void markInvalid(String messageId, String error) {
        updateAttempt(messageId, "INVALID", error, Long.MAX_VALUE, false);
        db().delete("mesh_outbox", "message_id=?", new String[] { messageId });
    }'''
    invalid_new = '''    synchronized void markInvalid(String messageId, String error) {
        updateAttempt(messageId, "INVALID", error, Long.MAX_VALUE, false);
        db().delete("mesh_outbox", "message_id=?", new String[] { messageId });
        db().delete("mesh_inbox", "message_id=?", new String[] { messageId });
    }'''
    if invalid_anchor not in text:
        fail("markInvalid anchor missing")
    text = text.replace(invalid_anchor, invalid_new, 1)

    expired_anchor = '''    synchronized void markExpired(String messageId, String error) {
        updateAttempt(messageId, "EXPIRED", error, Long.MAX_VALUE, false);
        db().delete("mesh_outbox", "message_id=?", new String[] { messageId });
    }'''
    expired_new = '''    synchronized void markExpired(String messageId, String error) {
        updateAttempt(messageId, "EXPIRED", error, Long.MAX_VALUE, false);
        db().delete("mesh_outbox", "message_id=?", new String[] { messageId });
        db().delete("mesh_inbox", "message_id=?", new String[] { messageId });
    }'''
    if expired_anchor not in text:
        fail("markExpired anchor missing")
    text = text.replace(expired_anchor, expired_new, 1)

    old_cleanup = '''            "SELECT message_id FROM relay_envelopes WHERE expires_at<=? AND state NOT IN ('CONFIRMED','ALREADY_SETTLED','EXPIRED','INVALID','NEEDS_SENDER_REFRESH')",'''
    new_cleanup = '''            "SELECT message_id FROM relay_envelopes WHERE expires_at<=? AND state NOT IN ('CONFIRMED','ALREADY_SETTLED','EXPIRED','INVALID')",'''
    if old_cleanup not in text:
        fail("relay expiry selector anchor missing")
    text = text.replace(old_cleanup, new_cleanup, 1)

    path.write_text(text)

    verified = path.read_text()
    if marker not in verified:
        fail("terminal cleanup marker missing")
    if "'INVALID','NEEDS_SENDER_REFRESH'" in verified:
        fail("NEEDS_SENDER_REFRESH is still excluded from authorization expiry")
    print("Blee Relay V1 terminal cleanup and sender-refresh expiry verified")


if __name__ == "__main__":
    main()
