#!/usr/bin/env bash
set -euo pipefail

APK="${1:-}"
[ -n "$APK" ] || { echo "APK VERIFY FAIL: usage: $0 <apk>" >&2; exit 1; }
[ -f "$APK" ] || { echo "APK VERIFY FAIL: missing APK: $APK" >&2; exit 1; }

fail() { echo "APK VERIFY FAIL: $*" >&2; exit 1; }
pass() { echo "APK VERIFY OK: $*"; }

unzip -t "$APK" >/dev/null || fail "APK zip structure is invalid"
pass "zip structure"

SIZE_BYTES="$(wc -c < "$APK" | tr -d ' ')"
[ "${SIZE_BYTES:-0}" -gt 4000000 ] || fail "APK is unexpectedly small (${SIZE_BYTES} bytes)"
pass "size ${SIZE_BYTES} bytes"

ENTRIES="$(unzip -Z1 "$APK")"
printf '%s\n' "$ENTRIES" | grep -qx 'AndroidManifest.xml' || fail "compiled AndroidManifest.xml missing"
printf '%s\n' "$ENTRIES" | grep -qx 'classes.dex' || fail "classes.dex missing"
printf '%s\n' "$ENTRIES" | grep -qx 'assets/public/index.html' || fail "Capacitor web index missing"
printf '%s\n' "$ENTRIES" | grep -qx 'assets/public/brand/blee-logo.svg' || fail "Blee logo missing from packaged web assets"
printf '%s\n' "$ENTRIES" | grep -q '^assets/public/_next/static/' || fail "Next static bundle missing"
printf '%s\n' "$ENTRIES" | grep -q '^res/raw/blee_open_chime' || fail "Blee launch sound missing"
pass "manifest + web bundle + brand + sound resources"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
unzip -p "$APK" 'classes*.dex' > "$TMP/all.dex" || fail "could not read DEX payload"
mkdir -p "$TMP/web"
unzip -q "$APK" 'assets/public/*' -d "$TMP/web" || fail "could not extract packaged web assets"

require_dex() {
  local token="$1" label="$2"
  LC_ALL=C grep -a -q "$token" "$TMP/all.dex" || fail "$label missing from DEX"
  pass "$label"
}

require_web() {
  local token="$1" label="$2"
  LC_ALL=C grep -R -a -q -- "$token" "$TMP/web/assets/public" || fail "$label missing from packaged web app"
  pass "$label"
}

forbid_web() {
  local token="$1" label="$2"
  if LC_ALL=C grep -R -a -q -- "$token" "$TMP/web/assets/public"; then
    fail "$label unexpectedly present in packaged web app"
  fi
  pass "$label absent"
}

require_dex 'BleeMeshService' 'Blee mesh service'
require_dex 'BleeMeshPlugin' 'Blee mesh Capacitor plugin'
require_dex 'BleeMeshDb' 'Blee SQLite mesh database'
require_dex 'BleePaymentNotifier' 'payment notification implementation'
require_dex 'POST_NOTIFICATIONS' 'Android notification permission path'
require_dex 'manualRefresh' 'non-destructive native refresh bridge'
require_dex 'listContacts' 'native contacts listing API'
require_dex 'saveContact' 'native contacts persistence API'
require_dex 'BleeQrScannerPlugin' 'QR scanner plugin'
require_dex 'BleeQrCaptureActivity' 'portrait QR capture activity'
require_dex 'com/google/android/gms/nearby' 'Google Nearby transport dependency'
require_dex 'IntentIntegrator' 'ZXing scanner dependency'
require_dex 'SENDER_FUNDED_RAW_TX' 'sender-funded settlement contract'
require_dex 'PAYMENT_ENVELOPE' 'offline payment envelope contract'

require_web 'blee-recipient-qr-icon' 'in-field QR scanner control'
require_web 'blee-refresh-splash' 'Blee refresh animation'
forbid_web 'activity-contact-filter' 'experimental React contact filter'
forbid_web 'Manage contacts' 'experimental React contact management UI'
forbid_web 'blee-activity-contact-tools' 'legacy DOM-injected Activity controls'
forbid_web 'blee-activity-contacts-button' 'legacy DOM contacts button'

DEX_COUNT="$(printf '%s\n' "$ENTRIES" | grep -Ec '^classes([0-9]+)?\.dex$' || true)"
WEB_COUNT="$(printf '%s\n' "$ENTRIES" | grep -c '^assets/public/' || true)"
if command -v shasum >/dev/null 2>&1; then
  SHA="$(shasum -a 256 "$APK" | awk '{print $1}')"
elif command -v sha256sum >/dev/null 2>&1; then
  SHA="$(sha256sum "$APK" | awk '{print $1}')"
else
  SHA="unavailable"
fi

echo "============================================================"
echo "APK INTEGRITY VERIFIED: Blee 2.7 production contract"
echo "APK: $APK"
echo "Bytes: $SIZE_BYTES"
echo "DEX files: $DEX_COUNT"
echo "Packaged web entries: $WEB_COUNT"
echo "SHA-256: $SHA"
echo "============================================================"
