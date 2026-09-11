#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Final hardening: missing {label} anchor")
    return text.replace(old, new, 1)


def harden_payments() -> None:
    path = ROOT / "src/lib/payments.ts"
    text = path.read_text()

    marker = "BLEE_COURIER_NEVER_SIGNS_V1"
    if marker not in text:
        anchor = "  const walletClient = createWalletClient({ account: relayer, chain: arcTestnet, transport: http(ARC_RPC) });"
        guard = '''  // BLEE_COURIER_NEVER_SIGNS_V1\n  // A courier may broadcast only the sender's already-signed raw transaction.\n  // Falling through to writeContract with Phone C's account would make C sign\n  // and pay gas, violating the Blee protocol. A fresh transaction may only be\n  // created when the active relayer is the original sender.\n  if (relayer.address.toLowerCase() !== auth.from.toLowerCase()) {\n    throw new Error('Blee courier cannot sign or fund another wallet payment. Waiting for a valid sender-signed settlement transaction.');\n  }\n\n'''
        text = replace_once(text, anchor, guard + anchor, "courier gas guard")

    text = text.replace("for (const log of logs.slice(0, 100)) {", "for (const log of logs) {")
    path.write_text(text)

    if marker not in path.read_text():
        raise SystemExit("Final hardening: courier gas invariant was not installed")
    print("final hardening: courier can never sign/pay another wallet settlement")


def harden_wallet_backup() -> None:
    path = ROOT / "src/lib/walletRecovery.ts"
    text = path.read_text()
    marker = "BLEE_BACKUP_VALIDATION_V1"
    if marker in text:
        return

    anchor = "const decoder = new TextDecoder();"
    helpers = r'''

// BLEE_BACKUP_VALIDATION_V1
const MAX_BACKUP_CHARS = 200_000;
const MIN_PBKDF2_ITERATIONS = 100_000;
const MAX_PBKDF2_ITERATIONS = 2_000_000;

function decodeBackupBase64(value: string, field: string): Uint8Array {
  if (!value || value.length > 4096) throw new Error(`Wallet backup ${field} is invalid`);
  try {
    return fromBase64(value);
  } catch {
    throw new Error(`Wallet backup ${field} is invalid`);
  }
}

function validateImportedVault(vault: StoredVault) {
  if (vault.version !== 1 && vault.version !== 2) throw new Error("Unsupported Blee wallet backup version");
  if (!/^0x[0-9a-fA-F]{40}$/.test(vault.address || "")) throw new Error("Wallet backup address is invalid");
  if (!Number.isInteger(vault.iterations) || vault.iterations < MIN_PBKDF2_ITERATIONS || vault.iterations > MAX_PBKDF2_ITERATIONS) {
    throw new Error("Wallet backup key-derivation parameters are invalid");
  }
  const salt = decodeBackupBase64(vault.salt, "salt");
  const iv = decodeBackupBase64(vault.iv, "IV");
  const ciphertext = decodeBackupBase64(vault.ciphertext, "ciphertext");
  if (salt.byteLength !== 16) throw new Error("Wallet backup salt has an invalid length");
  if (iv.byteLength !== 12) throw new Error("Wallet backup IV has an invalid length");
  if (ciphertext.byteLength < 32 || ciphertext.byteLength > 512) throw new Error("Wallet backup ciphertext has an invalid length");
  if (vault.createdAt !== undefined && (!Number.isFinite(vault.createdAt) || vault.createdAt <= 0)) {
    throw new Error("Wallet backup timestamp is invalid");
  }
}
'''
    text = replace_once(text, anchor, anchor + helpers, "wallet backup helper")

    start = "export async function importEncryptedWalletBackup(backupInput: string): Promise<string> {\n  await ensureStore();"
    replacement = "export async function importEncryptedWalletBackup(backupInput: string): Promise<string> {\n  if (!backupInput || backupInput.length > MAX_BACKUP_CHARS) throw new Error(\"Wallet backup is empty or too large\");\n  await ensureStore();"
    text = replace_once(text, start, replacement, "wallet backup size guard")

    old = '''  const vault = parsed.vault;\n  if (!/^0x[0-9a-fA-F]{40}$/.test(vault.address) || !vault.salt || !vault.iv || !vault.ciphertext) {\n    throw new Error("Wallet backup is incomplete");\n  }\n  await BleeStore.setValue({ key: VAULT_KEY, value: JSON.stringify(vault) });'''
    new = '''  const vault = parsed.vault;\n  if (!vault.address || !vault.salt || !vault.iv || !vault.ciphertext) throw new Error("Wallet backup is incomplete");\n  validateImportedVault(vault);\n  await BleeStore.setValue({ key: VAULT_KEY, value: JSON.stringify(vault) });'''
    text = replace_once(text, old, new, "wallet backup validation")
    path.write_text(text)
    print("final hardening: encrypted wallet backup input is strictly bounded and validated")


