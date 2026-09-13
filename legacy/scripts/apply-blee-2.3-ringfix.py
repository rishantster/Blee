#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "app/globals.css"
APP = ROOT / "src/components/BleeApp.tsx"

MARKER = "BLEE_ONBOARDING_NO_DECORATIVE_RING"

BLOCK = r'''

/* BLEE_ONBOARDING_NO_DECORATIVE_RING
   The old onboarding hero used a decorative concentric halo/orbit behind the
   Blee mark. Blee 2.3 intentionally has no decorative hero graphic at all. */
[class*="hero" i]::before,
[class*="hero" i]::after,
[class*="hero" i] [class*="ring" i],
[class*="hero" i] [class*="rings" i],
[class*="hero" i] [class*="orbit" i],
[class*="hero" i] [class*="halo" i],
[class*="hero" i] [class*="radar" i],
[class*="hero" i] [class*="pulse" i],
[class*="hero" i] [class*="signal" i],
[class*="hero" i] [class*="visual" i],
[class*="hero" i] [class*="emblem" i],
[class*="hero" i] [class*="hero-logo" i],
[class*="hero" i] [class*="hero-mark" i],
[class*="hero" i] > [aria-hidden="true"] {
  display: none !important;
  content: none !important;
  border: 0 !important;
  outline: 0 !important;
  box-shadow: none !important;
  background: transparent !important;
}

/* Defensive cleanup for SVG concentric-circle decoration in onboarding only. */
[class*="hero" i] svg circle,
[class*="hero" i] svg ellipse {
  display: none !important;
}

/* No dead visual spacer where the removed orbit used to live. */
[class*="hero" i] {
  gap: 0 !important;
}
'''


def main() -> None:
    css = CSS.read_text()
    if MARKER in css:
        css = css[: css.index("/* " + MARKER)].rstrip()
    CSS.write_text(css + BLOCK + "\n")

    app = APP.read_text()
    if MARKER not in app:
        APP.write_text("// " + MARKER + ": onboarding contains no decorative halo/orbit.\n" + app)

    generated = CSS.read_text()
    required = (
        MARKER,
        '[class*="hero" i]::before',
        '[class*="hero" i] [class*="orbit" i]',
        '[class*="hero" i] [class*="ring" i]',
        '[class*="hero" i] svg circle',
    )
    missing = [item for item in required if item not in generated]
    if missing:
        raise SystemExit(f"Blee 2.3 ring removal verification failed: {missing}")

    print("Blee 2.3: removed onboarding decorative ring/orbit and its spacer")


if __name__ == "__main__":
    main()
