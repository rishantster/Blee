#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/components/BleeApp.tsx"


def fail(message: str) -> None:
    raise SystemExit(f"Blee QR scanner placement: {message}")


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
    fail("unable to identify Send Recipient state setter")


def scanner_button(setter: str) -> str:
    return f'''
        <button
          type="button"
          className="blee-recipient-qr-scan"
          aria-label="Scan recipient QR code"
          onClick={{async () => {{
            try {{
              const result = await BleeQrScanner.scan();
              if (result?.cancelled || !result?.value) return;
              const scannedRecipient = parseBleeRecipientQr(result.value);
              {setter}(scannedRecipient);
            }} catch (error) {{
              const message = error instanceof Error ? error.message : 'Unable to scan this QR code.';
              window.alert(message);
            }}
          }}}}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4M8 8h3v3H8zM13 8h3v3h-3zM8 13h3v3H8zM13 13h3v3h-3z" />
          </svg>
          <span>Scan QR</span>
        </button>'''


def main() -> None:
    if not APP.is_file():
        fail("BleeApp.tsx missing")
    text = APP.read_text()
    if "BLEE_SEND_QR_SCANNER_V1" not in text:
        fail("base QR scanner stage must run first")

    # Remove every previously rendered scanner control. The original patch could
    # accidentally land inside the reusable PasswordField component, causing the
    # scanner to appear on both passphrase fields. Rebuild one control from zero.
    text, removed = re.subn(
        r'\s*<button\b(?=[^>]*\bclassName="blee-recipient-qr-scan")[\s\S]*?</button>',
        '',
        text,
    )

    review_matches = list(re.finditer(r"Review payment", text))
    if not review_matches:
        fail("Review payment anchor missing")
    review = review_matches[-1].start()
    window_start = max(0, review - 14000)

    # Locate the actual Send heading, then the visible Recipient label nearest to
    # Review payment. This prevents matches against helper text or onboarding.
    send_labels = list(re.finditer(r">\s*Send\s*<", text[window_start:review], re.I))
    if not send_labels:
        fail("Send screen heading anchor missing")
    send_start = window_start + send_labels[-1].start()

    recipient_labels = list(re.finditer(r">\s*Recipient\s*<", text[send_start:review], re.I))
    if not recipient_labels:
        fail("visible Send Recipient label missing")
    recipient = send_start + recipient_labels[-1].end()

    amount_labels = list(re.finditer(r">\s*Amount\s*<", text[recipient:review], re.I))
    if not amount_labels:
        fail("Send Amount label missing")
    amount = recipient + amount_labels[0].start()

    input_start, input_end = input_bounds(text, recipient, amount)
    input_tag = text[input_start:input_end]
    if re.search(r'type\s*=\s*["\']password["\']', input_tag, re.I) or "passphrase" in input_tag.lower():
        fail("refusing to install QR scanner beside a password/passphrase input")

    setter = recipient_setter(text, input_tag)
    button = scanner_button(setter)
    text = text[:input_end] + button + text[input_end:]
    APP.write_text(text)

    final = APP.read_text()
    button_hits = [m.start() for m in re.finditer(r'className="blee-recipient-qr-scan"', final)]
    if len(button_hits) != 1:
        fail(f"expected exactly one rendered QR scanner control, found {len(button_hits)}")
    button_at = button_hits[0]
    if not (send_start < recipient < input_start < button_at < amount < review):
        fail("QR scanner is not scoped to Send Recipient before Amount/Review")

    # Build-time regression guards for the exact screenshot failure.
    create_passphrase = final.find("Create passphrase")
    confirm_passphrase = final.find("Confirm passphrase")
    if create_passphrase >= 0 and abs(button_at - create_passphrase) < 2500:
        fail("QR scanner leaked into Create passphrase UI")
    if confirm_passphrase >= 0 and abs(button_at - confirm_passphrase) < 2500:
        fail("QR scanner leaked into Confirm passphrase UI")

    print("VERIFIED: QR scanner appears exactly once and only on Send Recipient")
    if removed:
        print(f"Blee QR placement: removed {removed} stale/misplaced scanner control(s) before reinstalling")


if __name__ == "__main__":
    main()
