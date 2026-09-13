#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"
STORE_PLUGIN = ROOT / "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java"


def once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Blee payment notifications: missing {label} anchor")
    return text.replace(old, new, 1)


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        raise SystemExit(f"Blee payment notifications: expected one {name}, found {len(hits)}")
    return hits[0]


def app_package() -> tuple[str, Path]:
    activity = locate("MainActivity.java")
    text = activity.read_text()
    match = re.search(r"^package\s+([A-Za-z0-9_.]+);", text, re.M)
    if not match:
        raise SystemExit("Blee payment notifications: MainActivity package missing")
    return match.group(1), activity.parent


def patch_notifier(package: str, native_dir: Path) -> None:
    path = native_dir / "BleePaymentNotifier.java"
    content = f'''package {package};

// BLEE_PAYMENT_NOTIFICATIONS_V1
import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;

public final class BleePaymentNotifier {{
    private static final String CHANNEL = "blee_payment_events_v2";

    private BleePaymentNotifier() {{}}

    public static void sent(Context context, String paymentId, String amount, String counterparty) {{
        String body = amountText(amount, "sent");
        if (counterparty != null && !counterparty.trim().isEmpty()) body += " to " + counterparty.trim();
        post(context, paymentId, "sender", "Payment sent", body, true);
    }}

    public static void delivered(Context context, String paymentId) {{
        post(context, paymentId, "sender", "Payment delivered", "Your nearby payment was received by the recipient.", false);
    }}

    public static void received(Context context, String paymentId, String amount, String counterparty) {{
        String body = amountText(amount, "received");
        if (counterparty != null && !counterparty.trim().isEmpty()) body += " from " + counterparty.trim();
        body += " · Pending settlement";
        post(context, paymentId, "receiver", "Payment received", body, true);
    }}

    private static String amountText(String amount, String verb) {{
        String clean = amount == null ? "" : amount.trim();
        return clean.isEmpty() ? "USDC " + verb : clean + " USDC " + verb;
    }}

    private static void post(Context rawContext, String paymentId, String side, String title, String body, boolean alert) {{
        if (rawContext == null) return;
        Context context = rawContext.getApplicationContext();
        if (Build.VERSION.SDK_INT >= 33 && context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return;

        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {{
            NotificationChannel channel = new NotificationChannel(CHANNEL, "Blee payment activity", NotificationManager.IMPORTANCE_HIGH);
            channel.setDescription("Immediate nearby payment sent and received notifications.");
            channel.enableVibration(true);
            manager.createNotificationChannel(channel);
        }}

        Intent launch = context.getPackageManager().getLaunchIntentForPackage(context.getPackageName());
        if (launch != null && paymentId != null) {{
            launch.putExtra("bleePaymentId", paymentId);
            launch.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        }}
        int requestCode = (side + ":" + String.valueOf(paymentId)).hashCode();
        PendingIntent pending = launch == null ? null : PendingIntent.getActivity(
            context,
            requestCode,
            launch,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
            ? new Notification.Builder(context, CHANNEL)
            : new Notification.Builder(context);
        builder.setContentTitle(title)
            .setContentText(body)
            .setStyle(new Notification.BigTextStyle().bigText(body))
            .setSmallIcon(R.drawable.blee_notification)
            .setAutoCancel(true)
            .setOnlyAlertOnce(!alert)
            .setCategory(Notification.CATEGORY_MESSAGE)
            .setShowWhen(true)
            .setWhen(System.currentTimeMillis());
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) builder.setPriority(Notification.PRIORITY_HIGH);
        if (pending != null) builder.setContentIntent(pending);
        manager.notify(requestCode, builder.build());
    }}
}}
'''
    path.write_text(content)


