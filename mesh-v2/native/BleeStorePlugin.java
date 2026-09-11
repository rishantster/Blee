package com.blee.store;

import android.content.ContentValues;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import org.json.JSONObject;

import java.util.Locale;

@CapacitorPlugin(name = "BleeStore")
public class BleeStorePlugin extends Plugin {
    private static final String DB_NAME = "blee.db";
    private static final int DB_VERSION = 5;
    private static final String STORE_MARKER = "BLEE_STORE_MESH_V2_ATOMIC_SIGNING_V1";

    private BleeDb helper;

    @Override
    public void load() {
        helper = new BleeDb();
        helper.setWriteAheadLoggingEnabled(true);
    }

    @Override
    protected void handleOnDestroy() {
        synchronized (this) {
            if (helper != null) {
                helper.close();
                helper = null;
            }
        }
        super.handleOnDestroy();
    }

    private synchronized SQLiteDatabase db() {
        if (helper == null) {
            helper = new BleeDb();
            helper.setWriteAheadLoggingEnabled(true);
        }
        SQLiteDatabase database = helper.getWritableDatabase();
        ensureSchema(database);
        return database;
    }

    private static void ensureSchema(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE IF NOT EXISTS payments (payment_key TEXT PRIMARY KEY NOT NULL,payment_id TEXT NOT NULL,direction TEXT NOT NULL,state TEXT NOT NULL,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,payload TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY NOT NULL,value TEXT NOT NULL,updated_at INTEGER NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS payment_events (event_id TEXT PRIMARY KEY NOT NULL,payment_id TEXT NOT NULL,event_type TEXT NOT NULL,event_at INTEGER NOT NULL,source_device TEXT,payload TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS mesh_inbox (message_id TEXT PRIMARY KEY NOT NULL,packet_type TEXT NOT NULL,payment_id TEXT,received_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,hop_count INTEGER NOT NULL,packet TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS mesh_outbox (message_id TEXT PRIMARY KEY NOT NULL,packet_type TEXT NOT NULL,payment_id TEXT,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,hop_count INTEGER NOT NULL,hop_limit INTEGER NOT NULL,copy_budget INTEGER NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,next_attempt_at INTEGER NOT NULL,packet TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS mesh_seen_packets (message_id TEXT PRIMARY KEY NOT NULL,seen_at INTEGER NOT NULL,expires_at INTEGER NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS courier_envelopes (message_id TEXT PRIMARY KEY NOT NULL,payment_id TEXT,destination_wallet TEXT,received_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,hop_count INTEGER NOT NULL,packet TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS settlement_jobs (payment_id TEXT PRIMARY KEY NOT NULL,state TEXT NOT NULL,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,next_attempt_at INTEGER NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT,authorization TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS settlement_receipts (payment_id TEXT PRIMARY KEY NOT NULL,tx_hash TEXT NOT NULL,chain_id INTEGER,block_number TEXT,reported_at INTEGER NOT NULL,verified_at INTEGER,receipt TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS peer_identities (wallet_address TEXT PRIMARY KEY NOT NULL,display_name TEXT,avatar TEXT,device_id TEXT,updated_at INTEGER NOT NULL,payload TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS signing_intents (signing_id TEXT PRIMARY KEY NOT NULL,session_id TEXT NOT NULL,chain_id INTEGER NOT NULL,sender TEXT NOT NULL,recipient TEXT NOT NULL,value TEXT NOT NULL,authorization_nonce TEXT NOT NULL,tx_nonce INTEGER,state TEXT NOT NULL,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,authorization_json TEXT,broadcast_json TEXT,bundle_hash TEXT,payment_id TEXT,last_error TEXT)");

        db.execSQL("CREATE INDEX IF NOT EXISTS payments_created_idx ON payments(created_at DESC)");
        db.execSQL("CREATE INDEX IF NOT EXISTS payments_state_idx ON payments(state)");
        db.execSQL("CREATE INDEX IF NOT EXISTS payment_events_payment_idx ON payment_events(payment_id,event_at ASC)");
        db.execSQL("CREATE INDEX IF NOT EXISTS mesh_outbox_due_idx ON mesh_outbox(next_attempt_at,expires_at)");
        db.execSQL("CREATE INDEX IF NOT EXISTS mesh_seen_expiry_idx ON mesh_seen_packets(expires_at)");
        db.execSQL("CREATE INDEX IF NOT EXISTS settlement_jobs_due_idx ON settlement_jobs(state,next_attempt_at)");
        db.execSQL("CREATE INDEX IF NOT EXISTS signing_intents_sender_idx ON signing_intents(chain_id,sender,state,tx_nonce)");
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS signing_intents_auth_nonce_uq ON signing_intents(authorization_nonce)");
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS signing_intents_active_tx_nonce_uq ON signing_intents(chain_id,sender,tx_nonce) WHERE tx_nonce IS NOT NULL AND state <> 'ABORTED'");
    }

    private static String message(Throwable error) {
        String detail = error.getMessage();
        if (detail == null || detail.trim().isEmpty()) detail = "no detail";
        return error.getClass().getSimpleName() + ": " + detail;
    }

    private static String require(PluginCall call, String key) {
        String value = call.getString(key);
        if (value == null || value.trim().isEmpty()) throw new IllegalArgumentException("Missing " + key);
        return value;
    }

    private static JSONObject authorization(JSONObject payment) {
        JSONObject auth = payment.optJSONObject("authorization");
        if (auth == null) auth = payment.optJSONObject("auth");
        return auth;
    }

    private static JSONObject broadcast(JSONObject auth) {
        return auth == null ? null : auth.optJSONObject("broadcast");
    }

    private static Integer txNonce(JSONObject broadcast) {
        if (broadcast == null || !"SENDER_FUNDED_RAW_TX".equals(broadcast.optString("mode", ""))) return null;
        if (!broadcast.has("txNonce")) return null;
        return broadcast.optInt("txNonce", -1) >= 0 ? broadcast.optInt("txNonce") : null;
    }

    private static long chainId(JSONObject broadcast) {
        return broadcast == null ? 0L : broadcast.optLong("chainId", 0L);
    }

    @PluginMethod
    public void init(PluginCall call) {
        try {
            SQLiteDatabase database = db();
            ContentValues probe = new ContentValues();
            probe.put("key", "__blee_store_probe__");
            probe.put("value", STORE_MARKER);
            probe.put("updated_at", System.currentTimeMillis());
            long inserted = database.insertWithOnConflict("kv", null, probe, SQLiteDatabase.CONFLICT_REPLACE);
            if (inserted == -1) throw new IllegalStateException("SQLite write probe failed");

            try (Cursor cursor = database.query("kv", new String[] { "value" }, "key = ?", new String[] { "__blee_store_probe__" }, null, null, null)) {
                if (!cursor.moveToFirst() || !STORE_MARKER.equals(cursor.getString(0))) throw new IllegalStateException("SQLite read probe failed");
            }
            database.delete("kv", "key = ?", new String[] { "__blee_store_probe__" });

            String journalMode = "unknown";
            try (Cursor cursor = database.rawQuery("PRAGMA journal_mode", null)) {
                if (cursor.moveToFirst()) journalMode = cursor.getString(0);
            } catch (Throwable ignored) {}

            JSObject result = new JSObject();
            result.put("ready", true);
            result.put("journalMode", journalMode);
            result.put("store", STORE_MARKER);
            result.put("schemaVersion", DB_VERSION);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Blee SQLite init failed [" + STORE_MARKER + "]: " + message(error));
        }
    }

    /**
     * First crash-atomic signing boundary.
     *
     * The authorization nonce and, when available, EOA transaction nonce are
     * durably reserved before the wallet signs anything that Blee may later
     * transmit. SIGNING rows owned by a previous JS process session are safe to
     * abandon because only READY/PERSISTED bundles are allowed into the journal
     * or mesh.
     */
    @PluginMethod
    public void reserveSigningIntent(PluginCall call) {
        SQLiteDatabase database = null;
        try {
            String signingId = require(call, "signingId");
            String sessionId = require(call, "sessionId");
            Long chain = call.getLong("chainId");
            String sender = require(call, "sender").toLowerCase(Locale.ROOT);
            String recipient = require(call, "recipient").toLowerCase(Locale.ROOT);
            String value = require(call, "value");
            String authorizationNonce = require(call, "authorizationNonce").toLowerCase(Locale.ROOT);
            Long expiresAt = call.getLong("expiresAt");
            Long minTxNonce = call.getLong("minTxNonce");
            if (chain == null || chain <= 0) throw new IllegalArgumentException("Invalid chainId");
            if (expiresAt == null || expiresAt <= System.currentTimeMillis()) throw new IllegalArgumentException("Invalid signing expiry");

            database = db();
            database.beginTransaction();
            long now = System.currentTimeMillis();

            ContentValues abandoned = new ContentValues();
            abandoned.put("state", "ABORTED");
            abandoned.put("updated_at", now);
            abandoned.put("last_error", "previous signing process ended before durable finalization");
            database.update("signing_intents", abandoned, "state='SIGNING' AND session_id<>?", new String[] { sessionId });

            try (Cursor existing = database.query("signing_intents", new String[] { "session_id","state","tx_nonce" }, "signing_id=?", new String[] { signingId }, null, null, null)) {
                if (existing.moveToFirst()) {
                    String owner = existing.getString(0);
                    String state = existing.getString(1);
                    if (sessionId.equals(owner) && "SIGNING".equals(state)) {
                        JSObject result = new JSObject();
                        result.put("reserved", true);
                        if (!existing.isNull(2)) result.put("txNonce", existing.getLong(2));
                        database.setTransactionSuccessful();
                        call.resolve(result);
                        return;
                    }
                    throw new IllegalStateException("Signing intent already exists in state " + state);
                }
            }

            Long reservedTxNonce = null;
            if (minTxNonce != null && minTxNonce >= 0) {
                long candidate = minTxNonce;
                try (Cursor cursor = database.rawQuery(
                    "SELECT MAX(tx_nonce) FROM signing_intents WHERE chain_id=? AND sender=? AND tx_nonce IS NOT NULL AND state<>'ABORTED'",
                    new String[] { String.valueOf(chain), sender }
                )) {
                    if (cursor.moveToFirst() && !cursor.isNull(0)) candidate = Math.max(candidate, cursor.getLong(0) + 1L);
                }
                if (candidate > Integer.MAX_VALUE) throw new IllegalStateException("Transaction nonce exceeds supported range");
                reservedTxNonce = candidate;
            }

            ContentValues values = new ContentValues();
            values.put("signing_id", signingId);
            values.put("session_id", sessionId);
            values.put("chain_id", chain);
            values.put("sender", sender);
            values.put("recipient", recipient);
            values.put("value", value);
            values.put("authorization_nonce", authorizationNonce);
            if (reservedTxNonce != null) values.put("tx_nonce", reservedTxNonce);
            else values.putNull("tx_nonce");
            values.put("state", "SIGNING");
            values.put("created_at", now);
            values.put("updated_at", now);
            values.put("expires_at", expiresAt);
            if (database.insertOrThrow("signing_intents", null, values) == -1) throw new IllegalStateException("Signing reservation failed");

            database.setTransactionSuccessful();
            JSObject result = new JSObject();
            result.put("reserved", true);
            if (reservedTxNonce != null) result.put("txNonce", reservedTxNonce);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to reserve atomic signing intent: " + message(error));
        } finally {
            if (database != null && database.inTransaction()) database.endTransaction();
        }
    }

    /** Second crash-atomic signing boundary: persist the exact signatures. */
    @PluginMethod
    public void finalizeSigningIntent(PluginCall call) {
        SQLiteDatabase database = null;
        try {
            String signingId = require(call, "signingId");
            String sessionId = require(call, "sessionId");
            String authorizationJson = require(call, "authorization");
            String broadcastJson = require(call, "broadcast");
            String bundleHash = require(call, "bundleHash");
            JSONObject auth = new JSONObject(authorizationJson);
            JSONObject tx = new JSONObject(broadcastJson);

            database = db();
            database.beginTransaction();
            try (Cursor cursor = database.query(
                "signing_intents",
                new String[] { "session_id","chain_id","sender","recipient","value","authorization_nonce","tx_nonce","state","bundle_hash" },
                "signing_id=?", new String[] { signingId }, null, null, null
            )) {
                if (!cursor.moveToFirst()) throw new IllegalStateException("Signing intent not found");
                String owner = cursor.getString(0);
                long chain = cursor.getLong(1);
                String sender = cursor.getString(2);
                String recipient = cursor.getString(3);
                String value = cursor.getString(4);
                String authNonce = cursor.getString(5);
                Long reservedTxNonce = cursor.isNull(6) ? null : cursor.getLong(6);
                String state = cursor.getString(7);
                String existingHash = cursor.isNull(8) ? null : cursor.getString(8);

                if (("READY".equals(state) || "PERSISTED".equals(state)) && bundleHash.equals(existingHash)) {
                    database.setTransactionSuccessful();
                    JSObject result = new JSObject();
                    result.put("ready", true);
                    call.resolve(result);
                    return;
                }
                if (!sessionId.equals(owner) || !"SIGNING".equals(state)) throw new IllegalStateException("Signing intent is not owned by this active session");
                if (!sender.equals(auth.optString("from", "").toLowerCase(Locale.ROOT))) throw new IllegalStateException("Authorization sender mismatch");
                if (!recipient.equals(auth.optString("to", "").toLowerCase(Locale.ROOT))) throw new IllegalStateException("Authorization recipient mismatch");
                if (!value.equals(auth.optString("value", ""))) throw new IllegalStateException("Authorization value mismatch");
                if (!authNonce.equals(auth.optString("nonce", "").toLowerCase(Locale.ROOT))) throw new IllegalStateException("Authorization nonce mismatch");
                if (auth.optString("signature", "").isEmpty()) throw new IllegalStateException("Authorization signature missing");

                String mode = tx.optString("mode", "");
                if (reservedTxNonce == null) {
                    if (!"AUTH_ONLY".equals(mode)) throw new IllegalStateException("Unexpected sender transaction without reserved nonce");
                } else {
                    if (!"SENDER_FUNDED_RAW_TX".equals(mode)) throw new IllegalStateException("Reserved transaction nonce requires sender-funded raw transaction");
                    if (tx.optLong("chainId", -1L) != chain) throw new IllegalStateException("Settlement chain mismatch");
                    if (tx.optLong("txNonce", -1L) != reservedTxNonce) throw new IllegalStateException("Reserved transaction nonce mismatch");
                    if (!tx.optString("rawTransaction", "").matches("^0x[0-9a-fA-F]+$")) throw new IllegalStateException("Raw transaction missing");
                    if (!tx.optString("txHash", "").matches("^0x[0-9a-fA-F]{64}$")) throw new IllegalStateException("Transaction hash missing");
                }
            }

            ContentValues values = new ContentValues();
            values.put("state", "READY");
            values.put("updated_at", System.currentTimeMillis());
            values.put("authorization_json", authorizationJson);
            values.put("broadcast_json", broadcastJson);
            values.put("bundle_hash", bundleHash);
            values.putNull("last_error");
            if (database.update("signing_intents", values, "signing_id=? AND state='SIGNING'", new String[] { signingId }) != 1) {
                throw new IllegalStateException("Signing bundle finalization lost its reservation");
            }

            database.setTransactionSuccessful();
            JSObject result = new JSObject();
            result.put("ready", true);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to finalize atomic signing bundle: " + message(error));
        } finally {
            if (database != null && database.inTransaction()) database.endTransaction();
        }
    }

    @PluginMethod
    public void abortSigningIntent(PluginCall call) {
        SQLiteDatabase database = null;
        try {
            String signingId = require(call, "signingId");
            String sessionId = require(call, "sessionId");
            String reason = call.getString("reason", "signing aborted before durable finalization");
            database = db();
            database.beginTransaction();
            ContentValues values = new ContentValues();
            values.put("state", "ABORTED");
            values.put("updated_at", System.currentTimeMillis());
            values.put("last_error", reason);
            database.update("signing_intents", values, "signing_id=? AND session_id=? AND state='SIGNING'", new String[] { signingId, sessionId });
            database.setTransactionSuccessful();
            call.resolve();
        } catch (Throwable error) {
            call.reject("Unable to abort signing intent: " + message(error));
        } finally {
            if (database != null && database.inTransaction()) database.endTransaction();
        }
    }

    @PluginMethod
    public void loadPayments(PluginCall call) {
        try {
            JSArray payments = new JSArray();
            try (Cursor cursor = db().query("payments", new String[] { "payload" }, null, null, null, null, "created_at DESC, updated_at DESC")) {
                while (cursor.moveToNext()) payments.put(cursor.getString(0));
            }
            JSObject result = new JSObject();
            result.put("payments", payments);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to load Blee payments: " + message(error));
        }
    }

    private static boolean criticalBundleMatches(Cursor cursor, JSONObject auth, JSONObject tx) {
        String sender = cursor.getString(0);
        String recipient = cursor.getString(1);
        String value = cursor.getString(2);
        String authNonce = cursor.getString(3);
        Long reservedTxNonce = cursor.isNull(4) ? null : cursor.getLong(4);
        if (!sender.equals(auth.optString("from", "").toLowerCase(Locale.ROOT))) return false;
        if (!recipient.equals(auth.optString("to", "").toLowerCase(Locale.ROOT))) return false;
        if (!value.equals(auth.optString("value", ""))) return false;
        if (!authNonce.equals(auth.optString("nonce", "").toLowerCase(Locale.ROOT))) return false;
        if (auth.optString("signature", "").isEmpty()) return false;
        if (reservedTxNonce == null) return tx == null || "AUTH_ONLY".equals(tx.optString("mode", ""));
        return tx != null
            && "SENDER_FUNDED_RAW_TX".equals(tx.optString("mode", ""))
            && tx.optLong("txNonce", -1L) == reservedTxNonce
            && tx.optString("rawTransaction", "").matches("^0x[0-9a-fA-F]+$")
            && tx.optString("txHash", "").matches("^0x[0-9a-fA-F]{64}$");
    }

    private static void persistSigningForPayment(SQLiteDatabase database, JSONObject row, String paymentId, long now) throws Exception {
        if (!"outgoing".equalsIgnoreCase(row.optString("direction", ""))) return;
        JSONObject auth = authorization(row);
        if (auth == null || auth.optString("signature", "").isEmpty()) return;
        JSONObject tx = broadcast(auth);
        JSONObject atomic = auth.optJSONObject("atomicSigning");
        String signingId = atomic == null ? "" : atomic.optString("signingId", "");

        if (!signingId.isEmpty()) {
            try (Cursor cursor = database.query(
                "signing_intents",
                new String[] { "sender","recipient","value","authorization_nonce","tx_nonce","state" },
                "signing_id=?", new String[] { signingId }, null, null, null
            )) {
                if (!cursor.moveToFirst()) throw new IllegalStateException("Atomic signing reservation is missing");
                String state = cursor.getString(5);
                if (!("READY".equals(state) || "PERSISTED".equals(state))) throw new IllegalStateException("Signed bundle is not READY");
                if (!criticalBundleMatches(cursor, auth, tx)) throw new IllegalStateException("Payment differs from its durably signed bundle");
            }
            ContentValues persisted = new ContentValues();
            persisted.put("state", "PERSISTED");
            persisted.put("payment_id", paymentId);
            persisted.put("updated_at", now);
            database.update("signing_intents", persisted, "signing_id=?", new String[] { signingId });
        } else {
            // Safe one-time migration path for payments already durably stored by
            // a pre-atomic Blee 2.1 build. New payments always carry atomicSigning.
            String authNonce = auth.optString("nonce", "").toLowerCase(Locale.ROOT);
            if (authNonce.isEmpty()) throw new IllegalStateException("Outgoing authorization nonce missing");
            signingId = "legacy:" + chainId(tx) + ":" + auth.optString("from", "").toLowerCase(Locale.ROOT) + ":" + authNonce;
            ContentValues legacy = new ContentValues();
            legacy.put("signing_id", signingId);
            legacy.put("session_id", "legacy-migration");
            legacy.put("chain_id", chainId(tx));
            legacy.put("sender", auth.optString("from", "").toLowerCase(Locale.ROOT));
            legacy.put("recipient", auth.optString("to", "").toLowerCase(Locale.ROOT));
            legacy.put("value", auth.optString("value", ""));
            legacy.put("authorization_nonce", authNonce);
            Integer nonce = txNonce(tx);
            if (nonce == null) legacy.putNull("tx_nonce"); else legacy.put("tx_nonce", nonce);
            legacy.put("state", "PERSISTED");
            legacy.put("created_at", row.optLong("createdAt", now));
            legacy.put("updated_at", now);
            legacy.put("expires_at", Math.max(now + 1L, Long.parseLong(auth.optString("validBefore", String.valueOf(now / 1000L + 86400L))) * 1000L));
            legacy.put("authorization_json", auth.toString());
            legacy.put("broadcast_json", tx == null ? "{}" : tx.toString());
            legacy.put("bundle_hash", "legacy-durable-payment");
            legacy.put("payment_id", paymentId);
            database.insertWithOnConflict("signing_intents", null, legacy, SQLiteDatabase.CONFLICT_IGNORE);
        }

        ContentValues event = new ContentValues();
        event.put("event_id", "SIGNATURE_BUNDLE_PERSISTED:" + paymentId + ":" + auth.optString("nonce", ""));
        event.put("payment_id", paymentId);
        event.put("event_type", "SIGNATURE_BUNDLE_PERSISTED");
        event.put("event_at", now);
        event.putNull("source_device");
        event.put("payload", auth.toString());
        database.insertWithOnConflict("payment_events", null, event, SQLiteDatabase.CONFLICT_IGNORE);
    }

    @PluginMethod
    public void replacePayments(PluginCall call) {
        JSArray payments = call.getArray("payments");
        if (payments == null) { call.reject("Missing payments"); return; }

        SQLiteDatabase database = null;
        try {
            database = db();
            database.beginTransaction();
            long now = System.currentTimeMillis();
            for (int i = 0; i < payments.length(); i++) {
                String payload = payments.optString(i, null);
                if (payload == null || payload.isEmpty()) throw new IllegalArgumentException("Invalid payment row at index " + i);
                JSONObject row = new JSONObject(payload);
                String paymentId = row.optString("id", "");
                String direction = row.optString("direction", "");
                String state = row.optString("state", "");
                if (paymentId.isEmpty() || direction.isEmpty() || state.isEmpty()) throw new IllegalArgumentException("Invalid payment row at index " + i);

                long createdAt = row.optLong("createdAt", now);
                long updatedAt = row.optLong("updatedAt", createdAt);
                String paymentKey = direction + ":" + paymentId;

                ContentValues values = new ContentValues();
                values.put("payment_key", paymentKey);
                values.put("payment_id", paymentId);
                values.put("direction", direction);
                values.put("state", state);
                values.put("created_at", createdAt);
                values.put("updated_at", updatedAt);
                values.put("payload", payload);
                if (database.insertWithOnConflict("payments", null, values, SQLiteDatabase.CONFLICT_REPLACE) == -1) throw new IllegalStateException("Payment insert failed at index " + i);

                // Payment row + signing-bundle state + audit event commit together.
                persistSigningForPayment(database, row, paymentId, now);
            }
            database.setTransactionSuccessful();
            JSObject result = new JSObject();
            result.put("count", payments.length());
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to persist Blee payment journal atomically: " + message(error));
        } finally {
            if (database != null && database.inTransaction()) database.endTransaction();
        }
    }

    @PluginMethod
    public void appendPaymentEvent(PluginCall call) {
        try {
            String eventId = require(call, "eventId");
            String paymentId = require(call, "paymentId");
            String eventType = require(call, "eventType");
            String payload = call.getString("payload", "{}");
            Long eventAt = call.getLong("eventAt");
            String sourceDevice = call.getString("sourceDevice", null);

            ContentValues values = new ContentValues();
            values.put("event_id", eventId);
            values.put("payment_id", paymentId);
            values.put("event_type", eventType);
            values.put("event_at", eventAt != null ? eventAt : System.currentTimeMillis());
            values.put("source_device", sourceDevice);
            values.put("payload", payload);
            db().insertWithOnConflict("payment_events", null, values, SQLiteDatabase.CONFLICT_IGNORE);
            call.resolve();
        } catch (Throwable error) {
            call.reject("Unable to append payment event: " + message(error));
        }
    }

    @PluginMethod
    public void loadPaymentEvents(PluginCall call) {
        try {
            String paymentId = call.getString("paymentId", null);
            JSArray events = new JSArray();
            String selection = paymentId == null ? null : "payment_id = ?";
            String[] args = paymentId == null ? null : new String[] { paymentId };
            try (Cursor cursor = db().query("payment_events", new String[] { "event_id","payment_id","event_type","event_at","source_device","payload" }, selection, args, null, null, "event_at ASC")) {
                while (cursor.moveToNext()) {
                    JSObject event = new JSObject();
                    event.put("eventId", cursor.getString(0));
                    event.put("paymentId", cursor.getString(1));
                    event.put("eventType", cursor.getString(2));
                    event.put("eventAt", cursor.getLong(3));
                    event.put("sourceDevice", cursor.isNull(4) ? null : cursor.getString(4));
                    event.put("payload", cursor.getString(5));
                    events.put(event);
                }
            }
            JSObject result = new JSObject();
            result.put("events", events);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to load payment events: " + message(error));
        }
    }

    @PluginMethod
    public void getValue(PluginCall call) {
        String key = call.getString("key");
        if (key == null || key.isEmpty()) { call.reject("Missing key"); return; }
        try {
            JSObject result = new JSObject();
            try (Cursor cursor = db().query("kv", new String[] { "value" }, "key = ?", new String[] { key }, null, null, null)) {
                if (cursor.moveToFirst()) result.put("value", cursor.getString(0));
            }
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to read Blee state: " + message(error));
        }
    }

    @PluginMethod
    public void setValue(PluginCall call) {
        String key = call.getString("key");
        String value = call.getString("value");
        if (key == null || key.isEmpty() || value == null) { call.reject("Missing key/value"); return; }
        try {
            ContentValues values = new ContentValues();
            values.put("key", key);
            values.put("value", value);
            values.put("updated_at", System.currentTimeMillis());
            if (db().insertWithOnConflict("kv", null, values, SQLiteDatabase.CONFLICT_REPLACE) == -1) throw new IllegalStateException("State write failed");
            call.resolve();
        } catch (Throwable error) {
            call.reject("Unable to persist Blee state: " + message(error));
        }
    }

    @PluginMethod
    public void removeValue(PluginCall call) {
        String key = call.getString("key");
        if (key == null || key.isEmpty()) { call.reject("Missing key"); return; }
        try { db().delete("kv", "key = ?", new String[] { key }); call.resolve(); }
        catch (Throwable error) { call.reject("Unable to remove Blee state: " + message(error)); }
    }

    private final class BleeDb extends SQLiteOpenHelper {
        BleeDb() { super(BleeStorePlugin.this.getContext().getApplicationContext(), DB_NAME, null, DB_VERSION); }
        @Override public void onConfigure(SQLiteDatabase db) { super.onConfigure(db); db.setForeignKeyConstraintsEnabled(false); }
        @Override public void onCreate(SQLiteDatabase db) { ensureSchema(db); }
        @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) { ensureSchema(db); }
        @Override public void onOpen(SQLiteDatabase db) { super.onOpen(db); ensureSchema(db); }
    }
}
