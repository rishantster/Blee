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
    private static final int DB_VERSION = 1;
    private static final String STORE_MARKER = "BLEE_STORE_SAFE_V2";

    private BleeDb helper;

    @Override
    public void load() {
        // Deliberately do not open SQLite during Capacitor plugin registration.
        // The database is opened lazily by init(), where errors can be returned to JS
        // with their real cause instead of making plugin loading fail generically.
        helper = new BleeDb();
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
        if (helper == null) helper = new BleeDb();
        SQLiteDatabase database = helper.getWritableDatabase();
        ensureSchema(database);
        return database;
    }

    private static void ensureSchema(SQLiteDatabase db) {
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS payments (" +
            "payment_key TEXT PRIMARY KEY NOT NULL," +
            "payment_id TEXT NOT NULL," +
            "direction TEXT NOT NULL," +
            "state TEXT NOT NULL," +
            "created_at INTEGER NOT NULL," +
            "updated_at INTEGER NOT NULL," +
            "payload TEXT NOT NULL)"
        );
        db.execSQL(
            "CREATE TABLE IF NOT EXISTS kv (" +
            "key TEXT PRIMARY KEY NOT NULL," +
            "value TEXT NOT NULL," +
            "updated_at INTEGER NOT NULL)"
        );
        db.execSQL("CREATE INDEX IF NOT EXISTS payments_created_idx ON payments(created_at DESC)");
        db.execSQL("CREATE INDEX IF NOT EXISTS payments_state_idx ON payments(state)");
    }

    private static String message(Throwable error) {
        String detail = error.getMessage();
        if (detail == null || detail.trim().isEmpty()) detail = "no detail";
        return error.getClass().getSimpleName() + ": " + detail;
    }

    @PluginMethod
    public void init(PluginCall call) {
        try {
            SQLiteDatabase database = db();

            // Real read/write smoke test. This catches open/schema issues immediately.
            ContentValues probe = new ContentValues();
            probe.put("key", "__blee_store_probe__");
            probe.put("value", STORE_MARKER);
            probe.put("updated_at", System.currentTimeMillis());
            long inserted = database.insertWithOnConflict("kv", null, probe, SQLiteDatabase.CONFLICT_REPLACE);
            if (inserted == -1) throw new IllegalStateException("SQLite write probe failed");

            try (Cursor cursor = database.query(
                "kv",
                new String[] { "value" },
                "key = ?",
                new String[] { "__blee_store_probe__" },
                null,
                null,
                null
            )) {
                if (!cursor.moveToFirst() || !STORE_MARKER.equals(cursor.getString(0))) {
                    throw new IllegalStateException("SQLite read probe failed");
                }
            }
            database.delete("kv", "key = ?", new String[] { "__blee_store_probe__" });

            String journalMode = "unknown";
            try (Cursor cursor = database.rawQuery("PRAGMA journal_mode", null)) {
                if (cursor.moveToFirst()) journalMode = cursor.getString(0);
            } catch (Throwable ignored) {
                // Journal mode is diagnostic only; it must never block payment storage.
            }

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
            SQLiteDatabase database = db();
            JSArray payments = new JSArray();
            try (Cursor cursor = database.query(
                "payments",
                new String[] { "payload" },
                null,
                null,
                null,
                null,
                "created_at DESC, updated_at DESC"
            )) {
                while (cursor.moveToNext()) {
                    String payload = cursor.getString(0);
                    if (payload != null) payments.put(payload);
                }
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
        if (payments == null) {
            call.reject("Missing payments");
            return;
        }

        SQLiteDatabase database = null;
        try {
            database = db();
            database.beginTransaction();
            database.delete("payments", null, null);

            long now = System.currentTimeMillis();
            for (int i = 0; i < payments.length(); i++) {
                String payload = payments.optString(i, null);
                if (payload == null || payload.isEmpty()) {
                    throw new IllegalArgumentException("Invalid payment row at index " + i);
                }

                JSONObject row = new JSONObject(payload);
                String paymentId = row.optString("id", "");
                String direction = row.optString("direction", "");
                String state = row.optString("state", "");
                if (paymentId.isEmpty() || direction.isEmpty() || state.isEmpty()) {
                    throw new IllegalArgumentException("Invalid payment row at index " + i);
                }

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

                long inserted = database.insertWithOnConflict(
                    "payments",
                    null,
                    values,
                    SQLiteDatabase.CONFLICT_REPLACE
                );
                if (inserted == -1) throw new IllegalStateException("Payment insert failed at index " + i);
            }

            database.setTransactionSuccessful();
            JSObject result = new JSObject();
            result.put("count", payments.length());
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to persist Blee payment journal: " + message(error));
        } finally {
            if (database != null && database.inTransaction()) {
                database.endTransaction();
            }
        }
    }

    @PluginMethod
    public void getValue(PluginCall call) {
        String key = call.getString("key");
        if (key == null || key.isEmpty()) {
            call.reject("Missing key");
            return;
        }
        try {
            SQLiteDatabase database = db();
            JSObject result = new JSObject();
            try (Cursor cursor = database.query(
                "kv",
                new String[] { "value" },
                "key = ?",
                new String[] { key },
                null,
                null,
                null
            )) {
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
        if (key == null || key.isEmpty() || value == null) {
            call.reject("Missing key/value");
            return;
        }
        try {
            ContentValues values = new ContentValues();
            values.put("key", key);
            values.put("value", value);
            values.put("updated_at", System.currentTimeMillis());
            long inserted = db().insertWithOnConflict("kv", null, values, SQLiteDatabase.CONFLICT_REPLACE);
            if (inserted == -1) throw new IllegalStateException("State write failed");
            call.resolve();
        } catch (Throwable error) {
            call.reject("Unable to persist Blee state: " + message(error));
        }
    }

    @PluginMethod
    public void removeValue(PluginCall call) {
        String key = call.getString("key");
        if (key == null || key.isEmpty()) {
            call.reject("Missing key");
            return;
        }
        try {
            db().delete("kv", "key = ?", new String[] { key });
            call.resolve();
        } catch (Throwable error) {
            call.reject("Unable to remove Blee state: " + message(error));
        }
    }

    private final class BleeDb extends SQLiteOpenHelper {
        BleeDb() {
            super(BleeStorePlugin.this.getContext().getApplicationContext(), DB_NAME, null, DB_VERSION);
        }

        @Override
        public void onCreate(SQLiteDatabase db) {
            ensureSchema(db);
        }

        @Override
        public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
            // Schema is additive/idempotent for this release. Never drop payment data.
            ensureSchema(db);
        }

        @Override
        public void onOpen(SQLiteDatabase db) {
            super.onOpen(db);
            ensureSchema(db);
        }
    }
}