def harden_monotonic_store() -> None:
    path = ROOT / "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java"
    text = path.read_text()
    marker = "BLEE_MONOTONIC_PAYMENT_STATE_V1"
    if marker in text:
        return

    helper_anchor = "    private static String message(Throwable error) {"
    helper = r'''    // BLEE_MONOTONIC_PAYMENT_STATE_V1
    // Native mesh events may advance while the WebView still holds an older
    // projection. Never allow a stale replacePayments() call to move a payment
    // backwards in its lifecycle.
    private static int paymentStateRank(String state) {
        String s = state == null ? "" : state.trim().toLowerCase(Locale.ROOT);
        if (s.contains("chain_confirmed") || (s.contains("chain") && s.contains("confirm"))) return 100;
        if (s.contains("revert")) return 95;
        if (s.contains("expired") || s.contains("fail") || s.contains("cancel")) return 90;
        if (s.contains("settled_relay_reported") || s.contains("settled")) return 80;
        if (s.contains("settlement_submitted") || s.contains("submitted")) return 70;
        if (s.contains("acknowledged") || s.contains("acknowledge")) return 60;
        if (s.contains("delivered_offline") || s.contains("delivered")) return 50;
        if (s.contains("queued")) return 40;
        if (s.contains("signed")) return 30;
        if (s.contains("created")) return 20;
        return 10;
    }

'''
    text = replace_once(text, helper_anchor, helper + helper_anchor, "monotonic state helper")

    anchor = '''                String paymentKey = direction + ":" + paymentId;\n\n                ContentValues values = new ContentValues();'''
    replacement = '''                String paymentKey = direction + ":" + paymentId;\n\n                // A native ACK/settlement may have advanced this row after the\n                // React caller loaded its snapshot. Preserve the newer native row.\n                try (Cursor existing = database.query("payments", new String[] { "state" }, "payment_key=?", new String[] { paymentKey }, null, null, null)) {\n                    if (existing.moveToFirst() && paymentStateRank(existing.getString(0)) > paymentStateRank(state)) {\n                        continue;\n                    }\n                }\n\n                ContentValues values = new ContentValues();'''
    text = replace_once(text, anchor, replacement, "replacePayments monotonic guard")
    path.write_text(text)
    print("final hardening: stale React snapshots cannot downgrade native payment state")


def patch_web_version() -> None:
    package = ROOT / "package.json"
    data = json.loads(package.read_text())
    data["version"] = "2.5.1"
    package.write_text(json.dumps(data, indent=2) + "\n")

    native = ROOT / "scripts/configure-native.mjs"
    if native.is_file():
        text = native.read_text()
        text = re.sub(r"versionCode\s+\d+", "versionCode 15", text)
        text = re.sub(r'versionName\s+\"[^\"]+\"', 'versionName "2.5.1"', text)
        native.write_text(text)


def harden_web() -> None:
    harden_payments()
    harden_wallet_backup()
    harden_monotonic_store()
    patch_web_version()


def locate_activity() -> Path:
    matches = list((ROOT / "android/app/src/main/java").rglob("MainActivity.java"))
    if len(matches) != 1:
        raise SystemExit(f"Final hardening: expected one MainActivity.java, found {len(matches)}")
    return matches[0]


