#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def locate_activity() -> Path:
    matches = list((ROOT / "android/app/src/main/java").rglob("MainActivity.java"))
    if len(matches) != 1:
        raise SystemExit(f"Blee final hardening 2: expected one MainActivity.java, found {len(matches)}")
    return matches[0]


def harden_atomic_signing() -> None:
    path = ROOT / "src/lib/atomicSigning.ts"
    text = path.read_text()
    marker = "BLEE_OFFLINE_SETTLEMENT_PROFILE_REQUIRED_V1"
    if marker in text:
        return

    text = text.replace(
        "const FRESH_FEE_WINDOW_MS = 6 * 60 * 60 * 1000;",
        "const FRESH_FEE_WINDOW_MS = 6 * 60 * 60 * 1000;\nconst MAX_OFFLINE_PROFILE_AGE_MS = 24 * 60 * 60 * 1000;\n// BLEE_OFFLINE_SETTLEMENT_PROFILE_REQUIRED_V1",
        1,
    )

    old_native = '''  // Browser/dev fallback cannot make SQLite guarantees. Native Android is the
  // production path and must reserve before either signature is returned.
  if (!nativeReady) {
    const auth = await signAuthorization(account, to, value, validAfter, validBefore, authorizationNonce);
    const broadcast = { mode: 'AUTH_ONLY' as const, reason: 'NATIVE_STORE_UNAVAILABLE' };
    const bundleHash = keccak256(stringToHex(JSON.stringify({ auth, broadcast })));
    return {
      ...auth,
      broadcast,
      atomicSigning: { version: 1, signingId: id, sessionId: SIGNING_SESSION_ID, state: 'READY', bundleHash },
    };
  }

  let profile = await loadProfile(account.address);
  if (!profile) {
    await refreshAtomicSigningProfile(account.address);
    profile = await loadProfile(account.address);
  }
'''
    new_native = '''  // Production Blee fails closed. A payment is not created unless its signed
  // authorization and sender-funded raw settlement transaction can both be
  // durably stored before any nearby transmission begins.
  if (!nativeReady) {
    throw new Error('Blee secure payment storage is unavailable. Reopen the Android app before sending.');
  }

  let profile = await loadProfile(account.address);
  const profileTooOld = profile ? Date.now() - profile.syncedAt > MAX_OFFLINE_PROFILE_AGE_MS : true;
  if (!profile || profileTooOld) {
    await refreshAtomicSigningProfile(account.address);
    profile = await loadProfile(account.address);
  }
  if (!profile || Date.now() - profile.syncedAt > MAX_OFFLINE_PROFILE_AGE_MS) {
    throw new Error('Connect Blee to the internet once to refresh offline settlement readiness before sending nearby.');
  }
'''
    if old_native not in text:
        raise SystemExit("Blee final hardening 2: atomic native/profile anchor not found")
    text = text.replace(old_native, new_native, 1)

    reservation_anchor = "    if (!reservation.reserved) throw new Error('Unable to reserve signing intent');\n    reserved = true;"
    reservation_new = reservation_anchor + "\n    if (!Number.isSafeInteger(reservation.txNonce)) {\n      throw new Error('Offline settlement nonce reservation failed. Refresh Blee online and try again.');\n    }"
    if reservation_anchor not in text:
        raise SystemExit("Blee final hardening 2: atomic reservation anchor not found")
    text = text.replace(reservation_anchor, reservation_new, 1)

    path.write_text(text)
    print("Blee final hardening 2: every Android nearby payment requires a fresh sender-funded settlement bundle")


def harden_backup_compatibility() -> None:
    path = ROOT / "src/lib/walletRecovery.ts"
    text = path.read_text()
    marker = "BLEE_BACKUP_V1_COMPAT_V1"
    if marker in text:
        return

    old = '''  if (!Number.isInteger(vault.iterations) || vault.iterations < MIN_PBKDF2_ITERATIONS || vault.iterations > MAX_PBKDF2_ITERATIONS) {
    throw new Error("Wallet backup key-derivation parameters are invalid");
  }
'''
    new = '''  // BLEE_BACKUP_V1_COMPAT_V1
  const iterations = vault.version === 2 ? vault.iterations : (vault.iterations || 210_000);
  if (!Number.isInteger(iterations) || iterations < MIN_PBKDF2_ITERATIONS || iterations > MAX_PBKDF2_ITERATIONS) {
    throw new Error("Wallet backup key-derivation parameters are invalid");
  }
  if (vault.version === 1 && !vault.iterations) vault.iterations = iterations;
'''
    if old not in text:
        raise SystemExit("Blee final hardening 2: backup KDF anchor not found")
    text = text.replace(old, new, 1)
    path.write_text(text)
    print("Blee final hardening 2: legacy encrypted backups retain bounded PBKDF2 compatibility")


