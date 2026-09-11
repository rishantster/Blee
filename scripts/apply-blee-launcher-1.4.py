#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Exact Blee mark geometry derived from the supplied brand asset, preserving
# its original width:height ratio instead of stretching it into a square.
MARK_PATH = 'M7.840,0.825L4.952,2.476L2.476,4.952L0.963,7.565L0.000,11.142L0.000,66.850L0.825,72.352L3.164,79.230L6.740,85.420L12.105,91.334L17.194,95.048L22.834,97.799L30.674,99.725L40.715,99.862L47.455,98.762L53.783,96.424L59.972,92.572L64.374,88.446L68.501,82.806L71.802,75.791L73.590,67.813L73.728,59.285L72.765,53.508L71.252,49.106L69.188,45.117L65.887,40.578L60.385,35.626L55.296,32.737L51.169,31.224L45.392,30.124L27.235,29.986L26.960,12.380L26.410,9.904L24.759,6.465L22.283,3.576L18.157,0.963L14.580,0.000L11.004,0.000Z M27.098,50.757L27.235,50.619L41.541,50.619L41.678,50.757L43.191,50.757L43.329,50.894L44.017,50.894L46.630,51.719L48.281,52.545L50.206,53.920L51.857,55.571L53.370,57.772L54.195,59.560L54.883,62.036L54.883,62.724L55.021,62.861L55.021,78.404L54.883,78.542L39.752,78.542L39.615,78.404L38.652,78.404L38.514,78.267L37.827,78.267L36.726,77.854L36.314,77.854L34.938,77.166L34.663,77.166L31.774,75.241L30.399,73.865L28.748,71.527L27.923,69.739L27.235,67.263L27.235,66.575L27.098,66.437Z'

res = ROOT / "android" / "app" / "src" / "main" / "res"
drawable = res / "drawable"
drawable.mkdir(parents=True, exist_ok=True)

# Android launcher tile: warm white field + centered supplied black Blee mark.
# The vector is intentionally inset to survive circular/squircle OEM masks.
xml = f"""<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp"
    android:height="108dp"
    android:viewportWidth="100"
    android:viewportHeight="100">
  <path android:fillColor="#FAFAF8" android:pathData="M0,0 H100 V100 H0 Z"/>
  <group
      android:scaleX="0.68"
      android:scaleY="0.68"
      android:translateX="24.886"
      android:translateY="16">
    <path
        android:fillColor="#090A0B"
        android:fillType="evenOdd"
        android:pathData="{MARK_PATH}"/>
  </group>
</vector>
"""
(drawable / "blee_launcher.xml").write_text(xml)
print("Blee 1.4 launcher mark applied with preserved proportions.")