def harden_mesh_db(native_dir: Path) -> None:
    path = native_dir / "BleeMeshDb.java"
    text = path.read_text()
    marker = "BLEE_CANONICAL_SETTLEMENT_VERIFY_V1"
    if marker in text:
        return

    old = '''                String txHash = receipt.optString("txHash", "");\n                if (!paymentId.isEmpty() && !txHash.isEmpty()) {\n                    persistSettlementReceipt(paymentId, receipt, now);'''
    new = '''                String txHash = receipt.optString("txHash", "");\n                String expectedHash = expectedSettlementHash(paymentId);\n                if (!paymentId.isEmpty() && !txHash.isEmpty() && !expectedHash.isEmpty() && expectedHash.equalsIgnoreCase(txHash)) {\n                    persistSettlementReceipt(paymentId, receipt, now);'''
    text = replace_once(text, old, new, "settlement receipt expected-hash check")

    old_record = '''            if (paymentId.isEmpty() || txHash.isEmpty()) return;\n            receipt.put("paymentId", paymentId);'''
    new_record = '''            if (paymentId.isEmpty() || txHash.isEmpty()) return;\n            String expectedHash = expectedSettlementHash(paymentId);\n            if (expectedHash.isEmpty() || !expectedHash.equalsIgnoreCase(txHash)) return;\n            receipt.put("paymentId", paymentId);'''
    text = replace_once(text, old_record, new_record, "local receipt expected-hash check")

    insert_anchor = "    synchronized void markSettlementAttempt(String paymentId, boolean success, String error) {"
    methods = r'''    // BLEE_CANONICAL_SETTLEMENT_VERIFY_V1
    synchronized List<String> unverifiedSettlementReceipts(int limit) {
        List<String> rows = new ArrayList<>();
        try (Cursor c = db().query(
            "settlement_receipts",
            new String[] { "payment_id","tx_hash","receipt" },
            "verified_at IS NULL",
            null, null, null, "reported_at ASC", String.valueOf(Math.max(1, limit))
        )) {
            while (c.moveToNext()) {
                JSONObject item = new JSONObject();
                item.put("paymentId", c.getString(0));
                item.put("txHash", c.getString(1));
                item.put("reportedReceipt", c.getString(2));
                rows.add(item.toString());
            }
        } catch (Throwable ignored) {}
        return rows;
    }

    synchronized boolean markChainConfirmed(String paymentId, String txHash, JSONObject canonicalReceipt, long now) {
        if (paymentId == null || paymentId.isEmpty() || txHash == null || txHash.isEmpty()) return false;
        String expectedHash = expectedSettlementHash(paymentId);
        if (expectedHash.isEmpty() || !expectedHash.equalsIgnoreCase(txHash)) return false;
        if (!"0x1".equalsIgnoreCase(canonicalReceipt.optString("status", ""))) return false;

        ContentValues verified = new ContentValues();
        verified.put("verified_at", now);
        verified.put("receipt", canonicalReceipt.toString());
        db().update("settlement_receipts", verified, "payment_id=? AND tx_hash=?", new String[] { paymentId, txHash });

        return updateAnyPaymentState(
            paymentId, "chain_confirmed", "CHAIN_CONFIRMED", now,
            deviceSource(canonicalReceipt), canonicalReceipt.toString()
        );
    }

    private static String deviceSource(JSONObject payload) {
        String value = payload.optString("verifiedBy", "");
        return value.isEmpty() ? null : value;
    }

    private String expectedSettlementHash(String paymentId) {
        if (paymentId == null || paymentId.isEmpty()) return "";
        // Prefer the durable local payment projection.
        try (Cursor c = db().query("payments", new String[] { "payload" }, "payment_id=?", new String[] { paymentId }, null, null, "updated_at DESC", "1")) {
            if (c.moveToFirst()) {
                String hash = settlementHashFromPayment(new JSONObject(c.getString(0)));
                if (!hash.isEmpty()) return hash;
            }
        } catch (Throwable ignored) {}

        // Courier nodes may not own the payment, but they have the signed source
        // envelope in mesh_inbox. This is enough to pin the only acceptable hash.
        try (Cursor c = db().query("mesh_inbox", new String[] { "packet" }, "payment_id=? AND packet_type=?", new String[] { paymentId, "PAYMENT_ENVELOPE" }, null, null, "received_at DESC", "1")) {
            if (c.moveToFirst()) {
                JSONObject packet = new JSONObject(c.getString(0));
                JSONObject payment = new JSONObject(packet.optString("payload", "{}"));
                return settlementHashFromPayment(payment);
            }
        } catch (Throwable ignored) {}
        return "";
    }

    private static String settlementHashFromPayment(JSONObject payment) {
        try {
            JSONObject auth = authorization(payment);
            if (auth == null) return "";
            JSONObject broadcast = auth.optJSONObject("broadcast");
            if (broadcast == null || !"SENDER_FUNDED_RAW_TX".equals(broadcast.optString("mode", ""))) return "";
            String hash = broadcast.optString("txHash", "");
            return hash.matches("^0x[0-9a-fA-F]{64}$") ? hash : "";
        } catch (Throwable ignored) {
            return "";
        }
    }

'''
    text = replace_once(text, insert_anchor, methods + insert_anchor, "canonical settlement DB methods")
    path.write_text(text)
    print("final hardening: relay receipts are pinned to the sender-signed transaction hash")


