#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

APP_NAME="Blee-1.0-sqlite-offline-debug.apk"
SDK_ROOT="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
CLI_VERSION="15859902"

case "$(uname -m)" in
  arm64)
    CLI_ARCHIVE="commandlinetools-mac_arm64-${CLI_VERSION}_latest.zip"
    CLI_SHA256="835b62a26162b229b441d1f6d4680383815a270809eb33522c0d480fa5002c4e"
    ;;
  x86_64)
    CLI_ARCHIVE="commandlinetools-mac_x86_64-${CLI_VERSION}_latest.zip"
    CLI_SHA256="c5a6378ab5cf7e0d5701921405115befff13e9ff7417fb588389338f8bd050f3"
    ;;
  *)
    echo "Unsupported Mac architecture: $(uname -m)"
    exit 1
    ;;
esac

require_or_brew() {
  local cmd="$1"
  local formula="$2"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
      echo "Installing $formula..."
      brew install "$formula"
    else
      echo "Missing $cmd and Homebrew is not installed. Install Homebrew first: https://brew.sh"
      exit 1
    fi
  fi
}

require_or_brew node node@22
require_or_brew npm node@22
require_or_brew java openjdk@21
require_or_brew python3 python@3.13

# Homebrew's versioned Node/OpenJDK can be keg-only.
if command -v brew >/dev/null 2>&1; then
  if [ -d "$(brew --prefix node@22 2>/dev/null)/bin" ]; then
    export PATH="$(brew --prefix node@22)/bin:$PATH"
  fi
  if [ -d "$(brew --prefix openjdk@21 2>/dev/null)" ]; then
    export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"
    export PATH="$JAVA_HOME/bin:$PATH"
  fi
fi

echo "Node: $(node --version)"
echo "npm: $(npm --version)"
java -version

mkdir -p "$SDK_ROOT/cmdline-tools"

if [ ! -x "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" ]; then
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "${TMP_DIR:-}"' EXIT
  echo "Installing Android command-line tools..."
  curl --fail --location --retry 3 \
    "https://dl.google.com/android/repository/$CLI_ARCHIVE" \
    --output "$TMP_DIR/$CLI_ARCHIVE"

  echo "$CLI_SHA256  $TMP_DIR/$CLI_ARCHIVE" | shasum -a 256 -c -
  unzip -q "$TMP_DIR/$CLI_ARCHIVE" -d "$TMP_DIR/unpacked"
  rm -rf "$SDK_ROOT/cmdline-tools/latest"
  mkdir -p "$SDK_ROOT/cmdline-tools/latest"
  cp -R "$TMP_DIR/unpacked/cmdline-tools/." "$SDK_ROOT/cmdline-tools/latest/"
fi

export ANDROID_HOME="$SDK_ROOT"
export ANDROID_SDK_ROOT="$SDK_ROOT"
export PATH="$SDK_ROOT/cmdline-tools/latest/bin:$SDK_ROOT/platform-tools:$PATH"

# Install both current SDK levels so Capacitor/AGP can choose what it needs.
yes | sdkmanager --licenses >/dev/null || true
sdkmanager \
  "platform-tools" \
  "platforms;android-35" \
  "platforms;android-36" \
  "build-tools;35.0.0" \
  "build-tools;36.0.0"

if [ -d bootstrap/parts ]; then
  echo "Reconstructing Blee source..."
  cat bootstrap/parts/part* > /tmp/blee-source.b64
  python3 - <<'PY'
import base64, hashlib, pathlib
src = pathlib.Path('/tmp/blee-source.b64').read_bytes()
out = base64.b64decode(src)
want = 'c28e106c9bbfb1687e061c33ec3bc3fb0ad9623fc8c320876611f390ddfc104d'
got = hashlib.sha256(out).hexdigest()
if got != want:
    raise SystemExit(f'Blee source checksum mismatch: {got}')
pathlib.Path('/tmp/blee-source.tar.gz').write_bytes(out)
print('Blee source archive verified:', got)
PY
  tar -xzf /tmp/blee-source.tar.gz -C .
fi

test -f package.json
test -f src/hooks/useBlee.ts
test -f plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java

echo "Installing app dependencies..."
npm install --no-audit --no-fund

echo "Typechecking..."
npm run check

echo "Building Blee UI..."
npm run build

echo "Generating Android project..."
npm run android:prepare

echo "Compiling APK..."
(
  cd android
  chmod +x gradlew
  ./gradlew assembleDebug --stacktrace
)

APK="android/app/build/outputs/apk/debug/app-debug.apk"
test -f "$APK"
unzip -t "$APK" >/dev/null
mkdir -p dist
cp "$APK" "dist/$APP_NAME"
shasum -a 256 "dist/$APP_NAME" | tee "dist/$APP_NAME.sha256"

printf '\n✅ Blee APK built successfully\n%s\n\n' "$ROOT/dist/$APP_NAME"
open "$ROOT/dist" 2>/dev/null || true
