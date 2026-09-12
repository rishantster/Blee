#!/bin/bash
set -euo pipefail
# CANONICAL_BLEE_BUILDER_V2

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

APP_VERSION="2.6.0"
FINAL_APK="$ROOT/dist/Blee-${APP_VERSION}.apk"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "ERROR: canonical Blee APK builder currently supports macOS hosts only"
  exit 1
fi

command -v python3 >/dev/null || { echo "ERROR: python3 is required"; exit 1; }
command -v node >/dev/null || { echo "ERROR: Node.js is required"; exit 1; }
command -v npm >/dev/null || { echo "ERROR: npm is required"; exit 1; }
command -v unzip >/dev/null || { echo "ERROR: unzip is required"; exit 1; }

ensure_cmd() {
  local cmd="$1"
  local brew_pkg="$2"
  if command -v "$cmd" >/dev/null 2>&1; then return 0; fi
  if ! command -v brew >/dev/null 2>&1; then
    echo "ERROR: missing $cmd and Homebrew is unavailable"
    exit 1
  fi
  echo "Installing $brew_pkg..."
  brew install "$brew_pkg"
}

ensure_cmd rsync rsync
ensure_cmd shasum perl

if ! /usr/libexec/java_home -V >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "Installing OpenJDK 21..."
    brew install --cask temurin@21 || brew install openjdk@21
  else
    echo "ERROR: JDK 17+ is required"
    exit 1
  fi
fi

JAVA_HOME_CANDIDATE=""
for major in 21 17; do
  if /usr/libexec/java_home -v "$major" >/dev/null 2>&1; then
    JAVA_HOME_CANDIDATE="$(/usr/libexec/java_home -v "$major")"
    break
  fi
done
if [ -z "$JAVA_HOME_CANDIDATE" ]; then
  JAVA_HOME_CANDIDATE="$(/usr/libexec/java_home 2>/dev/null || true)"
fi
[ -n "$JAVA_HOME_CANDIDATE" ] || { echo "ERROR: unable to locate a JDK"; exit 1; }
export JAVA_HOME="$JAVA_HOME_CANDIDATE"
export PATH="$JAVA_HOME/bin:$PATH"

echo "Using Java: $(java -version 2>&1 | head -1)"

SDK_ROOT="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Library/Android/sdk}}"
mkdir -p "$SDK_ROOT"
export ANDROID_HOME="$SDK_ROOT"
export ANDROID_SDK_ROOT="$SDK_ROOT"

SDKMANAGER="$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager"
if [ ! -x "$SDKMANAGER" ]; then
  echo "Android command-line tools not found; installing locally..."
  TMP_TOOLS="$(mktemp -d)"
  TOOLS_ZIP="$TMP_TOOLS/cmdline-tools.zip"
  curl -fL --retry 3 -o "$TOOLS_ZIP" "https://dl.google.com/android/repository/commandlinetools-mac-13114758_latest.zip"
  unzip -q "$TOOLS_ZIP" -d "$TMP_TOOLS/unpack"
  mkdir -p "$SDK_ROOT/cmdline-tools/latest"
  cp -R "$TMP_TOOLS/unpack/cmdline-tools/"* "$SDK_ROOT/cmdline-tools/latest/"
  rm -rf "$TMP_TOOLS"
fi

export PATH="$SDK_ROOT/cmdline-tools/latest/bin:$SDK_ROOT/platform-tools:$PATH"
yes | sdkmanager --licenses >/dev/null || true
sdkmanager "platform-tools" "platforms;android-35" "platforms;android-36" "build-tools;35.0.0" "build-tools;36.0.0"

if [ -d bootstrap/parts ]; then
  echo "Materializing Blee application source..."
  cat bootstrap/parts/part* > /tmp/blee-source.b64
  python3 - <<'PY'
import base64, hashlib, pathlib
src=pathlib.Path('/tmp/blee-source.b64').read_bytes(); out=base64.b64decode(src)
want='c28e106c9bbfb1687e061c33ec3bc3fb0ad9623fc8c320876611f390ddfc104d'
got=hashlib.sha256(out).hexdigest()
if got != want: raise SystemExit(f'Blee source checksum mismatch: {got}')
pathlib.Path('/tmp/blee-source.tar.gz').write_bytes(out)
print('Blee source archive verified:', got)
PY
  SOURCE_TMP="$(mktemp -d)"
  tar -xzf /tmp/blee-source.tar.gz -C "$SOURCE_TMP"
  rsync -a \
    --exclude 'README.md' \
    --exclude 'ARCHITECTURE.md' \
    --exclude 'UI_ARCHITECTURE.md' \
    --exclude '.github/' \
    --exclude 'dist/' \
    --exclude 'build-blee.command' \
    --exclude 'build-blee-macos.command' \
    --exclude 'build-blee-professional.command' \
    --exclude 'build-blee-final.command' \
    --exclude 'scripts/apply-blee-*.py' \
    --exclude 'scripts/verify-*.py' \
    "$SOURCE_TMP/" "$ROOT/"
  rm -rf "$SOURCE_TMP"

  grep -q 'CANONICAL_BLEE_BUILDER_V2' "$ROOT/build-blee.command" || {
    echo "ERROR: canonical build entrypoint was replaced during source materialization"
    exit 1
  }
  python3 scripts/verify-canonical-build.py
