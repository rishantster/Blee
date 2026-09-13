#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/components/BleeApp.tsx"


def fail(message: str) -> None:
    raise SystemExit(f"Blee contacts React v3 compilefix: {message}")


def main() -> None:
    if not APP.is_file():
        fail("BleeApp.tsx missing")
    text = APP.read_text()
    if "BLEE_CONTACTS_REACT_V3" not in text:
        fail("React contacts v3 must run first")

    # Do not depend on optional Icon-name union members for sheet chrome/checks.
    text = text.replace(
        '<button className="icon-button ghost" onClick={close} aria-label="Close contacts"><Icon name="close"/></button>',
        '<button className="icon-button ghost react-contact-close" onClick={close} aria-label="Close contacts">×</button>',
    )
    text = text.replace(
        '{!contactFilter && <Icon name="check" size={16}/>} ',
        '{!contactFilter && <span className="react-contact-check" aria-hidden="true">✓</span>} ',
    )
    text = text.replace(
        '{contactFilter === wallet && <Icon name="check" size={16}/>} ',
        '{contactFilter === wallet && <span className="react-contact-check" aria-hidden="true">✓</span>} ',
    )

    marker = "// BLEE_CONTACTS_REACT_V3_COMPILEFIX"
    if marker not in text:
        text = marker + "\n" + text
    APP.write_text(text)

    final = APP.read_text()
    for banned in ('name="close"', 'name="check"'):
        if banned in final:
            fail(f"optional icon dependency remains: {banned}")
    for required in ("BLEE_CONTACTS_REACT_V3_COMPILEFIX", "react-contact-close", "react-contact-check"):
        if required not in final:
            fail(f"missing {required}")

    print("VERIFIED: React contacts use compile-stable close/check controls")


if __name__ == "__main__":
    main()
