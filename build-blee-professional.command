#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

BASE_BUILDER="$ROOT/build-blee-macos.command"
INNER_BUILDER="$ROOT/.blee-professional-inner.command"
FINAL_APK="$ROOT/dist/Blee.apk"

if command -v brew >/dev/null 2>&1; then
  BREW_JDK="$(brew --prefix openjdk@21 2>/dev/null || true)"
  if [ -n "$BREW_JDK" ] && [ -x "$BREW_JDK/bin/java" ]; then
    export JAVA_HOME="$BREW_JDK/libexec/openjdk.jdk/Contents/Home"
    export PATH="$BREW_JDK/bin:$PATH"
  fi
fi

for required in \
  "$BASE_BUILDER" \
  "$ROOT/ARCHITECTURE.md" \
  "$ROOT/UI_ARCHITECTURE.md" \
  "$ROOT/brand-assets/blee-wordmark.svg" \
  "$ROOT/brand-assets/blee-mark.svg" \
  "$ROOT/scripts/apply-blee-professional.py" \
  "$ROOT/scripts/apply-blee-1.4.py" \
  "$ROOT/scripts/apply-blee-1.4-finalize.py" \
  "$ROOT/scripts/apply-blee-launcher-1.4.py" \
  "$ROOT/scripts/apply-blee-mesh-v2.py" \
  "$ROOT/scripts/apply-blee-mesh-v2-android.py" \
  "$ROOT/scripts/apply-blee-2.2.py" \
  "$ROOT/scripts/apply-blee-2.2-android.py" \
  "$ROOT/scripts/apply-blee-2.3.py" \
  "$ROOT/scripts/apply-blee-2.3-ringfix.py" \
  "$ROOT/scripts/apply-blee-2.4.py" \
  "$ROOT/scripts/apply-blee-2.5-ui.py" \
  "$ROOT/scripts/apply-blee-2.5.py" \
  "$ROOT/scripts/apply-blee-2.5-android.py" \
  "$ROOT/scripts/apply-blee-original-brand.py" \
  "$ROOT/scripts/apply-blee-final-hardening.py" \
  "$ROOT/scripts/verify-blee-original-brand.py" \
  "$ROOT/scripts/verify-blee-mesh-v2.py" \
  "$ROOT/mesh-v2/android/BleeBiometricPlugin.java.in" \
  "$ROOT/mesh-v2/web/payments.ts.in" \
  "$ROOT/mesh-v2/web/atomicSigning.ts.in" \
  "$ROOT/ui-v4/parts/part00" \
  "$ROOT/ui-v4/parts/part10" \
  "$ROOT/ui-v5/parts/part00" \
  "$ROOT/ui-v5/parts/part01" \
  "$ROOT/ui-v5/parts/part02" \
  "$ROOT/ui-v5/parts/part03"; do
  [ -e "$required" ] || { echo "ERROR: Missing $required"; exit 1; }
done

rm -f "$FINAL_APK" "$FINAL_APK.sha256"
cp "$BASE_BUILDER" "$INNER_BUILDER"
trap 'rm -f "$INNER_BUILDER"' EXIT

python3 - <<'PY'
from pathlib import Path

path = Path('.blee-professional-inner.command')
text = path.read_text()

replacements = {
    'APP_NAME="Blee-1.1.1-storage-fixed-debug.apk"': 'APP_NAME="Blee.apk"',
    "g=re.sub(r'versionCode\\s+\\d+', 'versionCode 4', g)": "g=re.sub(r'versionCode\\s+\\d+', 'versionCode 15', g)",
    "g=re.sub(r'versionName\\s+\"[^\"]+\"', 'versionName \"1.1.1\"', g)": "g=re.sub(r'versionName\\s+\"[^\"]+\"', 'versionName \"2.5.1\"', g)",
    "print('Blee 1.1.1 launcher identity and version verified.')": "print('Blee Android identity and version verified.')",
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f'Blee builder could not locate expected base-build marker: {old}')
    text = text.replace(old, new, 1)

anchor = '''echo "Applying Blee 1.1 wallet recovery + custom network support..."\npython3 scripts/apply-blee-1.1.py\n'''
addition = anchor + '''\necho "Applying professional identity, QR, discovery and profile source..."\npython3 scripts/apply-blee-professional.py\n\necho "Applying brand and ledger timestamp source..."\npython3 scripts/apply-blee-1.4.py\npython3 scripts/apply-blee-1.4-finalize.py\n\necho "Applying Mesh v2 + crash-atomic sender-funded settlement..."\npython3 scripts/apply-blee-mesh-v2.py\n\necho "Applying functional hardening..."\npython3 scripts/apply-blee-2.2.py\npython3 scripts/apply-blee-2.3.py\npython3 scripts/apply-blee-2.3-ringfix.py\n\necho "Installing current product UI..."\npython3 scripts/apply-blee-2.4.py\npython3 scripts/apply-blee-2.5-ui.py\n\necho "Installing supplied Blee brand assets..."\npython3 scripts/apply-blee-original-brand.py\n\necho "Applying authentication hardening..."\npython3 scripts/apply-blee-2.5.py\n\necho "Applying final source safety invariants..."\npython3 scripts/apply-blee-final-hardening.py --web\n'''
if anchor not in text:
    raise SystemExit('Blee builder could not locate base overlay stage')
text = text.replace(anchor, addition, 1)

compile_anchor = 'echo "Compiling APK..."'
compile_addition = '''echo "Applying original Blee launcher mark..."\npython3 scripts/apply-blee-launcher-1.4.py\n\necho "Verifying Blee brand assets..."\npython3 scripts/verify-blee-original-brand.py\n\necho "Installing Mesh v2 native Android service..."\npython3 scripts/apply-blee-mesh-v2-android.py\n\necho "Hardening Bluetooth discovery..."\npython3 scripts/apply-blee-2.2-android.py\n\necho "Installing biometric unlock, notifications and launch integration..."\npython3 scripts/apply-blee-2.5-android.py\n\necho "Applying final native safety invariants..."\npython3 scripts/apply-blee-final-hardening.py --android\n\necho "Verifying final source + native wiring..."\npython3 scripts/verify-blee-mesh-v2.py\n\necho "Compiling APK..."'''
if compile_anchor not in text:
    raise SystemExit('Blee builder could not locate Android compile stage')
text = text.replace(compile_anchor, compile_addition, 1)

path.write_text(text)
PY

chmod +x "$INNER_BUILDER"

echo "============================================================"
echo "Building Blee"
echo "Output: dist/Blee.apk"
echo "============================================================"
bash "$INNER_BUILDER"

[ -f "$FINAL_APK" ] || { echo "ERROR: Blee.apk was not produced"; exit 1; }
unzip -t "$FINAL_APK" >/dev/null

if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$FINAL_APK" > "$FINAL_APK.sha256"
elif command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$FINAL_APK" > "$FINAL_APK.sha256"
fi

echo
echo "Blee build complete:"
echo "$FINAL_APK"
