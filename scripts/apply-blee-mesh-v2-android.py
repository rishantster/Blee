#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "mesh-v2" / "android"
ANDROID = ROOT / "android" / "app" / "src" / "main"


def locate_main_activity() -> Path:
    matches = list((ANDROID / "java").rglob("MainActivity.java"))
    if len(matches) != 1:
        raise SystemExit(f"Expected one MainActivity.java, found {len(matches)}")
    return matches[0]


def app_package(activity: Path) -> str:
    match = re.search(r"^package\s+([A-Za-z0-9_.]+);", activity.read_text(), re.M)
    if not match:
        raise SystemExit("Could not determine Android app package")
    return match.group(1)


def install_templates(activity: Path, package: str) -> None:
    target_dir = activity.parent
    required = (
        "BleeDeviceIdentity.java.in",
        "BleeMeshDb.java.in",
        "BleeMeshService.java.in",
        "BleeMeshPlugin.java.in",
        "BleeBootReceiver.java.in",
    )
    for name in required:
        source = TEMPLATES / name
        if not source.exists():
            raise SystemExit(f"Missing Mesh v2 Android template: {name}")
        text = source.read_text().replace("__BLEE_APP_PACKAGE__", package)
        target = target_dir / name.removesuffix(".in")
        target.write_text(text)
        print(f"mesh v2 android: {target.relative_to(ROOT)}")


def harden_sender_funded_service(activity: Path) -> None:
    path = activity.parent / "BleeMeshService.java"
    text = path.read_text()

    text = text.replace(
        "List<String> candidates = db.settlementCandidates(now, 64);",
        "List<String> candidates = db.settlementCandidates(now, 512);",
        1,
    )

    old = "db.markSettlementAttempt(paymentId, true, null);\n                settlementRetryAfter.remove(paymentId);"
    new = "db.markSettlementAttempt(paymentId, true, null);\n                settlementRetryAfter.put(paymentId, Long.MAX_VALUE);"
    if old not in text:
        raise SystemExit("Could not locate sender-funded settlement success marker")
    text = text.replace(old, new, 1)
    path.write_text(text)


