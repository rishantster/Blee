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
    elif [ -n "$brew_jdk" ] && [ -x "$brew_jdk/bin/java" ]; then
      candidate="$brew_jdk"
    fi
  fi

  if [ -z "$candidate" ] && [ "$(uname -s)" = "Darwin" ] && [ -x /usr/libexec/java_home ]; then
    candidate="$(/usr/libexec/java_home -v 21 2>/dev/null || true)"
  fi

  if [ -z "$candidate" ] && [ -d "$ROOT/.blee-tools" ]; then
    local tool_java
    tool_java="$(find "$ROOT/.blee-tools" -type f -path '*/bin/java' -perm -111 2>/dev/null | while read -r j; do "$j" -version 2>&1 | head -n 1 | grep -q 'version "21' && { echo "$j"; break; }; done)"
    if [ -n "$tool_java" ]; then
      candidate="$(cd "$(dirname "$tool_java")/.." && pwd)"
    fi
  fi

  [ -n "$candidate" ] || fail "Java 21 not found. Install it with: brew install openjdk@21"
  [ -x "$candidate/bin/java" ] || fail "Java 21 candidate is invalid: $candidate"

  export JAVA_HOME="$candidate"
  export PATH="$JAVA_HOME/bin:$PATH"

  local java_major
  java_major="$($JAVA_HOME/bin/java -version 2>&1 | awk -F'[\".]' '/version/ {print $2; exit}')"
  [ "${java_major:-0}" -ge 21 ] 2>/dev/null || fail "Selected Java is ${java_major:-unknown}; Java 21+ is required"

  # Isolate Gradle from ~/.gradle/gradle.properties and old daemon state. A
  # machine-level org.gradle.java.home pointing at Java 8 must not affect Blee.
  export GRADLE_USER_HOME="$ROOT/.blee-tools/gradle-home-v27"
  mkdir -p "$GRADLE_USER_HOME"

  # Belt-and-suspenders JVM pin. JAVA_HOME selects the wrapper/launcher;
  # org.gradle.java.home selects the Gradle daemon/tooling JVM even if a user
  # property elsewhere tries to override it.
  export GRADLE_OPTS="-Dorg.gradle.java.home=$JAVA_HOME ${GRADLE_OPTS:-}"

  echo "============================================================"
  echo "Blee 2.7 Android JVM preflight"
  echo "JAVA_HOME: $JAVA_HOME"
  echo -n "Java: "
  "$JAVA_HOME/bin/java" -version 2>&1 | head -n 1
  echo "GRADLE_USER_HOME: $GRADLE_USER_HOME"
  echo "============================================================"
}

select_java_21

python3 scripts/apply-blee-verifier-version-v27.py
python3 scripts/verify-blee-mesh-v2.py
python3 scripts/verify-production-final-v5.py
python3 scripts/verify-canonical-build.py

(
  cd android

  # Do not chmod gradlew: changing tracked file mode can make a later git pull
  # fail. Invoke it through bash instead.
  bash ./gradlew --stop >/dev/null 2>&1 || true

  GRADLE_VERSION_OUTPUT="$(bash ./gradlew -Dorg.gradle.java.home="$JAVA_HOME" --version 2>&1)" || {
    echo "$GRADLE_VERSION_OUTPUT" >&2
    fail "Gradle JVM preflight failed"
  }
  echo "$GRADLE_VERSION_OUTPUT"

  if ! printf '%s\n' "$GRADLE_VERSION_OUTPUT" | grep -Eq 'Launcher JVM:[[:space:]]+21|JVM:[[:space:]]+21'; then
    fail "Gradle launcher is not using Java 21"
  fi
  if printf '%s\n' "$GRADLE_VERSION_OUTPUT" | grep -Eq 'Daemon JVM:.*(1\.8|Java 8|/1\.8)'; then
    fail "Gradle daemon resolved to Java 8"
  fi

  bash ./gradlew \
    -Dorg.gradle.java.home="$JAVA_HOME" \
    --no-daemon \
    assembleDebug \
    --stacktrace
)

APK="$ROOT/android/app/build/outputs/apk/debug/app-debug.apk"
FINAL_APK="$ROOT/dist/Blee-2.7.0.apk"
[ -f "$APK" ] || fail "Gradle APK missing"

unzip -t "$APK" >/dev/null || fail "Gradle APK is not a valid ZIP/APK"

mkdir -p "$ROOT/dist"
rm -f "$ROOT/dist"/*.apk "$ROOT/dist"/*.apk.sha256 2>/dev/null || true
cp "$APK" "$FINAL_APK"

bash scripts/verify-apk-integrity.sh "$FINAL_APK"

if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$FINAL_APK" > "$FINAL_APK.sha256"
elif command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$FINAL_APK" > "$FINAL_APK.sha256"
fi

[ -f "$FINAL_APK" ] || fail "final APK copy missing"
[ "$(find "$ROOT/dist" -maxdepth 1 -type f -name '*.apk' | wc -l | tr -d ' ')" = "1" ] || fail "dist must contain exactly one APK"

printf '\n============================================================\n'
printf 'Blee 2.7 production build completed\n'
printf '%s\n' "$FINAL_APK"
[ -f "$FINAL_APK.sha256" ] && cat "$FINAL_APK.sha256"
printf '============================================================\n'
