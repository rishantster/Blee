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


def recipient_setter(text: str, input_tag: str) -> str:
    value_match = re.search(r"\bvalue\s*=\s*\{\s*([A-Za-z_$][\w$]*)\s*\}", input_tag)
    if value_match:
        state_name = value_match.group(1)
        state_match = re.search(
            r"const\s*\[\s*" + re.escape(state_name) + r"\s*,\s*([A-Za-z_$][\w$]*)\s*\]\s*=\s*useState",
            text,
        )
        if state_match:
            return state_match.group(1)
    change_match = re.search(
        r"onChange\s*=\s*\{\s*\(?\s*([A-Za-z_$][\w$]*)\s*\)?\s*=>\s*([A-Za-z_$][\w$]*)\s*\(\s*\1\.target\.value\s*\)\s*\}",
        input_tag,
    )
    if change_match:
        return change_match.group(2)
    fail("Recipient setter missing")
    return ""


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

    # Only durable module-level QR plumbing must exist before normalization.
    # The rendered button/call is intentionally allowed to be absent because
    # this stage exists to reconstruct it after later React structural patches.
    for marker in (
        "BLEE_SEND_QR_SCANNER_V1",
        "registerPlugin<BleeQrScannerPlugin>('BleeQrScanner')",
        "parseBleeRecipientQr",
    ):
        if marker not in text:
            fail(f"QR implementation missing {marker}")

    send_start, recipient, amount, review = find_send_bounds(text)
    segment = text[recipient:amount]

    # Remove every rendered scanner control in the Recipient field. Both legacy
    # text-button and final icon forms are normalized to one canonical icon.
    segment = re.sub(
        r'\s*<button\b(?=[^>]*\bclassName="(?:blee-recipient-qr-scan|blee-recipient-qr-icon)")[\s\S]*?</button>',
        '',
        segment,
    )
    segment = segment.replace('{/* BLEE_QR_INPUT_SHELL_V2 */}', '')

    input_start, input_end = input_bounds(segment, 0, len(segment))
    input_tag = segment[input_start:input_end]
    if "password" in input_tag.lower() or "passphrase" in input_tag.lower():
        fail("refusing to install scanner on secret input")
    setter = recipient_setter(text, input_tag)
    button = scanner_button(setter)

    wrapper_token = '<div className="blee-recipient-input-shell">'
    wrapper_count = segment.count(wrapper_token)
    if wrapper_count > 1:
        fail(f"Recipient contains {wrapper_count} QR input wrappers")

    if wrapper_count == 1:
        wrapper_start = segment.find(wrapper_token)
        if wrapper_start > input_start:
            fail("QR input wrapper begins after Recipient input")
        wrapper_close = segment.find("</div>", input_end)
        if wrapper_close < 0:
            fail("existing QR input wrapper has no closing div")
        segment = segment[:wrapper_close] + button + "\n        " + segment[wrapper_close:]
        close_end = wrapper_close + len(button) + len("\n        ") + len("</div>")
        segment = segment[:close_end] + "{/* BLEE_QR_INPUT_SHELL_V2 */}" + segment[close_end:]
    else:
        shell = wrapper_token + "\n" + input_tag + button + '\n        </div>{/* BLEE_QR_INPUT_SHELL_V2 */}'
        segment = segment[:input_start] + shell + segment[input_end:]

    text = text[:recipient] + segment + text[amount:]

    marker = "// BLEE_FINAL_QR_NORMALIZE_V3"
    if marker not in text:
        text = marker + "\n" + text
    APP.write_text(text)

    final = APP.read_text()
    send_start, recipient, amount, review = find_send_bounds(final)
    send_region = final[send_start:review]
    recipient_region = final[recipient:amount]
    total = final.count('className="blee-recipient-qr-icon"')
    in_send = send_region.count('className="blee-recipient-qr-icon"')
    in_recipient = recipient_region.count('className="blee-recipient-qr-icon"')
    legacy = final.count('className="blee-recipient-qr-scan"')
    if total != 1 or in_send != 1 or in_recipient != 1 or legacy != 0:
        fail(f"scanner cardinality invalid total={total} send={in_send} recipient={in_recipient} legacy={legacy}")
    outside = final[:send_start] + final[review:]
    if 'className="blee-recipient-qr-icon"' in outside:
        fail("QR scanner exists outside Send")
    if '<span>Scan QR</span>' in final or '>Scan QR<' in final:
        fail("visible Scan QR text survived")
    if recipient_region.count('BLEE_QR_INPUT_SHELL_V2') != 1:
        fail("final Recipient QR input shell marker is missing or duplicated")
    if "BleeQrScanner.scan()" not in recipient_region:
        fail("final Recipient QR control is not wired to the native scanner")
    if "parseBleeRecipientQr(result.value)" not in recipient_region:
        fail("final Recipient QR control does not validate scanned recipient data")

    print("VERIFIED: final React tree contains exactly one native QR icon, inside Send Recipient only")


if __name__ == "__main__":
    main()
