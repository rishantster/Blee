#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def locate_service() -> Path:
    matches = list(ANDROID_JAVA.rglob("BleeMeshService.java"))
    if len(matches) != 1:
        raise SystemExit(f"Blee BLE v4 input normalization: expected one BleeMeshService.java, found {len(matches)}")
    return matches[0]


def main() -> None:
    path = locate_service()
    text = path.read_text()

    # final-hardening-2 installs an earlier advertiser-recovery layer. BLE v4
    # supersedes that implementation with a richer scanner/advertiser state
    # machine, but its patcher expects the pre-recovery anchors. Normalize only
    # those narrow pieces and leave every other hardening change intact.
    field_block = '''    private volatile boolean scanning = false;\n    private volatile boolean advertising = false;\n    // BLEE_ADVERTISER_RECOVERY_V1'''
    if field_block in text:
        text = text.replace(field_block, "    private volatile boolean scanning = false;", 1)

    text = text.replace(
        "if (!scanning || !advertising) startBluetooth();",
        "if (!scanning) startBluetooth();",
        1,
    )
    text = text.replace(
        "if (advertiser != null && !advertising) {",
        "if (advertiser != null) {",
        1,
    )

    callback_start = text.find("    private final AdvertiseCallback advertiseCallback = new AdvertiseCallback() {")
    callback_end_marker = "\n\n    private final ScanCallback scanCallback = new ScanCallback() {"
    callback_end = text.find(callback_end_marker, callback_start) if callback_start >= 0 else -1
    if callback_start >= 0 and callback_end >= 0:
        text = (
            text[:callback_start]
            + "    private final AdvertiseCallback advertiseCallback = new AdvertiseCallback() {};"
            + text[callback_end:]
        )

    required = (
        "private volatile boolean scanning = false;",
        "if (!scanning) startBluetooth();",
        "private final AdvertiseCallback advertiseCallback = new AdvertiseCallback() {};",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise SystemExit(f"Blee BLE v4 input normalization failed: {missing}")

    if text.count("private volatile boolean advertising = false;") > 0:
        raise SystemExit("Blee BLE v4 input normalization left an old advertising field behind")

    path.write_text(text)
    print("Blee BLE v4 input normalized: earlier advertiser recovery collapsed into the canonical v4 transport layer")


if __name__ == "__main__":
    main()
