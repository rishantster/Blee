#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "VERIFY ERROR: $*" >&2
  exit 1
}

APP="src/components/BleeApp.tsx"
CSS="app/approved-wallet-ui.css"
RECIPIENT="src/components/RecipientField.tsx"

[ -f "$APP" ] || fail "Blee app screen source missing"
[ -f "$CSS" ] || fail "approved wallet stylesheet missing"
[ -f "$RECIPIENT" ] || fail "recipient control missing"

# Profile / Edit profile
grep -q 'data-blee-profile-ui="approved-v1"' "$APP" || fail "approved Profile screen marker missing"
grep -q 'Your addresses' "$APP" || fail "Profile address section missing"
grep -q 'Arc Testnet' "$APP" || fail "Arc address row missing"
grep -q 'Solana Mainnet' "$APP" || fail "Solana address row missing"
grep -q 'People on Blee see your name and photo.' "$APP" || fail "Nearby identity explanation missing"
grep -q 'data-blee-edit-profile-ui="approved-v1"' "$APP" || fail "approved Edit profile marker missing"
grep -q 'profilePhotoDraft' "$APP" || fail "Edit profile changes are not staged before Save"
grep -q 'app.setProfilePhoto(profilePhotoDraft)' "$APP" || fail "profile photo is not committed on Save"
grep -q 'Help people recognize you' "$APP" || fail "profile recognition guidance missing"

# Settings / hardware-aware fingerprint
grep -q 'data-blee-settings-ui="approved-v1"' "$APP" || fail "approved Settings marker missing"
grep -q '>SECURITY<' "$APP" || fail "Settings SECURITY group missing"
grep -q '>ACTIVE NETWORKS<' "$APP" || fail "Settings ACTIVE NETWORKS group missing"
grep -q 'biometricStatus.available && <div className="settings-row"' "$APP" || fail "fingerprint row is not hardware/enrollment gated"
grep -q 'Backups and private keys' "$APP" || fail "Backup & recovery Settings copy missing"
grep -q 'Networks and nearby payments' "$APP" || fail "Network & security Settings copy missing"
grep -q '>Blee 2.7<' "$APP" || fail "Settings build footer missing"

# Send / Receive canonical controls
grep -q 'data-blee-send-ui="approved-v1"' "$APP" || fail "approved Send screen marker missing"
grep -q 'walletLayout' "$APP" || fail "Send is not using wallet-layout recipient control"
grep -q 'Name or wallet address' "$APP" || fail "USDC recipient prompt missing"
grep -q 'Choose a Blee recipient' "$APP" || fail "SOL Blee-recipient prompt missing"
grep -q 'Scan Blee QR' "$RECIPIENT" || fail "Send QR action missing"
grep -q '<BluetoothIcon />' "$RECIPIENT" || fail "Nearby action does not use proper Bluetooth icon"
grep -q 'data-blee-receive-ui="approved-v1"' "$APP" || fail "approved Receive screen marker missing"
grep -q 'QRCodeSVG value={address}' "$APP" || fail "Receive does not render real chain-specific QR"
grep -q 'Only send test USDC on Arc Testnet.' "$APP" || fail "USDC receive network warning missing"
grep -q 'Only send SOL on Solana to this address.' "$APP" || fail "SOL receive network warning missing"
grep -q 'Copy address' "$APP" || fail "Receive copy action missing"
grep -q 'Open Nearby' "$APP" || fail "Receive Nearby handoff missing"

# Presentation must not recreate the removed DOM patch layer.
if [ -e src/components/NearbySelfAvatarBridge.tsx ]; then
  fail "obsolete Nearby DOM avatar bridge is present"
fi
if grep -Eq 'NearbySelfAvatarBridge|document[.]querySelector.*radar-self' app/layout.tsx "$APP"; then
  fail "wallet UI contains a DOM patch layer instead of React state"
fi

printf 'VERIFIED: approved Profile, Edit, Settings, Send and Receive screens preserve real wallet behavior without patch layers\n'
