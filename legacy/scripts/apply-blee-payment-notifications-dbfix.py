#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        raise SystemExit(f"Blee notification DB fix: expected one {name}, found {len(hits)}")
    return hits[0]


def once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Blee notification DB fix: missing {label} anchor")
    return text.replace(old, new, 1)


def main() -> None:
    path = locate("BleeMeshDb.java")
    text = path.read_text()

    if (
        "BLEE_PAYMENT_NOTIFICATION_SUMMARY_V1" in text
        and "senderWalletForNotification" in text
        and "final boolean newlyAccepted" in text
        and "final String amount;" in text
    ):
        print("Blee notification DB fix already installed")
        return

    if "BLEE_ATOMIC_RECIPIENT_ACK_V1" not in text:
        raise SystemExit("Blee notification DB fix: atomic recipient flow must be installed first")

    if "import java.math.BigDecimal;" not in text:
        text = once(
            text,
            "import java.nio.charset.StandardCharsets;",
            "import java.nio.charset.StandardCharsets;\nimport java.math.BigDecimal;\nimport java.math.RoundingMode;",
            "BigDecimal imports",
        )

    early = '''            if ("PAYMENT_ENVELOPE".equals(type) && forUs) {
                // Immediate offline notification, but no balance/payment projection
                // until verifyAuthorization() succeeds in the local viem layer.
                notifyTitle = "Nearby payment received";
                notifyBody = "Open Blee to verify and add this payment to your pending balance.";
            } else if ("DELIVERY_ACK".equals(type) && forUs) {'''
    safe = '''            if ("PAYMENT_ENVELOPE".equals(type) && forUs) {
                // BLEE_PAYMENT_NOTIFICATION_SUMMARY_V1
                // Transport receipt wakes verification immediately, but the final
                // Payment received notification is emitted only after EIP-3009
                // verification and durable recipient acceptance succeed.
            } else if ("DELIVERY_ACK".equals(type) && forUs) {'''
    text = once(text, early, safe, "pre-verification notification suppression")

    atomic = '''            // BLEE_ATOMIC_RECIPIENT_ACK_V1
            SQLiteDatabase database = db();'''
    atomic_with_summary = '''            String senderWalletForNotification = extractSender(payment);
            final boolean newlyAccepted = !paymentExists("incoming:" + paymentId);

            // BLEE_ATOMIC_RECIPIENT_ACK_V1
            SQLiteDatabase database = db();'''
    text = once(text, atomic, atomic_with_summary, "atomic recipient summary")

    text = once(
        text,
        '''                if (!paymentExists("incoming:" + paymentId)) {''',
        '''                if (newlyAccepted) {''',
        "atomic recipient newness gate",
    )

    text = once(
        text,
        '''            return new AcceptedPayment(true, paymentId);''',
        '''            return new AcceptedPayment(
                true,
                paymentId,
                newlyAccepted,
                paymentDisplayAmount(payment),
                peerDisplayLabel(senderWalletForNotification)
            );''',
        "accepted payment summary return",
    )

    helper_anchor = "    private static JSONObject authorization(JSONObject payment) {"
    helpers = r'''    private String peerDisplayLabel(String wallet) {
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

'''
    text = once(text, helper_anchor, helpers + helper_anchor, "notification summary helpers")

    old_class = '''    static final class AcceptedPayment {
        final boolean accepted;
        final String paymentId;
        AcceptedPayment(boolean accepted, String paymentId) {
            this.accepted = accepted;
            this.paymentId = paymentId;
        }
        static AcceptedPayment reject() { return new AcceptedPayment(false, ""); }
    }'''
    new_class = '''    static final class AcceptedPayment {
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
    }'''
    text = once(text, old_class, new_class, "AcceptedPayment notification fields")

    path.write_text(text)

    verify = path.read_text()
    for marker in (
        "BLEE_PAYMENT_NOTIFICATION_SUMMARY_V1",
        "senderWalletForNotification",
        "final boolean newlyAccepted",
        "paymentDisplayAmount(payment)",
        "peerDisplayLabel(senderWalletForNotification)",
        "final String amount;",
        "final String counterparty;",
    ):
        if marker not in verify:
            raise SystemExit(f"Blee notification DB fix verification missing: {marker}")

    print("VERIFIED: payment notification DB summary is compatible with atomic recipient persistence")


if __name__ == "__main__":
    main()
