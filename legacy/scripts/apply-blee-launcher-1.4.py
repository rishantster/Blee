#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
LOGO_SVG = ROOT / "brand-assets" / "blee-logo.svg"

if not LOGO_SVG.is_file():
    raise SystemExit("Blee launcher: brand-assets/blee-logo.svg missing")

svg = LOGO_SVG.read_text()
path_match = re.search(r'<path\s+[^>]*d="([^"]+)"[^>]*/?>', svg)
viewbox_match = re.search(r'viewBox="0\s+0\s+([0-9.]+)\s+([0-9.]+)"', svg)
if not path_match or not viewbox_match:
    raise SystemExit("Blee launcher: supplied logo SVG is malformed")

LOGO_PATH = path_match.group(1)
source_w = float(viewbox_match.group(1))
source_h = float(viewbox_match.group(2))

# Preserve the exact user-supplied standalone logo geometry. Only scale and
# center it inside Android's safe launcher area; never stretch either axis.
target_h = 64.0
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
        android:pathData="{LOGO_PATH}"/>
  </group>
</vector>
"""

launcher = drawable / "blee_launcher.xml"
launcher.write_text(xml)

# Capacitor's generated Android project points at its own default mipmap icon.
# Explicitly bind both icon slots to Blee's standalone logo so the launcher,
# task switcher, system biometric prompt and Android splash all use the same
# identity instead of a stale/default Capacitor asset.
manifest = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
if not manifest.is_file():
    raise SystemExit("Blee launcher: AndroidManifest.xml missing")
manifest_text = manifest.read_text()
application_match = re.search(r'<application\b[^>]*>', manifest_text, re.S)
if not application_match:
    raise SystemExit("Blee launcher: <application> tag missing")
app_tag = application_match.group(0)

if re.search(r'android:icon="[^"]+"', app_tag):
    app_tag = re.sub(r'android:icon="[^"]+"', 'android:icon="@drawable/blee_launcher"', app_tag, count=1)
else:
    app_tag = app_tag[:-1] + '\n        android:icon="@drawable/blee_launcher">'

if re.search(r'android:roundIcon="[^"]+"', app_tag):
    app_tag = re.sub(r'android:roundIcon="[^"]+"', 'android:roundIcon="@drawable/blee_launcher"', app_tag, count=1)
else:
    app_tag = app_tag[:-1] + '\n        android:roundIcon="@drawable/blee_launcher">'

manifest_text = manifest_text[:application_match.start()] + app_tag + manifest_text[application_match.end():]
manifest.write_text(manifest_text)

# Verify the manifest cannot silently fall back to generated/default icons.
verified = manifest.read_text()
for attr in ('android:icon="@drawable/blee_launcher"', 'android:roundIcon="@drawable/blee_launcher"'):
    if attr not in verified:
        raise SystemExit(f"Blee launcher: manifest wiring missing {attr}")
if 'android:scaleX' not in xml or 'android:scaleY' not in xml:
    raise SystemExit("Blee launcher: aspect-ratio preserving logo transform missing")

print("Blee launcher: standalone supplied Blee logo applied with exact source geometry.")
print("Blee launcher: manifest icon + roundIcon now point to Blee, not generated defaults.")
