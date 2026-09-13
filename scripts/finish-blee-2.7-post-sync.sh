#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() { echo "Blee 2.7 finish FAIL: $*" >&2; exit 1; }

[ -f package.json ] || fail "package.json missing"
[ -f android/app/build.gradle ] || fail "Android tree missing"
[ -f android/app/src/main/java/com/blee/payments/BleeMeshService.java ] || fail "Blee mesh service missing"

grep -q '"version": "2.7.0"' package.json || fail "package.json is not Blee 2.7.0"
grep -q 'versionCode 17' android/app/build.gradle || fail "Android versionCode is not 17"
grep -q 'versionName "2.7.0"' android/app/build.gradle || fail "Android versionName is not 2.7.0"

select_java_21() {
  local candidate=""

  if command -v brew >/dev/null 2>&1; then
    local brew_jdk
    brew_jdk="$(brew --prefix openjdk@21 2>/dev/null || true)"
    if [ -n "$brew_jdk" ] && [ -x "$brew_jdk/libexec/openjdk.jdk/Contents/Home/bin/java" ]; then
      candidate="$brew_jdk/libexec/openjdk.jdk/Contents/Home"
    fi
  fi

  if [ -z "$candidate" ] && [ "$(uname -s)" = "Darwin" ] && [ -x /usr/libexec/java_home ]; then
    candidate="$(/usr/libexec/java_home -v 21 2>/dev/null || true)"
  fi

  if [ -z "$candidate" ] && [ -d "$ROOT/.blee-tools" ]; then
    local tool_java
    tool_java="$(find "$ROOT/.blee-tools" -type f -path '*jdk-21*/bin/java' -perm -111 2>/dev/null | head -n 1 || true)"
    if [ -n "$tool_java" ]; then
      candidate="$(cd "$(dirname "$tool_java")/.." && pwd)"
      if [[ "$candidate" == */Contents/Home ]]; then :; fi
    fi
  fi

  if [ -z "$candidate" ] && command -v java >/dev/null 2>&1; then
    local current_major
    current_major="$(java -version 2>&1 | awk -F'[\".]' '/version/ {print $2; exit}')"
    if [ "${current_major:-0}" -ge 21 ] 2>/dev/null; then
      candidate="$(cd "$(dirname "$(command -v java)")/.." && pwd)"
    fi
  fi

  [ -n "$candidate" ] || fail "Java 21 not found. Install with: brew install openjdk@21"
  [ -x "$candidate/bin/java" ] || fail "Java 21 candidate is invalid: $candidate"

  export JAVA_HOME="$candidate"
  export PATH="$JAVA_HOME/bin:$PATH"

  local java_major
  java_major="$(java -version 2>&1 | awk -F'[\".]' '/version/ {print $2; exit}')"
  [ "${java_major:-0}" -ge 21 ] 2>/dev/null || fail "Gradle would run on Java ${java_major:-unknown}; Java 21+ is required"

  echo "JAVA_HOME: $JAVA_HOME"
  echo -n "Java: "
  java -version 2>&1 | head -n 1
}

select_java_21

python3 scripts/apply-blee-verifier-version-v27.py
python3 scripts/verify-blee-mesh-v2.py
python3 scripts/verify-production-final-v5.py
python3 scripts/verify-canonical-build.py

(
  cd android
  chmod +x gradlew
  ./gradlew --stop >/dev/null 2>&1 || true
  echo "Gradle JVM:"
  ./gradlew --version | sed -n '/Launcher JVM:/p;/Daemon JVM:/p'
  ./gradlew --no-daemon assembleDebug --stacktrace
)

APK="$ROOT/android/app/build/outputs/apk/debug/app-debug.apk"
FINAL_APK="$ROOT/dist/Blee-2.7.0.apk"
[ -f "$APK" ] || fail "Gradle APK missing"
mkdir -p "$ROOT/dist"
rm -f "$ROOT/dist"/*.apk "$ROOT/dist"/*.apk.sha256 2>/dev/null || true
cp "$APK" "$FINAL_APK"

chmod +x scripts/verify-apk-integrity.sh
bash scripts/verify-apk-integrity.sh "$FINAL_APK"

if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$FINAL_APK" > "$FINAL_APK.sha256"
elif command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$FINAL_APK" > "$FINAL_APK.sha256"
fi

echo "============================================================"
echo "Blee 2.7 production build completed"
echo "$FINAL_APK"
[ -f "$FINAL_APK.sha256" ] && cat "$FINAL_APK.sha256"
echo "============================================================"
