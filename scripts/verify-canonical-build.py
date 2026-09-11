#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

required = {
    "build-blee.command": (
        'FINAL_APK="$ROOT/dist/Blee.apk"',
        'apply-blee-final-hardening.py --web',
        'apply-blee-final-hardening.py --android',
        'verify-blee-mesh-v2.py',
        'verify-canonical-build.py',
        'rm -f "$ROOT/dist"/*.apk',
    ),
    "ARCHITECTURE.md": (
        "main is the release/source-of-truth branch",
        "courier devices never spend their own wallet balance",
        "Blee.apk",
    ),
    "UI_ARCHITECTURE.md": (
        "Fingerprint unlock is optional",
        "APK output is not `dist/Blee.apk`",
    ),
    "scripts/apply-blee-final-hardening.py": (
        "BLEE_COURIER_NEVER_SIGNS_V1",
        "BLEE_MONOTONIC_PAYMENT_STATE_V1",
        "BLEE_NATIVE_LIFECYCLE_HARDENING_V1",
        "BLEE_CANONICAL_SETTLEMENT_VERIFY_V1",
    ),
}

for rel, markers in required.items():
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"Missing canonical Blee file: {rel}")
    text = path.read_text(errors="replace")
    missing = [m for m in markers if m not in text]
    if missing:
        raise SystemExit(f"Canonical Blee verification failed for {rel}: {missing}")

for rel in ("build-blee-macos.command", "build-blee-professional.command"):
    path = ROOT / rel
    if not path.is_file():
        continue
    text = path.read_text()
    if 'exec bash "$ROOT/build-blee.command"' not in text:
        raise SystemExit(f"Legacy builder still has independent logic: {rel}")

build = (ROOT / "build-blee.command").read_text()
if re.search(r"dist/Blee-[^\s\"']+\.apk", build):
    raise SystemExit("Versioned public APK naming survived in canonical builder")

print("Canonical Blee repository contract verified.")