def harden_mesh_service(native_dir: Path) -> None:
    path = native_dir / "BleeMeshService.java"
    text = path.read_text()
    marker = "BLEE_NATIVE_LIFECYCLE_HARDENING_V1"
    if marker in text:
        return

    text = text.replace("import android.content.Context;", "import android.content.BroadcastReceiver;\nimport android.content.Context;\nimport android.content.IntentFilter;")

    constants_anchor = "    private static final long SETTLEMENT_RETRY_MS = 12_000L;"
    constants = '''    private static final long SETTLEMENT_RETRY_MS = 12_000L;\n    // BLEE_NATIVE_LIFECYCLE_HARDENING_V1\n    private static final long PEER_STALE_MS = 60_000L;\n    private static final long ASSEMBLY_TTL_MS = 30_000L;\n    private static final int MAX_ASSEMBLIES = 64;\n    private static final int MAX_ASSEMBLIES_PER_PEER = 8;\n    private static final int MAX_FRAGMENTS = 512;\n    private static final int MAX_FRAME_CHARS = 512;\n    private static final int MAX_PACKET_BYTES = 48 * 1024;\n    private static final int MAX_ENCODED_PACKET_CHARS = 70 * 1024;'''
    text = replace_once(text, constants_anchor, constants, "native hardening constants")

    map_anchor = "    private final Map<String, Long> lastConnect = Collections.synchronizedMap(new HashMap<String, Long>());"
    text = replace_once(text, map_anchor, map_anchor + "\n    private final Map<String, Long> peerSeen = Collections.synchronizedMap(new HashMap<String, Long>());", "peer seen map")

    field_anchor = "    private volatile boolean settlementScheduled = false;"
    receiver = r'''    private volatile boolean settlementScheduled = false;

    private final BroadcastReceiver bluetoothStateReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            if (!BluetoothAdapter.ACTION_STATE_CHANGED.equals(intent.getAction())) return;
            int state = intent.getIntExtra(BluetoothAdapter.EXTRA_STATE, BluetoothAdapter.ERROR);
            if (state == BluetoothAdapter.STATE_OFF || state == BluetoothAdapter.STATE_TURNING_OFF) {
                scanning = false;
                stopBluetooth();
                peers.clear();
                peerSeen.clear();
                lastConnect.clear();
            } else if (state == BluetoothAdapter.STATE_ON) {
                scanning = false;
                handler.postDelayed(() -> startBluetooth(), 350L);
            }
        }
    };'''
    text = replace_once(text, field_anchor, receiver, "Bluetooth state receiver")

    oncreate_anchor = "        createNotificationChannels();\n        startForeground(SERVICE_NOTIFICATION_ID, serviceNotification(\"Nearby payments active\"));\n        observeConnectivity();"
    oncreate_new = '''        createNotificationChannels();\n        startForeground(SERVICE_NOTIFICATION_ID, serviceNotification("Nearby payments active"));\n        IntentFilter bluetoothFilter = new IntentFilter(BluetoothAdapter.ACTION_STATE_CHANGED);\n        if (Build.VERSION.SDK_INT >= 33) registerReceiver(bluetoothStateReceiver, bluetoothFilter, Context.RECEIVER_NOT_EXPORTED);\n        else registerReceiver(bluetoothStateReceiver, bluetoothFilter);\n        observeConnectivity();'''
    text = replace_once(text, oncreate_anchor, oncreate_new, "Bluetooth receiver registration")

    ondestroy_anchor = "        handler.removeCallbacksAndMessages(null);\n        stopBluetooth();"
    ondestroy_new = "        handler.removeCallbacksAndMessages(null);\n        try { unregisterReceiver(bluetoothStateReceiver); } catch (Throwable ignored) {}\n        stopBluetooth();"
    text = replace_once(text, ondestroy_anchor, ondestroy_new, "Bluetooth receiver unregister")

    loop_anchor = "                db.bootstrapOutgoing(deviceId, publicKey);\n                if (!scanning) startBluetooth();"
    loop_new = "                long loopNow = System.currentTimeMillis();\n                cleanupEphemeralState(loopNow);\n                db.bootstrapOutgoing(deviceId, publicKey);\n                if (!scanning) startBluetooth();"
    text = replace_once(text, loop_anchor, loop_new, "ephemeral cleanup loop")

    observe_anchor = "    private void observeConnectivity() {"
    cleanup = r'''    private void cleanupEphemeralState(long now) {
        synchronized (peerSeen) {
            for (String address : new ArrayList<String>(peerSeen.keySet())) {
                Long seenAt = peerSeen.get(address);
                if (seenAt == null || now - seenAt > PEER_STALE_MS) {
                    peerSeen.remove(address);
                    peers.remove(address);
                    lastConnect.remove(address);
                }
            }
        }
        synchronized (assemblies) {
            for (String key : new ArrayList<String>(assemblies.keySet())) {
                Assembly assembly = assemblies.get(key);
                if (assembly == null || now - assembly.createdAt > ASSEMBLY_TTL_MS) assemblies.remove(key);
            }
        }
    }

    private int assembliesForPeer(String address) {
        int count = 0;
        String prefix = address + ":";
        synchronized (assemblies) {
            for (String key : assemblies.keySet()) if (key.startsWith(prefix)) count++;
        }
        return count;
    }

'''
    text = replace_once(text, observe_anchor, cleanup + observe_anchor, "ephemeral cleanup helpers")

    text = text.replace("        if (adapter == null || !adapter.isEnabled()) return;", "        if (adapter == null || !adapter.isEnabled()) { scanning = false; return; }")
    text = text.replace("        gattServer = null;", "        gattServer = null;\n        scanner = null;\n        advertiser = null;", 1)

    scan_anchor = "            peers.put(device.getAddress(), device);\n            maybeConnect(device);"
    text = replace_once(text, scan_anchor, "            peers.put(device.getAddress(), device);\n            peerSeen.put(device.getAddress(), System.currentTimeMillis());\n            maybeConnect(device);", "peer last-seen update")

    frame_old = '''        if (total <= 0 || total > 512 || index < 0 || index >= total) return false;\n        String key = device.getAddress() + ":" + messageId;\n        Assembly assembly = assemblies.get(key);\n        if (assembly == null || assembly.total != total) {\n            assembly = new Assembly(total);\n            assemblies.put(key, assembly);\n        }\n        assembly.parts[index] = parts[4];\n        if (!assembly.complete()) return true;'''
    frame_new = '''        if (messageId.isEmpty() || messageId.length() > 160) return false;\n        if (total <= 0 || total > MAX_FRAGMENTS || index < 0 || index >= total) return false;\n        String chunk = parts[4];\n        if (chunk.length() > MAX_FRAME_CHARS) return false;\n        long now = System.currentTimeMillis();\n        cleanupEphemeralState(now);\n        String address = device.getAddress();\n        String key = address + ":" + messageId;\n        Assembly assembly = assemblies.get(key);\n        if (assembly == null || assembly.total != total) {\n            if (assemblies.size() >= MAX_ASSEMBLIES || assembliesForPeer(address) >= MAX_ASSEMBLIES_PER_PEER) return false;\n            assembly = new Assembly(total, now);\n            assemblies.put(key, assembly);\n        }\n        if (assembly.parts[index] == null) assembly.encodedChars += chunk.length();\n        if (assembly.encodedChars > MAX_ENCODED_PACKET_CHARS) { assemblies.remove(key); return false; }\n        assembly.parts[index] = chunk;\n        if (!assembly.complete()) return true;'''
    text = replace_once(text, frame_old, frame_new, "bounded frame assembly")

    decode_old = "            String raw = new String(Base64.decode(b64.toString(), Base64.NO_WRAP), StandardCharsets.UTF_8);\n            BleeMeshDb.ProcessResult result = db.receive(raw, deviceId, publicKey);"
    decode_new = "            byte[] decoded = Base64.decode(b64.toString(), Base64.NO_WRAP);\n            if (decoded.length == 0 || decoded.length > MAX_PACKET_BYTES) return false;\n            String raw = new String(decoded, StandardCharsets.UTF_8);\n            BleeMeshDb.ProcessResult result = db.receive(raw, deviceId, publicKey);"
    text = replace_once(text, decode_old, decode_new, "decoded packet size guard")

    assembly_old = '''    private static final class Assembly {\n        final int total;\n        final String[] parts;\n        Assembly(int total) { this.total = total; this.parts = new String[total]; }\n        boolean complete() { for (String p : parts) if (p == null) return false; return true; }\n    }'''
    assembly_new = '''    private static final class Assembly {\n        final int total;\n        final String[] parts;\n        final long createdAt;\n        int encodedChars = 0;\n        Assembly(int total, long createdAt) { this.total = total; this.createdAt = createdAt; this.parts = new String[total]; }\n        boolean complete() { for (String p : parts) if (p == null) return false; return true; }\n    }'''
    text = replace_once(text, assembly_old, assembly_new, "bounded Assembly class")

    # A notification inserted by the earlier UI patch was emitted on the relay
    # phone before its local ledger was actually promoted to CHAIN_CONFIRMED.
    text = re.sub(r'\s*paymentNotification\("Payment confirmed", "Your Blee payment is confirmed on Arc Testnet\.", paymentId\);', '', text)

    settlement_end = '''            } catch (Throwable error) {\n                Log.d(TAG, "sender-funded settlement candidate skipped: " + error.getMessage());\n            }\n        }\n    }\n\n    private String sendRawTransaction'''
    settlement_replacement = '''            } catch (Throwable error) {\n                Log.d(TAG, "sender-funded settlement candidate skipped: " + error.getMessage());\n            }\n        }\n        reconcileCanonicalReceipts();\n    }\n\n    private void reconcileCanonicalReceipts() {\n        if (!networkAvailable) return;\n        for (String raw : db.unverifiedSettlementReceipts(64)) {\n            try {\n                JSONObject item = new JSONObject(raw);\n                String paymentId = item.optString("paymentId", "");\n                String txHash = item.optString("txHash", "");\n                if (paymentId.isEmpty() || !isTxHash(txHash)) continue;\n                JSONObject receipt = transactionReceipt(txHash);\n                if (receipt == null || !"0x1".equalsIgnoreCase(receipt.optString("status", ""))) continue;\n                receipt.put("verifiedBy", deviceId);\n                if (db.markChainConfirmed(paymentId, txHash, receipt, System.currentTimeMillis())) {\n                    notifyLedgerChanged(paymentId, "CHAIN_CONFIRMED");\n                    paymentNotification("Payment confirmed", "Your Blee payment is confirmed on Arc Testnet.", paymentId);\n                }\n            } catch (Throwable error) {\n                Log.d(TAG, "chain confirmation reconciliation skipped: " + error.getMessage());\n            }\n        }\n    }\n\n    private String sendRawTransaction'''
    text = replace_once(text, settlement_end, settlement_replacement, "canonical receipt reconciliation")

    # Android notification small icons must be a simple monochrome drawable.
    text = text.replace(".setSmallIcon(getApplicationInfo().icon)", ".setSmallIcon(R.drawable.blee_notification)")
    path.write_text(text)
    print("final hardening: BLE radio recovery, stale peer cleanup and bounded fragmentation installed")


