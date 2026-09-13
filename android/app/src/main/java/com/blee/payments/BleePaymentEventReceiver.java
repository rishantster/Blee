package com.blee.payments;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * Bridges durable native mesh events to user-visible payment notifications.
 * A transport receipt is deliberately labelled as detected, not received: the
 * WebView still performs EIP-3009 verification before recipient acceptance.
 */
public final class BleePaymentEventReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (context == null || intent == null) return;
        if (!BleeMeshService.ACTION_LEDGER_CHANGED.equals(intent.getAction())) return;

        String eventType = intent.getStringExtra(BleeMeshService.EXTRA_EVENT_TYPE);
        String paymentId = intent.getStringExtra(BleeMeshService.EXTRA_PAYMENT_ID);
        if ("PAYMENT_ENVELOPE_RECEIVED".equals(eventType) && paymentId != null && !paymentId.isEmpty()) {
            BleePaymentNotifier.detected(context, paymentId);
        }
    }
}
