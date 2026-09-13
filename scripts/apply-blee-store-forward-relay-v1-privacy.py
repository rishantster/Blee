#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee relay privacy: {message}")


def locate() -> Path:
    hits = list(ANDROID_JAVA.rglob("BleeRelayStore.java"))
    if len(hits) != 1:
        fail(f"expected one BleeRelayStore.java, found {len(hits)}")
    return hits[0]


def replace_method(text: str, signature: str, replacement: str) -> str:
    start = text.find(signature)
    if start < 0:
        fail(f"method missing: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        fail("method opening brace missing")
    depth = 0
    quote = None
    escaped = False
    end = -1
    for i in range(brace, len(text)):
        ch = text[i]
        if quote is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        fail("method end missing")
    return text[:start] + replacement.rstrip() + text[end:]


def main() -> None:
    path = locate()
    text = path.read_text()
    marker = "BLEE_RELAY_PRIVACY_ALLOWLIST_V1"
    if marker in text:
        return

    if "import java.nio.charset.StandardCharsets;" not in text:
        anchor = "import java.io.File;\n"
        if anchor not in text:
            fail("java.io.File import anchor missing")
        text = text.replace(anchor, anchor + "import java.nio.charset.StandardCharsets;\nimport java.security.MessageDigest;\n", 1)

    call_old = "            boolean queued = enqueueForward(packet, now);"
    call_new = "            boolean queued = enqueueForward(packet, now, localDeviceId);"
    if call_old not in text:
        fail("forward enqueue call anchor missing")
    text = text.replace(call_old, call_new, 1)

    replacement = r'''    // BLEE_RELAY_PRIVACY_ALLOWLIST_V1
    private boolean enqueueForward(JSONObject packet, long now, String localDeviceId) {
        try {
            int hopCount = packet.optInt("hopCount", 0);
            int hopLimit = packet.optInt("hopLimit", 0);
            int copyBudget = packet.optInt("copyBudget", 0);
            if (hopCount >= hopLimit || copyBudget <= 1) return false;

            JSONObject sourcePayment = new JSONObject(packet.optString("payload", "{}"));
            JSONObject sourceAuth = sourcePayment.optJSONObject("authorization");
            if (sourceAuth == null) sourceAuth = sourcePayment.optJSONObject("auth");
            if (sourceAuth == null) return false;

            // Community forwarding carries only a financial allowlist. Human
            // profile/contact metadata stays on the local/direct identity path.
            JSONObject relayPayment = new JSONObject();
            for (String key : new String[] {
                "id", "sender", "receiver", "from", "to", "amount",
                "token", "symbol", "asset", "network", "chainId", "createdAt"
            }) {
                if (sourcePayment.has(key) && sourcePayment.opt(key) != JSONObject.NULL) {
                    relayPayment.put(key, sourcePayment.opt(key));
                }
            }
            relayPayment.put("authorization", new JSONObject(sourceAuth.toString()));
            String relayPayload = relayPayment.toString();

            JSONObject forwarded = new JSONObject(packet.toString());
            forwarded.put("hopCount", hopCount + 1);
            forwarded.put("copyBudget", copyBudget - 1);
            forwarded.put("payload", relayPayload);
            forwarded.put("payloadHash", sha256Relay(relayPayload));
            forwarded.put("originDeviceId", localDeviceId == null ? "" : localDeviceId);
            forwarded.put("devicePublicKey", BleeDeviceIdentity.publicKey());
            forwarded.put("deviceSignature", BleeDeviceIdentity.sign(relaySigningString(forwarded)));

            String raw = forwarded.toString();
            ContentValues cv = new ContentValues();
            cv.put("message_id", forwarded.optString("messageId", ""));
            cv.put("packet_type", "PAYMENT_ENVELOPE");
            cv.put("payment_id", forwarded.optString("paymentId", ""));
            cv.put("created_at", forwarded.optLong("createdAt", now));
            cv.put("expires_at", forwarded.optLong("expiresAt", now + 3600000L));
            cv.put("hop_count", hopCount + 1);
            cv.put("hop_limit", hopLimit);
            cv.put("copy_budget", copyBudget - 1);
            cv.put("attempts", 0);
            cv.put("next_attempt_at", now);
            cv.put("packet", raw);
            return db().insertWithOnConflict("mesh_outbox", null, cv, SQLiteDatabase.CONFLICT_IGNORE) != -1L;
        } catch (Throwable ignored) {
            return false;
        }
    }'''
    text = replace_method(text, "    private boolean enqueueForward(JSONObject packet, long now)", replacement)

    helper_anchor = "    private void updateAttempt(String messageId, String state, String error, long nextAttemptAt, boolean increment) {"
    helpers = r'''    private static String relaySigningString(JSONObject p) {
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

    private static String sha256Relay(String value) {
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

'''
    if helper_anchor not in text:
        fail("relay attempt helper anchor missing")
    text = text.replace(helper_anchor, helpers + helper_anchor, 1)
    path.write_text(text)

    verified = path.read_text()
    start = verified.index(marker)
    end = verified.index("private void updateAttempt", start)
    block = verified[start:end]
    for forbidden_field in ('"displayName"', '"avatar"', '"photo"', '"phone"', '"note"', '"contact"'):
        if forbidden_field in block:
            fail(f"relay forwarding allowlist contains private field {forbidden_field}")
    for required in (
        'relayPayment.put("authorization"',
        'forwarded.put("payloadHash", sha256Relay(relayPayload))',
        'BleeDeviceIdentity.sign(relaySigningString(forwarded))',
    ):
        if required not in block:
            fail(f"relay forwarding privacy path missing {required}")
    print("Blee Relay V1 multi-hop forwarding payload is limited to financial fields")


if __name__ == "__main__":
    main()
