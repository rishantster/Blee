#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP_VERSION="2.7.0"
VERSION_CODE="17"
FINAL_APK="$ROOT/dist/Blee-${APP_VERSION}.apk"

select_java_21() {
  local current=""
  current="$(java -version 2>&1 | head -n 1 || true)"
  if printf '%s' "$current" | grep -Eq 'version "21[.]|openjdk 21[.]'; then
    return 0
  fi

  if [ "$(uname -s)" = "Darwin" ] && [ -x /usr/libexec/java_home ]; then
    local mac_java=""
    mac_java="$(/usr/libexec/java_home -v 21 2>/dev/null || true)"
    if [ -n "$mac_java" ] && [ -x "$mac_java/bin/java" ]; then
      export JAVA_HOME="$mac_java"
      export PATH="$JAVA_HOME/bin:$PATH"
      return 0
    fi
  fi

  if command -v brew >/dev/null 2>&1; then
    local brew_java=""
    brew_java="$(brew --prefix openjdk@21 2>/dev/null || true)"
    if [ -n "$brew_java" ] && [ -d "$brew_java/libexec/openjdk.jdk/Contents/Home" ]; then
      export JAVA_HOME="$brew_java/libexec/openjdk.jdk/Contents/Home"
      export PATH="$JAVA_HOME/bin:$PATH"
      return 0
    fi
  fi

  echo "ERROR: Java 21 is required." >&2
  echo "macOS: brew install openjdk@21" >&2
  exit 1
}

select_java_21

JAVA_LINE="$(java -version 2>&1 | head -n 1)"
if ! printf '%s' "$JAVA_LINE" | grep -Eq 'version "21[.]|openjdk 21[.]'; then
  echo "ERROR: build resolved a non-Java-21 runtime: $JAVA_LINE" >&2
  exit 1
fi

if [ -z "${ANDROID_SDK_ROOT:-}" ]; then
  if [ -n "${ANDROID_HOME:-}" ]; then
    export ANDROID_SDK_ROOT="$ANDROID_HOME"
  elif [ -d "$HOME/Library/Android/sdk" ]; then
    export ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
  elif [ -d "$HOME/Android/Sdk" ]; then
    export ANDROID_SDK_ROOT="$HOME/Android/Sdk"
  else
    echo "ERROR: Android SDK not found. Set ANDROID_SDK_ROOT or ANDROID_HOME." >&2
    exit 1
  fi
fi
export ANDROID_HOME="$ANDROID_SDK_ROOT"
export PATH="$ANDROID_SDK_ROOT/platform-tools:$PATH"

command -v node >/dev/null 2>&1 || { echo "ERROR: Node.js is required." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "ERROR: npm is required." >&2; exit 1; }

NODE_MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])')"
if [ "$NODE_MAJOR" -lt 22 ]; then
  echo "ERROR: Node.js 22+ is required; found $(node --version)." >&2
  exit 1
fi

printf '\nBlee %s source-first Android build\n' "$APP_VERSION"
printf 'Node: %s\n' "$(node --version)"
printf 'Java: %s\n' "$JAVA_LINE"
printf 'Android SDK: %s\n\n' "$ANDROID_SDK_ROOT"

rm -rf "$ROOT/dist"
mkdir -p "$ROOT/dist"

npm ci
npm run verify
npm run check
npm run build
npx cap sync android

cd "$ROOT/android"
./gradlew --no-daemon --version
./gradlew --no-daemon assembleDebug --stacktrace

SOURCE_APK="$ROOT/android/app/build/outputs/apk/debug/app-debug.apk"
[ -f "$SOURCE_APK" ] || { echo "ERROR: Gradle completed without $SOURCE_APK" >&2; exit 1; }
cp "$SOURCE_APK" "$FINAL_APK"

unzip -tq "$FINAL_APK" >/dev/null

AAPT=""
if [ -d "$ANDROID_SDK_ROOT/build-tools" ]; then
  AAPT="$(find "$ANDROID_SDK_ROOT/build-tools" -type f -name aapt 2>/dev/null | sort | tail -n 1)"
fi
if [ -n "$AAPT" ] && [ -x "$AAPT" ]; then
  BADGING="$($AAPT dump badging "$FINAL_APK" | head -n 1)"
  printf '%s\n' "$BADGING"
  printf '%s' "$BADGING" | grep -q "versionCode='$VERSION_CODE'" || { echo "ERROR: APK versionCode is not $VERSION_CODE" >&2; exit 1; }
  printf '%s' "$BADGING" | grep -q "versionName='$APP_VERSION'" || { echo "ERROR: APK versionName is not $APP_VERSION" >&2; exit 1; }
fi

if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$FINAL_APK" | tee "$FINAL_APK.sha256"
elif command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$FINAL_APK" | tee "$FINAL_APK.sha256"
fi

printf '\nBUILD SUCCESSFUL\n%s\n' "$FINAL_APK"
