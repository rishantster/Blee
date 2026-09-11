#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

BASE_BUILDER="$ROOT/build-blee-macos.command"
INNER_BUILDER="$ROOT/.blee-professional-inner.command"
EXPECTED_APK="Blee-2.4.0-mesh-v2-debug.apk"

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
  "$ROOT/scripts/apply-blee-original-brand.py" \
  "$ROOT/scripts/verify-blee-original-brand.py" \
  "$ROOT/scripts/verify-blee-mesh-v2.py" \
  "$ROOT/mesh-v2/web/payments.ts.in" \
  "$ROOT/mesh-v2/web/atomicSigning.ts.in" \
  "$ROOT/ui-v4/parts/part00" \
  "$ROOT/ui-v4/parts/part10"; do
  [ -e "$required" ] || { echo "ERROR: Missing $required"; exit 1; }
done

cp "$BASE_BUILDER" "$INNER_BUILDER"
trap 'rm -f "$INNER_BUILDER"' EXIT

python3 - <<'PY'
from pathlib import Path

path = Path('.blee-professional-inner.command')
text = path.read_text()

replacements = {
    'APP_NAME="Blee-1.1.1-storage-fixed-debug.apk"': 'APP_NAME="Blee-2.4.0-mesh-v2-debug.apk"',
    "g=re.sub(r'versionCode\\s+\\d+', 'versionCode 4', g)": "g=re.sub(r'versionCode\\s+\\d+', 'versionCode 13', g)",
    "g=re.sub(r'versionName\\s+\"[^\"]+\"', 'versionName \"1.1.1\"', g)": "g=re.sub(r'versionName\\s+\"[^\"]+\"', 'versionName \"2.4.0\"', g)",
    "print('Blee 1.1.1 launcher identity and version verified.')": "print('Blee 2.4.0 launcher identity and version verified.')",
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f'Blee 2.4 builder could not locate expected base-build marker: {old}')
    text = text.replace(old, new, 1)

anchor = '''echo "Applying Blee 1.1 wallet recovery + custom network support..."\npython3 scripts/apply-blee-1.1.py\n'''
addition = anchor + '''\necho "Applying Blee 1.3 identity, QR, discovery and profile UX..."\npython3 scripts/apply-blee-professional.py\n\necho "Applying Blee 1.4 brand and ledger timestamp patch..."\npython3 scripts/apply-blee-1.4.py\npython3 scripts/apply-blee-1.4-finalize.py\n\necho "Applying Blee Mesh v2 + crash-atomic sender-funded settlement..."\npython3 scripts/apply-blee-mesh-v2.py\n\necho "Applying Blee 2.2 functional hardening..."\npython3 scripts/apply-blee-2.2.py\n\necho "Applying Blee 2.3 legacy compatibility cleanup..."\npython3 scripts/apply-blee-2.3.py\npython3 scripts/apply-blee-2.3-ringfix.py\n\necho "Replacing legacy presentation with Blee 2.4 ground-up product UI..."\npython3 scripts/apply-blee-2.4.py\n\necho "Installing original supplied Blee wordmark + mark..."\npython3 scripts/apply-blee-original-brand.py\n'''
if anchor not in text:
    raise SystemExit('Blee 2.4 builder could not locate Blee 1.1 overlay stage')
text = text.replace(anchor, addition, 1)

compile_anchor = 'echo "Compiling APK..."'
compile_addition = '''echo "Applying original Blee launcher mark..."\npython3 scripts/apply-blee-launcher-1.4.py\n\necho "Verifying original Blee brand assets..."\npython3 scripts/verify-blee-original-brand.py\n\necho "Installing Blee Mesh v2 native Android service..."\npython3 scripts/apply-blee-mesh-v2-android.py\n\necho "Hardening Bluetooth discovery..."\npython3 scripts/apply-blee-2.2-android.py\n\necho "Verifying final Blee 2.4 source + native wiring..."\npython3 scripts/verify-blee-mesh-v2.py\n\necho "Compiling APK..."'''
if compile_anchor not in text:
    raise SystemExit('Blee 2.4 builder could not locate Android compile stage')
text = text.replace(compile_anchor, compile_addition, 1)

path.write_text(text)
PY

chmod +x "$INNER_BUILDER"

echo "============================================================"
echo "Building Blee 2.4 — ground-up production UI / Mesh v2"
echo "============================================================"
echo "Architecture: ARCHITECTURE.md"
echo "UI contract: UI_ARCHITECTURE.md"
echo "Brand: original supplied Blee wordmark + mark"
bash "$INNER_BUILDER"

APK="$ROOT/dist/$EXPECTED_APK"
[ -f "$APK" ] || { echo "ERROR: Blee 2.4 APK was not produced: $APK"; exit 1; }
unzip -t "$APK" >/dev/null

if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$APK" | tee "$APK.sha256"
fi

echo
echo "Blee 2.4 Mesh v2 build complete:"
echo "$APK"
