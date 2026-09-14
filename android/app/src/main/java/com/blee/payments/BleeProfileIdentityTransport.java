package com.blee.payments;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;

import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Non-financial profile metadata carried over the same direct BLE packet pipe.
 *
 * This is deliberately separate from payment state. It never creates a payment,
 * settlement job, courier envelope or notification. Packets are device-signed,
 * direct-only (hopLimit=0), durable, and suppressed whenever financial mesh work
 * is pending so identity imagery can never delay a payment.
 */
final class BleeProfileIdentityTransport {
    static final String TYPE = "PROFILE_IDENTITY";
    private static final long PROFILE_TTL_MS = 24L * 60L * 60L * 1000L;
    private static final int PROFILE_COPY_BUDGET = 64;
    private static final int MAX_AVATAR_CHARS = 24_000;

    private BleeProfileIdentityTransport() {}

    static void syncLocalProfilePacket(Context context) {
        BleeMeshDb db = new BleeMeshDb(context);
        try {
            String wallet = db.activeWallet();
            if (!isWallet(wallet)) {
                clearProfileOutbox(db);
                return;
            }

            // Financial traffic owns the mesh. A profile transfer is removed and
            // recreated only after payment/receipt/ack work has cleared.
            if (hasFinancialOutbox(db)) {
                clearProfileOutbox(db);
                return;
            }

            String displayName = cleanName(db.localDisplayName());
            String avatar = cleanAvatar(db.localAvatar());
            long profileUpdatedAt = profileUpdatedAt(db);

            JSONObject payload = new JSONObject();
            payload.put("wallet", wallet.toLowerCase(Locale.ROOT));
            payload.put("displayName", displayName);
            payload.put("hasAvatar", avatar != null);
            if (avatar != null) payload.put("avatar", avatar);
            payload.put("updatedAt", profileUpdatedAt);

            String payloadRaw = payload.toString();
            String fingerprint = sha256(payloadRaw);
            String messageId = "profile:" + fingerprint.substring(0, 24);
            if (outboxExists(db, messageId)) return;

            clearProfileOutbox(db);

            long now = System.currentTimeMillis();
            long expiresAt = now + PROFILE_TTL_MS;
            JSONObject packet = new JSONObject();
            packet.put("version", 2);
            packet.put("messageId", messageId);
            packet.put("eventId", "profile-" + fingerprint.substring(24, 40));
            packet.put("paymentId", "");
            packet.put("type", TYPE);
            packet.put("originDeviceId", BleeDeviceIdentity.deviceId(context));
            packet.put("destinationWallet", "");
            packet.put("createdAt", now);
            packet.put("expiresAt", expiresAt);
            packet.put("hopCount", 0);
            packet.put("hopLimit", 0);
            packet.put("copyBudget", PROFILE_COPY_BUDGET);
            packet.put("payloadHash", sha256(payloadRaw));
            packet.put("payload", payloadRaw);
            packet.put("devicePublicKey", BleeDeviceIdentity.publicKey());
            packet.put("deviceSignature", BleeDeviceIdentity.sign(signingString(packet)));

            ContentValues cv = new ContentValues();
            cv.put("message_id", messageId);
            cv.put("packet_type", TYPE);
            cv.put("payment_id", "");
            cv.put("created_at", now);
            cv.put("expires_at", expiresAt);
            cv.put("hop_count", 0);
            cv.put("hop_limit", 0);
            cv.put("copy_budget", PROFILE_COPY_BUDGET);
            cv.put("attempts", 0);
            cv.put("next_attempt_at", now);
            cv.put("packet", packet.toString());
            db.db().insertWithOnConflict("mesh_outbox", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
        } catch (Throwable ignored) {
            // Profile imagery is best-effort and must never disturb payment mesh.
        } finally {
            db.close();
        }
    }

    /**
     * Consume direct-only profile packets already authenticated and accepted by
     * BleeMeshDb.receive(). Returns true when at least one peer identity changed.
     */
    static boolean processIncoming(Context context) {
        BleeMeshDb db = new BleeMeshDb(context);
        boolean changed = false;
        try {
            List<String[]> rows = new ArrayList<>();
            try (Cursor c = db.db().query(
                "mesh_inbox", new String[] { "message_id", "packet" },
                "packet_type=?", new String[] { TYPE }, null, null,
                "received_at ASC", "32"
            )) {
                while (c.moveToNext()) rows.add(new String[] { c.getString(0), c.getString(1) });
            }

            String ownWallet = db.activeWallet();
            for (String[] row : rows) {
                String messageId = row[0];
                String raw = row[1];
                try {
                    JSONObject packet = new JSONObject(raw);
                    if (!TYPE.equals(packet.optString("type", ""))
                        || packet.optInt("hopLimit", -1) != 0
                        || !verifyPacket(packet)) {
                        deleteInbox(db, messageId);
                        continue;
                    }

                    JSONObject profile = new JSONObject(packet.optString("payload", "{}"));
                    String wallet = profile.optString("wallet", "").trim().toLowerCase(Locale.ROOT);
                    if (!isWallet(wallet) || (ownWallet != null && ownWallet.equalsIgnoreCase(wallet))) {
                        deleteInbox(db, messageId);
                        continue;
                    }

                    String displayName = cleanName(profile.optString("displayName", ""));
                    boolean hasAvatar = profile.optBoolean("hasAvatar", profile.has("avatar"));
                    String avatar = hasAvatar ? cleanAvatar(profile.optString("avatar", "")) : null;
                    if (hasAvatar && avatar == null) {
                        deleteInbox(db, messageId);
                        continue;
                    }

                    JSONObject previous = db.peerIdentity(wallet);
                    String oldName = previous == null ? "" : previous.optString("displayName", "");
                    String oldAvatar = previous == null ? "" : previous.optString("avatar", "");

                    if (!hasAvatar) {
                        ContentValues clear = new ContentValues();
                        clear.putNull("avatar");
                        db.db().update("peer_identities", clear, "wallet_address=?", new String[] { wallet });
                    }
                    db.upsertPeerIdentity(
                        wallet,
                        displayName,
                        avatar,
                        packet.optString("originDeviceId", ""),
                        "native_ble_profile"
                    );

                    JSONObject current = db.peerIdentity(wallet);
                    String newName = current == null ? "" : current.optString("displayName", "");
                    String newAvatar = current == null ? "" : current.optString("avatar", "");
                    changed = changed || !oldName.equals(newName) || !oldAvatar.equals(newAvatar);
                    deleteInbox(db, messageId);
                } catch (Throwable ignored) {
                    deleteInbox(db, messageId);
                }
            }
        } catch (Throwable ignored) {
        } finally {
            db.close();
        }
        return changed;
    }

    static JSONObject enrichPeer(BleeMeshDb db, JSONObject source) {
        try {
            JSONObject out = new JSONObject(source.toString());
            String wallet = out.optString("wallet", "").trim().toLowerCase(Locale.ROOT);
            if (!isWallet(wallet)) return out;
            JSONObject identity = db.peerIdentity(wallet);
            if (identity == null) return out;

            String currentName = out.optString("displayName", "").trim();
            String storedName = cleanName(identity.optString("displayName", ""));
            if ((currentName.isEmpty() || currentName.startsWith("0x")) && !storedName.isEmpty()) {
                out.put("displayName", storedName);
            }
            String currentAvatar = cleanAvatar(out.optString("avatar", ""));
            String storedAvatar = cleanAvatar(identity.optString("avatar", ""));
            if (currentAvatar == null && storedAvatar != null) out.put("avatar", storedAvatar);
            if (storedAvatar == null && currentAvatar == null) out.put("avatar", "");
            return out;
        } catch (Throwable ignored) {
            return source;
        }
    }

    private static boolean hasFinancialOutbox(BleeMeshDb db) {
        try (Cursor c = db.db().rawQuery(
            "SELECT 1 FROM mesh_outbox WHERE packet_type<>? AND expires_at>? LIMIT 1",
            new String[] { TYPE, String.valueOf(System.currentTimeMillis()) }
        )) {
            return c.moveToFirst();
        } catch (Throwable ignored) {
            return true;
        }
    }

    private static boolean outboxExists(BleeMeshDb db, String messageId) {
        try (Cursor c = db.db().rawQuery(
            "SELECT 1 FROM mesh_outbox WHERE message_id=? LIMIT 1", new String[] { messageId }
        )) {
            return c.moveToFirst();
        } catch (Throwable ignored) {
            return false;
        }
    }

    private static void clearProfileOutbox(BleeMeshDb db) {
        try {
            db.db().execSQL(
                "DELETE FROM mesh_peer_deliveries WHERE message_id IN (SELECT message_id FROM mesh_outbox WHERE packet_type=?)",
                new Object[] { TYPE }
            );
            db.db().delete("mesh_outbox", "packet_type=?", new String[] { TYPE });
        } catch (Throwable ignored) {}
    }

    private static void deleteInbox(BleeMeshDb db, String messageId) {
        try { db.db().delete("mesh_inbox", "message_id=?", new String[] { messageId }); }
        catch (Throwable ignored) {}
    }

    private static long profileUpdatedAt(BleeMeshDb db) {
        try (Cursor c = db.db().rawQuery(
            "SELECT MAX(updated_at) FROM kv WHERE key IN ('profile.alias','profile.avatar')", null
        )) {
            if (c.moveToFirst() && !c.isNull(0)) return c.getLong(0);
        } catch (Throwable ignored) {}
        return 0L;
    }

    private static String cleanName(String value) {
        String name = value == null ? "" : value.trim().replaceAll("\\s+", " ");
        if (name.length() > 64) name = name.substring(0, 64);
        return name;
    }

    private static String cleanAvatar(String raw) {
        if (raw == null) return null;
        String value = raw.trim();
        if (value.isEmpty() || value.length() > MAX_AVATAR_CHARS) return null;
        if (!value.matches("^data:image/(?:png|jpe?g|webp);base64,[A-Za-z0-9+/=\\r\\n]+$")) return null;
        return value;
    }

    private static boolean isWallet(String wallet) {
        return wallet != null && wallet.matches("^0x[0-9a-fA-F]{40}$");
    }

    private static boolean verifyPacket(JSONObject packet) {
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
}