def harden_mesh_db(activity: Path) -> None:
    path = activity.parent / "BleeMeshDb.java"
    text = path.read_text()

    # Sender side: the mesh packet, QUEUED event and settlement job must either
    # all exist or none exist. A process death cannot leave a transmissible
    # outbox row without its corresponding durable ledger state.
    old_sender = '''                try {
                    JSONObject packet = packet(
                        "PAYMENT_ENVELOPE", messageId, paymentId, destination,
                        payment.toString(), now, expiry, 0, 6, 3, deviceId, publicKey
                    );
                    enqueue(packet);
                    addEvent(paymentId, "QUEUED", now, deviceId, packet.toString());
                    upsertSettlementJob(paymentId, auth.toString(), now);
                } catch (Throwable ignored) {}
'''
    new_sender = '''                // BLEE_ATOMIC_OUTBOX_V1
                SQLiteDatabase database = db();
                boolean ownTransaction = !database.inTransaction();
                if (ownTransaction) database.beginTransaction();
                try {
                    JSONObject packet = packet(
                        "PAYMENT_ENVELOPE", messageId, paymentId, destination,
                        payment.toString(), now, expiry, 0, 6, 3, deviceId, publicKey
                    );
                    enqueue(packet);
                    addEvent(paymentId, "QUEUED", now, deviceId, packet.toString());
                    upsertSettlementJob(paymentId, auth.toString(), now);
                    if (ownTransaction) database.setTransactionSuccessful();
                } catch (Throwable ignored) {
                } finally {
                    if (ownTransaction && database.inTransaction()) database.endTransaction();
                }
'''
    if old_sender not in text:
        raise SystemExit("Could not locate mesh sender persistence block")
    text = text.replace(old_sender, new_sender, 1)

    # Recipient side: incoming payment projection, RECIPIENT_RECEIVED event and
    # the durable DELIVERY_ACK outbox entry commit in one SQLite transaction.
    # The transport cannot ACK a payment that was not durably recorded.
    start = text.find('            if (!paymentExists("incoming:" + paymentId)) {')
    end_marker = '            return new AcceptedPayment(true, paymentId);'
    end = text.find(end_marker, start)
    if start < 0 or end < 0:
        raise SystemExit("Could not locate recipient persistence/ACK block")
    end += len(end_marker)
    old_recipient = text[start:end]
    new_recipient = '''            // BLEE_ATOMIC_RECIPIENT_ACK_V1
            SQLiteDatabase database = db();
            boolean ownTransaction = !database.inTransaction();
            if (ownTransaction) database.beginTransaction();
            try {
                if (!paymentExists("incoming:" + paymentId)) {
                    payment.put("direction", "incoming");
                    payment.put("state", "delivered_offline");
                    payment.put("updatedAt", now);
                    if (!payment.has("createdAt")) payment.put("createdAt", packet.optLong("createdAt", now));

                    ContentValues pv = new ContentValues();
                    pv.put("payment_key", "incoming:" + paymentId);
                    pv.put("payment_id", paymentId);
                    pv.put("direction", "incoming");
                    pv.put("state", "delivered_offline");
                    pv.put("created_at", payment.optLong("createdAt", now));
                    pv.put("updated_at", now);
                    pv.put("payload", payment.toString());
                    if (database.insertWithOnConflict("payments", null, pv, SQLiteDatabase.CONFLICT_REPLACE) == -1) throw new IllegalStateException("Incoming payment persistence failed");
                    addEvent(paymentId, "RECIPIENT_RECEIVED", now, packet.optString("originDeviceId", null), raw);
                }

                String senderWallet = extractSender(payment);
                if (!senderWallet.isEmpty()) {
                    JSONObject ackPayload = new JSONObject();
                    ackPayload.put("paymentId", paymentId);
                    ackPayload.put("receivedAt", now);
                    ackPayload.put("recipientWallet", wallet);
                    String ackId = "ack:" + paymentId + ":" + wallet;
                    JSONObject ack = packet(
                        "DELIVERY_ACK", ackId, paymentId, senderWallet,
                        ackPayload.toString(), now, packet.optLong("expiresAt", now + 3600000L),
                        0, 6, 3, localDeviceId, localPublicKey
                    );
                    enqueue(ack);
                }
                if (ownTransaction) database.setTransactionSuccessful();
            } finally {
                if (ownTransaction && database.inTransaction()) database.endTransaction();
            }
            return new AcceptedPayment(true, paymentId);'''
    text = text[:start] + new_recipient + text[end:]

    path.write_text(text)


def patch_main_activity(activity: Path) -> None:
    text = activity.read_text()
    if "import android.os.Bundle;" not in text:
        package_end = text.find(";", text.find("package "))
        text = text[: package_end + 1] + "\n\nimport android.os.Bundle;" + text[package_end + 1 :]

    if "registerPlugin(BleeMeshPlugin.class);" not in text:
        on_create = re.search(r"@Override\s+public\s+void\s+onCreate\s*\(Bundle\s+savedInstanceState\)\s*\{", text)
        if on_create:
            body_start = on_create.end()
            super_match = re.search(r"super\.onCreate\(savedInstanceState\);", text[body_start:])
            if not super_match:
                raise SystemExit("Existing MainActivity onCreate has no super.onCreate")
            absolute = body_start + super_match.start()
            text = text[:absolute] + "registerPlugin(BleeMeshPlugin.class);\n        " + text[absolute:]
            needle = "super.onCreate(savedInstanceState);"
            pos = text.find(needle, absolute)
            text = text[: pos + len(needle)] + "\n        BleeMeshService.start(this);" + text[pos + len(needle) :]
        else:
            class_open = text.find("{", text.find("class MainActivity"))
            if class_open < 0:
                raise SystemExit("Could not locate MainActivity class body")
            method = """

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(BleeMeshPlugin.class);
        super.onCreate(savedInstanceState);
        BleeMeshService.start(this);
    }
"""
            text = text[: class_open + 1] + method + text[class_open + 1 :]

    activity.write_text(text)


def add_permission(xml: str, permission: str, extra: str = "") -> str:
    if f'android:name="{permission}"' in xml:
        return xml
    line = f'    <uses-permission android:name="{permission}"{extra} />\n'
    marker = "<application"
    pos = xml.find(marker)
    if pos < 0:
        raise SystemExit("AndroidManifest.xml has no <application>")
    return xml[:pos] + line + xml[pos:]