def install_notification_icon() -> None:
    target = ROOT / "android/app/src/main/res/drawable/blee_notification.xml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('''<?xml version="1.0" encoding="utf-8"?>\n<vector xmlns:android="http://schemas.android.com/apk/res/android"\n    android:width="24dp" android:height="24dp" android:viewportWidth="24" android:viewportHeight="24">\n    <path android:fillColor="#FFFFFFFF" android:pathData="M5,3h7.1c3.7,0 5.9,1.7 5.9,4.5 0,1.8 -0.9,3.1 -2.4,3.9 2.1,0.7 3.4,2.2 3.4,4.5 0,3.2 -2.5,5.1 -6.7,5.1H5V3zM8,6v4h4c2,0 3,-0.6 3,-2s-1,-2 -3,-2H8zM8,13v5h4.3c2.4,0 3.7,-0.8 3.7,-2.5S14.7,13 12.3,13H8z"/>\n</vector>\n''')


def verify_android(activity: Path) -> None:
    native_dir = activity.parent
    service = (native_dir / "BleeMeshService.java").read_text()
    db = (native_dir / "BleeMeshDb.java").read_text()
    required_service = (
        "BLEE_NATIVE_LIFECYCLE_HARDENING_V1", "bluetoothStateReceiver", "PEER_STALE_MS",
        "MAX_ASSEMBLIES", "MAX_PACKET_BYTES", "reconcileCanonicalReceipts", "CHAIN_CONFIRMED",
        "R.drawable.blee_notification",
    )
    missing = [x for x in required_service if x not in service]
    if missing:
        raise SystemExit(f"Final hardening Android service incomplete: {missing}")
    required_db = ("BLEE_CANONICAL_SETTLEMENT_VERIFY_V1", "expectedSettlementHash", "markChainConfirmed", "unverifiedSettlementReceipts")
    missing = [x for x in required_db if x not in db]
    if missing:
        raise SystemExit(f"Final hardening Mesh DB incomplete: {missing}")
    if not (ROOT / "android/app/src/main/res/drawable/blee_notification.xml").is_file():
        raise SystemExit("Final hardening notification icon missing")


