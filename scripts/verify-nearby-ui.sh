#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

CSS="app/nearby-screen.css"
LAYOUT="app/layout.tsx"
APP="src/components/BleeApp.tsx"

[ -f "$CSS" ] || fail "Nearby screen stylesheet missing"
grep -q 'BLEE_NEARBY_REFERENCE_V1' "$CSS" || fail "approved Nearby style marker missing"
grep -q 'data-blee-nearby-ui="radar-reference-v1"' "$APP" || fail "approved Nearby UI marker missing"
grep -q 'Find someone. Tap to pay.' "$APP" || fail "Nearby screen helper copy missing"
grep -q 'Visible to nearby people' "$APP" || fail "Nearby visibility control missing"
grep -q 'nearby-radar' "$APP" || fail "Nearby radar missing"
grep -q '/brand/blee-mark.svg' "$APP" || fail "local Blee radar identity missing"
grep -q 'Looking for people nearby' "$APP" || fail "Nearby discovery state missing"
grep -q 'People nearby' "$APP" || fail "Nearby people list missing"
grep -q 'Available to pay' "$APP" || fail "Nearby peer availability state missing"
grep -q 'No wallet address. No QR code.' "$APP" || fail "Nearby trust statement missing"
grep -q "import './nearby-screen.css';" "$LAYOUT" || fail "Nearby stylesheet is not loaded"

# Nearby UI must continue to operate through the existing mesh start/stop and
# verified Blee identity send path. It must never introduce raw wallet entry.
grep -q 'if (app.meshStarted) await app.stopMesh' "$APP" || fail "existing Nearby stop path missing"
grep -q 'else await app.startMesh' "$APP" || fail "existing Nearby start path missing"
grep -q 'onClick={() => openSend(peer)}' "$APP" || fail "Nearby pay action is not bound to discovered Blee peers"

printf 'VERIFIED: approved Nearby UI preserves native mesh discovery behind the premium radar and pay surface\n'
