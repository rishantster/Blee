#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/components/BleeApp.tsx"


def fail(message: str) -> None:
    raise SystemExit(f"Blee final QR normalize v3: {message}")


def input_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    input_start = text.find("<input", start, end)
    if input_start < 0:
        fail("Send Recipient input not found")
    close = text.find("/>", input_start, end)
    if close >= 0:
        return input_start, close + 2
    quote = None
    braces = 0
    for i in range(input_start + 6, end):
        ch = text[i]
        if quote:
            if ch == quote and text[i - 1] != "\\":
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch == "{":
            braces += 1
        elif ch == "}" and braces:
            braces -= 1
        elif ch == ">" and braces == 0:
            return input_start, i + 1
    fail("Send Recipient input tag is unterminated")
    return -1, -1


def find_send_bounds(text: str) -> tuple[int, int, int, int]:
    review_matches = list(re.finditer(r"Review payment", text))
    if not review_matches:
        fail("Review payment anchor missing")
    review = review_matches[-1].start()
    window_start = max(0, review - 18000)
    send_labels = list(re.finditer(r">\s*Send\s*<", text[window_start:review], re.I))
    if not send_labels:
        fail("Send heading missing")
    send_start = window_start + send_labels[-1].start()
    recipient_labels = list(re.finditer(r">\s*Recipient\s*<", text[send_start:review], re.I))
    if not recipient_labels:
        fail("Recipient label missing")
    recipient = send_start + recipient_labels[-1].end()
    amount_labels = list(re.finditer(r">\s*Amount\s*<", text[recipient:review], re.I))
    if not amount_labels:
        fail("Amount label missing")
    amount = recipient + amount_labels[0].start()
    return send_start, recipient, amount, review


def main() -> None:
    if not APP.is_file():
        fail("materialized BleeApp.tsx missing")
    text = APP.read_text()
    for marker in ("BLEE_SEND_QR_SCANNER_V1", "BLEE_QR_INPUT_SHELL_V2", "BleeQrScanner.scan()"):
        if marker not in text:
            fail(f"QR base missing {marker}")

    # Remove every rendered QR control regardless of whether a previous stage
    # left the legacy text button or the final icon button. The final React tree
    # gets exactly one control rebuilt below.
    text = re.sub(
        r'\s*<button\b(?=[^>]*\bclassName="(?:blee-recipient-qr-scan|blee-recipient-qr-icon)")[\s\S]*?</button>',
        '',
        text,
    )
    # Collapse an old QR wrapper so we can reconstruct a single clean shell.
    text = text.replace('<div className="blee-recipient-input-shell">', '')
    text = text.replace('</div>{/* BLEE_QR_INPUT_SHELL_V2 */}', '')

    send_start, recipient, amount, review = find_send_bounds(text)
    input_start, input_end = input_bounds(text, recipient, amount)
    input_tag = text[input_start:input_end]
    if "password" in input_tag.lower() or "passphrase" in input_tag.lower():
        fail("refusing to install scanner on secret input")

    setter = None
    value_match = re.search(r"\bvalue\s*=\s*\{\s*([A-Za-z_$][\w$]*)\s*\}", input_tag)
    if value_match:
        state_name = value_match.group(1)
        state_match = re.search(
            r"const\s*\[\s*" + re.escape(state_name) + r"\s*,\s*([A-Za-z_$][\w$]*)\s*\]\s*=\s*useState",
            text,
        )
        if state_match:
            setter = state_match.group(1)
    if not setter:
        change_match = re.search(
            r"onChange\s*=\s*\{\s*\(?\s*([A-Za-z_$][\w$]*)\s*\)?\s*=>\s*([A-Za-z_$][\w$]*)\s*\(\s*\1\.target\.value\s*\)\s*\}",
            input_tag,
        )
        if change_match:
            setter = change_match.group(2)
    if not setter:
        fail("Recipient setter missing")

    button = f'''\n          <button
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
    shell = '<div className="blee-recipient-input-shell">\n' + input_tag + button + '\n        </div>{/* BLEE_QR_INPUT_SHELL_V2 */}'
    text = text[:input_start] + shell + text[input_end:]

    marker = "// BLEE_FINAL_QR_NORMALIZE_V3"
    if marker not in text:
        text = marker + "\n" + text
    APP.write_text(text)

    final = APP.read_text()
    send_start, _recipient, _amount, review = find_send_bounds(final)
    send_region = final[send_start:review]
    total = final.count('className="blee-recipient-qr-icon"')
    in_send = send_region.count('className="blee-recipient-qr-icon"')
    legacy = final.count('className="blee-recipient-qr-scan"')
    if total != 1 or in_send != 1 or legacy != 0:
        fail(f"scanner cardinality invalid total={total} send={in_send} legacy={legacy}")
    outside = final[:send_start] + final[review:]
    if 'className="blee-recipient-qr-icon"' in outside:
        fail("QR scanner exists outside Send")
    if '<span>Scan QR</span>' in final or '>Scan QR<' in final:
        fail("visible Scan QR text survived")
    if final.count('BLEE_QR_INPUT_SHELL_V2') != 1:
        fail("Recipient QR input shell is missing or duplicated")

    print("VERIFIED: final React tree contains exactly one QR icon, inside Send Recipient only")


if __name__ == "__main__":
    main()
