#!/usr/bin/env python3
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
WORDMARK = ROOT / "brand-assets" / "blee-wordmark.svg"
LOGO = ROOT / "brand-assets" / "blee-logo.svg"
MARK = ROOT / "brand-assets" / "blee-mark.svg"  # legacy alias only
CSS = ROOT / "app" / "globals.css"
PUBLIC = ROOT / "public" / "brand"
APP = ROOT / "src" / "components" / "BleeApp.tsx"

for source in (WORDMARK, LOGO):
    if not source.is_file():
        raise SystemExit(f"Blee brand source missing: {source.relative_to(ROOT)}")

PUBLIC.mkdir(parents=True, exist_ok=True)
shutil.copy2(WORDMARK, PUBLIC / "blee-wordmark.svg")
shutil.copy2(LOGO, PUBLIC / "blee-logo.svg")
# Keep the old mark path byte-identical for compatibility, but all new launch
# identity code uses the explicit canonical blee-logo.svg name.
shutil.copy2(LOGO, PUBLIC / "blee-mark.svg")

if not CSS.is_file() or not APP.is_file():
    raise SystemExit("Blee brand install: generated app/CSS missing")

app_text = APP.read_text(errors="replace")
if '/brand/blee-wordmark.svg' not in app_text or 'className="blee-wordmark"' not in app_text:
    raise SystemExit("Blee brand install: app does not render the supplied wordmark in normal headers")

# The cold-launch screen must use the standalone Blee logo, not the Blee
# wordmark. This deliberately leaves normal in-app headers on the wordmark.
splash_pattern = re.compile(
    r'(<img\b(?=[^>]*className=["\'][^"\']*splash-logo[^"\']*["\'])[^>]*?src=["\'])/brand/blee-wordmark\.svg(["\'][^>]*>)',
    re.I,
)
app_text, splash_hits = splash_pattern.subn(r'\1/brand/blee-logo.svg\2', app_text, count=1)
if splash_hits != 1:
    # Defensive fallback for JSX where src appears before className.
    tag_pattern = re.compile(r'<img\b[^>]*splash-logo[^>]*>', re.I)
    match = tag_pattern.search(app_text)
    if match and '/brand/blee-wordmark.svg' in match.group(0):
        replaced = match.group(0).replace('/brand/blee-wordmark.svg', '/brand/blee-logo.svg', 1)
        app_text = app_text[:match.start()] + replaced + app_text[match.end():]
        splash_hits = 1
if splash_hits != 1:
    raise SystemExit("Blee brand install: could not bind cold-launch splash to the standalone Blee logo")
APP.write_text(app_text)

text = CSS.read_text()
marker = "/* BLEE_ORIGINAL_BRAND_ASSETS */"
if marker in text:
    text = text[: text.index(marker)].rstrip()

override = r'''
/* BLEE_ORIGINAL_BRAND_ASSETS */
[data-blee-brand="lockup"] {
  width: auto !important;
  min-width: 0 !important;
  height: auto !important;
  min-height: 0 !important;
  flex: none !important;
  background: none !important;
  color: var(--ink) !important;
}
[data-blee-brand="lockup"] > * {
  visibility: visible !important;
}
.blee-wordmark {
  display: block !important;
  width: 118px !important;
  height: auto !important;
  max-width: none !important;
  object-fit: contain !important;
  object-position: center !important;
}
.blee-brand.compact .blee-wordmark {
  width: 82px !important;
  height: auto !important;
}
/* Cold launch uses the actual standalone Blee logo, never the wordmark. */
.splash-screen .splash-logo {
  display: block !important;
  width: 78px !important;
  height: auto !important;
  max-width: 78px !important;
  object-fit: contain !important;
  object-position: center !important;
  transform-origin: center center;
  animation: blee-launch-logo 680ms cubic-bezier(.22,.8,.24,1) both !important;
  will-change: transform, opacity;
}
@media (prefers-reduced-motion: reduce) {
  .splash-screen .splash-logo {
    animation: none !important;
  }
}
'''
CSS.write_text(text + "\n\n" + override + "\n")

if WORDMARK.read_bytes() != (PUBLIC / "blee-wordmark.svg").read_bytes():
    raise SystemExit("Blee brand install: wordmark copy is not byte-identical")
if LOGO.read_bytes() != (PUBLIC / "blee-logo.svg").read_bytes():
    raise SystemExit("Blee brand install: logo copy is not byte-identical")
if LOGO.read_bytes() != (PUBLIC / "blee-mark.svg").read_bytes():
    raise SystemExit("Blee brand install: legacy mark alias does not match canonical logo")

print("Blee brand: normal headers use the supplied wordmark at natural aspect ratio")
print("Blee brand: cold launch uses the supplied standalone logo with preserved geometry + subtle animation")
print("Blee brand: canonical logo staged for Android launcher identity")
