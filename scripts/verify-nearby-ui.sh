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
BRIDGE="src/components/NearbySelfAvatarBridge.tsx"

[ -f "$CSS" ] || fail "Nearby screen stylesheet missing"
[ -f "$BRIDGE" ] || fail "Nearby self-profile bridge missing"
grep -q 'BLEE_NEARBY_DOTTED_RADAR_V3' "$CSS" || fail "dotted Nearby radar marker missing"
grep -q 'data-blee-nearby-ui="radar-reference-v1"' "$APP" || fail "approved Nearby UI marker missing"
grep -q 'Find someone. Tap to pay.' "$APP" || fail "Nearby screen helper copy missing"
grep -q 'Visible to nearby people' "$APP" || fail "Nearby visibility control missing"
grep -q 'nearby-radar' "$APP" || fail "Nearby radar missing"
grep -q 'blee-nearby-heartbeat' "$CSS" || fail "Nearby heartbeat pulse missing"
grep -q 'nearby-radar-ring { display: none' "$CSS" || fail "legacy hard radar rings are still visible"
grep -q 'radar-self-mark' "$BRIDGE" || fail "local profile identity is not bound into radar center"
grep -q 'home-profile-button .person-avatar' "$BRIDGE" || fail "Nearby center does not mirror the local profile identity"
grep -q 'Looking for people nearby' "$APP" || fail "Nearby discovery state missing"
grep -q 'People nearby' "$APP" || fail "Nearby people list missing"
grep -q 'Available to pay' "$APP" || fail "Nearby peer availability state missing"
grep -q 'No wallet address. No QR code.' "$APP" || fail "Nearby trust statement missing"
grep -q "import './nearby-screen.css';" "$LAYOUT" || fail "Nearby stylesheet is not loaded"
grep -q 'NearbySelfAvatarBridge' "$LAYOUT" || fail "Nearby profile bridge is not mounted"

# Nearby UI must continue to operate through the existing mesh start/stop and
# verified Blee identity send path. It must never introduce raw wallet entry.
grep -q 'if (app.meshStarted) await app.stopMesh' "$APP" || fail "existing Nearby stop path missing"
grep -q 'else await app.startMesh' "$APP" || fail "existing Nearby start path missing"
grep -q 'onClick={() => openSend(peer)}' "$APP" || fail "Nearby pay action is not bound to discovered Blee peers"

printf 'VERIFIED: compact Nearby UI uses a pulsing dotted field and local profile identity over native mesh discovery\n'
