package com.blee.payments;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;

import java.util.Map;

/**
 * User-visible payment notifications have exactly two terminal surfaces:
 * sender -> "Payment sent" and recipient -> "Payment received".
 *
 * Transport detection, BLE retries, delivery ACKs, settlement submission and
 * chain confirmation remain in the durable Activity journal and never create
 * additional notification noise.
 */
public final class BleePaymentNotifier {
    private static final String CHANNEL = "blee_payment_events_v3";
    private static final String PREFS = "blee.payment.notifications.v3";
    private static final long DEDUPE_RETENTION_MS = 30L * 24L * 60L * 60L * 1000L;

    private BleePaymentNotifier() {}

    public static void ensureChannel(Context rawContext) {
        if (rawContext == null) return;
        Context context = rawContext.getApplicationContext();
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(CHANNEL, "Blee payments", NotificationManager.IMPORTANCE_HIGH);
            channel.setDescription("One notification when you send or receive a Blee payment.");
            channel.enableVibration(true);
            manager.createNotificationChannel(channel);
        }
    }

    /** Alert once when this device originates a payment. */
    public static void sent(Context context, String paymentId, String amount, String counterparty) {
        String body = amountText(amount, "sent");
        if (counterparty != null && !counterparty.trim().isEmpty()) body += " to " + counterparty.trim();
        postOnce(context, paymentId, "sender", "Payment sent", body);
    }

    /** Delivery acknowledgement belongs in Activity, not another notification. */
    public static void delivered(Context context, String paymentId) {
        // Intentionally silent.
    }

    /** Raw BLE detection belongs in Activity, not another notification. */
    public static void detected(Context context, String paymentId) {
        // Intentionally silent.
    }

    /** Alert once only after the verified envelope has been durably accepted. */
    public static void received(Context context, String paymentId, String amount, String counterparty) {
        String body = amountText(amount, "received");
        if (counterparty != null && !counterparty.trim().isEmpty()) body += " from " + counterparty.trim();
        post(context, paymentId, "receiver", "Payment received", body, false);
    }

    private static String amountText(String amount, String verb) {
        String clean = amount == null ? "" : amount.trim();
        return clean.isEmpty() ? "USDC " + verb : clean + " USDC " + verb;
    }

    /**
     * Compatibility boundary retained for the verified receive call site. Alert
     * flags no longer control lifecycle notifications; every terminal event is
     * exactly-once by payment+side.
     */
    private static void post(Context context, String paymentId, String side, String title, String body, boolean alert) {
        postOnce(context, paymentId, side, title, body);
    }

    private static void postOnce(Context rawContext, String paymentId, String side, String title, String body) {
        if (rawContext == null) return;
        String cleanPaymentId = paymentId == null ? "" : paymentId.trim();
        if (cleanPaymentId.isEmpty()) return;

        Context context = rawContext.getApplicationContext();
        if (Build.VERSION.SDK_INT >= 33 && context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return;

        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return;
        ensureChannel(context);

        // BLEE_PAYMENT_NOTIFICATION_EXACTLY_ONCE_V1
        // Native mesh/service retries can replay the same lifecycle event many
        // times. Persist the user-notification side independently from transport
        // state so one payment can never buzz the same phone repeatedly.
        String dedupeKey = side + ":" + cleanPaymentId;
        if (!claimNotification(context, dedupeKey)) return;

        Intent launch = context.getPackageManager().getLaunchIntentForPackage(context.getPackageName());
        if (launch != null) {
            launch.putExtra("bleePaymentId", cleanPaymentId);
            launch.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        }
        int requestCode = dedupeKey.hashCode();
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
            .setOnlyAlertOnce(true)
            .setCategory(Notification.CATEGORY_MESSAGE)
            .setShowWhen(true)
            .setWhen(System.currentTimeMillis());
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) builder.setPriority(Notification.PRIORITY_HIGH);
        if (pending != null) builder.setContentIntent(pending);
        manager.notify(requestCode, builder.build());
    }

    private static synchronized boolean claimNotification(Context context, String key) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (prefs.contains(key)) return false;

        long now = System.currentTimeMillis();
        SharedPreferences.Editor editor = prefs.edit().putLong(key, now);
        for (Map.Entry<String, ?> entry : prefs.getAll().entrySet()) {
            Object value = entry.getValue();
            if (value instanceof Long && now - (Long) value > DEDUPE_RETENTION_MS) {
                editor.remove(entry.getKey());
            }
        }
        return editor.commit();
    }
}