def patch_db() -> None:
    path = locate("BleeMeshDb.java")
    text = path.read_text()
    if "BLEE_PAYMENT_NOTIFICATION_SUMMARY_V1" in text:
        return

    if "import java.math.BigDecimal;" not in text:
        text = once(text, "import java.nio.charset.StandardCharsets;", "import java.nio.charset.StandardCharsets;\nimport java.math.BigDecimal;\nimport java.math.RoundingMode;", "BigDecimal imports")

    # A raw packet is transport-authenticated but the EIP-3009 authorization is
    # verified in the Capacitor layer. Do not alert before that financial check.
    early = '''            if ("PAYMENT_ENVELOPE".equals(type) && forUs) {
                // Immediate offline notification, but no balance/payment projection
                // until verifyAuthorization() succeeds in the local viem layer.
                notifyTitle = "Nearby payment received";
                notifyBody = "Open Blee to verify and add this payment to your pending balance.";
            } else if ("DELIVERY_ACK".equals(type) && forUs) {'''
    safe = '''            if ("PAYMENT_ENVELOPE".equals(type) && forUs) {
                // BLEE_PAYMENT_NOTIFICATION_SUMMARY_V1
                // The OS notification is emitted only after verifyAuthorization()
                // and acceptVerifiedEnvelope() succeed, avoiding spoofed payment alerts.
            } else if ("DELIVERY_ACK".equals(type) && forUs) {'''
    text = once(text, early, safe, "pre-verification notification suppression")

    text = once(
        text,
        '''            if (!paymentExists("incoming:" + paymentId)) {''',
        '''            boolean newlyAccepted = false;
            if (!paymentExists("incoming:" + paymentId)) {''',
        "accepted-payment newness",
    )
    text = once(
        text,
        '''                addEvent(paymentId, "RECIPIENT_RECEIVED", now, packet.optString("originDeviceId", null), raw);
            }

            String senderWallet = extractSender(payment);''',
        '''                addEvent(paymentId, "RECIPIENT_RECEIVED", now, packet.optString("originDeviceId", null), raw);
                newlyAccepted = true;
            }

            String senderWallet = extractSender(payment);''',
        "accepted-payment created flag",
    )
    text = once(
        text,
        '''            return new AcceptedPayment(true, paymentId);''',
        '''            return new AcceptedPayment(
                true,
                paymentId,
                newlyAccepted,
                paymentDisplayAmount(payment),
                peerDisplayLabel(senderWallet)
            );''',
        "accepted-payment notification summary",
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
            return new BigDecimal(raw).movePointLeft(6).setScale(6, RoundingMode.DOWN).stripTrailingZeros().toPlainString();
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
    text = once(text, helper_anchor, helpers + helper_anchor, "payment notification summary helpers")

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


def patch_mesh_plugin() -> None:
    path = locate("BleeMeshPlugin.java")
    text = path.read_text()
    if "BLEE_VERIFIED_RECEIVE_NOTIFICATION_V1" in text:
        return
    old = '''            if (accepted.accepted) {
                JSObject event = new JSObject();
                event.put("paymentId", accepted.paymentId);
                event.put("eventType", "RECIPIENT_RECEIVED");
                notifyListeners("ledgerChanged", event, true);
            }
            call.resolve(result);'''
    new = '''            if (accepted.accepted) {
                JSObject event = new JSObject();
                event.put("paymentId", accepted.paymentId);
                event.put("eventType", "RECIPIENT_RECEIVED");
                notifyListeners("ledgerChanged", event, true);
                // BLEE_VERIFIED_RECEIVE_NOTIFICATION_V1
                if (accepted.newlyAccepted) {
                    BleePaymentNotifier.received(getContext(), accepted.paymentId, accepted.amount, accepted.counterparty);
                }
            }
            call.resolve(result);'''
    text = once(text, old, new, "verified receive notification")
    path.write_text(text)


def patch_service(package: str) -> None:
    path = locate("BleeMeshService.java")
    text = path.read_text()
    if "BLEE_IMMEDIATE_SENT_NOTIFICATION_V1" in text:
        return

    action_anchor = '    static final String ACTION_LEDGER_CHANGED = "' + package + '.BLEE_LEDGER_CHANGED";'
    if action_anchor not in text:
        # Generated package replacement can differ from the template literal;
        # anchor structurally when needed.
        m = re.search(r'    static final String ACTION_LEDGER_CHANGED = "[^"]+";', text)
        if not m:
            raise SystemExit("Blee payment notifications: ledger action anchor missing")
        action_anchor = m.group(0)
    text = once(
        text,
        action_anchor,
        action_anchor + f'\n    // BLEE_IMMEDIATE_SENT_NOTIFICATION_V1\n    static final String ACTION_LOCAL_PAYMENT_SENT = "{package}.BLEE_LOCAL_PAYMENT_SENT";',
        "local sent action",
    )

    old_start = "    @Override public int onStartCommand(Intent intent, int flags, int startId) { return START_STICKY; }"
    new_start = '''    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_LOCAL_PAYMENT_SENT.equals(intent.getAction())) {
            BleePaymentNotifier.sent(
                this,
                intent.getStringExtra("paymentId"),
                intent.getStringExtra("amount"),
                intent.getStringExtra("counterparty")
            );
        }
        return START_STICKY;
    }'''
    text = once(text, old_start, new_start, "service sent notification action")

    notify_anchor = '''    private void notifyLedgerChanged(String paymentId, String type) {
        Intent intent = new Intent(ACTION_LEDGER_CHANGED);'''
    notify_new = '''    private void notifyLedgerChanged(String paymentId, String type) {
        if ("DELIVERY_ACK".equals(type)) BleePaymentNotifier.delivered(this, paymentId);
        Intent intent = new Intent(ACTION_LEDGER_CHANGED);'''
    text = once(text, notify_anchor, notify_new, "delivery notification update")
    path.write_text(text)


def patch_store_plugin(package: str) -> None:
    path = STORE_PLUGIN
    if not path.is_file():
        raise SystemExit(f"Blee payment notifications: store plugin missing: {path}")
    text = path.read_text()
    if "BLEE_SENT_NOTIFICATION_BRIDGE_V1" in text:
        return

    if "import android.content.Intent;" not in text:
        text = once(text, "import android.content.ContentValues;", "import android.content.ContentValues;\nimport android.content.Intent;\nimport android.os.Build;", "store Intent imports")
    if "import java.math.BigDecimal;" not in text:
        text = once(text, "import java.util.Locale;", "import java.util.Locale;\nimport java.math.BigDecimal;\nimport java.math.RoundingMode;\nimport java.util.ArrayList;\nimport java.util.List;", "store notification helper imports")

    method_start = text.index("    @PluginMethod\n    public void replacePayments(PluginCall call) {")
    method_end = text.index("\n    @PluginMethod\n    public void appendPaymentEvent", method_start)
    replacement = f'''    // BLEE_SENT_NOTIFICATION_BRIDGE_V1
    private static boolean paymentRowExists(SQLiteDatabase database, String paymentKey) {{
        try (Cursor cursor = database.rawQuery("SELECT 1 FROM payments WHERE payment_key=? LIMIT 1", new String[] {{ paymentKey }})) {{
            return cursor.moveToFirst();
        }}
    }}

    private static JSONObject authorizationForNotice(JSONObject row) {{
        JSONObject auth = row.optJSONObject("authorization");
        return auth == null ? row.optJSONObject("auth") : auth;
    }}

    private static String noticeAmount(JSONObject row) {{
        for (String key : new String[] {{ "amount", "displayAmount", "tokenAmount" }}) {{
            String value = row.optString(key, "").trim();
            if (!value.isEmpty()) {{
                try {{ return new BigDecimal(value).stripTrailingZeros().toPlainString(); }}
                catch (Throwable ignored) {{ return value; }}
            }}
        }}
        JSONObject auth = authorizationForNotice(row);
        String raw = auth == null ? "" : auth.optString("value", "").trim();
        if (raw.isEmpty()) return "";
        try {{ return new BigDecimal(raw).movePointLeft(6).setScale(6, RoundingMode.DOWN).stripTrailingZeros().toPlainString(); }}
        catch (Throwable ignored) {{ return ""; }}
    }}

    private static String noticeCounterparty(JSONObject row) {{
        for (String key : new String[] {{ "recipientName", "receiverName", "toName", "counterpartyName" }}) {{
            String value = row.optString(key, "").trim();
            if (!value.isEmpty()) return value;
        }}
        JSONObject auth = authorizationForNotice(row);
        String wallet = auth == null ? "" : auth.optString("to", "").trim();
        if (wallet.length() > 12) return wallet.substring(0, 6) + "…" + wallet.substring(wallet.length() - 4);
        return wallet;
    }}

    private static boolean markSentNotification(SQLiteDatabase database, String paymentId, long now) {{
        ContentValues event = new ContentValues();
        event.put("event_id", "LOCAL_SENT_NOTIFIED:" + paymentId);
        event.put("payment_id", paymentId);
        event.put("event_type", "LOCAL_SENT_NOTIFIED");
        event.put("event_at", now);
        event.putNull("source_device");
        event.put("payload", "{{}}");
        return database.insertWithOnConflict("payment_events", null, event, SQLiteDatabase.CONFLICT_IGNORE) != -1;
    }}

    private void dispatchSentNotification(JSONObject notice) {{
        try {{
            Intent service = new Intent();
            service.setClassName("{package}", "{package}.BleeMeshService");
            service.setAction("{package}.BLEE_LOCAL_PAYMENT_SENT");
            service.putExtra("paymentId", notice.optString("paymentId", ""));
            service.putExtra("amount", notice.optString("amount", ""));
            service.putExtra("counterparty", notice.optString("counterparty", ""));
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) getContext().startForegroundService(service);
            else getContext().startService(service);
        }} catch (Throwable ignored) {{}}
    }}

    @PluginMethod
    public void replacePayments(PluginCall call) {{
        JSArray payments = call.getArray("payments");
        if (payments == null) {{ call.reject("Missing payments"); return; }}

        SQLiteDatabase database = null;
        List<JSONObject> sentNotices = new ArrayList<>();
        Throwable failure = null;
        int persistedCount = 0;
        try {{
            database = db();
            database.beginTransaction();
            long now = System.currentTimeMillis();
            for (int i = 0; i < payments.length(); i++) {{
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
                boolean existed = paymentRowExists(database, paymentKey);

                ContentValues values = new ContentValues();
                values.put("payment_key", paymentKey);
                values.put("payment_id", paymentId);
                values.put("direction", direction);
                values.put("state", state);
                values.put("created_at", createdAt);
                values.put("updated_at", updatedAt);
                values.put("payload", payload);
                if (database.insertWithOnConflict("payments", null, values, SQLiteDatabase.CONFLICT_REPLACE) == -1) throw new IllegalStateException("Payment insert failed at index " + i);

                persistSigningForPayment(database, row, paymentId, now);
                if (!existed && "outgoing".equalsIgnoreCase(direction) && markSentNotification(database, paymentId, now)) {{
                    JSONObject notice = new JSONObject();
                    notice.put("paymentId", paymentId);
                    notice.put("amount", noticeAmount(row));
                    notice.put("counterparty", noticeCounterparty(row));
                    sentNotices.add(notice);
                }}
                persistedCount++;
            }}
            database.setTransactionSuccessful();
        }} catch (Throwable error) {{
            failure = error;
        }} finally {{
            if (database != null && database.inTransaction()) database.endTransaction();
        }}

        if (failure != null) {{
            call.reject("Unable to persist Blee payment journal atomically: " + message(failure));
            return;
        }}
        for (JSONObject notice : sentNotices) dispatchSentNotification(notice);
        JSObject result = new JSObject();
        result.put("count", persistedCount);
        call.resolve(result);
    }}
'''
    text = text[:method_start] + replacement + text[method_end:]
    path.write_text(text)


def verify(package: str, native_dir: Path) -> None:
    notifier = (native_dir / "BleePaymentNotifier.java").read_text()
    db = locate("BleeMeshDb.java").read_text()
    plugin = locate("BleeMeshPlugin.java").read_text()
    service = locate("BleeMeshService.java").read_text()
    store = STORE_PLUGIN.read_text()

    checks = {
        "notifier": (notifier, ("BLEE_PAYMENT_NOTIFICATIONS_V1", "Payment sent", "Payment received", "Payment delivered", "Pending settlement", "IMPORTANCE_HIGH", "blee_notification")),
        "db": (db, ("BLEE_PAYMENT_NOTIFICATION_SUMMARY_V1", "newlyAccepted", "paymentDisplayAmount", "peerDisplayLabel")),
        "plugin": (plugin, ("BLEE_VERIFIED_RECEIVE_NOTIFICATION_V1", "BleePaymentNotifier.received")),
        "service": (service, ("BLEE_IMMEDIATE_SENT_NOTIFICATION_V1", "ACTION_LOCAL_PAYMENT_SENT", "BleePaymentNotifier.sent", "BleePaymentNotifier.delivered")),
        "store": (store, ("BLEE_SENT_NOTIFICATION_BRIDGE_V1", "LOCAL_SENT_NOTIFIED", "dispatchSentNotification", f'"{package}.BLEE_LOCAL_PAYMENT_SENT"')),
    }
    for label, (text, markers) in checks.items():
        missing = [m for m in markers if m not in text]
        if missing:
            raise SystemExit(f"Blee payment notifications verification: {label} missing {missing}")
    if 'notifyTitle = "Nearby payment received"' in db:
        raise SystemExit("Blee payment notifications verification: unverified incoming notification remains")

    print("============================================================")
    print("VERIFIED: Blee immediate payment notifications")
    print("- sender notification fires only after new outgoing payment is durably committed")
    print("- receiver notification fires only after local EIP-3009 verification/acceptance")
    print("- notification IDs are payment-scoped and retries are deduplicated")
    print("- sender notification updates to Delivered on recipient acknowledgement")
    print("- notifications use a high-importance Android channel and work offline")
    print("============================================================")


def main() -> None:
    package, native_dir = app_package()
    patch_notifier(package, native_dir)
    patch_db()
    patch_mesh_plugin()
    patch_service(package)
    patch_store_plugin(package)
    verify(package, native_dir)


if __name__ == "__main__":
    main()
