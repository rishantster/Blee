#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/components/BleeApp.tsx"


def fail(message: str) -> None:
    raise SystemExit(f"Blee QR resume compatibility: {message}")


def main() -> None:
    if not APP.is_file():
        fail("materialized BleeApp.tsx missing")

    text = APP.read_text()

    # Clean builds have not installed the QR base yet. Let the base stage do its
    # normal work without changing anything.
    if "BLEE_SEND_QR_SCANNER_V1" not in text:
        print("Blee QR resume compatibility: clean tree; base scanner will install normally")
        return

    scan_token = 'className="blee-recipient-qr-scan"'
    icon_token = 'className="blee-recipient-qr-icon"'
    scan_count = text.count(scan_token)
    icon_count = text.count(icon_token)

    if scan_count > 1 or icon_count > 1 or (scan_count and icon_count):
        fail(f"ambiguous resumed scanner controls: old={scan_count}, icon={icon_count}")

    # A resumed tree may already be at QR UX v2. The base v1 verifier runs before
    # the v2 normalizer and historically expected the old class name, causing a
    # false failure. Temporarily map the one v2 control back to the base class;
    # placement-fix then rebuilds it once and QR UX v2 reinstalls the final icon.
    if scan_count == 0 and icon_count == 1:
        text = text.replace(icon_token, scan_token, 1)
        APP.write_text(text)
        scan_count = 1
        icon_count = 0

    if scan_count != 1:
        fail("base scanner marker exists but no rendered Send recipient scanner control exists")

    final = APP.read_text()
    for marker in (
        "BLEE_SEND_QR_SCANNER_V1",
        "registerPlugin<BleeQrScannerPlugin>('BleeQrScanner')",
        "parseBleeRecipientQr",
        'aria-label="Scan recipient QR code"',
        "BleeQrScanner.scan()",
        scan_token,
    ):
        if marker not in final:
            fail(f"resumed scanner implementation missing {marker}")

    print("VERIFIED: resumed QR scanner tree is normalized for the base/placement/v2 pipeline")


if __name__ == "__main__":
    main()
