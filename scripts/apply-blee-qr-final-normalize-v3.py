#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/components/BleeApp.tsx"


def fail(message: str) -> None:
    raise SystemExit(f"Blee final QR normalize v3: {message}")


def input_end(text: str, start: int) -> int:
    close = text.find("/>", start)
    gt = text.find(">", start)
    if close >= 0 and (gt < 0 or close < gt):
        return close + 2
    quote = None
    braces = 0
    i = start + 6
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote and text[i - 1] != "\\":
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch == "{":
            braces += 1
        elif ch == "}" and braces:
            braces -= 1
        elif ch == ">" and braces == 0:
            return i + 1
        i += 1
    fail("input tag is unterminated")
    return -1


def state_map(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    pattern = re.compile(
        r"const\s*\[\s*([A-Za-z_$][\w$]*)\s*,\s*([A-Za-z_$][\w$]*)\s*\]\s*=\s*useState"
    )
    for match in pattern.finditer(text):
        result[match.group(1)] = match.group(2)
    return result


def recipient_input(text: str) -> tuple[int, int, str, str]:
    states = state_map(text)
    candidates: list[tuple[int, int, int, str, str]] = []

    for match in re.finditer(r"<input\b", text):
        start = match.start()
        end = input_end(text, start)
        tag = text[start:end]
        lower = tag.lower()
        if "password" in lower or "passphrase" in lower:
            continue
        if re.search(r'type\s*=\s*["\'](?:number|file|email|date|time)["\']', tag, re.I):
            continue

        score = 0
        state_name = ""
        setter = ""

        value_match = re.search(r"\bvalue\s*=\s*\{\s*([A-Za-z_$][\w$]*)\s*\}", tag)
        if value_match:
            state_name = value_match.group(1)
            setter = states.get(state_name, "")
            name_lower = state_name.lower()
            if "recipient" in name_lower:
                score += 60
            if "send" in name_lower and any(token in name_lower for token in ("to", "address", "wallet")):
                score += 45
            if name_lower in ("to", "recipient", "recipientaddress", "sendto"):
                score += 60
            if "address" in name_lower or "wallet" in name_lower:
                score += 22
            if "amount" in name_lower or "note" in name_lower or "name" == name_lower:
                score -= 35

        change_match = re.search(
            r"onChange\s*=\s*\{\s*\(?\s*([A-Za-z_$][\w$]*)\s*\)?\s*=>\s*([A-Za-z_$][\w$]*)\s*\(\s*\1\.target\.value\s*\)\s*\}",
            tag,
        )
        if change_match and not setter:
            setter = change_match.group(2)
        if setter:
            setter_lower = setter.lower()
            if "recipient" in setter_lower:
                score += 45
            if "send" in setter_lower and any(token in setter_lower for token in ("to", "address", "wallet")):
                score += 30

        semantic = " ".join(
            re.findall(
                r'(?:placeholder|aria-label|name|id)\s*=\s*["\']([^"\']+)["\']',
                tag,
                re.I,
            )
        ).lower()
        if "recipient" in semantic:
            score += 45
        if "wallet" in semantic or "address" in semantic:
            score += 25
        if "amount" in semantic:
            score -= 35

        before = text[max(0, start - 900):start].lower()
        after = text[end:min(len(text), end + 900)].lower()
        context = before + " " + after
        if "recipient" in context:
            score += 16
        if "wallet address" in context:
            score += 10
        if "amount" in after:
            score += 5
        if "send" in context:
            score += 4

        if setter:
            candidates.append((score, start, end, tag, setter))

    if not candidates:
        fail("no editable text input with a React setter was found")

    candidates.sort(key=lambda item: item[0], reverse=True)
    top = candidates[0]
    if top[0] < 25:
        summary = ", ".join(str(item[0]) for item in candidates[:5])
        fail(f"could not identify recipient input semantically; top scores={summary}")

    if len(candidates) > 1 and candidates[1][0] == top[0]:
        fail(f"recipient input is ambiguous; tied semantic score={top[0]}")

    return top[1], top[2], top[3], top[4]


def scanner_button(setter: str) -> str:
    return f'''\n          <button
            type="button"
            className="blee-recipient-qr-icon"
            aria-label="Scan recipient QR code"
            title="Scan QR"
            onClick={{async () => {{
              try {{
                const result = await BleeQrScanner.scan();
                if (result?.cancelled || !result?.value) return;
                {setter}(parseBleeRecipientQr(result.value));
              }} catch (error) {{
                const message = error instanceof Error ? error.message : 'Unable to scan this QR code.';
                window.alert(message);
              }}
            }}}}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3" />
            </svg>
          </button>'''


def main() -> None:
    if not APP.is_file():
        fail("materialized BleeApp.tsx missing")

    text = APP.read_text()
    for marker in (
        "BLEE_SEND_QR_SCANNER_V1",
        "registerPlugin<BleeQrScannerPlugin>('BleeQrScanner')",
        "parseBleeRecipientQr",
    ):
        if marker not in text:
            fail(f"QR implementation missing {marker}")

    # Remove only scanner controls/markers from previous stages. Nothing else in
    # the Send form is rewritten until the actual recipient input is identified.
    text = re.sub(
        r'\s*<button\b(?=[^>]*\bclassName="(?:blee-recipient-qr-scan|blee-recipient-qr-icon)")[\s\S]*?</button>',
        '',
        text,
    )
    text = text.replace('{/* BLEE_QR_INPUT_SHELL_V2 */}', '')

    start, end, tag, setter = recipient_input(text)
    if "password" in tag.lower() or "passphrase" in tag.lower():
        fail("refusing to install scanner on secret input")

    button = scanner_button(setter)
    wrapper_token = '<div className="blee-recipient-input-shell">'
    wrapper_start = text.rfind(wrapper_token, max(0, start - 700), start + 1)

    if wrapper_start >= 0:
        wrapper_close = text.find("</div>", end)
        if wrapper_close < 0 or wrapper_close - end > 1200:
            fail("existing recipient input wrapper is malformed")
        text = text[:end] + button + text[end:]
        wrapper_close = text.find("</div>", end + len(button))
        close_end = wrapper_close + len("</div>")
        text = text[:close_end] + "{/* BLEE_QR_INPUT_SHELL_V2 */}" + text[close_end:]
    else:
        shell = wrapper_token + "\n" + tag + button + '\n        </div>{/* BLEE_QR_INPUT_SHELL_V2 */}'
        text = text[:start] + shell + text[end:]

    marker = "// BLEE_FINAL_QR_NORMALIZE_V4_SEMANTIC"
    if marker not in text:
        text = marker + "\n" + text
    APP.write_text(text)

    final = APP.read_text()
    final_start, final_end, _final_tag, _final_setter = recipient_input(final)
    window = final[max(0, final_start - 250):min(len(final), final_end + 1800)]

    total = final.count('className="blee-recipient-qr-icon"')
    legacy = final.count('className="blee-recipient-qr-scan"')
    if total != 1 or legacy != 0:
        fail(f"scanner cardinality invalid total={total} legacy={legacy}")
    if 'className="blee-recipient-qr-icon"' not in window:
        fail("QR icon is not adjacent to the semantic recipient input")
    if "BleeQrScanner.scan()" not in window:
        fail("recipient QR control is not wired to the native scanner")
    if "parseBleeRecipientQr(result.value)" not in window:
        fail("recipient QR control does not validate scanned recipient data")
    if '<span>Scan QR</span>' in final or '>Scan QR<' in final:
        fail("visible Scan QR text survived")
    if final.count('BLEE_QR_INPUT_SHELL_V2') != 1:
        fail("recipient QR input shell marker is missing or duplicated")

    print("VERIFIED: final React tree has one native QR icon bound to the semantic Send recipient input")


if __name__ == "__main__":
    main()
