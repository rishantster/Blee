package com.blee.payments;

import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

/**
 * Versioned profile metadata exchanged only after the BLE wallet identity
 * handshake has established the peer wallet for the current GATT connection.
 *
 * The 20-byte wallet characteristic remains the stable discovery anchor. This
 * profile is deliberately small and contains display metadata only; payment
 * authorization and financial state never depend on it.
 */
final class BleePeerProfile {
    static final int VERSION = 1;
    static final int MAX_BYTES = 1024;
    static final int MAX_DISPLAY_NAME = 64;

    final String wallet;
    final String displayName;
    final String fingerprint;

    private BleePeerProfile(String wallet, String displayName, String fingerprint) {
        this.wallet = wallet;
        this.displayName = displayName;
        this.fingerprint = fingerprint;
    }

    static BleePeerProfile local(BleeMeshDb db) {
        if (db == null) return null;
        String wallet = normalizeWallet(db.activeWallet());
        if (wallet == null) return null;
        String name = cleanName(db.localDisplayName());
        return new BleePeerProfile(wallet, name, fingerprint(wallet, name));
    }

    byte[] encode() {
        try {
            JSONObject json = new JSONObject();
            json.put("kind", "blee_peer_profile");
            json.put("version", VERSION);
            json.put("wallet", wallet);
            if (!displayName.isEmpty()) json.put("displayName", displayName);
            json.put("fingerprint", fingerprint);
            byte[] bytes = json.toString().getBytes(StandardCharsets.UTF_8);
            return bytes.length <= MAX_BYTES ? bytes : new byte[0];
        } catch (Throwable ignored) {
            return new byte[0];
        }
    }

    /**
     * Parse a profile and bind it to the wallet already learned from the
     * dedicated 20-byte BLE identity characteristic. A profile that claims a
     * different wallet is rejected instead of being allowed to rename a peer.
     */
    static BleePeerProfile decodeBound(byte[] bytes, String expectedWallet) {
        if (bytes == null || bytes.length == 0 || bytes.length > MAX_BYTES) return null;
        String expected = normalizeWallet(expectedWallet);
        if (expected == null) return null;
        try {
            JSONObject json = new JSONObject(new String(bytes, StandardCharsets.UTF_8));
            if (!"blee_peer_profile".equals(json.optString("kind", ""))) return null;
            if (json.optInt("version", 0) != VERSION) return null;
            String wallet = normalizeWallet(json.optString("wallet", ""));
            if (wallet == null || !expected.equals(wallet)) return null;
            String name = cleanName(json.optString("displayName", ""));
            String claimed = json.optString("fingerprint", "").trim().toLowerCase(Locale.ROOT);
            String actual = fingerprint(wallet, name);
            if (!claimed.isEmpty() && !actual.equals(claimed)) return null;
            return new BleePeerProfile(wallet, name, actual);
        } catch (Throwable ignored) {
            return null;
        }
    }

    private static String normalizeWallet(String value) {
        if (value == null) return null;
        String wallet = value.trim().toLowerCase(Locale.ROOT);
        return wallet.matches("^0x[0-9a-f]{40}$") ? wallet : null;
    }

    private static String cleanName(String value) {
        if (value == null) return "";
        String name = value.trim().replaceAll("[\\p{Cntrl}&&[^\\n\\t]]", "");
        if (name.length() > MAX_DISPLAY_NAME) name = name.substring(0, MAX_DISPLAY_NAME);
        return name;
    }

    private static String fingerprint(String wallet, String displayName) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest((VERSION + "|" + wallet + "|" + displayName).getBytes(StandardCharsets.UTF_8));
            StringBuilder out = new StringBuilder();
            for (byte b : hash) out.append(String.format(Locale.ROOT, "%02x", b & 0xff));
            return out.toString();
        } catch (Throwable ignored) {
            return Integer.toHexString((VERSION + "|" + wallet + "|" + displayName).hashCode());
        }
    }
}
