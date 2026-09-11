#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MARK_SVG = ROOT / "brand-assets" / "blee-mark.svg"

if not MARK_SVG.is_file():
    raise SystemExit("Blee launcher: brand-assets/blee-mark.svg missing")

svg = MARK_SVG.read_text()
path_match = re.search(r'<path\s+[^>]*d="([^"]+)"[^>]*/?>', svg)
viewbox_match = re.search(r'viewBox="0\s+0\s+([0-9.]+)\s+([0-9.]+)"', svg)
if not path_match or not viewbox_match:
    raise SystemExit("Blee launcher: supplied mark SVG is malformed")

MARK_PATH = path_match.group(1)
source_w = float(viewbox_match.group(1))
source_h = float(viewbox_match.group(2))

# Preserve the exact user-supplied mark geometry. Only scale/position it inside
# the Android launcher safe area so OEM circle/squircle masks do not crop it.
target_h = 72.0
scale = target_h / source_h
rendered_w = source_w * scale
translate_x = (100.0 - rendered_w) / 2.0
translate_y = (100.0 - target_h) / 2.0

res = ROOT / "android" / "app" / "src" / "main" / "res"
drawable = res / "drawable"
drawable.mkdir(parents=True, exist_ok=True)

xml = f"""<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp"
    android:height="108dp"
    android:viewportWidth="100"
    android:viewportHeight="100">
  <path android:fillColor="#FAFAF8" android:pathData="M0,0 H100 V100 H0 Z"/>
  <group
      android:scaleX="{scale:.8f}"
      android:scaleY="{scale:.8f}"
      android:translateX="{translate_x:.8f}"
      android:translateY="{translate_y:.8f}">
    <path
        android:fillColor="#0A0A0A"
        android:fillType="evenOdd"
        android:pathData="{MARK_PATH}"/>
  </group>
</vector>
"""

(drawable / "blee_launcher.xml").write_text(xml)
print("Blee launcher: original supplied mark applied with exact source geometry.")
