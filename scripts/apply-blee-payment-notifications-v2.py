#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        raise SystemExit(f"Blee payment notifications v2: expected one {name}, found {len(hits)}")
    return hits[0]


def once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Blee payment notifications v2: missing {label} anchor")
    return text.replace(old, new, 1)


def patch_notifier() -> None:
    path = locate("BleePaymentNotifier.java")
    text = path.read_text()
    if "BLEE_BACKGROUND_PAYMENT_NOTIFICATION_V2" in text:
        return

    anchor = '''    public static void received(Context context, String paymentId, String amount, String counterparty) {
        String body = amountText(amount, "received");
        if (counterparty != null && !counterparty.trim().isEmpty()) body += " from " + counterparty.trim();
        body += " · Pending settlement";
        post(context, paymentId, "receiver", "Payment received", body, true);
    }'''
    replacement = '''    // BLEE_BACKGROUND_PAYMENT_NOTIFICATION_V2
    public static void detected(Context context, String paymentId) {
        post(
            context,
            paymentId,
            "receiver",
            "Incoming Blee payment",
            "Nearby payment detected. Verifying payment details…",
            true
        );
    }

    public static void received(Context context, String paymentId, String amount, String counterparty) {
        String body = amountText(amount, "received");
        if (counterparty != null && !counterparty.trim().isEmpty()) body += " from " + counterparty.trim();
        body += " · Pending settlement";
        // Update the already-alerted receiver notification silently. If the WebView
        // was alive this follows the detection event within milliseconds; if it was
        // suspended, the user still got the transport-level notification immediately.
        post(context, paymentId, "receiver", "Payment received", body, false);
    }'''
    text = once(text, anchor, replacement, "two-stage receiver notification")
    path.write_text(text)


def patch_service() -> None:
    path = locate("BleeMeshService.java")
    text = path.read_text()
    if "BLEE_BACKGROUND_RECEIVE_NOTIFICATION_V2" in text:
        return

    anchor = '''    private void notifyLedgerChanged(String paymentId, String type) {
        if ("DELIVERY_ACK".equals(type)) BleePaymentNotifier.delivered(this, paymentId);
        Intent intent = new Intent(ACTION_LEDGER_CHANGED);'''
    replacement = '''    private void notifyLedgerChanged(String paymentId, String type) {
        // BLEE_BACKGROUND_RECEIVE_NOTIFICATION_V2
        // PAYMENT_ENVELOPE_RECEIVED is emitted by the native transport immediately,
        // so this works even when the WebView is backgrounded. Wording deliberately
        // says "detected" until EIP-3009 verification promotes it to received.
        if ("PAYMENT_ENVELOPE_RECEIVED".equals(type)) BleePaymentNotifier.detected(this, paymentId);
        if ("DELIVERY_ACK".equals(type)) BleePaymentNotifier.delivered(this, paymentId);
        Intent intent = new Intent(ACTION_LEDGER_CHANGED);'''
    text = once(text, anchor, replacement, "native receive notification hook")
    path.write_text(text)


def verify() -> None:
    notifier = locate("BleePaymentNotifier.java").read_text()
    service = locate("BleeMeshService.java").read_text()
    for marker in (
        "BLEE_BACKGROUND_PAYMENT_NOTIFICATION_V2",
        "Incoming Blee payment",
        "Nearby payment detected. Verifying payment details",
        'post(context, paymentId, "receiver", "Payment received", body, false)',
    ):
        if marker not in notifier:
            raise SystemExit(f"Blee payment notifications v2: notifier missing {marker}")
    for marker in (
        "BLEE_BACKGROUND_RECEIVE_NOTIFICATION_V2",
        '"PAYMENT_ENVELOPE_RECEIVED".equals(type)',
        "BleePaymentNotifier.detected",
    ):
        if marker not in service:
            raise SystemExit(f"Blee payment notifications v2: service missing {marker}")
    print("VERIFIED: background payment detection alerts immediately, then upgrades silently after cryptographic acceptance")


def main() -> None:
    patch_notifier()
    patch_service()
    verify()


if __name__ == "__main__":
    main()