fi

NATIVE_B64="$ROOT/bootstrap/blee-native-plugins.tar.gz.b64"
if [ -f "$NATIVE_B64" ]; then
  echo "Materializing native SQLite + nearby transport..."
  python3 - <<'PY'
import base64, hashlib, pathlib
src=pathlib.Path('bootstrap/blee-native-plugins.tar.gz.b64').read_bytes(); out=base64.b64decode(src)
want='fd7c6ddcc2d076b668986ee86b088220fba98e95989b33a7cfd391be3f83309e'
got=hashlib.sha256(out).hexdigest()
if got != want: raise SystemExit(f'Blee native plugin checksum mismatch: {got}')
pathlib.Path('/tmp/blee-native-plugins.tar.gz').write_bytes(out)
print('Blee native plugin archive verified:', got)
PY
  tar -xzf /tmp/blee-native-plugins.tar.gz -C "$ROOT"
fi

REQUIRED_FILES=(
  "package.json"
  "src/hooks/useBlee.ts"
  "src/lib/persistence.ts"
  "src/components/BleeApp.tsx"
  "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java"
  "plugins/blee-nearby/android/src/main/java/com/blee/nearby/BleeNearbyPlugin.java"
)
for REQUIRED in "${REQUIRED_FILES[@]}"; do
  [ -f "$ROOT/$REQUIRED" ] || { echo "ERROR: materialized source is missing: $REQUIRED"; exit 1; }
done

python3 - <<'PY'
from pathlib import Path
p=Path('src/lib/persistence.ts'); s=p.read_text()
start=s.index('export function nativePersistenceAvailable()')
end=s.index('function normalizePayments', start)
replacement='''export function nativePersistenceAvailable() {\n  return Capacitor.isNativePlatform();\n}\n\nexport async function initPersistence(): Promise<{ native: true; journalMode: string }> {\n  if (ready) return { native: true, journalMode: 'wal' };\n  if (!Capacitor.isNativePlatform()) throw new Error('Blee payment storage requires the Android app.');\n  try {\n    const result = await BleeStore.init();\n    if (!result.ready) throw new Error('native store returned not-ready');\n    ready = true;\n    return { native: true, journalMode: result.journalMode || 'unknown' };\n  } catch (error) {\n    const detail = error instanceof Error ? error.message : String(error);\n    throw new Error(`Blee SQLite initialization failed: ${detail}`);\n  }\n}\n\n'''
s=s[:start]+replacement+s[end:]
p.write_text(s)
PY

python3 scripts/apply-blee-1.1.py
python3 scripts/apply-blee-professional.py
python3 scripts/apply-blee-1.4.py
python3 scripts/apply-blee-1.4-finalize.py
python3 scripts/apply-blee-mesh-v2.py
python3 scripts/apply-blee-2.2.py
python3 scripts/apply-blee-2.3.py
python3 scripts/apply-blee-2.3-ringfix.py
python3 scripts/apply-blee-2.4.py
python3 scripts/apply-blee-2.5-ui.py
python3 scripts/apply-blee-original-brand.py
python3 scripts/apply-blee-2.5.py
python3 scripts/apply-blee-final-hardening.py --web
python3 scripts/apply-blee-single-ble-owner.py

npm install --no-audit --no-fund
npm run check
npm run build

rm -rf android
npm run android:prepare

python3 - <<'PY'
from pathlib import Path
import re
gradle=Path('android/app/build.gradle')
g=gradle.read_text()
g=re.sub(r'versionCode\s+\d+', 'versionCode 16', g)
g=re.sub(r'versionName\s+"[^"]+"', 'versionName "2.6.0"', g)
gradle.write_text(g)
PY

python3 scripts/apply-blee-launcher-1.4.py
python3 scripts/verify-blee-original-brand.py
python3 scripts/apply-blee-mesh-v2-android.py
python3 scripts/apply-blee-2.2-android.py
python3 scripts/apply-blee-2.5-android.py
python3 scripts/apply-blee-final-hardening.py --android
python3 scripts/apply-blee-final-hardening-2.py
python3 scripts/apply-blee-runtime-reliability.py
python3 scripts/apply-blee-ble-transport-v4.py
python3 scripts/apply-blee-ble-diagnostics.py
python3 scripts/apply-blee-bitchat-reliability.py
python3 scripts/apply-blee-gatt-interop.py

npm run check
npm run build
npx cap sync android

python3 scripts/verify-blee-mesh-v2.py
python3 scripts/verify-canonical-build.py

(
  cd android
  chmod +x gradlew
  ./gradlew --no-daemon assembleDebug --stacktrace
)

APK="$ROOT/android/app/build/outputs/apk/debug/app-debug.apk"
test -f "$APK"
unzip -t "$APK" >/dev/null
mkdir -p "$ROOT/dist"
rm -f "$ROOT/dist"/*.apk "$ROOT/dist"/*.apk.sha256 2>/dev/null || true
cp "$APK" "$FINAL_APK"
shasum -a 256 "$FINAL_APK" > "$FINAL_APK.sha256"

echo
echo "============================================================"
echo "Blee ${APP_VERSION} canonical APK built successfully"
echo "APK: $FINAL_APK"
echo "SHA256: $(cat "$FINAL_APK.sha256")"
echo "============================================================"
