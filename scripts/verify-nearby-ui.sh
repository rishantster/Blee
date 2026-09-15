#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

BASE_CSS="app/nearby-screen.css"
APPROVED_CSS="app/approved-wallet-ui.css"
LAYOUT="app/layout.tsx"
APP="src/components/BleeApp.tsx"
BRIDGE="src/components/NearbySelfAvatarBridge.tsx"

[ -f "$BASE_CSS" ] || fail "Nearby base stylesheet missing"
[ -f "$APPROVED_CSS" ] || fail "approved wallet UI stylesheet missing"
[ ! -e "$BRIDGE" ] || fail "obsolete DOM/localStorage Nearby avatar bridge must not exist"
grep -q 'data-blee-nearby-ui="approved-pulse-v2"' "$APP" || fail "approved Nearby UI marker missing"
grep -q 'Find someone. Tap to pay.' "$APP" || fail "Nearby screen helper copy missing"
grep -q 'Visible to nearby people' "$APP" || fail "Nearby visibility control missing"
grep -q 'nearby-radar' "$APP" || fail "Nearby discovery field missing"
grep -q '@keyframes blee-radar-pulse' "$APPROVED_CSS" || fail "Nearby heartbeat pulse missing"
grep -q 'background-image: radial-gradient' "$APPROVED_CSS" || fail "dotted discovery field missing"
grep -q 'nearby-radar-ring { display: none' "$APPROVED_CSS" || fail "legacy hard radar rings are still visible"
grep -q 'radar-self-mark"><PersonAvatar name={app.alias} src={app.profilePhoto}' "$APP" || fail "local profile identity is not rendered directly in radar center"
grep -q 'Looking for people nearby' "$APP" || fail "Nearby discovery state missing"
grep -q 'People nearby' "$APP" || fail "Nearby people list missing"
grep -q 'Available to pay' "$APP" || fail "Nearby peer availability state missing"
grep -q 'No wallet address. No QR code.' "$APP" || fail "Nearby trust statement missing"
grep -q "import './nearby-screen.css';" "$LAYOUT" || fail "Nearby base stylesheet is not loaded"
if grep -q 'NearbySelfAvatarBridge' "$LAYOUT"; then
  fail "Nearby profile identity must not be patched through a DOM bridge"
fi

# Nearby UI must continue to operate through existing native mesh start/stop and
# verified discovered-peer send path. It must never introduce raw peer identity.
grep -q 'if (app.meshStarted) await app.stopMesh' "$APP" || fail "existing Nearby stop path missing"
grep -q 'else await app.startMesh' "$APP" || fail "existing Nearby start path missing"
grep -q 'onClick={() => openSend(peer)}' "$APP" || fail "Nearby pay action is not bound to discovered Blee peers"

printf 'VERIFIED: approved Nearby UI uses direct local identity with a pulsing dotted discovery field over native mesh\n'
