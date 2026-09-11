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

    # Do not let already-settled envelopes consume the first small settlement
    # candidate window forever. The DB still bounds storage/expiry; the worker
    # can inspect a larger local batch cheaply.
    text = text.replace(
        "List<String> candidates = db.settlementCandidates(now, 64);",
        "List<String> candidates = db.settlementCandidates(now, 512);",
        1,
    )

    # Once this process has seen a successful chain receipt, stop re-submitting
    # the same raw transaction every loop. A reboot may re-check once, which is
    # harmless and useful for recovery.
    old = "db.markSettlementAttempt(paymentId, true, null);\n                settlementRetryAfter.remove(paymentId);"
    new = "db.markSettlementAttempt(paymentId, true, null);\n                settlementRetryAfter.put(paymentId, Long.MAX_VALUE);"
    if old not in text:
        raise SystemExit("Could not locate sender-funded settlement success marker")
    text = text.replace(old, new, 1)
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


def main() -> None:
    activity = locate_main_activity()
    package = app_package(activity)
    install_templates(activity, package)
    harden_sender_funded_service(activity)
    patch_main_activity(activity)
    patch_manifest(package)
    verify(activity, package)
    print(f"Blee 2.1 Mesh v2 sender-funded Android service installed for {package}.")


if __name__ == "__main__":
    main()
