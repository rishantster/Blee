#!/usr/bin/env python3
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[1]
source_wordmark = ROOT / "brand-assets" / "blee-wordmark.svg"
source_logo = ROOT / "brand-assets" / "blee-logo.svg"
public_wordmark = ROOT / "public" / "brand" / "blee-wordmark.svg"
public_logo = ROOT / "public" / "brand" / "blee-logo.svg"
public_mark_alias = ROOT / "public" / "brand" / "blee-mark.svg"
css = ROOT / "app" / "globals.css"
app = ROOT / "src" / "components" / "BleeApp.tsx"
launcher = ROOT / "android" / "app" / "src" / "main" / "res" / "drawable" / "blee_launcher.xml"
manifest = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"

for path in (
    source_wordmark, source_logo, public_wordmark, public_logo, public_mark_alias,
    css, app, launcher, manifest,
):
    if not path.is_file():
        raise SystemExit(f"BRAND VERIFY ERROR: missing {path.relative_to(ROOT)}")

if source_wordmark.read_bytes() != public_wordmark.read_bytes():
    raise SystemExit("BRAND VERIFY ERROR: in-app wordmark differs from supplied source asset")
if source_logo.read_bytes() != public_logo.read_bytes():
    raise SystemExit("BRAND VERIFY ERROR: public standalone logo differs from supplied source asset")
if source_logo.read_bytes() != public_mark_alias.read_bytes():
    raise SystemExit("BRAND VERIFY ERROR: legacy mark alias is not byte-identical to canonical standalone logo")

# Pin the canonical logo bytes so a generated/default icon cannot silently return.
logo_hash = hashlib.sha256(source_logo.read_bytes()).hexdigest()
if logo_hash != "87812e386ba533b4e4dc6ea52c0fda6c60dee996d2428eaa13203a99b7b313e6":
    raise SystemExit(f"BRAND VERIFY ERROR: canonical standalone logo changed unexpectedly: {logo_hash}")

app_text = app.read_text(errors="replace")
if '/brand/blee-wordmark.svg' not in app_text or 'blee-wordmark' not in app_text:
    raise SystemExit("BRAND VERIFY ERROR: normal app headers are not rendering the supplied wordmark")
if 'splash-logo' not in app_text:
    raise SystemExit("BRAND VERIFY ERROR: cold-launch splash element is missing")

css_text = css.read_text(errors="replace")
for marker in (
    "BLEE_ORIGINAL_BRAND_ASSETS",
    "BLEE_STANDALONE_LAUNCH_LOGO_V2",
    ".blee-wordmark",
    "height: auto",
    '/brand/blee-logo.svg',
    'animation: blee-launch-logo 680ms',
    'aspect-ratio: 300 / 399',
):
    if marker not in (css_text + "\n" + app_text):
        raise SystemExit(f"BRAND VERIFY ERROR: generated UI missing {marker}")

# Old implementations hid the normal wordmark or painted it as a fixed-height
# background, which caused the stout/compressed logo regression. Splash wrapper
# children may intentionally be hidden because the wrapper is replaced by the
# standalone logo asset; that is not the same bug.
brand_tail = css_text[css_text.find('BLEE_ORIGINAL_BRAND_ASSETS'):]
if "background-image: url('/brand/blee-wordmark.svg')" in brand_tail:
    raise SystemExit("BRAND VERIFY ERROR: old wordmark background-image implementation returned")

launcher_text = launcher.read_text(errors="replace")
for marker in (
    'android:fillColor="#0A0A0A"',
    'android:fillType="evenOdd"',
    'android:scaleX=',
    'android:scaleY=',
):
    if marker not in launcher_text:
        raise SystemExit(f"BRAND VERIFY ERROR: launcher logo missing expected geometry marker: {marker}")

manifest_text = manifest.read_text(errors="replace")
for marker in (
    'android:icon="@drawable/blee_launcher"',
    'android:roundIcon="@drawable/blee_launcher"',
):
    if marker not in manifest_text:
        raise SystemExit(f"BRAND VERIFY ERROR: Android launcher identity missing {marker}")

print("============================================================")
print("VERIFIED: Blee supplied brand assets")
print("- normal in-app headers use the supplied wordmark at natural aspect ratio")
print("- cold launch uses the supplied standalone Blee logo with original 300:399 geometry")
print("- cold-launch logo animation remains wired")
print("- Android icon + roundIcon use the standalone Blee logo")
print("- no synthetic/default launcher identity is accepted")
print("============================================================")
