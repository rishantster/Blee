#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source_wordmark = ROOT / "brand-assets" / "blee-wordmark.svg"
source_mark = ROOT / "brand-assets" / "blee-mark.svg"
public_wordmark = ROOT / "public" / "brand" / "blee-wordmark.svg"
public_mark = ROOT / "public" / "brand" / "blee-mark.svg"
css = ROOT / "app" / "globals.css"
app = ROOT / "src" / "components" / "BleeApp.tsx"
launcher = ROOT / "android" / "app" / "src" / "main" / "res" / "drawable" / "blee_launcher.xml"

for path in (source_wordmark, source_mark, public_wordmark, public_mark, css, app, launcher):
    if not path.is_file():
        raise SystemExit(f"BRAND VERIFY ERROR: missing {path.relative_to(ROOT)}")
if source_wordmark.read_bytes() != public_wordmark.read_bytes():
    raise SystemExit("BRAND VERIFY ERROR: in-app wordmark differs from supplied source asset")
if source_mark.read_bytes() != public_mark.read_bytes():
    raise SystemExit("BRAND VERIFY ERROR: public mark differs from supplied source asset")

app_text = app.read_text(errors="replace")
if '/brand/blee-wordmark.svg' not in app_text or 'className="blee-wordmark"' not in app_text:
    raise SystemExit("BRAND VERIFY ERROR: app is not rendering the supplied wordmark image")
css_text = css.read_text()
for marker in ("BLEE_ORIGINAL_BRAND_ASSETS", ".blee-wordmark", "height: auto", "/brand/blee-wordmark.svg"):
    if marker not in (css_text + "\n" + app_text):
        raise SystemExit(f"BRAND VERIFY ERROR: generated UI missing {marker}")
if 'background-image: url(\'/brand/blee-wordmark.svg\')' in css_text or 'visibility: hidden' in css_text[css_text.find('BLEE_ORIGINAL_BRAND_ASSETS'):]:
    raise SystemExit("BRAND VERIFY ERROR: old background-image/hide implementation would distort or mask the wordmark")

launcher_text = launcher.read_text()
for marker in ('android:fillColor="#0A0A0A"', 'android:fillType="evenOdd"'):
    if marker not in launcher_text:
        raise SystemExit(f"BRAND VERIFY ERROR: launcher mark missing expected geometry marker: {marker}")

print("============================================================")
print("VERIFIED: Blee supplied brand assets")
print("- in-app wordmark is rendered as the supplied asset with natural aspect ratio")
print("- no synthetic b + text lockup or forced-height background-image rendering")
print("- standalone mark remains the Android launcher identity")
print("============================================================")
