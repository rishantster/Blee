#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

BASE_BUILDER="$ROOT/build-blee-macos.command"
INNER_BUILDER="$ROOT/.blee-professional-inner.command"
EXPECTED_APK="Blee-1.3.0-professional-debug.apk"

[ -f "$BASE_BUILDER" ] || { echo "ERROR: Missing build-blee-macos.command"; exit 1; }
[ -f "$ROOT/scripts/apply-blee-professional.py" ] || { echo "ERROR: Missing scripts/apply-blee-professional.py"; exit 1; }
[ -d "$ROOT/professional" ] || { echo "ERROR: Missing professional/ source overlay"; exit 1; }

cp "$BASE_BUILDER" "$INNER_BUILDER"
trap 'rm -f "$INNER_BUILDER"' EXIT

python3 - <<'PY'
from pathlib import Path

path = Path('.blee-professional-inner.command')
text = path.read_text()

replacements = {
    'APP_NAME="Blee-1.1.1-storage-fixed-debug.apk"': 'APP_NAME="Blee-1.3.0-professional-debug.apk"',
    "g=re.sub(r'versionCode\\s+\\d+', 'versionCode 4', g)": "g=re.sub(r'versionCode\\s+\\d+', 'versionCode 6', g)",
    "g=re.sub(r'versionName\\s+\"[^\"]+\"', 'versionName \"1.1.1\"', g)": "g=re.sub(r'versionName\\s+\"[^\"]+\"', 'versionName \"1.3.0\"', g)",
    "print('Blee 1.1.1 launcher identity and version verified.')": "print('Blee 1.3.0 launcher identity and version verified.')",
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f'Professional builder could not locate expected base-build marker: {old}')
    text = text.replace(old, new, 1)

anchor = '''echo "Applying Blee 1.1 wallet recovery + custom network support..."\npython3 scripts/apply-blee-1.1.py\n'''
addition = anchor + '''\necho "Applying Blee 1.3 identity, QR, discovery and profile UX..."\npython3 scripts/apply-blee-professional.py\n'''
if anchor not in text:
    raise SystemExit('Professional builder could not locate Blee 1.1 overlay stage')
text = text.replace(anchor, addition, 1)
path.write_text(text)
PY

chmod +x "$INNER_BUILDER"

echo "============================================================"
echo "Building Blee 1.3 Professional"
echo "============================================================"
bash "$INNER_BUILDER"

APK="$ROOT/dist/$EXPECTED_APK"
[ -f "$APK" ] || { echo "ERROR: Professional APK was not produced: $APK"; exit 1; }
unzip -t "$APK" >/dev/null

echo
echo "Blee 1.3 Professional build complete:"
echo "$APK"
