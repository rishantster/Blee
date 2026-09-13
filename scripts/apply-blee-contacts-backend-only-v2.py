#!/usr/bin/env python3
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee contacts backend-only v2: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def main() -> None:
    source = ROOT / "scripts" / "apply-blee-contacts-v1.py"
    if not source.is_file():
        fail("contacts v1 source stage missing")

    # Load functions without executing contacts-v1 main(). This deliberately
    # installs only durable storage/native API. The old runtime DOM UI is not
    # installed; it was the source of Activity/Home/navigation regressions.
    ns = runpy.run_path(str(source), run_name="blee_contacts_backend_library")
    ns["patch_db"]()
    ns["patch_plugin"]()

    db = locate("BleeMeshDb.java").read_text()
    plugin = locate("BleeMeshPlugin.java").read_text()
    for marker in (
        "BLEE_LOCAL_CONTACTS_V1",
        "CREATE TABLE IF NOT EXISTS contacts",
        "saveContact(String wallet",
        "listContacts()",
        "contactCandidates()",
    ):
        if marker not in db:
            fail(f"database missing {marker}")
    for marker in (
        "BLEE_CONTACTS_PLUGIN_V1",
        "listContacts(PluginCall call)",
        "contactCandidates(PluginCall call)",
        "saveContact(PluginCall call)",
        "deleteContact(PluginCall call)",
    ):
        if marker not in plugin:
            fail(f"plugin missing {marker}")

    print("VERIFIED: Blee contacts backend-only v2")
    print("- durable SQLite contacts remain available")
    print("- native contacts API remains available")
    print("- no Activity/Home DOM controls are installed")


if __name__ == "__main__":
    main()
