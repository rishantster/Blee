#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee relay ingress: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def main() -> None:
    path = locate("BleeMeshDb.java")
    text = path.read_text()
    marker = "BLEE_RELAY_INGRESS_GUARD_V1"
    if marker in text:
        return
    if "BLEE_RELAY_VALIDATION_GATE_V1" not in text:
        fail("relay validation gate must run first")

    start_old = '''    synchronized ProcessResult receive(String raw, String localDeviceId, String localPublicKey) {
        long now = System.currentTimeMillis();
        try {
            JSONObject packet = new JSONObject(raw);'''
    start_new = '''    synchronized ProcessResult receive(String raw, String localDeviceId, String localPublicKey) {
        long now = System.currentTimeMillis();
        // BLEE_RELAY_INGRESS_GUARD_V1
        if (raw == null || raw.getBytes(StandardCharsets.UTF_8).length > 128 * 1024) return ProcessResult.reject();
        try {
            JSONObject packet = new JSONObject(raw);'''
    if start_old not in text:
        fail("receive method start anchor missing")
    text = text.replace(start_old, start_new, 1)

    validation_old = '''            if (messageId.isEmpty() || type.isEmpty() || expiresAt <= now || hopCount > hopLimit) return ProcessResult.reject();
            if (!verifyPacket(packet)) return ProcessResult.reject();
            if (hasSeen(messageId)) return ProcessResult.duplicate();'''
    validation_new = '''            if (messageId.isEmpty() || type.isEmpty() || expiresAt <= now || hopCount < 0 || hopCount > hopLimit) return ProcessResult.reject();
            if (hopLimit < 1 || hopLimit > 16 || copyBudget < 1 || copyBudget > 16) return ProcessResult.reject();
            if (!verifyPacket(packet)) return ProcessResult.reject();
            if ("PAYMENT_ENVELOPE".equals(type)) {
                if (!basicRelayEnvelopeShape(packet, now)) return ProcessResult.reject();
                if (!relayIngressAllowed(packet, now)) return ProcessResult.reject();
            }
            if (hasSeen(messageId)) return ProcessResult.duplicate();'''
    if validation_old not in text:
        fail("receive validation anchor missing")
    text = text.replace(validation_old, validation_new, 1)

    helper_anchor = "    synchronized List<String> pendingEnvelopes() {"
    helpers = r'''    private boolean basicRelayEnvelopeShape(JSONObject packet, long now) {
        try {
            String destination = packet.optString("destinationWallet", "").toLowerCase(Locale.ROOT);
            if (!destination.matches("^0x[0-9a-f]{40}$")) return false;
            JSONObject payment = new JSONObject(packet.optString("payload", "{}"));
            JSONObject auth = authorization(payment);
            if (auth == null) return false;
            String from = auth.optString("from", "").toLowerCase(Locale.ROOT);
            String to = auth.optString("to", "").toLowerCase(Locale.ROOT);
            String nonce = auth.optString("nonce", "");
            String signature = auth.optString("signature", "");
            if (!from.matches("^0x[0-9a-f]{40}$") || !to.matches("^0x[0-9a-f]{40}$") || !destination.equals(to)) return false;
            if (!nonce.matches("^0x[0-9a-fA-F]{64}$") || !signature.matches("^0x[0-9a-fA-F]+$")) return false;
            long validBefore;
            try { validBefore = Long.parseLong(auth.optString("validBefore", "0")) * 1000L; }
            catch (Throwable ignored) { return false; }
            if (validBefore <= now || packet.optLong("expiresAt", 0L) > validBefore + 1000L) return false;

            JSONObject broadcast = auth.optJSONObject("broadcast");
            if (broadcast == null || !"SENDER_FUNDED_RAW_TX".equals(broadcast.optString("mode", ""))) return false;
            if (broadcast.optLong("chainId", -1L) != 5042002L) return false;
            String rawTx = broadcast.optString("rawTransaction", "");
            String txHash = broadcast.optString("txHash", "");
            return txHash.matches("^0x[0-9a-fA-F]{64}$")
                && rawTx.length() >= 4 && rawTx.length() <= 262144
                && rawTx.matches("^0x[0-9a-fA-F]+$") && ((rawTx.length() - 2) % 2 == 0);
        } catch (Throwable ignored) {
            return false;
        }
    }

    private boolean relayIngressAllowed(JSONObject packet, long now) {
        String origin = packet.optString("originDeviceId", "");
        if (origin.isEmpty() || origin.length() > 256) return false;
        int global = 0;
        int source = 0;
        long since = now - 60_000L;
        try (Cursor c = db().query(
            "mesh_inbox", new String[] { "packet" },
            "packet_type=? AND received_at>?",
            new String[] { "PAYMENT_ENVELOPE", String.valueOf(since) },
            null, null, "received_at DESC", "256"
        )) {
            while (c.moveToNext()) {
                global++;
                try {
                    JSONObject existing = new JSONObject(c.getString(0));
                    if (origin.equals(existing.optString("originDeviceId", ""))) source++;
                } catch (Throwable ignored) {}
                if (global >= 128 || source >= 32) return false;
            }
        } catch (Throwable ignored) {
            return false;
        }
        return true;
    }

'''
    if helper_anchor not in text:
        fail("pendingEnvelopes helper anchor missing")
    text = text.replace(helper_anchor, helpers + helper_anchor, 1)
    path.write_text(text)

    verified = path.read_text()
    for required in (
        marker,
        "raw.getBytes(StandardCharsets.UTF_8).length > 128 * 1024",
        "hopLimit > 16",
        "copyBudget > 16",
        "basicRelayEnvelopeShape",
        "relayIngressAllowed",
        "global >= 128",
        "source >= 32",
        '"SENDER_FUNDED_RAW_TX"',
    ):
        if required not in verified:
            fail(f"ingress guard missing {required}")
    print("Blee Relay V1 ingress quarantine limits verified")


if __name__ == "__main__":
    main()
