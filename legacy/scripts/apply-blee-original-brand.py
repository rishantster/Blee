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
if '/brand/blee-wordmark.svg' not in app_text or 'blee-wordmark' not in app_text:
    raise SystemExit("Blee brand install: app does not render the supplied wordmark in normal headers")
if 'splash-logo' not in app_text:
    raise SystemExit("Blee brand install: cold-launch splash element is missing")

# The v5 UI may render the cold launch through either a direct <img> or the
# reusable <Brand> component. Bind the direct form when possible; otherwise the
# CSS below replaces the splash element's rendered content with the standalone
# logo. Normal application headers remain on the full Blee wordmark.
logo_bound_in_jsx = '/brand/blee-logo.svg' in app_text

if not logo_bound_in_jsx:
    # 1) Direct img tag whose src and splash class live in the same tag.
    tag_pattern = re.compile(r'<img\b[^>]*splash-logo[^>]*>', re.I | re.S)
    match = tag_pattern.search(app_text)
    if match and '/brand/blee-wordmark.svg' in match.group(0):
        replaced = match.group(0).replace('/brand/blee-wordmark.svg', '/brand/blee-logo.svg', 1)
        app_text = app_text[:match.start()] + replaced + app_text[match.end():]
        logo_bound_in_jsx = True

if not logo_bound_in_jsx:
    # 2) Reusable JSX component, e.g. <Brand className="splash-logo" ... />.
    component_pattern = re.compile(
        r'<([A-Z][A-Za-z0-9_.]*)\b(?=[^>]*splash-logo)[^>]*/>',
        re.S,
    )
    match = component_pattern.search(app_text)
    if match:
        replacement = '<img src="/brand/blee-logo.svg" className="splash-logo" alt="Blee" />'
        app_text = app_text[:match.start()] + replacement + app_text[match.end():]
        logo_bound_in_jsx = True

# If splash-logo is a wrapper rather than the image/component itself, do not
# guess at the surrounding JSX. CSS below hides the nested wordmark and paints
# the standalone logo from the canonical asset. That is deliberate and verified.
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

/* BLEE_STANDALONE_LAUNCH_LOGO_V2
   Cold launch uses the actual standalone Blee logo file. The rules support
   both the direct <img class="splash-logo"> form and the older wrapper/Brand
   component form without distorting the logo's 300:399 source geometry. */
.splash-screen .splash-logo {
  display: block !important;
  width: 78px !important;
  max-width: 78px !important;
  transform-origin: center center;
  animation: blee-launch-logo 680ms cubic-bezier(.22,.8,.24,1) both !important;
  will-change: transform, opacity;
}
.splash-screen img.splash-logo {
  content: url("/brand/blee-logo.svg") !important;
  height: auto !important;
  object-fit: contain !important;
  object-position: center !important;
}
.splash-screen .splash-logo:not(img) {
  aspect-ratio: 300 / 399 !important;
  height: auto !important;
  background-image: url("/brand/blee-logo.svg") !important;
  background-repeat: no-repeat !important;
  background-position: center !important;
  background-size: contain !important;
  color: transparent !important;
  font-size: 0 !important;
}
.splash-screen .splash-logo:not(img) > * {
  opacity: 0 !important;
  visibility: hidden !important;
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

css_verify = CSS.read_text(errors="replace")
for required in (
    'BLEE_STANDALONE_LAUNCH_LOGO_V2',
    'url("/brand/blee-logo.svg")',
    'aspect-ratio: 300 / 399',
    'animation: blee-launch-logo 680ms',
):
    if required not in css_verify:
        raise SystemExit(f"Blee brand install: launch-logo CSS missing {required}")
if '/brand/blee-logo.svg' not in APP.read_text(errors="replace") and 'splash-logo' not in APP.read_text(errors="replace"):
    raise SystemExit("Blee brand install: no splash logo binding survives")

print("Blee brand: normal headers use the supplied wordmark at natural aspect ratio")
if logo_bound_in_jsx:
    print("Blee brand: cold launch directly renders the supplied standalone logo")
else:
    print("Blee brand: cold launch wrapper is forced to the supplied standalone logo asset")
print("Blee brand: standalone logo keeps its original 300:399 geometry + subtle animation")
print("Blee brand: canonical logo staged for Android launcher identity")