def patch_manifest(package: str) -> None:
    manifest = ANDROID / "AndroidManifest.xml"
    xml = manifest.read_text()
    permissions = (
        ("android.permission.INTERNET", ""),
        ("android.permission.ACCESS_NETWORK_STATE", ""),
        ("android.permission.RECEIVE_BOOT_COMPLETED", ""),
        ("android.permission.BLUETOOTH", ' android:maxSdkVersion="30"'),
        ("android.permission.BLUETOOTH_ADMIN", ' android:maxSdkVersion="30"'),
        ("android.permission.ACCESS_FINE_LOCATION", ' android:maxSdkVersion="30"'),
        ("android.permission.BLUETOOTH_SCAN", ' android:usesPermissionFlags="neverForLocation"'),
        ("android.permission.BLUETOOTH_CONNECT", ""),
        ("android.permission.BLUETOOTH_ADVERTISE", ""),
        ("android.permission.POST_NOTIFICATIONS", ""),
        ("android.permission.FOREGROUND_SERVICE", ""),
        ("android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE", ""),
    )
    for permission, extra in permissions:
        xml = add_permission(xml, permission, extra)

    close = xml.rfind("</application>")
    if close < 0:
        raise SystemExit("AndroidManifest.xml has no </application>")

    additions = ""
    if "BleeMeshService" not in xml:
        additions += f'''        <service
            android:name="{package}.BleeMeshService"
            android:enabled="true"
            android:exported="false"
            android:foregroundServiceType="connectedDevice" />
'''
    if "BleeBootReceiver" not in xml:
        additions += f'''        <receiver
            android:name="{package}.BleeBootReceiver"
            android:enabled="true"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.BOOT_COMPLETED" />
                <action android:name="android.intent.action.MY_PACKAGE_REPLACED" />
            </intent-filter>
        </receiver>
'''
    if additions:
        xml = xml[:close] + additions + xml[close:]
    manifest.write_text(xml)


def verify(activity: Path, package: str) -> None:
    text = activity.read_text()
    for marker in ("BleeMeshPlugin.class", "BleeMeshService.start(this)"):
        if marker not in text:
            raise SystemExit(f"MainActivity Mesh v2 registration missing: {marker}")

    manifest = (ANDROID / "AndroidManifest.xml").read_text()
    for marker in (
        "BLUETOOTH_SCAN",
        "POST_NOTIFICATIONS",
        "FOREGROUND_SERVICE_CONNECTED_DEVICE",
        "RECEIVE_BOOT_COMPLETED",
        "BleeMeshService",
        "BleeBootReceiver",
    ):
        if marker not in manifest:
            raise SystemExit(f"AndroidManifest Mesh v2 marker missing: {marker}")

    for name in (
        "BleeDeviceIdentity.java",
        "BleeMeshDb.java",
        "BleeMeshService.java",
        "BleeMeshPlugin.java",
        "BleeBootReceiver.java",
    ):
        path = activity.parent / name
        if not path.exists() or f"package {package};" not in path.read_text():
            raise SystemExit(f"Mesh v2 Android source invalid: {name}")

    service = (activity.parent / "BleeMeshService.java").read_text()
    required_service = (
        "attemptSenderFundedSettlement",
        "eth_sendRawTransaction",
        "SENDER_FUNDED_RAW_TX",
        "settlementRetryAfter.put(paymentId, Long.MAX_VALUE)",
    )
    missing = [marker for marker in required_service if marker not in service]
    if missing:
        raise SystemExit(f"Sender-funded Android service incomplete: {missing}")

    mesh_db = (activity.parent / "BleeMeshDb.java").read_text()
    required_db = (
        "BLEE_ATOMIC_OUTBOX_V1",
        "BLEE_ATOMIC_RECIPIENT_ACK_V1",
        "database.beginTransaction()",
        "database.setTransactionSuccessful()",
    )
    missing_db = [marker for marker in required_db if marker not in mesh_db]
    if missing_db:
        raise SystemExit(f"Atomic Mesh DB persistence incomplete: {missing_db}")


def main() -> None:
    activity = locate_main_activity()
    package = app_package(activity)
    install_templates(activity, package)
    harden_sender_funded_service(activity)
    harden_mesh_db(activity)
    patch_main_activity(activity)
    patch_manifest(package)
    verify(activity, package)
    print(f"Blee 2.1.1 Mesh v2 atomic sender-funded Android service installed for {package}.")


if __name__ == "__main__":
    main()
