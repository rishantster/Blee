package com.blee.payments;

import android.content.Intent;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Wallet-canonical local contacts API.
 *
 * Contacts are durable local display metadata backed by the same Blee SQLite
 * database as peer identities. Saving a contact never implies that the wallet
 * is currently nearby or reachable.
 */
@CapacitorPlugin(name = "BleeContacts")
public final class BleeContactsPlugin extends Plugin {

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
            call.reject("Unable to load Blee contact candidates: " + error.getMessage());
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
            call.resolve(result);
            publishContactChanged();
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
            publishContactChanged();
        } catch (Throwable error) {
            call.reject("Unable to remove Blee contact: " + error.getMessage());
        } finally {
            db.close();
        }
    }

    private void publishContactChanged() {
        Intent refresh = new Intent(BleeMeshService.ACTION_LEDGER_CHANGED);
        refresh.setPackage(getContext().getPackageName());
        refresh.putExtra(BleeMeshService.EXTRA_PAYMENT_ID, "");
        refresh.putExtra(BleeMeshService.EXTRA_EVENT_TYPE, "CONTACT_UPDATED");
        getContext().sendBroadcast(refresh);
    }
}
