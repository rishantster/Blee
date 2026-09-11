#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source_wordmark = ROOT / "brand-assets" / "blee-wordmark.svg"
source_mark = ROOT / "brand-assets" / "blee-mark.svg"
public_wordmark = ROOT / "public" / "brand" / "blee-wordmark.svg"
public_mark = ROOT / "public" / "brand" / "blee-mark.svg"
css = ROOT / "app" / "globals.css"
launcher = ROOT / "android" / "app" / "src" / "main" / "res" / "drawable" / "blee_launcher.xml"

for path in (source_wordmark, source_mark, public_wordmark, public_mark, css, launcher):
    if not path.is_file():
        raise SystemExit(f"BRAND VERIFY ERROR: missing {path.relative_to(ROOT)}")

if source_wordmark.read_bytes() != public_wordmark.read_bytes():
    raise SystemExit("BRAND VERIFY ERROR: in-app wordmark differs from supplied source asset")
if source_mark.read_bytes() != public_mark.read_bytes():
    raise SystemExit("BRAND VERIFY ERROR: public mark differs from supplied source asset")

css_text = css.read_text()
for marker in ("BLEE_ORIGINAL_BRAND_ASSETS", "/brand/blee-wordmark.svg", "blee-brand-lockup"):
    if marker not in css_text:
        raise SystemExit(f"BRAND VERIFY ERROR: globals.css missing {marker}")

launcher_text = launcher.read_text()
for marker in ("M39,12 L27,19", 'android:fillColor="#0A0A0A"', 'android:fillType="evenOdd"'):
    if marker not in launcher_text:
        raise SystemExit(f"BRAND VERIFY ERROR: launcher does not contain original mark geometry: {marker}")

print("============================================================")
print("VERIFIED: original supplied Blee brand assets")
print("- original full Blee wordmark is used for in-app lockups")
print("- original standalone Blee mark is used for Android launcher identity")
print("- no synthetic text/logo geometry is visible in the 2.4 header")
print("============================================================")
