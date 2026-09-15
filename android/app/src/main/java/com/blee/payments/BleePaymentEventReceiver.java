package com.blee.payments;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * Ledger broadcasts wake/update application state only. They are intentionally
 * not user-notification events: BLE retries and transport detection may occur
 * repeatedly for the same payment. User-visible notifications are emitted only
 * by the terminal native paths in BleePaymentNotifier.sent()/received().
 */
public final class BleePaymentEventReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (context == null || intent == null) return;
        if (!BleeMeshService.ACTION_LEDGER_CHANGED.equals(intent.getAction())) return;

        String eventType = intent.getStringExtra(BleeMeshService.EXTRA_EVENT_TYPE);
        if ("PAYMENT_ENVELOPE_RECEIVED".equals(eventType)) {
            // BLEE_PAYMENT_NOTIFICATION_TERMINAL_ONLY_V1
            // Transport detection is deliberately silent. The verified
            // BleeMeshPlugin.acceptEnvelope path owns "Payment received".
            return;
        }
    }
}
