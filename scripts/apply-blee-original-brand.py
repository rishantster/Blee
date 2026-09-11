#!/usr/bin/env python3
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
WORDMARK = ROOT / "brand-assets" / "blee-wordmark.svg"
MARK = ROOT / "brand-assets" / "blee-mark.svg"
CSS = ROOT / "app" / "globals.css"
PUBLIC = ROOT / "public" / "brand"

for source in (WORDMARK, MARK):
    if not source.is_file():
        raise SystemExit(f"Blee brand source missing: {source.relative_to(ROOT)}")

PUBLIC.mkdir(parents=True, exist_ok=True)
shutil.copy2(WORDMARK, PUBLIC / "blee-wordmark.svg")
shutil.copy2(MARK, PUBLIC / "blee-mark.svg")

if not CSS.is_file():
    raise SystemExit("Blee brand install: app/globals.css missing")

text = CSS.read_text()
marker = "/* BLEE_ORIGINAL_BRAND_ASSETS */"
if marker in text:
    text = text[: text.index(marker)].rstrip()

# The 2.4 UI already owns spacing/layout. This block only replaces the synthetic
# in-app lockup with the user-supplied original Blee wordmark, preserving the
# existing header geometry and all interactions.
override = r'''
/* BLEE_ORIGINAL_BRAND_ASSETS */
.blee-brand-lockup,
.brand-lockup,
[data-blee-brand="lockup"] {
  width: 108px !important;
  min-width: 108px !important;
  height: 43px !important;
  flex: 0 0 108px !important;
  background-image: url('/brand/blee-wordmark.svg') !important;
  background-repeat: no-repeat !important;
  background-position: center !important;
  background-size: contain !important;
  color: transparent !important;
  text-shadow: none !important;
}

.blee-brand-lockup > *,
.brand-lockup > *,
[data-blee-brand="lockup"] > * {
  visibility: hidden !important;
}

.blee-brand-lockup::before,
.blee-brand-lockup::after,
.brand-lockup::before,
.brand-lockup::after,
[data-blee-brand="lockup"]::before,
[data-blee-brand="lockup"]::after {
  content: none !important;
  display: none !important;
}
'''
CSS.write_text(text + "\n\n" + override + "\n")

app = ROOT / "src" / "components" / "BleeApp.tsx"
app_text = app.read_text(errors="replace") if app.is_file() else ""
if not any(token in (app_text + "\n" + CSS.read_text()) for token in ("blee-brand-lockup", "brand-lockup", 'data-blee-brand="lockup"')):
    raise SystemExit("Blee brand install: could not find the 2.4 brand lockup hook")

for generated in (PUBLIC / "blee-wordmark.svg", PUBLIC / "blee-mark.svg"):
    if generated.stat().st_size < 500:
        raise SystemExit(f"Blee brand install: generated asset looks invalid: {generated}")

print("Blee 2.4: original supplied wordmark installed in app headers")
print("Blee 2.4: original supplied mark staged for launcher/app identity")
