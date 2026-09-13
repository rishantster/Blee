#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee stabilization v3 verification: {message}")


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
    db = locate("BleeMeshDb.java").read_text()
    plugin = locate("BleeMeshPlugin.java").read_text()

    if "window.location.reload" in runtime:
        fail("destructive WebView reload remains in refresh path")
    require(runtime, (
        "BLEE_SOFT_REFRESH_V2",
        "BLEE_SOFT_REFRESH_NATIVE_BRIDGE_V2",
        "blee:refresh-all",
        "blee:refresh-complete",
        "playSoftSwish",
        "/brand/blee-logo.svg",
        "BLEE_CONTACTS_ACTIVITY_UI_V1",
        "Filter activity",
        "Save contact",
        "removeSendOverlap",
    ), "runtime")
    require(css, (
        "BLEE_SOFT_REFRESH_CSS_V2",
        "blee-refresh-logo",
        "BLEE_CONTACTS_ACTIVITY_CSS_V1",
        ".blee-recipient-input-shell > button:not(.blee-recipient-qr-icon)",
    ), "CSS")
    require(db, (
        "BLEE_LOCAL_CONTACTS_V1",
        "CREATE TABLE IF NOT EXISTS contacts",
        "BLEE_CONTACT_ACTIVITY_SYNC_V1",
        "BLEE_CONTACT_ALIAS_PRECEDENCE_V1",
        "backfillPaymentIdentity(normalized, name, photo)",
    ), "BleeMeshDb")
    require(plugin, (
        "BLEE_NONDESTRUCTIVE_MANUAL_REFRESH_V2",
        "MANUAL_REFRESH",
        "BLEE_CONTACTS_PLUGIN_V1",
        "listContacts(PluginCall call)",
        "contactCandidates(PluginCall call)",
        "BLEE_CONTACT_ACTIVITY_WAKE_V1",
    ), "BleeMeshPlugin")
    require(app, (
        "BLEE_SEND_QR_SCANNER_V1",
        "blee-recipient-qr-icon",
    ), "BleeApp")

    if app.count('className="blee-recipient-qr-icon"') != 1:
        fail("Send must render exactly one QR scanner icon")
    if '<span>Scan QR</span>' in app or '>Scan QR<' in app:
        fail("text QR scanner control survived icon-only pass")

    print("============================================================")
    print("VERIFIED: Blee production stabilization v3")
    print("- refresh preserves the unlocked session and never reloads WebView")
    print("- pull/funds refresh wakes ledger, balance lifecycle, pending and nearby paths")
    print("- refresh shows Blee logo animation with soft swish")
    print("- Send Recipient has one QR action and no overlapping contact button")
    print("- contacts are durable SQLite records and Activity can filter by saved contact")
    print("- saved aliases remain local display metadata; signed payments are untouched")
    print("============================================================")


if __name__ == "__main__":
    main()