def harden_android() -> None:
    activity = locate_activity()
    harden_mesh_db(activity.parent)
    harden_mesh_service(activity.parent)
    install_notification_icon()
    verify_android(activity)


def verify_web() -> None:
    payments = (ROOT / "src/lib/payments.ts").read_text()
    recovery = (ROOT / "src/lib/walletRecovery.ts").read_text()
    store = (ROOT / "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java").read_text()
    if "BLEE_COURIER_NEVER_SIGNS_V1" not in payments:
        raise SystemExit("Final hardening verification: courier gas guard missing")
    if "logs.slice(0, 100)" in payments:
        raise SystemExit("Final hardening verification: incoming transfer scan still truncates at 100")
    if "BLEE_BACKUP_VALIDATION_V1" not in recovery:
        raise SystemExit("Final hardening verification: wallet backup validation missing")
    if "BLEE_MONOTONIC_PAYMENT_STATE_V1" not in store:
        raise SystemExit("Final hardening verification: payment state downgrade guard missing")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--android", action="store_true")
    args = parser.parse_args()
    if not args.web and not args.android:
        args.web = args.android = True
    if args.web:
        harden_web()
        verify_web()
    if args.android:
        harden_android()
    print("Final Blee hardening verified.")


if __name__ == "__main__":
    main()
