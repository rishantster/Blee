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
    )
    for name in required:
        source = TEMPLATES / name
        if not source.exists():
            raise SystemExit(f"Missing Mesh v2 Android template: {name}")
        text = source.read_text().replace("__BLEE_APP_PACKAGE__", package)
        target = target_dir / name.removesuffix(".in")
        target.write_text(text)
        print(f"mesh v2 android: {target.relative_to(ROOT)}")


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
            super_end = body_start + super_match.end() + len("registerPlugin(BleeMeshPlugin.class);\n        ")
            # Insert service start after super. Exact placement is intentionally simple and deterministic.
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
        ("android.permission.BLUETOOTH", ' android:maxSdkVersion="30"'),
        ("android.permission.BLUETOOTH_ADMIN", ' android:maxSdkVersion="30"'),
        ("android.permission.ACCESS_FINE_LOCATION", ' android:maxSdkVersion="30"'),
        ("android.permission.BLUETOOTH_SCAN", ' android:usesPermissionFlags="neverForLocation"'),
        ("android.permission.BLUETOOTH_CONNECT", ""),
        ("android.permission.BLUETOOTH_ADVERTISE", ""),
        ("android.permission.POST_NOTIFICATIONS", ""),
        ("android.permission.FOREGROUND_SERVICE", ""),
        ("android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE", ""),
        ("android.permission.FOREGROUND_SERVICE_DATA_SYNC", ""),
    )
    for permission, extra in permissions:
        xml = add_permission(xml, permission, extra)

    if "BleeMeshService" not in xml:
        close = xml.rfind("</application>")
        if close < 0:
            raise SystemExit("AndroidManifest.xml has no </application>")
        service = f'''        <service
            android:name="{package}.BleeMeshService"
            android:enabled="true"
            android:exported="false"
            android:foregroundServiceType="connectedDevice|dataSync" />
'''
        xml = xml[:close] + service + xml[close:]
    manifest.write_text(xml)


def verify(activity: Path, package: str) -> None:
    text = activity.read_text()
    for marker in ("BleeMeshPlugin.class", "BleeMeshService.start(this)"):
        if marker not in text:
            raise SystemExit(f"MainActivity Mesh v2 registration missing: {marker}")

    manifest = (ANDROID / "AndroidManifest.xml").read_text()
    for marker in ("BLUETOOTH_SCAN", "POST_NOTIFICATIONS", "FOREGROUND_SERVICE_CONNECTED_DEVICE", "BleeMeshService"):
        if marker not in manifest:
            raise SystemExit(f"AndroidManifest Mesh v2 marker missing: {marker}")

    for name in ("BleeDeviceIdentity.java", "BleeMeshDb.java", "BleeMeshService.java", "BleeMeshPlugin.java"):
        path = activity.parent / name
        if not path.exists() or f"package {package};" not in path.read_text():
            raise SystemExit(f"Mesh v2 Android source invalid: {name}")


def main() -> None:
    activity = locate_main_activity()
    package = app_package(activity)
    install_templates(activity, package)
    patch_main_activity(activity)
    patch_manifest(package)
    verify(activity, package)
    print(f"Blee Mesh v2 Android service installed for {package}.")


if __name__ == "__main__":
    main()
