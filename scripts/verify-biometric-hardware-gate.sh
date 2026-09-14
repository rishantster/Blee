#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

NATIVE="android/app/src/main/java/com/blee/payments/BleeBiometricPlugin.java"
WEB="src/lib/biometric.ts"
CSS="app/biometric-auth.css"
LAYOUT="app/layout.tsx"
ICON="public/brand/fingerprint-clean.svg"

[ -f "$NATIVE" ] || fail "native biometric plugin missing"
[ -f "$WEB" ] || fail "biometric web boundary missing"
[ -f "$CSS" ] || fail "biometric UI guard missing"
[ -f "$ICON" ] || fail "clean fingerprint icon missing"

grep -q 'PackageManager.FEATURE_FINGERPRINT' "$NATIVE" || fail "native status does not require a real fingerprint hardware feature"
grep -q 'FingerprintManager' "$NATIVE" || fail "native fingerprint hardware manager gate missing"
grep -q 'fingerprint.hasEnrolledFingerprints()' "$NATIVE" || fail "native fingerprint enrollment gate missing"
grep -q 'boolean usableFingerprint = availability.available && availability.enrolled' "$NATIVE" || fail "native status can expose unusable fingerprint state"
grep -q 'const usable = Boolean(status.available && status.enrolled)' "$WEB" || fail "web biometric status is not enrollment-gated"
grep -q 'BLEE_BIOMETRIC_CAPABILITY_GATE_V2' "$WEB" || fail "biometric capability gate v2 marker missing"
grep -q 'data-blee-biometric' "$CSS" || fail "unsupported-hardware visual guard missing"
grep -q 'fingerprint-clean.svg' "$CSS" || fail "clean fingerprint asset not used"
grep -q "import './biometric-auth.css';" "$LAYOUT" || fail "biometric auth stylesheet not loaded"

printf 'VERIFIED: fingerprint UI is real-hardware/enrollment gated and uses the clean auth icon\n'
