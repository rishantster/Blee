#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/verify-blee-mesh-v2.py"

if not TARGET.is_file():
    raise SystemExit("Blee verifier alignment: verify-blee-mesh-v2.py missing")

text = TARGET.read_text()
old_check = 'if package.get("version") != "2.5.1":\n        raise SystemExit(f"VERIFY ERROR: package version is {package.get(\'version\')}, expected 2.5.1")'
new_check = 'if package.get("version") != "2.7.0":\n        raise SystemExit(f"VERIFY ERROR: package version is {package.get(\'version\')}, expected 2.7.0")'

if old_check in text:
    text = text.replace(old_check, new_check, 1)
elif 'expected 2.7.0' not in text:
    raise SystemExit("Blee verifier alignment: expected version check not found")

if 'expected 2.5.1' in text or '!= "2.5.1"' in text:
    raise SystemExit("Blee verifier alignment: stale 2.5.1 version gate remains")

TARGET.write_text(text)
print("VERIFIED: mesh verifier release gate aligned to Blee 2.7.0")
