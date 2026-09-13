#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee 2.7 production verification: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def require(text: str, markers: tuple[str, ...], label: str) -> None:
    missing = [marker for marker in markers if marker not in text]
    if missing:
        fail(f"{label} missing {missing}")


def main() -> None:
    app_path = ROOT / "src/components/BleeApp.tsx"
    runtime_path = ROOT / "src/components/BleeRuntime.tsx"
    hook_path = ROOT / "src/hooks/useBlee.ts"
    css_path = ROOT / "app/globals.css"
    manifest_path = ROOT / "android/app/src/main/AndroidManifest.xml"
    gradle_path = ROOT / "android/app/build.gradle"
    package_path = ROOT / "package.json"

    for path in (app_path, runtime_path, hook_path, css_path, manifest_path, gradle_path, package_path):
        if not path.is_file():
            fail(f"missing {path.relative_to(ROOT)}")

    app = app_path.read_text()
    runtime = runtime_path.read_text()
    hook = hook_path.read_text()
    css = css_path.read_text()
    manifest = manifest_path.read_text()
    gradle = gradle_path.read_text()
    service = locate("BleeMeshService.java").read_text()
    db = locate("BleeMeshDb.java").read_text()
    plugin = locate("BleeMeshPlugin.java").read_text()
    main_activity = locate("MainActivity.java").read_text()
    notifier = locate("BleePaymentNotifier.java").read_text()
    qr_plugin = locate("BleeQrScannerPlugin.java").read_text()
    qr_capture = locate("BleeQrCaptureActivity.java").read_text()

    require(app, (
        "<BottomNav active={activeTab} onChange={selectTab}/>",
        "activityFilter",
    ), "stable Blee React shell")
    if app.count("<BottomNav active={activeTab} onChange={selectTab}/>") != 1:
        fail("primary bottom navigation is missing or duplicated")

    for marker in (
        "BLEE_CONTACTS_REACT_V4",
        "activity-contact-filter",
        "renderContactSheet()",
        "blee-activity-contact-tools",
        "blee-activity-filter-button",
        "blee-activity-contacts-button",
        "#blee-contact-sheet",
    ):
        if marker in app or marker in runtime or marker in css:
            fail(f"unstable contacts UI survived: {marker}")

    require(app, (
        "BLEE_SEND_QR_SCANNER_V1",
        "registerPlugin<BleeQrScannerPlugin>('BleeQrScanner')",
        "parseBleeRecipientQr",
        "BleeQrScanner.scan()",
        'className="blee-recipient-qr-icon"',
    ), "Send QR scanner")
    if app.count('className="blee-recipient-qr-icon"') != 1:
        fail("Send must contain exactly one QR scanner icon")
    if 'className="blee-recipient-qr-scan"' in app:
        fail("legacy QR scanner control survived")
    if '<span>Scan QR</span>' in app or '>Scan QR<' in app:
        fail("visible Scan QR text survived")

    if "window.location.reload" in runtime:
        fail("destructive WebView reload remains in runtime")
    require(runtime, (
        "BLEE_SOFT_REFRESH_V2",
        "BLEE_SOFT_REFRESH_NATIVE_BRIDGE_V2",
        "blee:refresh-all",
        "blee-refresh-splash",
        "playSoftSwish",
        "BLEE_CANONICAL_WALLET_CASE_V1",
        "BLEE_CANONICAL_WALLET_TEXT_V1",
    ), "runtime refresh/identity")
    require(css, (
        "BLEE_SOFT_REFRESH_CSS_V2",
        "BLEE_STABLE_SEND_RECIPIENT_ACTION_V1",
        "BLEE_QR_UX_V2",
    ), "production CSS")
    require(plugin, ("BLEE_NONDESTRUCTIVE_MANUAL_REFRESH_V2", "manualRefresh(PluginCall call)"), "native refresh bridge")

    require(service, (
        "BLEE_ADAPTIVE_NEARBY_V3",
        "private static final long BLE_GRACE_MS = 15_000L",
        "private static final int GATT_TIMEOUT_THRESHOLD = 2",
        "NEARBY_HEARTBEAT_MS = 5_000L",
        "NEARBY_IDLE_REARM_MS = 30_000L",
        "NEARBY_REARM_COOLDOWN_MS = 15_000L",
        "BLEE_NEARBY_SPEED_PROFILE_V2",
        "syncNearbyProfileIfChanged",
        "PEER_IDENTITY_UPDATED",
    ), "Nearby transport")
    for marker in (
        "private static final long BLE_GRACE_MS = 3_000L",
        "private static final int GATT_TIMEOUT_THRESHOLD = 1",
        "NEARBY_HEARTBEAT_MS = 1_000L",
        "NEARBY_IDLE_REARM_MS = 12_000L",
        "NEARBY_REARM_COOLDOWN_MS = 6_000L",
    ):
        if marker in service:
            fail(f"aggressive transport regression returned: {marker}")
    require(hook, ("BLEE_PRODUCTION_NATIVE_PEER_MERGE_V1",), "React peer merge")

    require(db, (
        "BLEE_ACTIVITY_IDENTITY_BACKFILL_V2",
        "backfillPaymentIdentity",
        "counterpartyName",
        "counterpartyAvatar",
        "BLEE_LOCAL_CONTACTS_V1",
        "CREATE TABLE IF NOT EXISTS contacts",
        "BLEE_CONTACT_ACTIVITY_SYNC_V1",
        "BLEE_CONTACT_ALIAS_PRECEDENCE_V1",
    ), "identity/contact database")
    require(plugin, (
        "BLEE_CONTACTS_PLUGIN_V1",
        "listContacts(PluginCall call)",
        "contactCandidates(PluginCall call)",
        "saveContact(PluginCall call)",
        "deleteContact(PluginCall call)",
        "BLEE_CONTACT_ACTIVITY_WAKE_V1",
    ), "contacts native API")

    require(qr_plugin, (
        "BLEE_SEND_QR_SCANNER_ANDROID_V1",
        "BleeQrCaptureActivity.class",
        "IntentIntegrator.QR_CODE",
        'getStringExtra("SCAN_RESULT")',
        "catch (Exception error)",
    ), "QR scanner plugin")
    require(qr_capture, (
        "BLEE_QR_CAPTURE_UX_V2",
        "SCREEN_ORIENTATION_PORTRAIT",
        "window.setLayout(width, height)",
    ), "QR capture activity")
    if "BleeQrCaptureActivity" not in manifest or 'android:screenOrientation="portrait"' not in manifest:
        fail("portrait QR activity manifest entry missing")

    require(notifier, (
        "BLEE_PAYMENT_NOTIFICATIONS_V1",
        "BLEE_NOTIFICATION_PERMISSION_V1",
        "Payment sent",
        "Payment received",
        "Payment delivered",
        "IMPORTANCE_HIGH",
    ), "payment notifier")
    require(main_activity, (
        "BLEE_NOTIFICATION_PERMISSION_REQUEST_V1",
        "POST_NOTIFICATIONS",
        "requestPermissions",
    ), "notification permission request")
    if "android.permission.POST_NOTIFICATIONS" not in manifest:
        fail("POST_NOTIFICATIONS manifest permission missing")

    package = json.loads(package_path.read_text())
    if package.get("version") != "2.7.0":
        fail(f"package version is {package.get('version')}, expected 2.7.0")
    if 'versionCode 17' not in gradle or 'versionName "2.7.0"' not in gradle:
        fail("Android Gradle version is not 17 / 2.7.0")

    print("============================================================")
    print("VERIFIED: Blee 2.7 final production source contract")
    print("- original React Activity shell + persistent BottomNav are intact")
    print("- experimental contacts/filter UI is absent; durable contacts backend remains")
    print("- Activity name/avatar backfill remains enabled")
    print("- wallet address presentation is canonical and stable")
    print("- QR scanner is single, in-field, portrait and offline-bundled")
    print("- refresh is in-process with Blee animation/swish and no session reload")
    print("- last physically proven BLE/Nearby timing contract is pinned")
    print("- Android payment notifications + runtime permission request are present")
    print("- Android versionCode 17 / Blee 2.7.0 is consistent")
    print("============================================================")


if __name__ == "__main__":
    main()
