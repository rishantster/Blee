#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

APP_NAME="Blee-1.0.1-sqlite-fixed-debug.apk"
SDK_ROOT="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
TOOLS_ROOT="$ROOT/.blee-tools"
CLI_VERSION="15859902"
mkdir -p "$TOOLS_ROOT"

case "$(uname -m)" in
  arm64)
    CLI_ARCHIVE="commandlinetools-mac_arm64-${CLI_VERSION}_latest.zip"
    CLI_SHA256="835b62a26162b229b441d1f6d4680383815a270809eb33522c0d480fa5002c4e"
    ADOPTIUM_ARCH="aarch64"
    ;;
  x86_64)
    CLI_ARCHIVE="commandlinetools-mac_x86_64-${CLI_VERSION}_latest.zip"
    CLI_SHA256="c5a6378ab5cf7e0d5701921405115befff13e9ff7417fb588389338f8bd050f3"
    ADOPTIUM_ARCH="x64"
    ;;
  *) echo "Unsupported Mac architecture: $(uname -m)"; exit 1 ;;
esac

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Node.js/npm are required. Install Node 22+ and rerun."
  exit 1
fi
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" -lt 22 ]; then
  echo "Node 22+ is required. Current: $(node --version)"
  exit 1
fi

JAVA_OK=0
if java -version >/tmp/blee-java-version.txt 2>&1; then
  JAVA_MAJOR="$(java -version 2>&1 | awk -F'[\".]' '/version/ {print $2; exit}')"
  if [ "${JAVA_MAJOR:-0}" -ge 21 ] 2>/dev/null; then JAVA_OK=1; fi
fi
if [ "$JAVA_OK" -ne 1 ]; then
  JDK_DIR="$TOOLS_ROOT/jdk-21"
  if [ ! -x "$JDK_DIR/bin/java" ] && [ ! -x "$JDK_DIR/Contents/Home/bin/java" ]; then
    echo "Java 21 not found. Installing a private Temurin JDK 21 (no sudo)..."
    TMP_JDK="$(mktemp -d)"
    trap 'rm -rf "${TMP_JDK:-}" "${TMP_SDK:-}"' EXIT
    CACHE_DIR="$TOOLS_ROOT/cache"; mkdir -p "$CACHE_DIR"
    JDK_ARCHIVE="$CACHE_DIR/temurin21-${ADOPTIUM_ARCH}.tar.gz"
    if [ ! -s "$JDK_ARCHIVE" ]; then
      curl --fail --location --retry 4 --retry-delay 2 \
        "https://api.adoptium.net/v3/binary/latest/21/ga/mac/${ADOPTIUM_ARCH}/jdk/hotspot/normal/eclipse" \
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

echo "Node: $(node --version)"
echo "npm: $(npm --version)"
echo "Java:"; java -version

mkdir -p "$SDK_ROOT/cmdline-tools"
if [ ! -x "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" ]; then
  TMP_SDK="$(mktemp -d)"
  trap 'rm -rf "${TMP_JDK:-}" "${TMP_SDK:-}"' EXIT
  echo "Installing Android command-line tools (no Android Studio required)..."
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
  echo "Reconstructing Blee source..."
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
  tar -xzf /tmp/blee-source.tar.gz -C "$ROOT"
fi

NATIVE_B64="$ROOT/bootstrap/blee-native-plugins.tar.gz.b64"
if [ -f "$NATIVE_B64" ]; then
  echo "Restoring Blee native SQLite + nearby transport..."
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
  [ -f "$ROOT/$REQUIRED" ] || { echo "ERROR: reconstructed source is missing: $REQUIRED"; exit 1; }
done

echo "Applying Blee 1.0.1 SQLite startup + identity fixes..."
python3 - <<'PY'
from pathlib import Path
import json

p=Path('src/lib/persistence.ts'); s=p.read_text()
start=s.index('export function nativePersistenceAvailable()')
end=s.index('function normalizePayments', start)
replacement='''export function nativePersistenceAvailable() {\n  return Capacitor.isNativePlatform();\n}\n\nexport async function initPersistence(): Promise<{ native: true; journalMode: string }> {\n  if (ready) return { native: true, journalMode: 'wal' };\n  if (!Capacitor.isNativePlatform()) {\n    throw new Error('Blee payment storage requires the Android app.');\n  }\n  try {\n    const result = await BleeStore.init();\n    if (!result.ready) throw new Error('native store returned not-ready');\n    ready = true;\n    return { native: true, journalMode: result.journalMode || 'wal' };\n  } catch (error) {\n    const detail = error instanceof Error ? error.message : String(error);\n    throw new Error(`Blee SQLite initialization failed: ${detail}`);\n  }\n}\n\n'''
s=s[:start]+replacement+s[end:]
p.write_text(s)