def harden_ui_truthfulness() -> None:
    for path in (ROOT / "src").rglob("*.tsx"):
        text = path.read_text(errors="replace")
        before = text
        text = text.replace("Recipient acknowledgement is authenticated", "Nearby delivery acknowledgement is transport-level")
        text = text.replace("authenticated recipient acknowledgement", "nearby delivery acknowledgement")
        text = text.replace("authenticated acknowledgement", "nearby delivery acknowledgement")
        if text != before:
            path.write_text(text)
    print("Blee final hardening 2: delivery copy no longer overstates wallet-level ACK authentication")


def harden_mesh_db(native_dir: Path) -> None:
    path = native_dir / "BleeMeshDb.java"
    text = path.read_text()
    marker = "BLEE_MESH_STATE_MACHINE_HARDENING_V2"
    if marker in text:
        return

    # Delivery ACK is useful transport evidence, but it is not wallet-bound
    # authorization. It must never destroy the sender's durable settlement path.
    ack_delete = '                db().delete("mesh_outbox", "message_id=?", new String[] { "pay:" + paymentId });'
    if ack_delete not in text:
        raise SystemExit("Blee final hardening 2: delivery ACK delete anchor not found")
    text = text.replace(
        ack_delete,
        '                // BLEE_ACK_NON_DESTRUCTIVE_V1: ACK updates UX only; settlement durability remains intact.',
        1,
    )
    text = text.replace(
        'notifyBody = "Your payment reached the intended Blee recipient.";',
        'notifyBody = "A nearby Blee device acknowledged durable receipt.";',
    )

    # A relay report is not chain finality. Keep the payment envelope until this
    # device independently observes the canonical successful receipt.
    relay_delete = '                    db().delete("mesh_outbox", "payment_id=? AND packet_type=?", new String[] { paymentId, "PAYMENT_ENVELOPE" });'
    text = text.replace(
        relay_delete,
        '                    // Relay report is non-final: keep PAYMENT_ENVELOPE until CHAIN_CONFIRMED.',
        1,
    )
    local_relay_delete = '            db().delete("mesh_outbox", "payment_id=? AND packet_type=?", new String[] { paymentId, "PAYMENT_ENVELOPE" });'
    text = text.replace(
        local_relay_delete,
        '            // Local relay report is non-final: keep PAYMENT_ENVELOPE until CHAIN_CONFIRMED.',
        1,
    )

    # Candidate selection must include the sender's own durable outbox so Phone A
    # can auto-settle the moment it regains internet, without opening the WebView.
    method_pattern = re.compile(
        r'''    synchronized List<String> settlementCandidates\(long now, int limit\) \{.*?\n    \}\n\n    synchronized void recordSettlementReceipt''',
        re.S,
    )
    replacement = r'''    synchronized List<String> settlementCandidates(long now, int limit) {
        List<String> rows = new ArrayList<>();
        java.util.HashSet<String> seen = new java.util.HashSet<>();

        // Received/courier envelopes: Phone B or Phone C may settle.
        try (Cursor c = db().query(
            "mesh_inbox", new String[] { "payment_id","packet" },
            "packet_type=? AND expires_at>?",
            new String[] { "PAYMENT_ENVELOPE", String.valueOf(now) },
            null, null, "received_at ASC", String.valueOf(Math.max(1, limit))
        )) {
            while (c.moveToNext() && rows.size() < limit) {
                String paymentId = c.getString(0);
                if (paymentId == null || paymentId.isEmpty() || hasVerifiedSettlement(paymentId)) continue;
                if (seen.add(paymentId)) rows.add(c.getString(1));
            }
        }

        // Sender's own outbox: Phone A auto-settles immediately on OFFLINE -> ONLINE.
        if (rows.size() < limit) {
            try (Cursor c = db().query(
                "mesh_outbox", new String[] { "payment_id","packet" },
                "packet_type=? AND expires_at>?",
                new String[] { "PAYMENT_ENVELOPE", String.valueOf(now) },
                null, null, "created_at ASC", String.valueOf(Math.max(1, limit))
            )) {
                while (c.moveToNext() && rows.size() < limit) {
                    String paymentId = c.getString(0);
                    if (paymentId == null || paymentId.isEmpty() || hasVerifiedSettlement(paymentId)) continue;
                    if (seen.add(paymentId)) rows.add(c.getString(1));
                }
            }
        }
        return rows;
    }

    private boolean hasVerifiedSettlement(String paymentId) {
        try (Cursor c = db().rawQuery(
            "SELECT 1 FROM settlement_receipts WHERE payment_id=? AND verified_at IS NOT NULL LIMIT 1",
            new String[] { paymentId }
        )) {
            return c.moveToFirst();
        }
    }

    synchronized void recordSettlementReceipt'''
    text, count = method_pattern.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit("Blee final hardening 2: settlementCandidates method anchor not found")

    # Persist proof verification instead of wiping verified_at when a duplicate
    # gossip packet is received after local chain confirmation.
    persist_pattern = re.compile(
        r'''    private void persistSettlementReceipt\(String paymentId, JSONObject receipt, long now\) \{.*?\n    \}\n\n    private boolean outboxExists''',
        re.S,
    )
    persist_replacement = r'''    private void persistSettlementReceipt(String paymentId, JSONObject receipt, long now) {
        Long verifiedAt = null;
        try (Cursor c = db().query("settlement_receipts", new String[] { "verified_at" }, "payment_id=?", new String[] { paymentId }, null, null, null)) {
            if (c.moveToFirst() && !c.isNull(0)) verifiedAt = c.getLong(0);
        }
        ContentValues rv = new ContentValues();
        rv.put("payment_id", paymentId);
        rv.put("tx_hash", receipt.optString("txHash", ""));
        rv.put("chain_id", receipt.optLong("chainId", 0L));
        rv.put("block_number", receipt.optString("blockNumber", ""));
        rv.put("reported_at", now);
        if (verifiedAt != null) rv.put("verified_at", verifiedAt); else rv.putNull("verified_at");
        rv.put("receipt", receipt.toString());
        db().insertWithOnConflict("settlement_receipts", null, rv, SQLiteDatabase.CONFLICT_REPLACE);
    }

    private boolean outboxExists'''
    text, count = persist_pattern.subn(persist_replacement, text, count=1)
    if count != 1:
        raise SystemExit("Blee final hardening 2: persistSettlementReceipt anchor not found")

    # Native state transitions themselves are monotonic, not just React journal
    # writes. Late ACK/gossip packets can never roll CHAIN_CONFIRMED backwards.
    state_anchor = "    private boolean updateAnyPaymentState(String paymentId, String state, String eventType, long at, String sourceDevice, String eventPayload) {"
    state_helpers = r'''    // BLEE_MESH_STATE_MACHINE_HARDENING_V2
    private static int paymentStateRank(String state) {
        String s = state == null ? "" : state.trim().toLowerCase(Locale.ROOT);
        if (s.contains("chain_confirmed") || (s.contains("chain") && s.contains("confirm"))) return 100;
        if (s.contains("revert")) return 95;
        if (s.contains("expired") || s.contains("fail") || s.contains("cancel")) return 90;
        if (s.contains("settled_relay_reported")) return 80;
        if (s.contains("settlement_submitted") || s.contains("submitted")) return 70;
        if (s.contains("acknowledged") || s.contains("acknowledge")) return 60;
        if (s.contains("delivered_offline") || s.contains("delivered")) return 50;
        if (s.contains("queued")) return 40;
        if (s.contains("signed")) return 30;
        if (s.contains("created")) return 20;
        return 10;
    }

'''
    if state_anchor not in text:
        raise SystemExit("Blee final hardening 2: updateAnyPaymentState anchor not found")
    text = text.replace(state_anchor, state_helpers + state_anchor, 1)

    old_query = 'try (Cursor c = db().query("payments", new String[] { "payload" }, "payment_key=?", new String[] { key }, null, null, null)) {\n            if (!c.moveToFirst()) return false;\n            JSONObject payment = new JSONObject(c.getString(0));'
    new_query = 'try (Cursor c = db().query("payments", new String[] { "payload","state" }, "payment_key=?", new String[] { key }, null, null, null)) {\n            if (!c.moveToFirst()) return false;\n            String currentState = c.getString(1);\n            int currentRank = paymentStateRank(currentState);\n            int nextRank = paymentStateRank(state);\n            if (currentRank > nextRank || (currentRank == nextRank && state.equalsIgnoreCase(currentState))) return false;\n            JSONObject payment = new JSONObject(c.getString(0));'
    if old_query not in text:
        raise SystemExit("Blee final hardening 2: updatePaymentState query anchor not found")
    text = text.replace(old_query, new_query, 1)

    old_final = '''    private static boolean isFinalState(String state) {
        String s = state == null ? "" : state.toLowerCase(Locale.ROOT);
        return s.contains("confirm") || s.contains("settled") || s.contains("expired") || s.contains("fail") || s.contains("revert");
    }'''
    new_final = '''    private static boolean isFinalState(String state) {
        String s = state == null ? "" : state.toLowerCase(Locale.ROOT);
        // Relay-reported settlement is intentionally NOT final. Only canonical
        // chain confirmation or terminal failure/expiry stops settlement work.
        return s.contains("chain_confirmed")
            || (s.contains("chain") && s.contains("confirm"))
            || s.contains("expired")
            || s.contains("fail")
            || s.contains("revert")
            || s.contains("cancel");
    }'''
    if old_final not in text:
        raise SystemExit("Blee final hardening 2: isFinalState anchor not found")
    text = text.replace(old_final, new_final, 1)

    # markChainConfirmed was installed by final-hardening-1. Canonical success is
    # the only point allowed to retire the payment delivery envelope.
    old_confirm = '''        return updateAnyPaymentState(
            paymentId, "chain_confirmed", "CHAIN_CONFIRMED", now,
            deviceSource(canonicalReceipt), canonicalReceipt.toString()
        );'''
    new_confirm = '''        boolean changed = updateAnyPaymentState(
            paymentId, "chain_confirmed", "CHAIN_CONFIRMED", now,
            deviceSource(canonicalReceipt), canonicalReceipt.toString()
        );
        db().delete("mesh_outbox", "payment_id=? AND packet_type=?", new String[] { paymentId, "PAYMENT_ENVELOPE" });
        ContentValues job = new ContentValues();
        job.put("state", "CONFIRMED");
        job.put("updated_at", now);
        job.putNull("last_error");
        db().update("settlement_jobs", job, "payment_id=?", new String[] { paymentId });
        return changed;'''
    if old_confirm not in text:
        raise SystemExit("Blee final hardening 2: markChainConfirmed anchor not found")
    text = text.replace(old_confirm, new_confirm, 1)

    # Persist peer-specific delivery history so copy budget is a real spray-and-
    # wait budget rather than a decorative field.
    seen_schema = '        db.execSQL("CREATE TABLE IF NOT EXISTS mesh_seen_packets (message_id TEXT PRIMARY KEY NOT NULL,seen_at INTEGER NOT NULL,expires_at INTEGER NOT NULL)");'
    peer_schema = seen_schema + '\n        db.execSQL("CREATE TABLE IF NOT EXISTS mesh_peer_deliveries (message_id TEXT NOT NULL,peer_address TEXT NOT NULL,delivered_at INTEGER NOT NULL,PRIMARY KEY(message_id,peer_address))");'
    if seen_schema not in text:
        raise SystemExit("Blee final hardening 2: mesh schema anchor not found")
    text = text.replace(seen_schema, peer_schema, 1)

    due_anchor = '''    synchronized void recordAttempt(String messageId) {'''
    peer_methods = r'''    synchronized List<String> duePacketsForPeer(long now, String peerAddress, int limit) {
        List<String> rows = new ArrayList<>();
        try (Cursor c = db().query(
            "mesh_outbox",
            new String[] { "message_id","packet","copy_budget" },
            "expires_at>? AND next_attempt_at<=? AND copy_budget>0",
            new String[] { String.valueOf(now), String.valueOf(now) },
            null, null, "created_at ASC", String.valueOf(Math.max(limit * 8, 16))
        )) {
            while (c.moveToNext() && rows.size() < limit) {
                String messageId = c.getString(0);
                if (hasPeerDelivery(messageId, peerAddress)) continue;
                try {
                    JSONObject packet = new JSONObject(c.getString(1));
                    packet.put("copyBudget", c.getInt(2));
                    rows.add(packet.toString());
                } catch (Throwable ignored) {}
            }
        }
        return rows;
    }

    private boolean hasPeerDelivery(String messageId, String peerAddress) {
        try (Cursor c = db().rawQuery(
            "SELECT 1 FROM mesh_peer_deliveries WHERE message_id=? AND peer_address=? LIMIT 1",
            new String[] { messageId, peerAddress }
        )) {
            return c.moveToFirst();
        }
    }

    synchronized void recordPeerDelivery(String messageId, String peerAddress) {
        long now = System.currentTimeMillis();
        ContentValues delivered = new ContentValues();
        delivered.put("message_id", messageId);
        delivered.put("peer_address", peerAddress);
        delivered.put("delivered_at", now);
        db().insertWithOnConflict("mesh_peer_deliveries", null, delivered, SQLiteDatabase.CONFLICT_IGNORE);

        int attempts = 0;
        int budget = 0;
        try (Cursor c = db().query("mesh_outbox", new String[] { "attempts","copy_budget" }, "message_id=?", new String[] { messageId }, null, null, null)) {
            if (c.moveToFirst()) {
                attempts = c.getInt(0);
                budget = c.getInt(1);
            }
        }
        ContentValues cv = new ContentValues();
        cv.put("attempts", attempts + 1);
        cv.put("copy_budget", Math.max(0, budget - 1));
        cv.put("next_attempt_at", now + 1000L);
        db().update("mesh_outbox", cv, "message_id=?", new String[] { messageId });
    }

'''
    if due_anchor not in text:
        raise SystemExit("Blee final hardening 2: recordAttempt anchor not found")
    text = text.replace(due_anchor, peer_methods + due_anchor, 1)

    cleanup_anchor = '        db().delete("mesh_seen_packets", "expires_at<?", new String[] { String.valueOf(now) });'
    cleanup_new = cleanup_anchor + '\n        db().execSQL("DELETE FROM mesh_peer_deliveries WHERE message_id NOT IN (SELECT message_id FROM mesh_outbox)");'
    if cleanup_anchor not in text:
        raise SystemExit("Blee final hardening 2: cleanup anchor not found")
    text = text.replace(cleanup_anchor, cleanup_new, 1)

    path.write_text(text)
    print("Blee final hardening 2: native ledger monotonicity, non-final relay reports, sender auto-settlement and bounded spray-and-wait enforced")


