#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "src/components/BleeRuntime.tsx"
CSS = ROOT / "app/globals.css"


def fail(message: str) -> None:
    raise SystemExit(f"Blee contacts UI preclean v2: {message}")


def clean_runtime(text: str) -> str:
    marker = "// BLEE_CONTACTS_ACTIVITY_UI_V1"
    tail = "  window.setTimeout(() => { void refreshContacts(); syncActivityUi(); }, 160);\n}\n"
    start = text.find(marker)
    if start >= 0:
        end_start = text.find(tail, start)
        if end_start < 0:
            fail("contacts runtime start marker exists but deterministic end marker is missing")
        end = end_start + len(tail)
        text = text[:start] + "// BLEE_CONTACTS_RUNTIME_UI_DISABLED_STABILITY_V1\n" + text[end:]
    elif "BLEE_CONTACTS_RUNTIME_UI_DISABLED_STABILITY_V1" not in text:
        anchor = "const BleeMesh = registerPlugin<MeshPlugin>('BleeMesh');"
        if anchor not in text:
            fail("runtime registration anchor missing")
        text = text.replace(anchor, anchor + "\n\n// BLEE_CONTACTS_RUNTIME_UI_DISABLED_STABILITY_V1", 1)
    return text


def clean_css(text: str) -> str:
    marker = "/* BLEE_CONTACTS_ACTIVITY_CSS_V1 */"
    tail = ".blee-contact-empty.compact { min-height: 90px; }\n"
    start = text.find(marker)
    if start >= 0:
        end_start = text.find(tail, start)
        if end_start < 0:
            fail("contacts CSS start marker exists but deterministic end marker is missing")
        end = end_start + len(tail)
        text = text[:start].rstrip() + "\n\n/* BLEE_CONTACTS_RUNTIME_UI_DISABLED_STABILITY_V1 */\n" + text[end:].lstrip()
    elif "BLEE_CONTACTS_RUNTIME_UI_DISABLED_STABILITY_V1" not in text:
        text = text.rstrip() + "\n\n/* BLEE_CONTACTS_RUNTIME_UI_DISABLED_STABILITY_V1 */\n"
    return text


def main() -> None:
    if not RUNTIME.is_file() or not CSS.is_file():
        fail("materialized runtime/CSS missing")

    runtime = clean_runtime(RUNTIME.read_text())
    css = clean_css(CSS.read_text())
    RUNTIME.write_text(runtime)
    CSS.write_text(css)

    combined = runtime + "\n" + css
    forbidden = (
        "BLEE_CONTACTS_ACTIVITY_UI_V1",
        "blee-activity-contact-tools",
        "blee-activity-filter-button",
        "blee-activity-contacts-button",
        "#blee-contact-sheet",
    )
    for marker in forbidden:
        if marker in combined:
            fail(f"injected contacts UI survived deterministic cleanup: {marker}")
    if "BLEE_CONTACTS_RUNTIME_UI_DISABLED_STABILITY_V1" not in runtime:
        fail("runtime disabled marker missing")

    print("VERIFIED: injected contacts UI removed deterministically; backend remains untouched")


if __name__ == "__main__":
    main()
