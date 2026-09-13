package com.blee.payments;

import android.Manifest;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Build;

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

@CapacitorPlugin(
    name = "BleeMesh",
    permissions = {
        @Permission(alias = "notifications", strings = { Manifest.permission.POST_NOTIFICATIONS })
    }
)
public class BleeMeshPlugin extends Plugin {
    private BroadcastReceiver receiver;

    @Override
    public void load() {
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
                    JSObject event = new JSObject();
                    event.put("transportId", intent.getStringExtra(BleeMeshService.EXTRA_PEER_TRANSPORT_ID));
                    event.put("wallet", intent.getStringExtra(BleeMeshService.EXTRA_PEER_WALLET));
                    event.put("displayName", intent.getStringExtra(BleeMeshService.EXTRA_PEER_DISPLAY_NAME));
                    event.put("avatar", intent.getStringExtra(BleeMeshService.EXTRA_PEER_AVATAR));
                    // BLEE_PRODUCTION_PEER_EVENT_V1
                    event.put("rssi", intent.getIntExtra(BleeMeshService.EXTRA_PEER_RSSI, 0));
                    event.put("lastSeen", intent.getLongExtra(BleeMeshService.EXTRA_PEER_LAST_SEEN, 0L));
                    event.put("present", intent.getBooleanExtra(BleeMeshService.EXTRA_PEER_PRESENT, true));
                    event.put("transport", "ble");
                    notifyListeners("peerChanged", event, true);
                }
            }
        };
        IntentFilter filter = new IntentFilter(BleeMeshService.ACTION_LEDGER_CHANGED);
        filter.addAction(BleeMeshService.ACTION_PEER_CHANGED);
        // BLEE_NATIVE_PEER_BRIDGE_V1
        if (Build.VERSION.SDK_INT >= 33) getContext().registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED);
        else getContext().registerReceiver(receiver, filter);
        BleeMeshService.start(getContext());
    }

    @Override
    protected void handleOnDestroy() {
        if (receiver != null) {
            try { getContext().unregisterReceiver(receiver); } catch (Throwable ignored) {}
            receiver = null;
        }
        super.handleOnDestroy();
    }

    @PluginMethod
    public void start(PluginCall call) {
        try {
            BleeMeshService.start(getContext());
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

    // BLEE_NONDESTRUCTIVE_MANUAL_REFRESH_V2
    // Refresh is deliberately a state re-query, never a logout, vault reset or
    // WebView restart. Existing listeners already know how to rebuild UI state
    // when ACTION_LEDGER_CHANGED is emitted.
    @PluginMethod
    public void manualRefresh(PluginCall call) {
        try {
            BleeMeshService.start(getContext());

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

    // BLEE_CONTACTS_PLUGIN_V1
    @PluginMethod
    public void listContacts(PluginCall call) {
        BleeMeshDb db = new BleeMeshDb(getContext());
        try {
            JSArray contacts = new JSArray();
            for (org.json.JSONObject item : db.listContacts()) contacts.put(item);
            JSObject result = new JSObject();
            result.put("contacts", contacts);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to load Blee contacts: " + error.getMessage());
        } finally {
            db.close();
        }
    }

    @PluginMethod
    public void contactCandidates(PluginCall call) {
        BleeMeshDb db = new BleeMeshDb(getContext());
        try {
            JSArray contacts = new JSArray();
            for (org.json.JSONObject item : db.contactCandidates()) contacts.put(item);
            JSObject result = new JSObject();
            result.put("contacts", contacts);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to load contact candidates: " + error.getMessage());
        } finally {
            db.close();
        }
    }

    @PluginMethod
    public void saveContact(PluginCall call) {
        String wallet = call.getString("wallet", "");
        String displayName = call.getString("displayName", "");
        String avatar = call.getString("avatar", "");
        BleeMeshDb db = new BleeMeshDb(getContext());
        try {
            org.json.JSONObject saved = db.saveContact(wallet, displayName, avatar);
            if (saved == null) {
                call.reject("Invalid Blee contact");
                return;
            }
            JSObject result = new JSObject();
            result.put("contact", saved);
            // BLEE_CONTACT_ACTIVITY_WAKE_V1
            Intent refresh = new Intent(BleeMeshService.ACTION_LEDGER_CHANGED);
            refresh.setPackage(getContext().getPackageName());
            refresh.putExtra(BleeMeshService.EXTRA_PAYMENT_ID, "");
            refresh.putExtra(BleeMeshService.EXTRA_EVENT_TYPE, "CONTACT_UPDATED");
            getContext().sendBroadcast(refresh);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to save Blee contact: " + error.getMessage());
        } finally {
            db.close();
        }
    }

    @PluginMethod
    public void deleteContact(PluginCall call) {
        String wallet = call.getString("wallet", "");
        BleeMeshDb db = new BleeMeshDb(getContext());
        try {
            JSObject result = new JSObject();
            result.put("deleted", db.deleteContact(wallet));
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to remove Blee contact: " + error.getMessage());
        } finally {
            db.close();
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

    // BLEE_BLE_DIAGNOSTICS_PLUGIN_V1
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
            JSArray peers = new JSArray();
            for (org.json.JSONObject item : BleeMeshService.nearbyPeersSnapshot()) {
                JSObject peer = new JSObject();
                peer.put("transportId", item.optString("transportId", ""));
                peer.put("wallet", item.optString("wallet", ""));
                peer.put("displayName", item.optString("displayName", ""));
                peer.put("avatar", item.optString("avatar", ""));
                peer.put("rssi", item.optInt("rssi", 0));
                peer.put("lastSeen", item.optLong("lastSeen", 0L));
                peer.put("transport", "ble");
                peers.put(peer);
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
                // BLEE_VERIFIED_RECEIVE_NOTIFICATION_V1
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
