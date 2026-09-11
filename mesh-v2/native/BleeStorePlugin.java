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

@CapacitorPlugin(name = "BleeStore")
public class BleeStorePlugin extends Plugin {
    private static final String DB_NAME = "blee.db";
    private static final int DB_VERSION = 4;
    private static final String STORE_MARKER = "BLEE_STORE_MESH_V2";

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

        db.execSQL("CREATE INDEX IF NOT EXISTS payments_created_idx ON payments(created_at DESC)");
        db.execSQL("CREATE INDEX IF NOT EXISTS payments_state_idx ON payments(state)");
        db.execSQL("CREATE INDEX IF NOT EXISTS payment_events_payment_idx ON payment_events(payment_id,event_at ASC)");
        db.execSQL("CREATE INDEX IF NOT EXISTS mesh_outbox_due_idx ON mesh_outbox(next_attempt_at,expires_at)");
        db.execSQL("CREATE INDEX IF NOT EXISTS mesh_seen_expiry_idx ON mesh_seen_packets(expires_at)");
        db.execSQL("CREATE INDEX IF NOT EXISTS settlement_jobs_due_idx ON settlement_jobs(state,next_attempt_at)");
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
            }
            database.setTransactionSuccessful();
            JSObject result = new JSObject();
            result.put("count", payments.length());
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to persist Blee payment journal: " + message(error));
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
