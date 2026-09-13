#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"Blee refresh preclean v2: {message}")


def find_block_end(text: str, brace: int) -> int:
    depth = 0
    quote = None
    escape = False
    line_comment = False
    block_comment = False
    i = brace
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ''
        if line_comment:
            if ch == '\n': line_comment = False
            i += 1
            continue
        if block_comment:
            if ch == '*' and nxt == '/':
                block_comment = False
                i += 2
                continue
            i += 1
            continue
        if quote:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch == '/' and nxt == '/':
            line_comment = True
            i += 2
            continue
        if ch == '/' and nxt == '*':
            block_comment = True
            i += 2
            continue
        if ch in ('\'', '"', '`'):
            quote = ch
            i += 1
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    fail("legacy refresh block is unterminated")
    return -1


def main() -> None:
    path = ROOT / "src/components/BleeRuntime.tsx"
    if not path.is_file():
        fail("materialized BleeRuntime.tsx missing")
    text = path.read_text()
    marker = "// BLEE_PULL_TO_REFRESH_V1"
    start = text.find(marker)
    if start >= 0:
        if_start = text.find("if (", start)
        if if_start < 0:
            fail("legacy refresh marker exists without global if block")
        brace = text.find('{', if_start)
        if brace < 0:
            fail("legacy refresh global if opening brace missing")
        end = find_block_end(text, brace)
        text = text[:start] + "// BLEE_LEGACY_REFRESH_REMOVED_V2\n" + text[end:]
        path.write_text(text)

    generated = path.read_text()
    if "BLEE_PULL_TO_REFRESH_V1" in generated:
        fail("legacy refresh block survived preclean")
    if "window.location.reload" in generated:
        fail("destructive WebView reload survived preclean")
    print("VERIFIED: legacy destructive refresh block removed before soft-refresh v2")


if __name__ == "__main__":
    main()
