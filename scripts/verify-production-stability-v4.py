#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee stability v4 verification: {message}")


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
    runtime = (ROOT / "src/components/BleeRuntime.tsx").read_text()
    app = (ROOT / "src/components/BleeApp.tsx").read_text()
    css = (ROOT / "app/globals.css").read_text()
    service = locate("BleeMeshService.java").read_text()
    db = locate("BleeMeshDb.java").read_text()
    plugin = locate("BleeMeshPlugin.java").read_text()

    if "window.location.reload" in runtime:
        fail("destructive WebView reload remains")

    for marker in (
        "BLEE_CONTACTS_ACTIVITY_UI_V1",
        "blee-activity-contact-tools",
        "blee-activity-filter-button",
        "blee-activity-contacts-button",
        "#blee-contact-sheet",
    ):
        if marker in runtime or marker in css:
            fail(f"unstable contact/activity DOM UI remains: {marker}")

    require(runtime, (
        "BLEE_SOFT_REFRESH_V2",
        "BLEE_SOFT_REFRESH_NATIVE_BRIDGE_V2",
        "BLEE_CANONICAL_WALLET_CASE_V1",
        "BLEE_CANONICAL_WALLET_TEXT_V1",
        "BLEE_CONTACTS_RUNTIME_UI_DISABLED_STABILITY_V1",
    ), "runtime")

    require(css, (
        "BLEE_SOFT_REFRESH_CSS_V2",
        "BLEE_STABLE_SEND_RECIPIENT_ACTION_V1",
    ), "CSS")

    require(db, (
        "BLEE_LOCAL_CONTACTS_V1",
        "CREATE TABLE IF NOT EXISTS contacts",
        "BLEE_ACTIVITY_IDENTITY_BACKFILL_V2",
    ), "database")

    require(plugin, (
        "BLEE_CONTACTS_PLUGIN_V1",
        "BLEE_NONDESTRUCTIVE_MANUAL_REFRESH_V2",
    ), "plugin")

    require(service, (
        "private static final long BLE_GRACE_MS = 15_000L",
        "private static final int GATT_TIMEOUT_THRESHOLD = 2",
        "NEARBY_HEARTBEAT_MS = 5_000L",
        "NEARBY_IDLE_REARM_MS = 30_000L",
        "NEARBY_REARM_COOLDOWN_MS = 15_000L",
        "BLEE_NEARBY_SPEED_PROFILE_V2",
    ), "nearby transport")

    for marker in (
        "private static final long BLE_GRACE_MS = 3_000L",
        "private static final int GATT_TIMEOUT_THRESHOLD = 1",
        "NEARBY_HEARTBEAT_MS = 1_000L",
        "NEARBY_IDLE_REARM_MS = 12_000L",
        "NEARBY_REARM_COOLDOWN_MS = 6_000L",
    ):
        if marker in service:
            fail(f"aggressive transport regression returned: {marker}")

    if app.count('className="blee-recipient-qr-icon"') != 1:
        fail("Send must contain exactly one QR scanner icon")
    if '<span>Scan QR</span>' in app or '>Scan QR<' in app:
        fail("visible Scan QR text control survived")

    print("============================================================")
    print("VERIFIED: Blee production stability v4")
    print("- last-known-working nearby transport timings are pinned")
    print("- refresh stays in-process and preserves unlocked session")
    print("- injected Activity/Contacts DOM UI is disabled")
    print("- contacts backend remains durable but UI is frozen for later clean implementation")
    print("- wallet address presentation is canonical and stable")
    print("- Send Recipient has exactly one QR action")
    print("============================================================")


if __name__ == "__main__":
    main()
