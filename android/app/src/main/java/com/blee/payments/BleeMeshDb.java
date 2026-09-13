package com.blee.payments;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;

import org.json.JSONObject;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

final class BleeMeshDb {
    private final Context context;
    private SQLiteDatabase database;

    BleeMeshDb(Context context) {
        this.context = context.getApplicationContext();
    }

    synchronized SQLiteDatabase db() {
        if (database == null || !database.isOpen()) {
            File file = context.getDatabasePath("blee.db");
            File parent = file.getParentFile();
            if (parent != null) parent.mkdirs();
            database = SQLiteDatabase.openOrCreateDatabase(file, null);
            database.enableWriteAheadLogging();
            ensureSchema(database);
        }
        return database;
    }

    synchronized void close() {
        if (database != null) database.close();
        database = null;
    }

    private static void ensureSchema(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE IF NOT EXISTS payments (payment_key TEXT PRIMARY KEY NOT NULL,payment_id TEXT NOT NULL,direction TEXT NOT NULL,state TEXT NOT NULL,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,payload TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY NOT NULL,value TEXT NOT NULL,updated_at INTEGER NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS payment_events (event_id TEXT PRIMARY KEY NOT NULL,payment_id TEXT NOT NULL,event_type TEXT NOT NULL,event_at INTEGER NOT NULL,source_device TEXT,payload TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS mesh_inbox (message_id TEXT PRIMARY KEY NOT NULL,packet_type TEXT NOT NULL,payment_id TEXT,received_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,hop_count INTEGER NOT NULL,packet TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS mesh_outbox (message_id TEXT PRIMARY KEY NOT NULL,packet_type TEXT NOT NULL,payment_id TEXT,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,hop_count INTEGER NOT NULL,hop_limit INTEGER NOT NULL,copy_budget INTEGER NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,next_attempt_at INTEGER NOT NULL,packet TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS mesh_seen_packets (message_id TEXT PRIMARY KEY NOT NULL,seen_at INTEGER NOT NULL,expires_at INTEGER NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS mesh_peer_deliveries (message_id TEXT NOT NULL,peer_address TEXT NOT NULL,delivered_at INTEGER NOT NULL,PRIMARY KEY(message_id,peer_address))");
        db.execSQL("CREATE TABLE IF NOT EXISTS courier_envelopes (message_id TEXT PRIMARY KEY NOT NULL,payment_id TEXT,destination_wallet TEXT,received_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,hop_count INTEGER NOT NULL,packet TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS settlement_jobs (payment_id TEXT PRIMARY KEY NOT NULL,state TEXT NOT NULL,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,next_attempt_at INTEGER NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT,authorization TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS settlement_receipts (payment_id TEXT PRIMARY KEY NOT NULL,tx_hash TEXT NOT NULL,chain_id INTEGER,block_number TEXT,reported_at INTEGER NOT NULL,verified_at INTEGER,receipt TEXT NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS peer_identities (wallet_address TEXT PRIMARY KEY NOT NULL,display_name TEXT,avatar TEXT,device_id TEXT,updated_at INTEGER NOT NULL,payload TEXT NOT NULL)");
        // BLEE_LOCAL_CONTACTS_V1
        db.execSQL("CREATE TABLE IF NOT EXISTS contacts (wallet_address TEXT PRIMARY KEY NOT NULL,display_name TEXT NOT NULL,avatar TEXT,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,last_interacted_at INTEGER NOT NULL DEFAULT 0)");
        db.execSQL("CREATE INDEX IF NOT EXISTS contacts_updated_idx ON contacts(updated_at DESC)");
        db.execSQL("CREATE INDEX IF NOT EXISTS payments_created_idx ON payments(created_at DESC)");
        db.execSQL("CREATE INDEX IF NOT EXISTS payment_events_payment_idx ON payment_events(payment_id,event_at ASC)");
        db.execSQL("CREATE INDEX IF NOT EXISTS mesh_outbox_due_idx ON mesh_outbox(next_attempt_at,expires_at)");
        db.execSQL("CREATE INDEX IF NOT EXISTS mesh_seen_expiry_idx ON mesh_seen_packets(expires_at)");
        db.execSQL("CREATE INDEX IF NOT EXISTS settlement_jobs_due_idx ON settlement_jobs(state,next_attempt_at)");
    }

    // BLEE_ACTIVE_WALLET_RESOLUTION_V4
    synchronized String activeWallet() {
        for (String key : new String[] {
            "wallet.vault.v2", "wallet.vault.v1", "blee.wallet.v2",
            "blee.wallet.v1", "wallet", "vault", "account"
        }) {
            String address = walletAddressFromStoredValue(getKv(key));
            if (address != null) return address;
        }

        try (Cursor c = db().rawQuery(
            "SELECT key,value FROM kv WHERE lower(key) LIKE '%vault%' OR lower(key) LIKE '%wallet%' OR lower(key) LIKE '%account%' ORDER BY updated_at DESC LIMIT 64",
            null
        )) {
            while (c.moveToNext()) {
                String address = walletAddressFromStoredValue(c.getString(1));
                if (address != null) return address;
            }
        } catch (Throwable ignored) {}
        return null;
    }

    private static String walletAddressFromStoredValue(String raw) {
        if (raw == null) return null;
        String value = raw.trim();
        if (value.matches("^0x[0-9a-fA-F]{40}$")) return value.toLowerCase(Locale.ROOT);
        if (value.length() < 2 || value.length() > 65536) return null;
        try {
            JSONObject object = new JSONObject(value);
            String direct = object.optString("address", "").trim();
            if (direct.matches("^0x[0-9a-fA-F]{40}$")) return direct.toLowerCase(Locale.ROOT);
            for (String key : new String[] { "account", "wallet", "vault", "identity" }) {
                JSONObject nested = object.optJSONObject(key);
                if (nested == null) continue;
                String address = nested.optString("address", "").trim();
                if (address.matches("^0x[0-9a-fA-F]{40}$")) return address.toLowerCase(Locale.ROOT);
            }
        } catch (Throwable ignored) {}
        return null;
    }

    synchronized String localDisplayName() {
        String wallet = activeWallet();
        if (wallet != null) {
            try (Cursor c = db().query(
                "peer_identities", new String[] { "display_name" },
                "wallet_address=?", new String[] { wallet }, null, null, null, "1"
            )) {
                if (c.moveToFirst()) {
                    String candidate = cleanDisplayName(c.getString(0));
                    if (candidate != null) return candidate;
                }
            } catch (Throwable ignored) {}
        }

        String[] preferred = new String[] {
            "profile.alias", "profile.displayName", "wallet.alias", "blee.alias",
            "displayName", "alias", "profile.name"
        };
        for (String key : preferred) {
            String candidate = cleanDisplayName(getKv(key));
            if (candidate != null) return candidate;
        }

        try (Cursor c = db().rawQuery(
            "SELECT key,value FROM kv WHERE lower(key) LIKE '%alias%' OR lower(key) LIKE '%display%' OR lower(key) LIKE '%profile%' ORDER BY updated_at DESC LIMIT 16",
            null
        )) {
            while (c.moveToNext()) {
                String key = c.getString(0) == null ? "" : c.getString(0).toLowerCase(Locale.ROOT);
                if (key.contains("photo") || key.contains("avatar") || key.contains("vault") || key.contains("key")) continue;
                String candidate = cleanDisplayName(c.getString(1));
                if (candidate != null) return candidate;
            }
        } catch (Throwable ignored) {}
        return null;
    }

    private static String cleanDisplayName(String raw) {
        if (raw == null) return null;
        String value = raw.trim();
        if (value.isEmpty() || value.length() > 512 || value.startsWith("data:")) return null;
        try {
            JSONObject object = new JSONObject(value);
            for (String key : new String[] { "alias", "displayName", "name" }) {
                String candidate = object.optString(key, "").trim();
                if (!candidate.isEmpty() && candidate.length() <= 64) return candidate;
            }
        } catch (Throwable ignored) {}
        if (value.startsWith("\"") && value.endsWith("\"") && value.length() >= 2) {
            value = value.substring(1, value.length() - 1).trim();
        }
        if (value.isEmpty() || value.length() > 64 || value.startsWith("{") || value.startsWith("[")) return null;
        return value;
    }

    // BLEE_PRODUCTION_PROFILE_IDENTITY_V1
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

    // BLEE_PEER_IDENTITY_MERGE_V1
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
            // BLEE_CONTACT_ALIAS_PRECEDENCE_V1
            JSONObject localContact = contact(normalized);
            if (localContact != null) {
                String localName = localContact.optString("displayName", "").trim();
                String localAvatar = localContact.optString("avatar", "").trim();
                if (!localName.isEmpty()) cleanName = localName;
                String savedAvatar = cleanAvatar(localAvatar);
                if (savedAvatar != null) cleanAvatarValue = savedAvatar;
            }
            backfillPaymentIdentity(normalized, cleanName, cleanAvatarValue);
        } catch (Throwable ignored) {}
    }

    // BLEE_ACTIVITY_IDENTITY_BACKFILL_V2
    // Payment authorization/signature data is untouched. This only adds display
    // metadata to the local projection so Activity can immediately replace a raw
    // wallet label with the resolved peer name/avatar.
    private void backfillPaymentIdentity(String wallet, String displayName, String avatar) {
        if (wallet == null || wallet.isEmpty()) return;
        String normalized = wallet.toLowerCase(Locale.ROOT);
        List<String[]> updates = new ArrayList<String[]>();
        try (Cursor c = db().query(
            "payments", new String[] { "payment_key", "payload" },
            null, null, null, null, "updated_at DESC"
        )) {
            while (c.moveToNext()) {
                String key = c.getString(0);
                String raw = c.getString(1);
                try {
                    JSONObject payment = new JSONObject(raw);
                    if (!paymentReferencesWallet(payment, normalized)) continue;
                    boolean changed = false;
                    String cleanName = displayName == null ? "" : displayName.trim();
                    JSONObject auth = authorization(payment);
                    boolean peerIsSender = auth != null && normalized.equalsIgnoreCase(auth.optString("from", ""));
                    boolean peerIsReceiver = auth != null && normalized.equalsIgnoreCase(auth.optString("to", ""));

                    if (!cleanName.isEmpty()) {
                        if (!cleanName.equals(payment.optString("counterpartyName", ""))) { payment.put("counterpartyName", cleanName); changed = true; }
                        payment.put("peerName", cleanName);
                        payment.put("contactName", cleanName);
                        payment.put("displayName", cleanName);
                        if (peerIsSender) payment.put("senderName", cleanName);
                        if (peerIsReceiver) payment.put("receiverName", cleanName);
                    }
                    if (avatar != null && !avatar.isEmpty()) {
                        if (!avatar.equals(payment.optString("counterpartyAvatar", ""))) { payment.put("counterpartyAvatar", avatar); changed = true; }
                        payment.put("peerAvatar", avatar);
                        payment.put("contactAvatar", avatar);
                        payment.put("avatar", avatar);
                        if (peerIsSender) payment.put("senderAvatar", avatar);
                        if (peerIsReceiver) payment.put("receiverAvatar", avatar);
                    }
                    payment.put("counterpartyWallet", normalized);
                    JSONObject profile = payment.optJSONObject("counterpartyProfile");
                    if (profile == null) profile = new JSONObject();
                    profile.put("wallet", normalized);
                    if (!cleanName.isEmpty()) profile.put("displayName", cleanName);
                    if (avatar != null && !avatar.isEmpty()) profile.put("avatar", avatar);
                    payment.put("counterpartyProfile", profile);
                    if (changed) updates.add(new String[] { key, payment.toString() });
                } catch (Throwable ignored) {}
            }
        } catch (Throwable ignored) {}
        for (String[] update : updates) {
            ContentValues values = new ContentValues();
            values.put("payload", update[1]);
            values.put("updated_at", System.currentTimeMillis());
            db().update("payments", values, "payment_key=?", new String[] { update[0] });
        }
    }

    private static boolean paymentReferencesWallet(JSONObject payment, String wallet) {
        if (payment == null || wallet == null) return false;
        for (String key : new String[] { "sender", "receiver", "from", "to", "counterparty", "counterpartyWallet", "senderWallet", "receiverWallet", "recipient" }) {
            if (wallet.equalsIgnoreCase(payment.optString(key, ""))) return true;
        }
        JSONObject auth = authorization(payment);
        if (auth != null) {
            if (wallet.equalsIgnoreCase(auth.optString("from", ""))) return true;
            if (wallet.equalsIgnoreCase(auth.optString("to", ""))) return true;
        }
        return false;
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
    }

    // BLEE_LOCAL_CONTACTS_V1
    synchronized JSONObject saveContact(String wallet, String displayName, String avatar) {
        if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) return null;
        String normalized = wallet.toLowerCase(Locale.ROOT);
        String own = activeWallet();
        if (own != null && own.equalsIgnoreCase(normalized)) return null;

        String name = displayName == null ? "" : displayName.trim();
        String photo = cleanAvatar(avatar);
        long createdAt = System.currentTimeMillis();
        long lastInteractedAt = 0L;

        try (Cursor c = db().query(
            "contacts", new String[] { "display_name", "avatar", "created_at", "last_interacted_at" },
            "wallet_address=?", new String[] { normalized }, null, null, null, "1"
        )) {
            if (c.moveToFirst()) {
                if (name.isEmpty()) name = c.isNull(0) ? "" : c.getString(0);
                if (photo == null) photo = cleanAvatar(c.isNull(1) ? null : c.getString(1));
                createdAt = c.getLong(2);
                lastInteractedAt = c.getLong(3);
            }
        } catch (Throwable ignored) {}

        JSONObject known = peerIdentity(normalized);
        if (known != null) {
            if (name.isEmpty()) name = known.optString("displayName", "").trim();
            if (photo == null) photo = cleanAvatar(known.optString("avatar", ""));
        }
        if (name.length() > 64) name = name.substring(0, 64);
        if (name.isEmpty()) name = normalized.substring(0, 6) + "…" + normalized.substring(normalized.length() - 4);

        long now = System.currentTimeMillis();
        ContentValues cv = new ContentValues();
        cv.put("wallet_address", normalized);
        cv.put("display_name", name);
        if (photo != null) cv.put("avatar", photo); else cv.putNull("avatar");
        cv.put("created_at", createdAt);
        cv.put("updated_at", now);
        cv.put("last_interacted_at", lastInteractedAt);
        db().insertWithOnConflict("contacts", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
        // BLEE_CONTACT_ACTIVITY_SYNC_V1
        // A locally chosen contact name/avatar is display metadata only. Reuse
        // the existing Activity backfill path; signed payment authorization is
        // never modified.
        backfillPaymentIdentity(normalized, name, photo);
        return contact(normalized);
    }

    synchronized boolean deleteContact(String wallet) {
        if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) return false;
        return db().delete("contacts", "wallet_address=?", new String[] { wallet.toLowerCase(Locale.ROOT) }) > 0;
    }

    synchronized JSONObject contact(String wallet) {
        if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) return null;
        String normalized = wallet.toLowerCase(Locale.ROOT);
        try (Cursor c = db().query(
            "contacts", new String[] { "display_name", "avatar", "created_at", "updated_at", "last_interacted_at" },
            "wallet_address=?", new String[] { normalized }, null, null, null, "1"
        )) {
            if (!c.moveToFirst()) return null;
            JSONObject out = new JSONObject();
            out.put("wallet", normalized);
            out.put("displayName", c.isNull(0) ? "" : c.getString(0));
            if (!c.isNull(1)) out.put("avatar", c.getString(1));
            out.put("createdAt", c.getLong(2));
            out.put("updatedAt", c.getLong(3));
            out.put("lastInteractedAt", c.getLong(4));
            out.put("saved", true);
            return out;
        } catch (Throwable ignored) {
            return null;
        }
    }

    synchronized List<JSONObject> listContacts() {
        List<JSONObject> rows = new ArrayList<JSONObject>();
        try (Cursor c = db().query(
            "contacts", new String[] { "wallet_address", "display_name", "avatar", "created_at", "updated_at", "last_interacted_at" },
            null, null, null, null, "display_name COLLATE NOCASE ASC, updated_at DESC"
        )) {
            while (c.moveToNext()) {
                JSONObject out = new JSONObject();
                out.put("wallet", c.getString(0));
                out.put("displayName", c.getString(1));
                if (!c.isNull(2)) out.put("avatar", c.getString(2));
                out.put("createdAt", c.getLong(3));
                out.put("updatedAt", c.getLong(4));
                out.put("lastInteractedAt", c.getLong(5));
                out.put("saved", true);
                rows.add(out);
            }
        } catch (Throwable ignored) {}
        return rows;
    }

    private static JSONObject candidateByWallet(List<JSONObject> rows, String wallet) {
        if (wallet == null) return null;
        for (JSONObject row : rows) {
            if (wallet.equalsIgnoreCase(row.optString("wallet", ""))) return row;
        }
        return null;
    }

    private void mergeContactCandidate(List<JSONObject> rows, String wallet, String displayName, String avatar, long interactedAt) {
        if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) return;
        String normalized = wallet.toLowerCase(Locale.ROOT);
        String own = activeWallet();
        if (own != null && own.equalsIgnoreCase(normalized)) return;
        try {
            JSONObject row = candidateByWallet(rows, normalized);
            if (row == null) {
                row = new JSONObject();
                row.put("wallet", normalized);
                rows.add(row);
            }
            String name = displayName == null ? "" : displayName.trim();
            if (!name.isEmpty() && row.optString("displayName", "").isEmpty()) row.put("displayName", name);
            String photo = cleanAvatar(avatar);
            if (photo != null && row.optString("avatar", "").isEmpty()) row.put("avatar", photo);
            if (interactedAt > row.optLong("lastInteractedAt", 0L)) row.put("lastInteractedAt", interactedAt);
            row.put("saved", contact(normalized) != null);
        } catch (Throwable ignored) {}
    }