def harden_mesh_service(native_dir: Path) -> None:
    path = native_dir / "BleeMeshService.java"
    text = path.read_text()
    marker = "BLEE_ADVERTISER_RECOVERY_V1"
    if marker in text:
        return

    text = text.replace(
        "    private volatile boolean scanning = false;",
        "    private volatile boolean scanning = false;\n    private volatile boolean advertising = false;\n    // BLEE_ADVERTISER_RECOVERY_V1",
        1,
    )
    text = text.replace(
        "                if (!scanning) startBluetooth();",
        "                if (!scanning || !advertising) startBluetooth();",
        1,
    )
    text = text.replace(
        "            if (advertiser != null) {",
        "            if (advertiser != null && !advertising) {",
        1,
    )

    empty_callback = "    private final AdvertiseCallback advertiseCallback = new AdvertiseCallback() {};"
    callback = '''    private final AdvertiseCallback advertiseCallback = new AdvertiseCallback() {
        @Override public void onStartSuccess(AdvertiseSettings settingsInEffect) {
            advertising = true;
        }
        @Override public void onStartFailure(int errorCode) {
            advertising = false;
            Log.w(TAG, "BLE advertise failed: " + errorCode + "; rearming");
            handler.postDelayed(new Runnable() {
                @Override public void run() { startBluetooth(); }
            }, 1500L);
        }
    };'''
    if empty_callback not in text:
        raise SystemExit("Blee final hardening 2: advertise callback anchor not found")
    text = text.replace(empty_callback, callback, 1)

    stop_anchor = "        scanning = false;\n        gattServer = null;"
    if stop_anchor not in text:
        raise SystemExit("Blee final hardening 2: stopBluetooth anchor not found")
    text = text.replace(stop_anchor, "        scanning = false;\n        advertising = false;\n        gattServer = null;", 1)

    # Send each envelope to a given peer at most once durably and decrement the
    # database copy budget only after the final GATT frame was acknowledged.
    old_send = "        List<String> packets = db.duePackets(System.currentTimeMillis(), 1);"
    new_send = "        String peerAddress = gatt.getDevice() == null ? \"unknown\" : gatt.getDevice().getAddress();\n        List<String> packets = db.duePacketsForPeer(System.currentTimeMillis(), peerAddress, 1);"
    if old_send not in text:
        raise SystemExit("Blee final hardening 2: sendOnePacket duePackets anchor not found")
    text = text.replace(old_send, new_send, 1)

    old_success = "                db.recordAttempt(state.messageId);"
    new_success = "                String peerAddress = gatt.getDevice() == null ? \"unknown\" : gatt.getDevice().getAddress();\n                db.recordPeerDelivery(state.messageId, peerAddress);"
    if old_success not in text:
        raise SystemExit("Blee final hardening 2: GATT success accounting anchor not found")
    text = text.replace(old_success, new_success, 1)

    path.write_text(text)
    print("Blee final hardening 2: BLE advertiser recovery and durable peer-specific copy budget enabled")


