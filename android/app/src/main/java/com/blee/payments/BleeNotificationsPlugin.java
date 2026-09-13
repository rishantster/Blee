package com.blee.payments;

import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "BleeNotifications")
public class BleeNotificationsPlugin extends Plugin {
    @PluginMethod
    public void received(PluginCall call) {
        String paymentId = call.getString("paymentId", "");
        String amount = call.getString("amount", "");
        String counterparty = call.getString("counterparty", "");
        if (paymentId.isEmpty()) {
            call.reject("Missing paymentId");
            return;
        }
        BleePaymentNotifier.received(getContext(), paymentId, amount, counterparty);
        call.resolve();
    }

    @PluginMethod
    public void delivered(PluginCall call) {
        String paymentId = call.getString("paymentId", "");
        if (paymentId.isEmpty()) {
            call.reject("Missing paymentId");
            return;
        }
        BleePaymentNotifier.delivered(getContext(), paymentId);
        call.resolve();
    }
}
