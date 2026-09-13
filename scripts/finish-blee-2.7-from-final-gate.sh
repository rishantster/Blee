#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() { echo "Blee 2.7 finish FAIL: $*" >&2; exit 1; }

[ -f src/components/BleeApp.tsx ] || fail "materialized BleeApp.tsx missing; run the canonical build instead"
[ -f android/app/build.gradle ] || fail "materialized Android tree missing; run the canonical build instead"
[ -f package.json ] || fail "materialized package.json missing; run the canonical build instead"

grep -q 'BLEE_CONTACTS_REACT_V4' src/components/BleeApp.tsx || fail "React contacts stage has not completed"
grep -q 'BLEE_ADAPTIVE_NEARBY_V3' android/app/src/main/java/com/blee/payments/BleeMeshService.java || fail "adaptive Nearby stage has not completed"
grep -q 'versionCode 17' android/app/build.gradle || fail "Android versionCode is not 17"
grep -q 'versionName "2.7.0"' android/app/build.gradle || fail "Android versionName is not 2.7.0"

python3 scripts/apply-blee-qr-final-normalize-v3.py
python3 scripts/apply-blee-notification-permission-v1.py
python3 scripts/verify-production-final-v5.py

npm run check
npm run build
npx cap sync android

python3 scripts/verify-blee-mesh-v2.py
python3 scripts/verify-production-final-v5.py
python3 scripts/verify-canonical-build.py

(
  cd android
  chmod +x gradlew
  ./gradlew --stop >/dev/null 2>&1 || true
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
echo "Blee 2.7 final-gate recovery build completed"
echo "$FINAL_APK"
[ -f "$FINAL_APK.sha256" ] && cat "$FINAL_APK.sha256"
echo "============================================================"
