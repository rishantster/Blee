#!/usr/bin/env python3
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
WORDMARK = ROOT / "brand-assets" / "blee-wordmark.svg"
MARK = ROOT / "brand-assets" / "blee-mark.svg"
CSS = ROOT / "app" / "globals.css"
PUBLIC = ROOT / "public" / "brand"
APP = ROOT / "src" / "components" / "BleeApp.tsx"

for source in (WORDMARK, MARK):
    if not source.is_file():
        raise SystemExit(f"Blee brand source missing: {source.relative_to(ROOT)}")

PUBLIC.mkdir(parents=True, exist_ok=True)
shutil.copy2(WORDMARK, PUBLIC / "blee-wordmark.svg")
shutil.copy2(MARK, PUBLIC / "blee-mark.svg")

if not CSS.is_file() or not APP.is_file():
    raise SystemExit("Blee brand install: generated app/CSS missing")

app_text = APP.read_text(errors="replace")
if '/brand/blee-wordmark.svg' not in app_text or 'className="blee-wordmark"' not in app_text:
    raise SystemExit("Blee brand install: app does not render the supplied wordmark as an image")

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
.splash-screen .blee-wordmark {
  width: 136px !important;
  height: auto !important;
}
'''
CSS.write_text(text + "\n\n" + override + "\n")

if WORDMARK.read_bytes() != (PUBLIC / "blee-wordmark.svg").read_bytes():
    raise SystemExit("Blee brand install: wordmark copy is not byte-identical")
if MARK.read_bytes() != (PUBLIC / "blee-mark.svg").read_bytes():
    raise SystemExit("Blee brand install: mark copy is not byte-identical")

print("Blee 2.5: supplied Blee wordmark installed with natural aspect ratio and no forced-height compression")
print("Blee 2.5: supplied standalone mark staged for launcher identity")