    synchronized List<JSONObject> contactCandidates() {
        List<JSONObject> rows = new ArrayList<JSONObject>();
        try (Cursor c = db().query(
            "peer_identities", new String[] { "wallet_address", "display_name", "avatar", "updated_at" },
            null, null, null, null, "updated_at DESC"
        )) {
            while (c.moveToNext()) {
                mergeContactCandidate(
                    rows,
                    c.getString(0),
                    c.isNull(1) ? "" : c.getString(1),
                    c.isNull(2) ? null : c.getString(2),
                    c.getLong(3)
                );
            }
        } catch (Throwable ignored) {}

        try (Cursor c = db().query(
            "payments", new String[] { "payload", "updated_at" },
            null, null, null, null, "updated_at DESC"
        )) {
            while (c.moveToNext()) {
                try {
                    JSONObject payment = new JSONObject(c.getString(0));
                    long at = c.getLong(1);
                    String own = activeWallet();
                    JSONObject auth = authorization(payment);
                    String[] wallets = new String[] {
                        payment.optString("counterpartyWallet", ""),
                        payment.optString("counterparty", ""),
                        payment.optString("sender", ""),
                        payment.optString("receiver", ""),
                        payment.optString("from", ""),
                        payment.optString("to", ""),
                        auth == null ? "" : auth.optString("from", ""),
                        auth == null ? "" : auth.optString("to", "")
                    };
                    for (String wallet : wallets) {
                        if (wallet == null || !wallet.matches("^0x[0-9a-fA-F]{40}$")) continue;
                        if (own != null && own.equalsIgnoreCase(wallet)) continue;
                        String name = firstNonEmpty(
                            payment.optString("counterpartyName", ""),
                            payment.optString("peerName", ""),
                            payment.optString("contactName", ""),
                            payment.optString("senderName", ""),
                            payment.optString("receiverName", "")
                        );
                        String photo = firstNonEmpty(
                            payment.optString("counterpartyAvatar", ""),
                            payment.optString("peerAvatar", ""),
                            payment.optString("contactAvatar", ""),
                            payment.optString("senderAvatar", ""),
                            payment.optString("receiverAvatar", "")
                        );
                        mergeContactCandidate(rows, wallet, name, photo, at);
                    }
                } catch (Throwable ignored) {}
            }
        } catch (Throwable ignored) {}

        // Saved contacts always remain available even if their last payment has
        // aged out of the visible activity projection.
        for (JSONObject saved : listContacts()) {
            mergeContactCandidate(
                rows,
                saved.optString("wallet", ""),
                saved.optString("displayName", ""),
                saved.optString("avatar", ""),
                saved.optLong("lastInteractedAt", saved.optLong("updatedAt", 0L))
            );
        }

        // Small lists are expected; insertion sort avoids extra comparator/imports.
        for (int i = 1; i < rows.size(); i++) {
            JSONObject key = rows.get(i);
            long keyAt = key.optLong("lastInteractedAt", 0L);
            int j = i - 1;
            while (j >= 0 && rows.get(j).optLong("lastInteractedAt", 0L) < keyAt) {
                rows.set(j + 1, rows.get(j));
                j--;
            }
            rows.set(j + 1, key);
        }
        return rows;
    }

