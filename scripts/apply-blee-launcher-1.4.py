#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARK_PATH = 'M10.615,0.825L6.704,2.476L3.352,4.952L1.304,7.565L0.000,11.142L0.000,66.850L1.117,72.352L4.283,79.230L9.125,85.420L16.387,91.334L23.277,95.048L30.912,97.799L41.527,99.725L55.121,99.862L64.246,98.762L72.812,96.424L81.192,92.572L87.151,88.446L92.737,82.806L97.207,75.791L99.628,67.813L99.814,59.285L98.510,53.508L96.462,49.106L93.669,45.117L89.199,40.578L81.750,35.626L74.860,32.737L69.274,31.224L61.453,30.124L36.872,29.986L36.499,12.380L35.754,9.904L33.520,6.465L30.168,3.576L24.581,0.963L19.739,0.000L14.898,0.000Z M36.685,50.757L36.872,50.619L56.238,50.619L56.425,50.757L58.473,50.757L58.659,50.894L59.590,50.894L63.128,51.719L65.363,52.545L67.970,53.920L70.205,55.571L72.253,57.772L73.371,59.560L74.302,62.036L74.302,62.724L74.488,62.861L74.488,78.404L74.302,78.542L53.818,78.542L53.631,78.404L52.328,78.404L52.142,78.267L51.210,78.267L49.721,77.854L49.162,77.854L47.300,77.166L46.927,77.166L43.017,75.241L41.155,73.865L38.920,71.527L37.803,69.739L36.872,67.263L36.872,66.575L36.685,66.437Z'

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
      android:scaleX="0.68"
      android:scaleY="0.68"
      android:translateX="16"
      android:translateY="16">
    <path
        android:fillColor="#090A0B"
        android:fillType="evenOdd"
        android:pathData="{MARK_PATH}"/>
  </group>
</vector>
"""
(drawable / "blee_launcher.xml").write_text(xml)
print("Blee 1.4 launcher mark applied.")
