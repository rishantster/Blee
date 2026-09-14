package com.blee.payments;

import android.Manifest;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

@CapacitorPlugin(
    name = "BleeMesh",
    permissions = {
        @Permission(alias = "notifications", strings = { Manifest.permission.POST_NOTIFICATIONS })
    }
)
public class BleeMeshPlugin extends Plugin {
    private BroadcastReceiver receiver;
    private ScheduledExecutorService profileExecutor;
    private Handler mainHandler;

    @Override
    public void load() {
        mainHandler = new Handler(Looper.getMainLooper());
        final Context appContext = getContext().getApplicationContext();
        receiver = new BroadcastReceiver() {
            @Override public void onReceive(Context context, Intent intent) {
                String action = intent.getAction();
                if (BleeMeshService.ACTION_LEDGER_CHANGED.equals(action)) {
                    JSObject event = new JSObject();
                    event.put("paymentId", intent.getStringExtra(BleeMeshService.EXTRA_PAYMENT_ID));
                    event.put("eventType", intent.getStringExtra(BleeMeshService.EXTRA_EVENT_TYPE));
                    notifyListeners("ledgerChanged", event, true);
                    return;
                }
                if (BleeMeshService.ACTION_PEER_CHANGED.equals(action)) {
                    org.json.JSONObject raw = new org.json.JSONObject();
                    try {
                        raw.put("transportId", intent.getStringExtra(BleeMeshService.EXTRA_PEER_TRANSPORT_ID));
                        raw.put("wallet", intent.getStringExtra(BleeMeshService.EXTRA_PEER_WALLET));
                        raw.put("displayName", intent.getStringExtra(BleeMeshService.EXTRA_PEER_DISPLAY_NAME));
                        raw.put("avatar", intent.getStringExtra(BleeMeshService.EXTRA_PEER_AVATAR));
                        raw.put("rssi", intent.getIntExtra(BleeMeshService.EXTRA_PEER_RSSI, 0));
                        raw.put("lastSeen", intent.getLongExtra(BleeMeshService.EXTRA_PEER_LAST_SEEN, 0L));
                    } catch (Throwable ignored) {}
                    BleeMeshDb db = new BleeMeshDb(appContext);
                    org.json.JSONObject enriched = BleeProfileIdentityTransport.enrichPeer(db, raw);
                    db.close();
                    JSObject event = peerObject(enriched);
                    event.put("present", intent.getBooleanExtra(BleeMeshService.EXTRA_PEER_PRESENT, true));
                    notifyListeners("peerChanged", event, true);
                }
            }
        };
        IntentFilter filter = new IntentFilter(BleeMeshService.ACTION_LEDGER_CHANGED);
        filter.addAction(BleeMeshService.ACTION_PEER_CHANGED);
        if (Build.VERSION.SDK_INT >= 33) getContext().registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED);
        else getContext().registerReceiver(receiver, filter);
        BleeMeshService.start(getContext());
        startProfileIdentityLoop(appContext);
    }

    @Override
    protected void handleOnDestroy() {
        if (receiver != null) {
            try { getContext().unregisterReceiver(receiver); } catch (Throwable ignored) {}
            receiver = null;
        }
        if (profileExecutor != null) {
            try { profileExecutor.shutdownNow(); } catch (Throwable ignored) {}
            profileExecutor = null;
        }
        super.handleOnDestroy();
    }

    // BLEE_NATIVE_OFFLINE_PROFILE_IDENTITY_V1
    // Profile imagery is display metadata only. A tiny native worker keeps the
    // signed direct-only profile packet durable and consumes received profile
    // packets even when no payment event occurs. Financial packets remain owned
    // exclusively by BleeMeshDb/BleeMeshService and always suppress profile sends.
    private void startProfileIdentityLoop(Context context) {
        if (profileExecutor != null) return;
        profileExecutor = Executors.newSingleThreadScheduledExecutor();
        profileExecutor.scheduleWithFixedDelay(() -> {
            try {
                BleeProfileIdentityTransport.syncLocalProfilePacket(context);
                boolean changed = BleeProfileIdentityTransport.processIncoming(context);
                if (changed && mainHandler != null) {
                    mainHandler.post(this::emitEnrichedPeerSnapshot);
                }
            } catch (Throwable ignored) {}
        }, 0L, 1500L, TimeUnit.MILLISECONDS);
    }

    private void emitEnrichedPeerSnapshot() {
        BleeMeshDb db = new BleeMeshDb(getContext());
        try {
            for (org.json.JSONObject item : BleeMeshService.nearbyPeersSnapshot()) {
                JSObject event = peerObject(BleeProfileIdentityTransport.enrichPeer(db, item));
                event.put("present", true);
                notifyListeners("peerChanged", event, true);
            }
        } finally {
            db.close();
        }
    }

    private static JSObject peerObject(org.json.JSONObject item) {
        JSObject peer = new JSObject();
        peer.put("transportId", item.optString("transportId", ""));
        peer.put("wallet", item.optString("wallet", ""));
        peer.put("displayName", item.optString("displayName", ""));
        peer.put("avatar", item.optString("avatar", ""));
        peer.put("rssi", item.optInt("rssi", 0));
        peer.put("lastSeen", item.optLong("lastSeen", 0L));
        peer.put("transport", "ble");
        return peer;
    }

    @PluginMethod
    public void start(PluginCall call) {
        try {
            BleeMeshService.start(getContext());
            BleeProfileIdentityTransport.syncLocalProfilePacket(getContext());
            JSObject result = new JSObject();
            result.put("running", true);
            result.put("protocol", "blee-mesh-v2");
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to start Blee Mesh v2: " + error.getMessage());
        }
    }

    @PluginMethod
    public void ensureNotificationPermission(PluginCall call) {
        if (Build.VERSION.SDK_INT < 33 || getPermissionState("notifications") == PermissionState.GRANTED) {
            call.resolve();
            return;
        }
        requestPermissionForAlias("notifications", call, "notificationPermissionCallback");
    }

    @PermissionCallback
    private void notificationPermissionCallback(PluginCall call) {
        JSObject result = new JSObject();
        result.put("granted", Build.VERSION.SDK_INT < 33 || getPermissionState("notifications") == PermissionState.GRANTED);
        call.resolve(result);
    }

    @PluginMethod
    public void manualRefresh(PluginCall call) {
        try {
            BleeMeshService.start(getContext());
            BleeProfileIdentityTransport.syncLocalProfilePacket(getContext());
            if (BleeProfileIdentityTransport.processIncoming(getContext())) emitEnrichedPeerSnapshot();

            Intent refresh = new Intent(BleeMeshService.ACTION_LEDGER_CHANGED);
            refresh.setPackage(getContext().getPackageName());
            refresh.putExtra(BleeMeshService.EXTRA_PAYMENT_ID, "");
            refresh.putExtra(BleeMeshService.EXTRA_EVENT_TYPE, "MANUAL_REFRESH");
            getContext().sendBroadcast(refresh);

            JSObject result = new JSObject();
            result.put("refreshed", true);
            result.put("running", BleeMeshService.running);
            result.put("peerCount", BleeMeshService.nearbyPeersSnapshot().size());
            result.put("at", System.currentTimeMillis());
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to refresh Blee state: " + error.getMessage());
        }
    }

    @PluginMethod
    public void status(PluginCall call) {
        try {
            BleeMeshDb db = new BleeMeshDb(getContext());
            JSObject result = new JSObject();
            result.put("running", BleeMeshService.running);
            result.put("protocol", "blee-mesh-v2");
            result.put("wallet", db.activeWallet());
            result.put("broadcastMode", "SENDER_FUNDED_RAW_TX");
            result.put("senderPaysGas", true);
            result.put("relayPaysGas", false);
            db.close();
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to read Blee Mesh status: " + error.getMessage());
        }
    }

    @PluginMethod
    public void diagnostics(PluginCall call) {
        try {
            org.json.JSONObject snapshot = BleeMeshService.diagnosticsSnapshot(getContext());
            JSObject result = new JSObject();
            java.util.Iterator<String> keys = snapshot.keys();
            while (keys.hasNext()) {
                String key = keys.next();
                result.put(key, snapshot.opt(key));
            }
            call.resolve(result);
        } catch (Exception error) {
            call.reject("Unable to read BLE diagnostics", error);
        }
    }

    @PluginMethod
    public void rearmBluetooth(PluginCall call) {
        try {
            BleeMeshService.requestBluetoothRearm(getContext());
            JSObject result = new JSObject();
            result.put("requested", true);
            call.resolve(result);
        } catch (Exception error) {
            call.reject("Unable to restart Bluetooth discovery", error);
        }
    }

    @PluginMethod
    public void nearbyPeers(PluginCall call) {
        try {
            BleeProfileIdentityTransport.syncLocalProfilePacket(getContext());
            BleeProfileIdentityTransport.processIncoming(getContext());
            JSArray peers = new JSArray();
            BleeMeshDb db = new BleeMeshDb(getContext());
            try {
                for (org.json.JSONObject item : BleeMeshService.nearbyPeersSnapshot()) {
                    peers.put(peerObject(BleeProfileIdentityTransport.enrichPeer(db, item)));
                }
            } finally {
                db.close();
            }
            JSObject result = new JSObject();
            result.put("peers", peers);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to read native BLE peers: " + error.getMessage());
        }
    }

    @PluginMethod
    public void pendingEnvelopes(PluginCall call) {
        try {
            BleeMeshDb db = new BleeMeshDb(getContext());
            List<String> pending = db.pendingEnvelopes();
            db.close();
            JSArray packets = new JSArray();
            for (String raw : pending) packets.put(raw);
            JSObject result = new JSObject();
            result.put("packets", packets);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to load pending Blee envelopes: " + error.getMessage());
        }
    }

    @PluginMethod
    public void rejectEnvelope(PluginCall call) {
        String messageId = call.getString("messageId", "");
        String reason = call.getString("reason", "Payment authorization could not be verified");
        if (messageId.isEmpty()) {
            call.reject("Missing messageId");
            return;
        }
        try {
            BleeMeshDb db = new BleeMeshDb(getContext());
            boolean rejected = db.rejectPendingEnvelope(messageId, reason);
            db.close();
            JSObject result = new JSObject();
            result.put("rejected", rejected);
            if (rejected) {
                JSObject event = new JSObject();
                event.put("paymentId", "");
                event.put("eventType", "RECIPIENT_VERIFICATION_FAILED");
                notifyListeners("ledgerChanged", event, true);
            }
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to reject invalid Blee payment: " + error.getMessage());
        }
    }

    @PluginMethod
    public void acceptEnvelope(PluginCall call) {
        String messageId = call.getString("messageId", "");
        if (messageId.isEmpty()) {
            call.reject("Missing messageId");
            return;
        }
        try {
            BleeMeshDb db = new BleeMeshDb(getContext());
            String deviceId = BleeDeviceIdentity.deviceId(getContext());
            String publicKey = BleeDeviceIdentity.publicKey();
            BleeMeshDb.AcceptedPayment accepted = db.acceptVerifiedEnvelope(messageId, deviceId, publicKey);
            db.close();
            JSObject result = new JSObject();
            result.put("accepted", accepted.accepted);
            result.put("paymentId", accepted.paymentId);
            if (accepted.accepted) {
                JSObject event = new JSObject();
                event.put("paymentId", accepted.paymentId);
                event.put("eventType", "RECIPIENT_RECEIVED");
                notifyListeners("ledgerChanged", event, true);
                if (accepted.newlyAccepted) {
                    BleePaymentNotifier.received(getContext(), accepted.paymentId, accepted.amount, accepted.counterparty);
                }
            }
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to accept verified Blee payment: " + error.getMessage());
        }
    }
}