p=Path('plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java'); s=p.read_text()
old='''    @Override\n    public void load() {\n        helper = new BleeDb();\n        helper.setWriteAheadLoggingEnabled(true);\n        helper.getWritableDatabase();\n    }\n\n    private SQLiteDatabase db() {\n        if (helper == null) { helper = new BleeDb(); helper.setWriteAheadLoggingEnabled(true); }\n        return helper.getWritableDatabase();\n    }'''
new='''    @Override\n    public void load() {\n        helper = new BleeDb();\n        helper.setWriteAheadLoggingEnabled(true);\n    }\n\n    private synchronized SQLiteDatabase db() {\n        if (helper == null) {\n            helper = new BleeDb();\n            helper.setWriteAheadLoggingEnabled(true);\n        }\n        return helper.getWritableDatabase();\n    }'''
if old not in s: raise SystemExit('Could not patch BleeStore startup block')
s=s.replace(old,new)
s=s.replace('            db.rawQuery("PRAGMA journal_mode=WAL", null).close();\n','')
p.write_text(s)

p=Path('src/components/BleeApp.tsx'); s=p.read_text()
start=s.index('function LogoMark('); end=s.index('\nfunction Brand', start)
logo='''function LogoMark({ size = 36 }: { size?: number }) {\n  return (\n    <span className="logo-mark" style={{ width: size, height: size }} aria-hidden="true">\n      <svg viewBox="0 0 36 36" fill="none">\n        <rect x="1" y="1" width="34" height="34" rx="11" fill="currentColor"/>\n        <path d="M11.2 8.7v18.6M11.2 9h7.3c3.7 0 5.9 1.8 5.9 4.6 0 2.9-2.2 4.7-5.9 4.7h-7.3M11.2 18.3h8.2c4 0 6.4 1.8 6.4 4.6 0 2.9-2.4 4.7-6.4 4.7h-8.2" stroke="white" strokeWidth="2.65" strokeLinecap="round" strokeLinejoin="round"/>\n      </svg>\n    </span>\n  );\n}\n'''
s=s[:start]+logo+s[end:]
s=s.replace('<span className="avatar tiny">A</span>','<span className="avatar tiny">B</span>')
s=s.replace('Blee 1.0 · ARC Testnet','Blee 1.0.1 · ARC Testnet')
p.write_text(s)

pkg=Path('package.json'); data=json.loads(pkg.read_text()); data['version']='1.0.1'; pkg.write_text(json.dumps(data, indent=2)+'\n')
print('Blee 1.0.1 source hotfixes applied.')
PY

echo "Installing app dependencies..."
npm install --no-audit --no-fund

echo "Typechecking..."
npm run check

echo "Building Blee UI..."
npm run build

echo "Generating Android project..."
rm -rf android
npm run android:prepare

echo "Applying Blee launcher icon + Android version..."
python3 - <<'PY'
from pathlib import Path
import re

manifest=Path('android/app/src/main/AndroidManifest.xml')
xml=manifest.read_text()
xml=re.sub(r'android:icon="[^"]+"', 'android:icon="@drawable/blee_launcher"', xml)
xml=re.sub(r'android:roundIcon="[^"]+"', 'android:roundIcon="@drawable/blee_launcher"', xml)
manifest.write_text(xml)

res=Path('android/app/src/main/res')
drawable=res/'drawable'; drawable.mkdir(parents=True, exist_ok=True)
(drawable/'blee_launcher.xml').write_text('''<?xml version="1.0" encoding="utf-8"?>\n<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="108dp" android:height="108dp" android:viewportWidth="48" android:viewportHeight="48">\n  <path android:fillColor="#0B0C0D" android:pathData="M8,4 H40 C42.2,4 44,5.8 44,8 V40 C44,42.2 42.2,44 40,44 H8 C5.8,44 4,42.2 4,40 V8 C4,5.8 5.8,4 8,4 Z"/>\n  <path android:fillColor="#00000000" android:strokeColor="#FFFFFF" android:strokeWidth="3.2" android:strokeLineCap="round" android:strokeLineJoin="round" android:pathData="M15,12 V36 M15,12 H25 C29.5,12 32,14.3 32,17.8 C32,21.3 29.5,23.5 25,23.5 H15 M15,23.5 H26 C30.8,23.5 33.5,25.8 33.5,29.7 C33.5,33.5 30.8,36 26,36 H15"/>\n</vector>\n''')

gradle=Path('android/app/build.gradle')
g=gradle.read_text()
g=re.sub(r'versionCode\s+\d+', 'versionCode 2', g)
g=re.sub(r'versionName\s+"[^"]+"', 'versionName "1.0.1"', g)
gradle.write_text(g)

for rel in ('values/styles.xml','values-v31/styles.xml'):
    f=res/rel
    if f.exists():
        v=f.read_text()
        v=re.sub(r'@mipmap/ic_launcher(?:_round)?', '@drawable/blee_launcher', v)
        f.write_text(v)
print('Blee launcher identity and version verified.')
PY

echo "Compiling APK..."
(
  cd android
  chmod +x gradlew
  ./gradlew --no-daemon assembleDebug --stacktrace
)

APK="android/app/build/outputs/apk/debug/app-debug.apk"
test -f "$APK"
unzip -t "$APK" >/dev/null
mkdir -p dist
cp "$APK" "dist/$APP_NAME"
shasum -a 256 "dist/$APP_NAME" | tee "dist/$APP_NAME.sha256"
printf '\n✅ Blee APK built successfully\n%s\n\n' "$ROOT/dist/$APP_NAME"
open "$ROOT/dist" 2>/dev/null || true
