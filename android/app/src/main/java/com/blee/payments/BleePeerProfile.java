package com.blee.payments;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/**
 * Compact, versioned BLE profile metadata layered on top of the canonical
 * 20-byte wallet identity handshake.
 *
 * This payload is intentionally capped at 20 bytes so profile exchange remains
 * reliable even when Android falls back to the default ATT MTU. The wallet is
 * not duplicated in this characteristic: the profile is accepted only after a
 * wallet has already been learned on the same GATT connection, and is bound to
 * that wallet by decodeBound(). Financial authorization never depends on this
 * display metadata.
 */
final class BleePeerProfile {
    static final int VERSION = 1;
    static final int MAX_BYTES = 20;
    static final int HEADER_BYTES = 2;
    static final int MAX_NAME_BYTES = MAX_BYTES - HEADER_BYTES;

    final String wallet;
    final String displayName;

    private BleePeerProfile(String wallet, String displayName) {
        this.wallet = wallet;
        this.displayName = displayName;
    }

    static BleePeerProfile local(BleeMeshDb db) {
        if (db == null) return null;
        String wallet = normalizeWallet(db.activeWallet());
        if (wallet == null) return null;
        return new BleePeerProfile(wallet, fitUtf8(db.localDisplayName(), MAX_NAME_BYTES));
    }

    byte[] encode() {
        byte[] name = displayName.getBytes(StandardCharsets.UTF_8);
        if (name.length > MAX_NAME_BYTES) name = fitUtf8(displayName, MAX_NAME_BYTES).getBytes(StandardCharsets.UTF_8);
        byte[] out = new byte[HEADER_BYTES + name.length];
        out[0] = (byte) VERSION;
        out[1] = (byte) name.length;
        System.arraycopy(name, 0, out, HEADER_BYTES, name.length);
        return out;
    }

    /**
     * Bind profile metadata to the wallet already established by the dedicated
     * 20-byte identity characteristic on this GATT session.
     */
    static BleePeerProfile decodeBound(byte[] bytes, String expectedWallet) {
        String wallet = normalizeWallet(expectedWallet);
        if (wallet == null || bytes == null || bytes.length < HEADER_BYTES || bytes.length > MAX_BYTES) return null;
        int version = bytes[0] & 0xff;
        int length = bytes[1] & 0xff;
        if (version != VERSION || length < 0 || length > MAX_NAME_BYTES || HEADER_BYTES + length != bytes.length) return null;
        try {
            String name = new String(bytes, HEADER_BYTES, length, StandardCharsets.UTF_8).trim();
            if (name.indexOf('\uFFFD') >= 0) return null;
            return new BleePeerProfile(wallet, fitUtf8(name, MAX_NAME_BYTES));
        } catch (Throwable ignored) {
            return null;
        }
    }

    private static String normalizeWallet(String value) {
        if (value == null) return null;
        String wallet = value.trim().toLowerCase(Locale.ROOT);
        return wallet.matches("^0x[0-9a-f]{40}$") ? wallet : null;
    }

    private static String fitUtf8(String value, int maxBytes) {
        if (value == null || maxBytes <= 0) return "";
        String clean = value.trim().replaceAll("[\\p{Cntrl}]", "");
        ByteArrayOutputStream out = new ByteArrayOutputStream(maxBytes);
        for (int offset = 0; offset < clean.length();) {
            int codePoint = clean.codePointAt(offset);
            String piece = new String(Character.toChars(codePoint));
            byte[] encoded = piece.getBytes(StandardCharsets.UTF_8);
            if (out.size() + encoded.length > maxBytes) break;
            out.write(encoded, 0, encoded.length);
            offset += Character.charCount(codePoint);
        }
        return new String(out.toByteArray(), StandardCharsets.UTF_8).trim();
    }
}
