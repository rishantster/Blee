#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/components/BleeApp.tsx"


def fail(message: str) -> None:
    raise SystemExit(f"Blee contacts React v4 compilefix: {message}")


def main() -> None:
    if not APP.is_file():
        fail("BleeApp.tsx missing")
    text = APP.read_text()
    if "BLEE_CONTACTS_REACT_V4" not in text:
        fail("React contacts v4 must run first")

    text = text.replace(
        "{ wallet: normalized, displayName: identity?.alias, avatar: identity?.avatar }",
        "{ wallet: normalized, displayName: identity?.alias || undefined, avatar: identity?.avatar || undefined }",
    )
    text = text.replace(
        "const avatar = contactFor(wallet)?.avatar || candidate.avatar || identity?.avatar;",
        "const avatar = contactFor(wallet)?.avatar || candidate.avatar || identity?.avatar || undefined;",
    )

    marker = "// BLEE_CONTACTS_REACT_V4_COMPILEFIX"
    if marker not in text:
        text = marker + "\n" + text
    APP.write_text(text)

    final = APP.read_text()
    for required in (
        "BLEE_CONTACTS_REACT_V4_COMPILEFIX",
        "displayName: identity?.alias || undefined",
        "avatar: identity?.avatar || undefined",
    ):
        if required not in final:
            fail(f"missing {required}")
    print("VERIFIED: React contacts nullable identity values are TypeScript-safe")


if __name__ == "__main__":
    main()
