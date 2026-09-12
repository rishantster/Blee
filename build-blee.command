#!/usr/bin/env bash
set -euo pipefail

# CANONICAL_BLEE_BUILDER_V2
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

APP_VERSION="2.6.0"
FINAL_APK="$ROOT/dist/Blee-${APP_VERSION}.apk"
SDK_ROOT="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
TOOLS_ROOT="$ROOT/.blee-tools"
CLI_VERSION="15859902"
mkdir -p "$TOOLS_ROOT" "$ROOT/dist"

rm -f "$ROOT/dist"/*.apk "$ROOT/dist"/*.apk.sha256 2>/dev/null || true

python3 scripts/verify-canonical-build.py

case "$(uname -m)" in
  arm64|aarch64) ADOPTIUM_ARCH="aarch64" ;;
  x86_64) ADOPTIUM_ARCH="x64" ;;
  *) echo "Unsupported architecture: $(uname -m)"; exit 1 ;;
esac

case "$(uname -s)" in
  Darwin) ADOPTIUM_OS="mac" ;;
  Linux) ADOPTIUM_OS="linux" ;;
  *) echo "Unsupported operating system: $(uname -s)"; exit 1 ;;
esac

if [ "$ADOPTIUM_OS" = "mac" ]; then
  case "$(uname -m)" in
    arm64)
      CLI_ARCHIVE="commandlinetools-mac_arm64-${CLI_VERSION}_latest.zip"
      CLI_SHA256="835b62a26162b229b441d1f6d4680383815a270809eb33522c0d480fa5002c4e"
      ;;
    x86_64)
      CLI_ARCHIVE="commandlinetools-mac_x86_64-${CLI_VERSION}_latest.zip"
      CLI_SHA256="c5a6378ab5cf7e0d5701921405115befff13e9ff7417fb588389338f8bd050f3"
      ;;
  esac
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Node.js/npm are required. Install Node 22+ and rerun."
  exit 1
fi
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" -lt 22 ]; then
  echo "Node 22+ is required. Current: $(node --version)"
  exit 1
fi

if command -v brew >/dev/null 2>&1; then
  BREW_JDK="$(brew --prefix openjdk@21 2>/dev/null || true)"
  if [ -n "$BREW_JDK" ] && [ -x "$BREW_JDK/bin/java" ]; then
    export JAVA_HOME="$BREW_JDK/libexec/openjdk.jdk/Contents/Home"
    export PATH="$BREW_JDK/bin:$PATH"
  fi
fi

JAVA_OK=0
if command -v java >/dev/null 2>&1 && java -version >/tmp/blee-java-version.txt 2>&1; then
  JAVA_MAJOR="$(java -version 2>&1 | awk -F'[\".]' '/version/ {print $2; exit}')"
  if [ "${JAVA_MAJOR:-0}" -ge 21 ] 2>/dev/null; then JAVA_OK=1; fi
fi
if [ "$JAVA_OK" -ne 1 ]; then
  JDK_DIR="$TOOLS_ROOT/jdk-21-${ADOPTIUM_OS}-${ADOPTIUM_ARCH}"
  if [ ! -x "$JDK_DIR/bin/java" ] && [ ! -x "$JDK_DIR/Contents/Home/bin/java" ]; then
    echo "Java 21 not found. Installing a private Temurin JDK 21 (no sudo)..."
    TMP_JDK="$(mktemp -d)"
    trap 'rm -rf "${TMP_JDK:-}" "${TMP_SDK:-}"' EXIT
    CACHE_DIR="$TOOLS_ROOT/cache"; mkdir -p "$CACHE_DIR"
    JDK_ARCHIVE="$CACHE_DIR/temurin21-${ADOPTIUM_OS}-${ADOPTIUM_ARCH}.tar.gz"
    if [ ! -s "$JDK_ARCHIVE" ]; then
      curl --fail --location --retry 4 --retry-delay 2 \
        "https://api.adoptium.net/v3/binary/latest/21/ga/${ADOPTIUM_OS}/${ADOPTIUM_ARCH}/jdk/hotspot/normal/eclipse" \
        --output "$JDK_ARCHIVE"
    fi
    tar -xzf "$JDK_ARCHIVE" -C "$TMP_JDK"
    JAVA_BIN="$(find "$TMP_JDK" -type f -path '*/bin/java' -perm -111 | head -n 1 || true)"
    [ -n "$JAVA_BIN" ] || { echo "Could not locate Java in the downloaded JDK archive."; exit 1; }
    JAVA_HOME_FOUND="$(cd "$(dirname "$JAVA_BIN")/.." && pwd)"
    rm -rf "$JDK_DIR"; mkdir -p "$JDK_DIR"; cp -R "$JAVA_HOME_FOUND/." "$JDK_DIR/"
  fi
  if [ -x "$JDK_DIR/bin/java" ]; then export JAVA_HOME="$JDK_DIR"; else export JAVA_HOME="$JDK_DIR/Contents/Home"; fi
  export PATH="$JAVA_HOME/bin:$PATH"
fi

echo "============================================================"
echo "Building Blee"
echo "Canonical artifact: dist/Blee-${APP_VERSION}.apk"
echo "============================================================"
echo "Node: $(node --version)"
echo "npm: $(npm --version)"
echo "Java:"; java -version

mkdir -p "$SDK_ROOT/cmdline-tools"
if ! command -v sdkmanager >/dev/null 2>&1 && [ ! -x "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" ]; then
  if [ "$(uname -s)" != "Darwin" ]; then
    echo "Android sdkmanager is required on $(uname -s). Configure ANDROID_HOME or add sdkmanager to PATH."
    exit 1
  fi
  TMP_SDK="$(mktemp -d)"
  trap 'rm -rf "${TMP_JDK:-}" "${TMP_SDK:-}"' EXIT
  echo "Installing Android command-line tools..."
  CACHE_DIR="$TOOLS_ROOT/cache"; mkdir -p "$CACHE_DIR"
  SDK_ARCHIVE="$CACHE_DIR/$CLI_ARCHIVE"
  if [ ! -s "$SDK_ARCHIVE" ]; then
    curl --fail --location --retry 4 --retry-delay 2 \
      "https://dl.google.com/android/repository/$CLI_ARCHIVE" --output "$SDK_ARCHIVE"
  fi
  echo "$CLI_SHA256  $SDK_ARCHIVE" | shasum -a 256 -c -
  unzip -q "$SDK_ARCHIVE" -d "$TMP_SDK/unpacked"
  rm -rf "$SDK_ROOT/cmdline-tools/latest"; mkdir -p "$SDK_ROOT/cmdline-tools/latest"
  cp -R "$TMP_SDK/unpacked/cmdline-tools/." "$SDK_ROOT/cmdline-tools/latest/"
fi
export ANDROID_HOME="$SDK_ROOT"
export ANDROID_SDK_ROOT="$SDK_ROOT"
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

[ -f "$FINAL_APK" ] || { echo "ERROR: versioned Blee APK was not produced: $FINAL_APK"; exit 1; }
[ "$(find "$ROOT/dist" -maxdepth 1 -type f -name '*.apk' | wc -l | tr -d ' ')" = "1" ] || {
  echo "ERROR: dist must contain exactly one APK"
  find "$ROOT/dist" -maxdepth 1 -type f -name '*.apk' -print
  exit 1
}

if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$FINAL_APK" > "$FINAL_APK.sha256"
elif command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$FINAL_APK" > "$FINAL_APK.sha256"
fi

printf '\nBlee APK built successfully\n%s\n' "$FINAL_APK"
open "$ROOT/dist" 2>/dev/null || true