def verify(native_dir: Path) -> None:
    atomic = (ROOT / "src/lib/atomicSigning.ts").read_text()
    recovery = (ROOT / "src/lib/walletRecovery.ts").read_text()
    db = (native_dir / "BleeMeshDb.java").read_text()
    service = (native_dir / "BleeMeshService.java").read_text()

    required_atomic = (
        "BLEE_OFFLINE_SETTLEMENT_PROFILE_REQUIRED_V1",
        "MAX_OFFLINE_PROFILE_AGE_MS",
        "Blee secure payment storage is unavailable",
        "Offline settlement nonce reservation failed",
    )
    required_db = (
        "BLEE_MESH_STATE_MACHINE_HARDENING_V2",
        "BLEE_ACK_NON_DESTRUCTIVE_V1",
        "hasVerifiedSettlement",
        "duePacketsForPeer",
        "recordPeerDelivery",
        "mesh_peer_deliveries",
        "Relay-reported settlement is intentionally NOT final",
        "state\", \"CONFIRMED",
    )
    required_service = (
        "BLEE_ADVERTISER_RECOVERY_V1",
        "advertising = false",
        "onStartFailure",
        "duePacketsForPeer",
        "recordPeerDelivery",
    )
    for name, text, markers in (
        ("atomicSigning", atomic, required_atomic),
        ("meshDb", db, required_db),
        ("meshService", service, required_service),
    ):
        missing = [m for m in markers if m not in text]
        if missing:
            raise SystemExit(f"Blee final hardening 2 verification failed for {name}: {missing}")

    if "BLEE_BACKUP_V1_COMPAT_V1" not in recovery:
        raise SystemExit("Blee final hardening 2: backup compatibility marker missing")
    if 'db().delete("mesh_outbox", "message_id=?", new String[] { "pay:" + paymentId });' in db:
        raise SystemExit("Blee final hardening 2: destructive ACK handling remains")
    if 's.contains("settled")' in db:
        raise SystemExit("Blee final hardening 2: relay-reported settlement is still treated as terminal")

    print("Blee final hardening 2 verified.")


def main() -> None:
    harden_atomic_signing()
    harden_backup_compatibility()
    harden_ui_truthfulness()
    activity = locate_activity()
    native_dir = activity.parent
    harden_mesh_db(native_dir)
    harden_mesh_service(native_dir)
    verify(native_dir)


if __name__ == "__main__":
    main()
