#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP_VERSION="2.7.1"
VERSION_CODE="18"
FINAL_APK="$ROOT/dist/Blee-${APP_VERSION}.apk"

is_java_21_home() {
  local home="$1"
  [ -n "$home" ] || return 1
  [ -x "$home/bin/java" ] || return 1
  local line=""
  line="$("$home/bin/java" -version 2>&1 | head -n 1 || true)"
  printf '%s' "$line" | grep -Eq 'version "21[.]|openjdk 21[.]'
}

use_java_home() {
  local home="$1"
  if is_java_21_home "$home"; then
    export JAVA_HOME="$home"
    export PATH="$JAVA_HOME/bin:$PATH"
    return 0
  fi
  return 1
}

select_java_21() {
  if [ -n "${JAVA_HOME:-}" ] && use_java_home "$JAVA_HOME"; then
    return 0
  fi

  if [ "$(uname -s)" = "Darwin" ]; then
    if command -v brew >/dev/null 2>&1; then
      local brew_prefix=""
      brew_prefix="$(brew --prefix openjdk@21 2>/dev/null || true)"
      if [ -n "$brew_prefix" ]; then
        if use_java_home "$brew_prefix/libexec/openjdk.jdk/Contents/Home"; then
          return 0
        fi
        if use_java_home "$brew_prefix"; then
          return 0
        fi
      fi
    fi

    if use_java_home "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"; then
      return 0
    fi
    if use_java_home "/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"; then
      return 0
    fi

    if [ -x /usr/libexec/java_home ]; then
      local mac_java=""
      mac_java="$(/usr/libexec/java_home -v 21 2>/dev/null || true)"
      if [ -n "$mac_java" ] && use_java_home "$mac_java"; then
        return 0
      fi
    fi
  fi

  if command -v java >/dev/null 2>&1; then
    local java_bin=""
    java_bin="$(command -v java)"
    local resolved_java="$java_bin"
    if command -v realpath >/dev/null 2>&1; then
      resolved_java="$(realpath "$java_bin" 2>/dev/null || printf '%s' "$java_bin")"
    elif command -v readlink >/dev/null 2>&1; then
      resolved_java="$(readlink -f "$java_bin" 2>/dev/null || printf '%s' "$java_bin")"
    fi
    local inferred_home=""
    inferred_home="$(cd "$(dirname "$resolved_java")/.." 2>/dev/null && pwd || true)"
    if [ -n "$inferred_home" ] && use_java_home "$inferred_home"; then
      return 0
    fi
  fi

  for candidate in \
    /usr/lib/jvm/temurin-21-jdk-amd64 \
    /usr/lib/jvm/java-21-openjdk-amd64 \
    /usr/lib/jvm/java-21-openjdk \
    /opt/java/openjdk; do
    if use_java_home "$candidate"; then
      return 0
    fi
  done

  echo "ERROR: Java 21 is required, but no validated Java 21 installation was found." >&2
  echo "macOS: brew install openjdk@21" >&2
  echo "Then rerun: npm run android:build" >&2
  exit 1
}

select_java_21

JAVA_LINE="$("$JAVA_HOME/bin/java" -version 2>&1 | head -n 1)"
if ! printf '%s' "$JAVA_LINE" | grep -Eq 'version "21[.]|openjdk 21[.]'; then
  echo "ERROR: internal Java selector chose a non-Java-21 runtime: $JAVA_LINE" >&2
  echo "JAVA_HOME=$JAVA_HOME" >&2
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

export GRADLE_USER_HOME="$ROOT/.blee-tools/gradle-home-v27"
mkdir -p "$GRADLE_USER_HOME"

printf '\nBlee %s source-first Android build\n' "$APP_VERSION"
printf 'Node: %s\n' "$(node --version)"
printf 'JAVA_HOME: %s\n' "$JAVA_HOME"
printf 'Java: %s\n' "$JAVA_LINE"
printf 'Android SDK: %s\n' "$ANDROID_SDK_ROOT"
printf 'Gradle user home: %s\n\n' "$GRADLE_USER_HOME"

rm -rf "$ROOT/dist"
mkdir -p "$ROOT/dist"

npm ci
npm run verify
npm run check
npm run build
npx cap sync android

cd "$ROOT/android"
./gradlew --stop >/dev/null 2>&1 || true
GRADLE_VERSION_OUTPUT="$(./gradlew --no-daemon -Dorg.gradle.java.home="$JAVA_HOME" --version 2>&1)"
printf '%s\n' "$GRADLE_VERSION_OUTPUT"
if ! printf '%s\n' "$GRADLE_VERSION_OUTPUT" | grep -Eq 'Launcher JVM:[[:space:]]+21|Daemon JVM:[[:space:]]+21|JVM:[[:space:]]+21'; then
  echo "ERROR: Gradle is not using Java 21 despite JAVA_HOME=$JAVA_HOME" >&2
  exit 1
fi

./gradlew --no-daemon -Dorg.gradle.java.home="$JAVA_HOME" assembleDebug --stacktrace

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
