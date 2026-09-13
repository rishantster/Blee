package com.blee.payments;

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

public final class BleePaymentNotifier {
    private static final String CHANNEL = "blee_payment_events_v2";

    private BleePaymentNotifier() {}

    // BLEE_NOTIFICATION_PERMISSION_V1
    public static void ensureChannel(Context rawContext) {
        if (rawContext == null) return;
        Context context = rawContext.getApplicationContext();
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(CHANNEL, "Blee payment activity", NotificationManager.IMPORTANCE_HIGH);
            channel.setDescription("Immediate nearby payment sent and received notifications.");
            channel.enableVibration(true);
            manager.createNotificationChannel(channel);
        }
    }

    public static void sent(Context context, String paymentId, String amount, String counterparty) {
        String body = amountText(amount, "sent");
        if (counterparty != null && !counterparty.trim().isEmpty()) body += " to " + counterparty.trim();
        post(context, paymentId, "sender", "Payment sent", body, true);
    }

    public static void delivered(Context context, String paymentId) {
        post(context, paymentId, "sender", "Payment delivered", "Your nearby payment was received by the recipient.", false);
    }

    // BLEE_BACKGROUND_PAYMENT_NOTIFICATION_V2
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
    }

    private static String amountText(String amount, String verb) {
        String clean = amount == null ? "" : amount.trim();
        return clean.isEmpty() ? "USDC " + verb : clean + " USDC " + verb;
    }

    private static void post(Context rawContext, String paymentId, String side, String title, String body, boolean alert) {
        if (rawContext == null) return;
        Context context = rawContext.getApplicationContext();
        if (Build.VERSION.SDK_INT >= 33 && context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return;

        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(CHANNEL, "Blee payment activity", NotificationManager.IMPORTANCE_HIGH);
            channel.setDescription("Immediate nearby payment sent and received notifications.");
            channel.enableVibration(true);
            manager.createNotificationChannel(channel);
        }

        Intent launch = context.getPackageManager().getLaunchIntentForPackage(context.getPackageName());
        if (launch != null && paymentId != null) {
            launch.putExtra("bleePaymentId", paymentId);
            launch.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        }
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
    }
}
