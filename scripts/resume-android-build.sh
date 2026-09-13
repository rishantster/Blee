#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP_VERSION="2.6.0"
APK_SRC="$ROOT/android/app/build/outputs/apk/debug/app-debug.apk"
APK_DST="$ROOT/dist/Blee-${APP_VERSION}.apk"

resolve_java_home() {
  if command -v brew >/dev/null 2>&1; then
    local prefix
    prefix="$(brew --prefix openjdk@21 2>/dev/null || true)"
    if [ -n "$prefix" ]; then
      if [ -x "$prefix/libexec/openjdk.jdk/Contents/Home/bin/java" ]; then
        printf '%s\n' "$prefix/libexec/openjdk.jdk/Contents/Home"
        return 0
      fi
      if [ -x "$prefix/bin/java" ]; then
        printf '%s\n' "$prefix"
        return 0
      fi
    fi
  fi

  if [ "$(uname -s)" = "Darwin" ] && [ -x /usr/libexec/java_home ]; then
    local mac_home
    mac_home="$(/usr/libexec/java_home -v 21 2>/dev/null || true)"
    if [ -n "$mac_home" ] && [ -x "$mac_home/bin/java" ]; then
      printf '%s\n' "$mac_home"
      return 0
    fi
  fi

  local private_java
  private_java="$(find "$ROOT/.blee-tools" -type f -path '*/bin/java' -perm -111 2>/dev/null | grep 'jdk-21' | head -n 1 || true)"
  if [ -n "$private_java" ]; then
    (cd "$(dirname "$private_java")/.." && pwd)
    return 0
  fi

  if [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/java" ]; then
    printf '%s\n' "$JAVA_HOME"
    return 0
  fi

  return 1
}

JAVA21_HOME="$(resolve_java_home || true)"
if [ -z "$JAVA21_HOME" ]; then
  echo "ERROR: Java 21 not found. Run 'brew install openjdk@21' or run the canonical build once so Blee can provision its private JDK." >&2
  exit 1
fi

export JAVA_HOME="$JAVA21_HOME"
export PATH="$JAVA_HOME/bin:$PATH"

JAVA_MAJOR="$(java -version 2>&1 | awk -F'[\".]' '/version/ {print $2; exit}')"
if [ "${JAVA_MAJOR:-0}" -lt 21 ] 2>/dev/null; then
  echo "ERROR: Android resume build resolved Java $(java -version 2>&1 | head -n 1), but Java 21+ is required." >&2
  exit 1
fi

echo "============================================================"
echo "Blee Android resume build"
echo "JAVA_HOME: $JAVA_HOME"
echo "Java: $(java -version 2>&1 | head -n 1)"
echo "============================================================"

[ -d "$ROOT/android" ] || { echo "ERROR: android/ is missing. Run bash build-blee.command first." >&2; exit 1; }
[ -x "$ROOT/android/gradlew" ] || chmod +x "$ROOT/android/gradlew"

SERVICE_FILE="$(find "$ROOT/android/app/src/main/java" -type f -name BleeMeshService.java -print -quit)"
[ -n "$SERVICE_FILE" ] || { echo "ERROR: generated BleeMeshService.java is missing." >&2; exit 1; }

# A resume build may be running against Android sources materialized before the
# adaptive-v3 commit landed. Bring that generated tree forward in-place so the
# user does not have to rerun the entire source-materialization pipeline.
if ! grep -q 'BLEE_ADAPTIVE_NEARBY_V3' "$SERVICE_FILE"; then
  echo "Applying Adaptive Transport V3 to the existing generated Android tree..."
  python3 scripts/apply-blee-adaptive-nearby-v3.py
fi
python3 scripts/apply-blee-adaptive-nearby-v3-compilefix.py

# The adaptive patch also adds diagnostics to the web runtime. Rebuild/sync the
# already-materialized web app before Gradle so the APK and native transport are
# guaranteed to describe the same runtime.
npm run check
npm run build
npx cap sync android

python3 scripts/verify-blee-mesh-v2.py
python3 scripts/verify-canonical-build.py

(
  cd android
  ./gradlew --stop >/dev/null 2>&1 || true
  ./gradlew --no-daemon assembleDebug --stacktrace
)

[ -f "$APK_SRC" ] || { echo "ERROR: Gradle completed but APK is missing: $APK_SRC" >&2; exit 1; }
unzip -t "$APK_SRC" >/dev/null
mkdir -p "$ROOT/dist"
rm -f "$ROOT/dist"/*.apk "$ROOT/dist"/*.apk.sha256 2>/dev/null || true
cp "$APK_SRC" "$APK_DST"

if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$APK_DST" | tee "$APK_DST.sha256"
elif command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$APK_DST" | tee "$APK_DST.sha256"
fi

echo
echo "Blee APK ready:"
echo "$APK_DST"
ls -lh "$APK_DST"
