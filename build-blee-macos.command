#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

APP_NAME="Blee-1.0-sqlite-offline-debug.apk"
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
  *)
    echo "Unsupported Mac architecture: $(uname -m)"
    exit 1
    ;;
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

# macOS ships a /usr/bin/java launcher even when no JDK exists, so `command -v java`
# is not sufficient. Verify a working Java 21+ runtime and, if absent, install a
# private Temurin JDK into this repo. No Homebrew, sudo or Android Studio required.
JAVA_OK=0
if java -version >/tmp/blee-java-version.txt 2>&1; then
  JAVA_MAJOR="$(java -version 2>&1 | awk -F'[\".]' '/version/ {print $2; exit}')"
  if [ "${JAVA_MAJOR:-0}" -ge 21 ] 2>/dev/null; then
    JAVA_OK=1
  fi
fi

if [ "$JAVA_OK" -ne 1 ]; then
  JDK_DIR="$TOOLS_ROOT/jdk-21"
  if [ ! -x "$JDK_DIR/bin/java" ] && [ ! -x "$JDK_DIR/Contents/Home/bin/java" ]; then
    echo "Java 21 not found. Installing a private Temurin JDK 21 (no sudo)..."
    TMP_JDK="$(mktemp -d)"
    trap 'rm -rf "${TMP_JDK:-}" "${TMP_SDK:-}"' EXIT
    CACHE_DIR="$TOOLS_ROOT/cache"
    mkdir -p "$CACHE_DIR"
    JDK_ARCHIVE="$CACHE_DIR/temurin21-${ADOPTIUM_ARCH}.tar.gz"
    if [ ! -s "$JDK_ARCHIVE" ]; then
      curl --fail --location --retry 4 --retry-delay 2 \
        "https://api.adoptium.net/v3/binary/latest/21/ga/mac/${ADOPTIUM_ARCH}/jdk/hotspot/normal/eclipse" \
        --output "$JDK_ARCHIVE"
    fi
    tar -xzf "$JDK_ARCHIVE" -C "$TMP_JDK"
    JAVA_BIN="$(find "$TMP_JDK" -type f -path '*/bin/java' -perm -111 | head -n 1 || true)"
    if [ -z "$JAVA_BIN" ]; then
      echo "Could not locate Java in the downloaded JDK archive."
      exit 1
    fi
    JAVA_HOME_FOUND="$(cd "$(dirname "$JAVA_BIN")/.." && pwd)"
    rm -rf "$JDK_DIR"
    mkdir -p "$JDK_DIR"
    cp -R "$JAVA_HOME_FOUND/." "$JDK_DIR/"
  fi
  if [ -x "$JDK_DIR/bin/java" ]; then
    export JAVA_HOME="$JDK_DIR"
  else
    export JAVA_HOME="$JDK_DIR/Contents/Home"
  fi
  export PATH="$JAVA_HOME/bin:$PATH"
fi

echo "Node: $(node --version)"
echo "npm: $(npm --version)"
echo "Java:"
java -version

mkdir -p "$SDK_ROOT/cmdline-tools"

if [ ! -x "$SDK_ROOT/cmdline-tools/latest/bin/sdkmanager" ]; then
  TMP_SDK="$(mktemp -d)"
  trap 'rm -rf "${TMP_JDK:-}" "${TMP_SDK:-}"' EXIT
  echo "Installing Android command-line tools (no Android Studio required)..."
  CACHE_DIR="$TOOLS_ROOT/cache"
  mkdir -p "$CACHE_DIR"
  SDK_ARCHIVE="$CACHE_DIR/$CLI_ARCHIVE"
  if [ ! -s "$SDK_ARCHIVE" ]; then
    curl --fail --location --retry 4 --retry-delay 2 \
      "https://dl.google.com/android/repository/$CLI_ARCHIVE" \
      --output "$SDK_ARCHIVE"
  fi

  echo "$CLI_SHA256  $SDK_ARCHIVE" | shasum -a 256 -c -
  unzip -q "$SDK_ARCHIVE" -d "$TMP_SDK/unpacked"
  rm -rf "$SDK_ROOT/cmdline-tools/latest"
  mkdir -p "$SDK_ROOT/cmdline-tools/latest"
  cp -R "$TMP_SDK/unpacked/cmdline-tools/." "$SDK_ROOT/cmdline-tools/latest/"
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
  if command -v python3 >/dev/null 2>&1; then
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
  else
    openssl base64 -d -A -in /tmp/blee-source.b64 -out /tmp/blee-source.tar.gz
    GOT="$(shasum -a 256 /tmp/blee-source.tar.gz | awk '{print $1}')"
    WANT="c28e106c9bbfb1687e061c33ec3bc3fb0ad9623fc8c320876611f390ddfc104d"
    [ "$GOT" = "$WANT" ] || { echo "Blee source checksum mismatch: $GOT"; exit 1; }
  fi
  tar -xzf /tmp/blee-source.tar.gz -C .
fi

# Some tar writers add a single wrapper directory. Normalize that automatically.
if [ ! -f "$ROOT/package.json" ]; then
  CANDIDATE_PACKAGE="$(find "$ROOT" -maxdepth 5 -type f -name package.json -not -path '*/node_modules/*' | head -n 1 || true)"
  if [ -n "$CANDIDATE_PACKAGE" ]; then
    SOURCE_ROOT="$(dirname "$CANDIDATE_PACKAGE")"
    if [ "$SOURCE_ROOT" != "$ROOT" ]; then
      echo "Detected wrapped source directory: $SOURCE_ROOT"
      echo "Normalizing source into repository root..."
      rsync -a --exclude '.git' --exclude '.blee-tools' "$SOURCE_ROOT/" "$ROOT/"
    fi
  fi
fi

REQUIRED_FILES=(
  "package.json"
  "src/hooks/useBlee.ts"
  "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java"
)
MISSING=0
for REQUIRED in "${REQUIRED_FILES[@]}"; do
  if [ ! -f "$ROOT/$REQUIRED" ]; then
    echo "ERROR: reconstructed source is missing: $REQUIRED"
    MISSING=1
  fi
done
if [ "$MISSING" -ne 0 ]; then
  echo
  echo "Top of reconstructed source tree:"
  find "$ROOT" -maxdepth 4 -type f \
    -not -path '*/.git/*' \
    -not -path '*/.blee-tools/*' \
    | sed "s#^$ROOT/##" | sort | head -n 120
  echo
  echo "Archive contents:"
  tar -tzf /tmp/blee-source.tar.gz | head -n 120
  exit 1
fi

echo "Blee source layout verified."

echo "Installing app dependencies..."
npm install --no-audit --no-fund

echo "Typechecking..."
npm run check

echo "Building Blee UI..."
npm run build

echo "Generating Android project..."
rm -rf android
npm run android:prepare

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