    synchronized String getKv(String key) {
        try (Cursor c = db().query("kv", new String[] { "value" }, "key=?", new String[] { key }, null, null, null)) {
            return c.moveToFirst() ? c.getString(0) : null;
        }
    }

    synchronized void setKv(String key, String value) {
        ContentValues cv = new ContentValues();
        cv.put("key", key);
        cv.put("value", value);
        cv.put("updated_at", System.currentTimeMillis());
        db().insertWithOnConflict("kv", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
    }

    synchronized void bootstrapOutgoing(String deviceId, String publicKey) {
        long now = System.currentTimeMillis();
        cleanup(now);
        try (Cursor c = db().query("payments", new String[] { "payment_id","state","payload" }, "direction=?", new String[] { "outgoing" }, null, null, "created_at ASC")) {
            while (c.moveToNext()) {
                String paymentId = c.getString(0);
                String state = c.getString(1);
                if (isFinalState(state)) continue;

                JSONObject payment;
                try { payment = new JSONObject(c.getString(2)); }
                catch (Throwable ignored) { continue; }

                JSONObject auth = authorization(payment);
                if (auth == null || auth.optString("signature", "").isEmpty()) continue;

                long expiry = authorizationExpiry(auth, now + 24L * 60L * 60L * 1000L);
                String messageId = "pay:" + paymentId;
                if (outboxExists(messageId)) continue;

                String destination = firstNonEmpty(
                    payment.optString("receiver", ""),
                    payment.optString("to", ""),
                    auth.optString("to", "")
                ).toLowerCase(Locale.ROOT);
                if (destination.isEmpty()) continue;

                // BLEE_ATOMIC_OUTBOX_V1
                SQLiteDatabase database = db();
                boolean ownTransaction = !database.inTransaction();
                if (ownTransaction) database.beginTransaction();
                try {
                    JSONObject packet = packet(
                        "PAYMENT_ENVELOPE", messageId, paymentId, destination,
                        payment.toString(), now, expiry, 0, 6, 3, deviceId, publicKey
                    );
                    enqueue(packet);
                    addEvent(paymentId, "QUEUED", now, deviceId, packet.toString());
                    upsertSettlementJob(paymentId, auth.toString(), now);
                    if (ownTransaction) database.setTransactionSuccessful();
                } catch (Throwable ignored) {
                } finally {
                    if (ownTransaction && database.inTransaction()) database.endTransaction();
                }
            }
        }
    }

    synchronized List<String> duePackets(long now, int limit) {
        List<String> rows = new ArrayList<>();
        try (Cursor c = db().query(
            "mesh_outbox",
            new String[] { "packet" },
            "expires_at>? AND next_attempt_at<=? AND copy_budget>0",
            new String[] { String.valueOf(now), String.valueOf(now) },
            null, null, "created_at ASC", String.valueOf(limit)
        )) {
            while (c.moveToNext()) rows.add(c.getString(0));
        }
        return rows;
    }

    synchronized List<String> duePacketsForPeer(long now, String peerAddress, int limit) {
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

    synchronized void recordAttempt(String messageId) {
        long now = System.currentTimeMillis();
        int attempts = 0;
        try (Cursor c = db().query("mesh_outbox", new String[] { "attempts" }, "message_id=?", new String[] { messageId }, null, null, null)) {
            if (c.moveToFirst()) attempts = c.getInt(0);
        }
        attempts += 1;
        long delay = Math.min(60_000L, (1L << Math.min(attempts, 6)) * 1000L);
        ContentValues cv = new ContentValues();
        cv.put("attempts", attempts);
        cv.put("next_attempt_at", now + delay);
        db().update("mesh_outbox", cv, "message_id=?", new String[] { messageId });
    }

    /**
     * Accept transport-level packets only. PAYMENT_ENVELOPE is never promoted
     * into the financial ledger here; the Capacitor/viem layer verifies the
     * EIP-712/EIP-3009 authorization first and then calls acceptVerifiedEnvelope().
     */
    synchronized ProcessResult receive(String raw, String localDeviceId, String localPublicKey) {
        long now = System.currentTimeMillis();
        try {
            JSONObject packet = new JSONObject(raw);
            if (packet.optInt("version", 0) != 2) return ProcessResult.reject();
            String messageId = packet.optString("messageId", "");
            String type = packet.optString("type", "");
            String paymentId = packet.optString("paymentId", "");
            long expiresAt = packet.optLong("expiresAt", 0L);
            int hopCount = packet.optInt("hopCount", 0);
            int hopLimit = packet.optInt("hopLimit", 6);
            int copyBudget = packet.optInt("copyBudget", 3);
            if (messageId.isEmpty() || type.isEmpty() || expiresAt <= now || hopCount > hopLimit) return ProcessResult.reject();
            if (!verifyPacket(packet)) return ProcessResult.reject();
            if (hasSeen(messageId)) return ProcessResult.duplicate();

            ContentValues seen = new ContentValues();
            seen.put("message_id", messageId);
            seen.put("seen_at", now);
            seen.put("expires_at", expiresAt);
            db().insertWithOnConflict("mesh_seen_packets", null, seen, SQLiteDatabase.CONFLICT_IGNORE);

            ContentValues inbox = new ContentValues();
            inbox.put("message_id", messageId);
            inbox.put("packet_type", type);
            inbox.put("payment_id", paymentId);
            inbox.put("received_at", now);
            inbox.put("expires_at", expiresAt);
            inbox.put("hop_count", hopCount);
            inbox.put("packet", raw);
            db().insertWithOnConflict("mesh_inbox", null, inbox, SQLiteDatabase.CONFLICT_IGNORE);

            String destination = packet.optString("destinationWallet", "").toLowerCase(Locale.ROOT);
            String wallet = activeWallet();
            boolean forUs = wallet != null && !destination.isEmpty() && wallet.equals(destination);
            boolean changed = false;
            String notifyTitle = null;
            String notifyBody = null;

            if ("PAYMENT_ENVELOPE".equals(type) && forUs) {
                // Transport receipt becomes a durable, explicitly non-spendable
                // recipient projection. Cryptographic acceptance remains owned by
                // the local viem verifier via acceptVerifiedEnvelope().
                changed = persistVerificationPending(packet, now) || changed;
            } else if ("DELIVERY_ACK".equals(type) && forUs) {
                changed = updatePaymentState(
                    paymentId, "outgoing", "acknowledged", "RECIPIENT_ACKNOWLEDGED",
                    now, packet.optString("originDeviceId", null), raw
                );
                // BLEE_ACK_NON_DESTRUCTIVE_V1: ACK updates UX only; settlement durability remains intact.
                notifyTitle = "Payment delivered";
                notifyBody = "A nearby Blee device acknowledged durable receipt.";
            } else if ("SETTLEMENT_RECEIPT".equals(type)) {
                JSONObject receipt = new JSONObject(packet.optString("payload", "{}"));
                String txHash = receipt.optString("txHash", "");
                String expectedHash = expectedSettlementHash(paymentId);
                if (!paymentId.isEmpty() && !txHash.isEmpty() && !expectedHash.isEmpty() && expectedHash.equalsIgnoreCase(txHash)) {
                    persistSettlementReceipt(paymentId, receipt, now);
                    changed = updateAnyPaymentState(
                        paymentId, "settled_relay_reported", "SETTLED_RELAY_REPORTED",
                        now, packet.optString("originDeviceId", null), receipt.toString()
                    );
                    // Relay report is non-final: keep PAYMENT_ENVELOPE until CHAIN_CONFIRMED.
                    notifyTitle = "Settlement reported";
                    notifyBody = "A Blee relay reported settlement. This phone will independently verify it when online.";
                }
            }

            // Payment envelopes continue beyond the recipient so that a third
            // online Blee node can become a settlement relay. Settlement receipts
            // are gossip events and likewise continue through the mesh.
            boolean relayEvent = "PAYMENT_ENVELOPE".equals(type) || "SETTLEMENT_RECEIPT".equals(type);
            boolean shouldForward = copyBudget > 1 && hopCount < hopLimit && (relayEvent || !forUs);
            if (shouldForward) {
                JSONObject forwarded = new JSONObject(raw);
                forwarded.put("hopCount", hopCount + 1);
                forwarded.put("copyBudget", copyBudget - 1);
                String forwardedRaw = forwarded.toString();

                ContentValues courier = new ContentValues();
                courier.put("message_id", messageId);
                courier.put("payment_id", paymentId);
                courier.put("destination_wallet", destination);
                courier.put("received_at", now);
                courier.put("expires_at", expiresAt);
                courier.put("hop_count", hopCount + 1);
                courier.put("packet", forwardedRaw);
                db().insertWithOnConflict("courier_envelopes", null, courier, SQLiteDatabase.CONFLICT_IGNORE);
                enqueueRaw(forwardedRaw, type, paymentId, expiresAt, hopCount + 1, hopLimit, copyBudget - 1);
            }

            return new ProcessResult(true, false, changed, paymentId, type, notifyTitle, notifyBody);
        } catch (Throwable ignored) {
            return ProcessResult.reject();
        }
    }

    private boolean persistVerificationPending(JSONObject packet, long now) {
        try {
            JSONObject payment = new JSONObject(packet.optString("payload", "{}"));
            JSONObject auth = authorization(payment);
            String paymentId = firstNonEmpty(payment.optString("id", ""), packet.optString("paymentId", ""));
            String wallet = activeWallet();
            if (paymentId.isEmpty() || auth == null || wallet == null) return false;
            if (!wallet.equalsIgnoreCase(auth.optString("to", ""))) return false;

            String key = "incoming:" + paymentId;
            String priorState = paymentState(key);
            if (priorState != null && !priorState.toLowerCase(Locale.ROOT).contains("verification_pending")) return false;

            long createdAt = payment.optLong("createdAt", packet.optLong("createdAt", now));
            payment.put("id", paymentId);
            payment.put("direction", "incoming");
            payment.put("state", "verification_pending");
            payment.put("route", "ble-mesh");
            payment.put("createdAt", createdAt);
            payment.put("updatedAt", now);
            payment.put("durablyReceivedAt", now);

            String sender = extractSender(payment);
            if (!sender.isEmpty()) {
                payment.put("counterparty", sender);
                payment.put("counterpartyWallet", sender);
                JSONObject known = peerIdentity(sender);
                if (known != null) {
                    String name = known.optString("displayName", "").trim();
                    String avatar = known.optString("avatar", "").trim();
                    if (!name.isEmpty()) {
                        payment.put("counterpartyName", name);
                        payment.put("senderName", name);
                    }
                    if (!avatar.isEmpty()) {
                        payment.put("counterpartyAvatar", avatar);
                        payment.put("senderAvatar", avatar);
                    }
                }
            }

            ContentValues values = new ContentValues();
            values.put("payment_key", key);
            values.put("payment_id", paymentId);
            values.put("direction", "incoming");
            values.put("state", "verification_pending");
            values.put("created_at", createdAt);
            values.put("updated_at", now);
            values.put("payload", payment.toString());
            db().insertWithOnConflict("payments", null, values, SQLiteDatabase.CONFLICT_REPLACE);
            if (priorState == null) {
                addEvent(paymentId, "RECIPIENT_ENVELOPE_STORED", now, packet.optString("originDeviceId", null), packet.toString());
            }
            return priorState == null;
        } catch (Throwable ignored) {
            return false;
        }
    }

    private String paymentState(String key) {
        try (Cursor c = db().query("payments", new String[] { "state" }, "payment_key=?", new String[] { key }, null, null, null, "1")) {
            return c.moveToFirst() ? c.getString(0) : null;
        } catch (Throwable ignored) {
            return null;
        }
    }

    private boolean recipientNeedsVerification(String paymentId) {
        String state = paymentState("incoming:" + paymentId);
        return state == null || state.toLowerCase(Locale.ROOT).contains("verification_pending");
    }

    synchronized boolean rejectPendingEnvelope(String messageId, String reason) {
        long now = System.currentTimeMillis();
        String raw = null;
        try (Cursor c = db().query(
            "mesh_inbox", new String[] { "packet" },
            "message_id=? AND packet_type=?", new String[] { messageId, "PAYMENT_ENVELOPE" },
            null, null, null, "1"
        )) {
            if (c.moveToFirst()) raw = c.getString(0);
        }
        if (raw == null) return false;

        try {
            JSONObject packet = new JSONObject(raw);
            JSONObject payment = new JSONObject(packet.optString("payload", "{}"));
            String paymentId = firstNonEmpty(payment.optString("id", ""), packet.optString("paymentId", ""));
            if (!paymentId.isEmpty()) {
                String key = "incoming:" + paymentId;
                String state = paymentState(key);
                if (state != null && state.toLowerCase(Locale.ROOT).contains("verification_pending")) {
                    payment.put("id", paymentId);
                    payment.put("direction", "incoming");
                    payment.put("state", "verification_failed");
                    payment.put("error", reason == null || reason.trim().isEmpty()
                        ? "Payment authorization could not be verified" : reason.trim());
                    payment.put("updatedAt", now);
                    ContentValues values = new ContentValues();
                    values.put("state", "verification_failed");
                    values.put("updated_at", now);
                    values.put("payload", payment.toString());
                    db().update("payments", values, "payment_key=?", new String[] { key });
                    addEvent(paymentId, "RECIPIENT_VERIFICATION_FAILED", now, packet.optString("originDeviceId", null), payment.toString());
                }
            }
            // Do not continue gossiping something this phone proved invalid.
            db().delete("mesh_inbox", "message_id=?", new String[] { messageId });
            db().delete("mesh_outbox", "message_id=?", new String[] { messageId });
            db().delete("courier_envelopes", "message_id=?", new String[] { messageId });
            return true;
        } catch (Throwable ignored) {
            return false;
        }
    }

    synchronized List<String> pendingEnvelopes() {
        List<String> rows = new ArrayList<>();
        String wallet = activeWallet();
        if (wallet == null) return rows;
        long now = System.currentTimeMillis();
        try (Cursor c = db().query(
            "mesh_inbox",
            new String[] { "message_id","payment_id","packet" },
            "packet_type=? AND expires_at>?",
            new String[] { "PAYMENT_ENVELOPE", String.valueOf(now) },
            null, null, "received_at ASC"
        )) {
            while (c.moveToNext()) {
                String paymentId = c.getString(1);
                if (!recipientNeedsVerification(paymentId)) continue;
                String raw = c.getString(2);
                try {
                    JSONObject packet = new JSONObject(raw);
                    if (wallet.equals(packet.optString("destinationWallet", "").toLowerCase(Locale.ROOT))) rows.add(raw);
                } catch (Throwable ignored) {}
            }
        }
        return rows;
    }

    /** Called only after the local viem layer has verified EIP-3009 typed data. */
    synchronized AcceptedPayment acceptVerifiedEnvelope(String messageId, String localDeviceId, String localPublicKey) {
        long now = System.currentTimeMillis();
        String raw = null;
        try (Cursor c = db().query("mesh_inbox", new String[] { "packet" }, "message_id=? AND packet_type=?", new String[] { messageId, "PAYMENT_ENVELOPE" }, null, null, null)) {
            if (c.moveToFirst()) raw = c.getString(0);
        }
        if (raw == null) return AcceptedPayment.reject();

        try {
            JSONObject packet = new JSONObject(raw);
            if (!verifyPacket(packet) || packet.optLong("expiresAt", 0) <= now) return AcceptedPayment.reject();
            String wallet = activeWallet();
            String destination = packet.optString("destinationWallet", "").toLowerCase(Locale.ROOT);
            if (wallet == null || !wallet.equals(destination)) return AcceptedPayment.reject();

            JSONObject payment = new JSONObject(packet.optString("payload", "{}"));
            JSONObject auth = authorization(payment);
            String paymentId = firstNonEmpty(payment.optString("id", ""), packet.optString("paymentId", ""));
            if (paymentId.isEmpty() || auth == null) return AcceptedPayment.reject();
            if (!wallet.equals(auth.optString("to", "").toLowerCase(Locale.ROOT))) return AcceptedPayment.reject();

            String senderWalletForNotification = extractSender(payment);
            String priorState = paymentState("incoming:" + paymentId);
            if (priorState != null && isFinalState(priorState) && !priorState.toLowerCase(Locale.ROOT).contains("chain_confirmed")) {
                return AcceptedPayment.reject();
            }
            final boolean newlyAccepted = priorState == null || priorState.toLowerCase(Locale.ROOT).contains("verification_pending");

            // BLEE_ATOMIC_RECIPIENT_ACK_V1
            SQLiteDatabase database = db();
            boolean ownTransaction = !database.inTransaction();
            if (ownTransaction) database.beginTransaction();
            try {
                if (newlyAccepted) {
                    payment.put("direction", "incoming");
                    payment.put("state", "delivered_offline");
                    payment.put("updatedAt", now);
                    if (!payment.has("createdAt")) payment.put("createdAt", packet.optLong("createdAt", now));

                    ContentValues pv = new ContentValues();
                    pv.put("payment_key", "incoming:" + paymentId);
                    pv.put("payment_id", paymentId);
                    pv.put("direction", "incoming");
                    pv.put("state", "delivered_offline");
                    pv.put("created_at", payment.optLong("createdAt", now));
                    pv.put("updated_at", now);
                    pv.put("payload", payment.toString());
                    if (database.insertWithOnConflict("payments", null, pv, SQLiteDatabase.CONFLICT_REPLACE) == -1) throw new IllegalStateException("Incoming payment persistence failed");
                    addEvent(paymentId, "RECIPIENT_RECEIVED", now, packet.optString("originDeviceId", null), raw);
                }

                String senderWallet = extractSender(payment);
                if (!senderWallet.isEmpty()) {
                    JSONObject ackPayload = new JSONObject();
                    ackPayload.put("paymentId", paymentId);
                    ackPayload.put("receivedAt", now);
                    ackPayload.put("recipientWallet", wallet);
                    String ackId = "ack:" + paymentId + ":" + wallet;
                    JSONObject ack = packet(
                        "DELIVERY_ACK", ackId, paymentId, senderWallet,
                        ackPayload.toString(), now, packet.optLong("expiresAt", now + 3600000L),
                        0, 6, 3, localDeviceId, localPublicKey
                    );
                    enqueue(ack);
                }
                if (ownTransaction) database.setTransactionSuccessful();
            } finally {
                if (ownTransaction && database.inTransaction()) database.endTransaction();
            }
            return new AcceptedPayment(
                true,
                paymentId,
                newlyAccepted,
                paymentDisplayAmount(payment),
                firstNonEmpty(payment.optString("senderName", ""), peerDisplayLabel(senderWalletForNotification))
            );
        } catch (Throwable ignored) {
            return AcceptedPayment.reject();
        }
    }

    synchronized List<String> settlementCandidates(long now, int limit) {
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

    synchronized void recordSettlementReceipt(JSONObject sourcePacket, JSONObject receipt, String deviceId, String publicKey) {
        try {
            long now = System.currentTimeMillis();
            String paymentId = sourcePacket.optString("paymentId", "");
            String txHash = receipt.optString("txHash", "");
            if (paymentId.isEmpty() || txHash.isEmpty()) return;
            String expectedHash = expectedSettlementHash(paymentId);
            if (expectedHash.isEmpty() || !expectedHash.equalsIgnoreCase(txHash)) return;
            receipt.put("paymentId", paymentId);
            persistSettlementReceipt(paymentId, receipt, now);
            updateAnyPaymentState(paymentId, "settled_relay_reported", "SETTLED_RELAY_REPORTED", now, deviceId, receipt.toString());
            // Local relay report is non-final: keep PAYMENT_ENVELOPE until CHAIN_CONFIRMED.

            JSONObject packet = packet(
                "SETTLEMENT_RECEIPT", "settle:" + paymentId + ":" + txHash, paymentId, "",
                receipt.toString(), now, sourcePacket.optLong("expiresAt", now + 3600000L),
                0, 6, 3, deviceId, publicKey
            );
            enqueue(packet);
        } catch (Throwable ignored) {}
    }

    // BLEE_CANONICAL_SETTLEMENT_VERIFY_V1
    synchronized List<String> unverifiedSettlementReceipts(int limit) {
        List<String> rows = new ArrayList<>();
        try (Cursor c = db().query(
            "settlement_receipts",
            new String[] { "payment_id","tx_hash","receipt" },
            "verified_at IS NULL",
            null, null, null, "reported_at ASC", String.valueOf(Math.max(1, limit))
        )) {
            while (c.moveToNext()) {
                JSONObject item = new JSONObject();
                item.put("paymentId", c.getString(0));
                item.put("txHash", c.getString(1));
                item.put("reportedReceipt", c.getString(2));
                rows.add(item.toString());
            }
        } catch (Throwable ignored) {}
        return rows;
    }

    synchronized boolean markChainConfirmed(String paymentId, String txHash, JSONObject canonicalReceipt, long now) {
        if (paymentId == null || paymentId.isEmpty() || txHash == null || txHash.isEmpty()) return false;
        String expectedHash = expectedSettlementHash(paymentId);
        if (expectedHash.isEmpty() || !expectedHash.equalsIgnoreCase(txHash)) return false;
        if (!"0x1".equalsIgnoreCase(canonicalReceipt.optString("status", ""))) return false;

        ContentValues verified = new ContentValues();
        verified.put("verified_at", now);
        verified.put("receipt", canonicalReceipt.toString());
        db().update("settlement_receipts", verified, "payment_id=? AND tx_hash=?", new String[] { paymentId, txHash });

        boolean changed = updateAnyPaymentState(
            paymentId, "chain_confirmed", "CHAIN_CONFIRMED", now,
            deviceSource(canonicalReceipt), canonicalReceipt.toString()
        );
        db().delete("mesh_outbox", "payment_id=? AND packet_type=?", new String[] { paymentId, "PAYMENT_ENVELOPE" });
        ContentValues job = new ContentValues();
        job.put("state", "CONFIRMED");
        job.put("updated_at", now);
        job.putNull("last_error");
        db().update("settlement_jobs", job, "payment_id=?", new String[] { paymentId });
        return changed;
    }

    private static String deviceSource(JSONObject payload) {
        String value = payload.optString("verifiedBy", "");
        return value.isEmpty() ? null : value;
    }

    private String expectedSettlementHash(String paymentId) {
        if (paymentId == null || paymentId.isEmpty()) return "";
        // Prefer the durable local payment projection.
        try (Cursor c = db().query("payments", new String[] { "payload" }, "payment_id=?", new String[] { paymentId }, null, null, "updated_at DESC", "1")) {
            if (c.moveToFirst()) {
                String hash = settlementHashFromPayment(new JSONObject(c.getString(0)));
                if (!hash.isEmpty()) return hash;
            }
        } catch (Throwable ignored) {}

        // Courier nodes may not own the payment, but they have the signed source
        // envelope in mesh_inbox. This is enough to pin the only acceptable hash.
        try (Cursor c = db().query("mesh_inbox", new String[] { "packet" }, "payment_id=? AND packet_type=?", new String[] { paymentId, "PAYMENT_ENVELOPE" }, null, null, "received_at DESC", "1")) {
            if (c.moveToFirst()) {
                JSONObject packet = new JSONObject(c.getString(0));
                JSONObject payment = new JSONObject(packet.optString("payload", "{}"));
                return settlementHashFromPayment(payment);
            }
        } catch (Throwable ignored) {}
        return "";
    }

    private static String settlementHashFromPayment(JSONObject payment) {
        try {
            JSONObject auth = authorization(payment);
            if (auth == null) return "";
            JSONObject broadcast = auth.optJSONObject("broadcast");
            if (broadcast == null || !"SENDER_FUNDED_RAW_TX".equals(broadcast.optString("mode", ""))) return "";
            String hash = broadcast.optString("txHash", "");
            return hash.matches("^0x[0-9a-fA-F]{64}$") ? hash : "";
        } catch (Throwable ignored) {
            return "";
        }
    }

    synchronized void markSettlementAttempt(String paymentId, boolean success, String error) {
        long now = System.currentTimeMillis();
        ContentValues cv = new ContentValues();
        cv.put("updated_at", now);
        if (success) {
            cv.put("state", "REPORTED");
            cv.putNull("last_error");
        } else {
            int attempts = 0;
            try (Cursor c = db().query("settlement_jobs", new String[] { "attempts" }, "payment_id=?", new String[] { paymentId }, null, null, null)) {
                if (c.moveToFirst()) attempts = c.getInt(0);
            }
            attempts += 1;
            cv.put("attempts", attempts);
            cv.put("state", "PENDING");
            cv.put("last_error", error);
            cv.put("next_attempt_at", now + Math.min(120_000L, (1L << Math.min(attempts, 7)) * 1000L));
        }
        db().update("settlement_jobs", cv, "payment_id=?", new String[] { paymentId });
    }

    private void upsertSettlementJob(String paymentId, String authorizationJson, long now) {
        ContentValues job = new ContentValues();
        job.put("payment_id", paymentId);
        job.put("state", "PENDING");
        job.put("created_at", now);
        job.put("updated_at", now);
        job.put("next_attempt_at", now);
        job.put("attempts", 0);
        job.put("authorization", authorizationJson);
        db().insertWithOnConflict("settlement_jobs", null, job, SQLiteDatabase.CONFLICT_IGNORE);
    }

    private void persistSettlementReceipt(String paymentId, JSONObject receipt, long now) {
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

    private boolean outboxExists(String id) {
        try (Cursor c = db().rawQuery("SELECT 1 FROM mesh_outbox WHERE message_id=? LIMIT 1", new String[] { id })) {
            return c.moveToFirst();
        }
    }

    private boolean paymentExists(String key) {
        try (Cursor c = db().rawQuery("SELECT 1 FROM payments WHERE payment_key=? LIMIT 1", new String[] { key })) {
            return c.moveToFirst();
        }
    }

    private boolean hasSeen(String id) {
        try (Cursor c = db().rawQuery("SELECT 1 FROM mesh_seen_packets WHERE message_id=? LIMIT 1", new String[] { id })) {
            return c.moveToFirst();
        }
    }

    private void enqueue(JSONObject packet) {
        enqueueRaw(
            packet.toString(), packet.optString("type", ""), packet.optString("paymentId", ""),
            packet.optLong("expiresAt", System.currentTimeMillis() + 3600000L),
            packet.optInt("hopCount", 0), packet.optInt("hopLimit", 6), packet.optInt("copyBudget", 3)
        );
    }

    private void enqueueRaw(String raw, String type, String paymentId, long expiresAt, int hopCount, int hopLimit, int copyBudget) {
        try {
            JSONObject packet = new JSONObject(raw);
            String id = packet.optString("messageId", "");
            if (id.isEmpty() || copyBudget <= 0) return;
            ContentValues cv = new ContentValues();
            cv.put("message_id", id);
            cv.put("packet_type", type);
            cv.put("payment_id", paymentId);
            cv.put("created_at", packet.optLong("createdAt", System.currentTimeMillis()));
            cv.put("expires_at", expiresAt);
            cv.put("hop_count", hopCount);
            cv.put("hop_limit", hopLimit);
            cv.put("copy_budget", copyBudget);
            cv.put("attempts", 0);
            cv.put("next_attempt_at", System.currentTimeMillis());
            cv.put("packet", raw);
            db().insertWithOnConflict("mesh_outbox", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
        } catch (Throwable ignored) {}
    }

    private JSONObject packet(
        String type, String messageId, String paymentId, String destination, String payload,
        long createdAt, long expiresAt, int hopCount, int hopLimit, int copyBudget,
        String deviceId, String publicKey
    ) throws Exception {
        JSONObject packet = new JSONObject();
        packet.put("version", 2);
        packet.put("messageId", messageId);
        packet.put("eventId", UUID.randomUUID().toString());
        packet.put("paymentId", paymentId);
        packet.put("type", type);
        packet.put("originDeviceId", deviceId);
        packet.put("destinationWallet", destination == null ? "" : destination.toLowerCase(Locale.ROOT));
        packet.put("createdAt", createdAt);
        packet.put("expiresAt", expiresAt);
        packet.put("hopCount", hopCount);
        packet.put("hopLimit", hopLimit);
        packet.put("copyBudget", copyBudget);
        packet.put("payloadHash", sha256(payload));
        packet.put("payload", payload);
        packet.put("devicePublicKey", publicKey);
        packet.put("deviceSignature", BleeDeviceIdentity.sign(signingString(packet)));
        return packet;
    }

    private boolean verifyPacket(JSONObject packet) {
        try {
            String payload = packet.optString("payload", "");
            if (!sha256(payload).equals(packet.optString("payloadHash", ""))) return false;
            return BleeDeviceIdentity.verify(
                packet.optString("devicePublicKey", ""),
                signingString(packet),
                packet.optString("deviceSignature", "")
            );
        } catch (Throwable ignored) {
            return false;
        }
    }

    // hopCount/copyBudget are mutable routing metadata. Financial payload,
    // destination, expiry and hop limit remain origin-signed.
    private static String signingString(JSONObject p) {
        return p.optInt("version", 0) + "|"
            + p.optString("messageId", "") + "|"
            + p.optString("paymentId", "") + "|"
            + p.optString("type", "") + "|"
            + p.optString("originDeviceId", "") + "|"
            + p.optString("destinationWallet", "") + "|"
            + p.optLong("createdAt", 0L) + "|"
            + p.optLong("expiresAt", 0L) + "|"
            + p.optInt("hopLimit", 0) + "|"
            + p.optString("payloadHash", "");
    }

    // BLEE_MESH_STATE_MACHINE_HARDENING_V2
    private static int paymentStateRank(String state) {
        String s = state == null ? "" : state.trim().toLowerCase(Locale.ROOT);
        if (s.contains("chain_confirmed") || (s.contains("chain") && s.contains("confirm"))) return 100;
        if (s.contains("revert")) return 95;
        if (s.contains("expired") || s.contains("fail") || s.contains("cancel")) return 90;
        if (s.contains("settled_relay_reported")) return 80;
        if (s.contains("settlement_submitted") || s.contains("submitted")) return 70;
        if (s.contains("acknowledged") || s.contains("acknowledge")) return 60;
        if (s.contains("delivered_offline") || s.contains("delivered")) return 50;
        if (s.contains("verification_pending") || s.contains("verification-pending")) return 45;
        if (s.contains("queued")) return 40;
        if (s.contains("signed")) return 30;
        if (s.contains("created")) return 20;
        return 10;
    }

    private boolean updateAnyPaymentState(String paymentId, String state, String eventType, long at, String sourceDevice, String eventPayload) {
        boolean a = updatePaymentState(paymentId, "incoming", state, eventType, at, sourceDevice, eventPayload);
        boolean b = updatePaymentState(paymentId, "outgoing", state, eventType, at, sourceDevice, eventPayload);
        return a || b;
    }

    private boolean updatePaymentState(String paymentId, String direction, String state, String eventType, long at, String sourceDevice, String eventPayload) {
        String key = direction + ":" + paymentId;
        try (Cursor c = db().query("payments", new String[] { "payload","state" }, "payment_key=?", new String[] { key }, null, null, null)) {
            if (!c.moveToFirst()) return false;
            String currentState = c.getString(1);
            int currentRank = paymentStateRank(currentState);
            int nextRank = paymentStateRank(state);
            if (currentRank > nextRank || (currentRank == nextRank && state.equalsIgnoreCase(currentState))) return false;
            JSONObject payment = new JSONObject(c.getString(0));
            payment.put("state", state);
            payment.put("updatedAt", at);
            ContentValues cv = new ContentValues();
            cv.put("state", state);
            cv.put("updated_at", at);
            cv.put("payload", payment.toString());
            db().update("payments", cv, "payment_key=?", new String[] { key });
            addEvent(paymentId, eventType, at, sourceDevice, eventPayload);
            return true;
        } catch (Throwable ignored) {
            return false;
        }
    }

    private void addEvent(String paymentId, String type, long at, String sourceDevice, String payload) {
        String safePayload = payload == null ? "{}" : payload;
        ContentValues cv = new ContentValues();
        cv.put("event_id", type + ":" + paymentId + ":" + at + ":" + sha256(safePayload).substring(0, 12));
        cv.put("payment_id", paymentId);
        cv.put("event_type", type);
        cv.put("event_at", at);
        cv.put("source_device", sourceDevice);
        cv.put("payload", safePayload);
        db().insertWithOnConflict("payment_events", null, cv, SQLiteDatabase.CONFLICT_IGNORE);
    }

    private void cleanup(long now) {
        db().delete("mesh_seen_packets", "expires_at<?", new String[] { String.valueOf(now) });
        db().execSQL("DELETE FROM mesh_peer_deliveries WHERE message_id NOT IN (SELECT message_id FROM mesh_outbox)");
        db().delete("mesh_outbox", "expires_at<?", new String[] { String.valueOf(now) });
        db().delete("courier_envelopes", "expires_at<?", new String[] { String.valueOf(now) });
    }

    private String peerDisplayLabel(String wallet) {
        if (wallet == null || wallet.isEmpty()) return "";
        try (Cursor c = db().query(
            "peer_identities", new String[] { "display_name" },
            "wallet_address=?", new String[] { wallet.toLowerCase(Locale.ROOT) }, null, null, null
        )) {
            if (c.moveToFirst()) {
                String value = c.getString(0);
                if (value != null && !value.trim().isEmpty()) return value.trim();
            }
        } catch (Throwable ignored) {}
        return shortWallet(wallet);
    }

    private static String paymentDisplayAmount(JSONObject payment) {
        if (payment == null) return "";
        for (String key : new String[] { "amount", "displayAmount", "tokenAmount" }) {
            String value = payment.optString(key, "").trim();
            if (!value.isEmpty()) return normalizeAmount(value);
        }
        JSONObject auth = authorization(payment);
        String raw = auth == null ? "" : auth.optString("value", "").trim();
        if (raw.isEmpty()) return "";
        try {
            return new BigDecimal(raw)
                .movePointLeft(6)
                .setScale(6, RoundingMode.DOWN)
                .stripTrailingZeros()
                .toPlainString();
        } catch (Throwable ignored) { return ""; }
    }

    private static String normalizeAmount(String raw) {
        try { return new BigDecimal(raw).stripTrailingZeros().toPlainString(); }
        catch (Throwable ignored) { return raw; }
    }

    private static String shortWallet(String wallet) {
        if (wallet == null) return "";
        String value = wallet.trim();
        if (value.length() <= 12) return value;
        return value.substring(0, 6) + "…" + value.substring(value.length() - 4);
    }

    private static JSONObject authorization(JSONObject payment) {
        JSONObject auth = payment.optJSONObject("authorization");
        if (auth == null) auth = payment.optJSONObject("auth");
        return auth;
    }

    private static long authorizationExpiry(JSONObject auth, long fallback) {
        try {
            String raw = auth.optString("validBefore", "");
            if (raw.isEmpty()) return fallback;
            return Long.parseLong(raw) * 1000L;
        } catch (Throwable ignored) {
            return fallback;
        }
    }

    private static String extractSender(JSONObject payment) {
        JSONObject auth = authorization(payment);
        return firstNonEmpty(
            payment.optString("sender", ""),
            payment.optString("from", ""),
            auth == null ? "" : auth.optString("from", "")
        ).toLowerCase(Locale.ROOT);
    }

    private static boolean isFinalState(String state) {
        String s = state == null ? "" : state.toLowerCase(Locale.ROOT);
        // Relay-reported settlement is intentionally NOT final. Only canonical
        // chain confirmation or terminal failure/expiry stops settlement work.
        return s.contains("chain_confirmed")
            || (s.contains("chain") && s.contains("confirm"))
            || s.contains("expired")
            || s.contains("fail")
            || s.contains("revert")
            || s.contains("cancel");
    }

    private static String firstNonEmpty(String... values) {
        for (String value : values) {
            if (value != null && !value.trim().isEmpty()) return value.trim();
        }
        return "";
    }

    private static String sha256(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest((value == null ? "" : value).getBytes(StandardCharsets.UTF_8));
            StringBuilder out = new StringBuilder();
            for (byte b : bytes) out.append(String.format(Locale.ROOT, "%02x", b));
            return out.toString();
        } catch (Throwable ignored) {
            return "0000000000000000000000000000000000000000000000000000000000000000";
        }
    }

    static final class AcceptedPayment {
        final boolean accepted;
        final String paymentId;
        final boolean newlyAccepted;
        final String amount;
        final String counterparty;
        AcceptedPayment(boolean accepted, String paymentId, boolean newlyAccepted, String amount, String counterparty) {
            this.accepted = accepted;
            this.paymentId = paymentId;
            this.newlyAccepted = newlyAccepted;
            this.amount = amount == null ? "" : amount;
            this.counterparty = counterparty == null ? "" : counterparty;
        }
        static AcceptedPayment reject() { return new AcceptedPayment(false, "", false, "", ""); }
    }

    static final class ProcessResult {
        final boolean accepted;
        final boolean duplicate;
        final boolean ledgerChanged;
        final String paymentId;
        final String type;
        final String notificationTitle;
        final String notificationBody;

        ProcessResult(boolean accepted, boolean duplicate, boolean ledgerChanged, String paymentId, String type, String notificationTitle, String notificationBody) {
            this.accepted = accepted;
            this.duplicate = duplicate;
            this.ledgerChanged = ledgerChanged;
            this.paymentId = paymentId;
            this.type = type;
            this.notificationTitle = notificationTitle;
            this.notificationBody = notificationBody;
        }

        static ProcessResult reject() { return new ProcessResult(false, false, false, "", "", null, null); }
        static ProcessResult duplicate() { return new ProcessResult(true, true, false, "", "", null, null); }
    }
}
