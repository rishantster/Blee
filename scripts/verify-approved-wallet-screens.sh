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
RESPONSIVE="app/responsive-mobile.css"
RECIPIENT="src/components/RecipientField.tsx"
LAYOUT="app/layout.tsx"

[ -f "$APP" ] || fail "Blee app screen source missing"
[ -f "$CSS" ] || fail "approved wallet stylesheet missing"
[ -f "$RESPONSIVE" ] || fail "responsive mobile viewport contract missing"
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

# Responsive viewport contract: design elements scale within sensible bounds rather
# than increasing fixed sizes across every phone. Short screens get an explicit
# height-aware treatment and auth remains scroll-safe.
grep -q 'BLEE_RESPONSIVE_MOBILE_V1' "$RESPONSIVE" || fail "responsive mobile contract marker missing"
grep -q -- '--blee-vp-x: clamp' "$RESPONSIVE" || fail "horizontal viewport spacing is not fluid"
grep -q -- '--blee-touch: clamp' "$RESPONSIVE" || fail "touch target sizing is not bounded"
grep -q '@media (max-height: 760px)' "$RESPONSIVE" || fail "short-screen adaptation missing"
grep -q 'overflow-y: auto' "$RESPONSIVE" || fail "auth screen is not scroll-safe on short phones"
grep -q 'width: clamp(220px, 68vw, 310px)' "$RESPONSIVE" || fail "Nearby discovery field is not viewport bounded"
grep -q 'font-size: clamp(48px, 14vw, 68px)' "$RESPONSIVE" || fail "Send amount is not viewport bounded"
grep -q 'width: min(68vw, 280px, 36dvh)' "$RESPONSIVE" || fail "Receive QR is not bounded by width and height"
grep -q "import './responsive-mobile.css';" "$LAYOUT" || fail "responsive viewport contract is not loaded"
[ "$(grep -n "import './responsive-mobile.css';" "$LAYOUT" | cut -d: -f1)" -gt "$(grep -n "import './approved-wallet-ui.css';" "$LAYOUT" | cut -d: -f1)" ] || fail "responsive viewport contract must load after approved screen styling"

# Unlock/create must never return the user to whatever sub-screen was open when
# the wallet was locked. Both passphrase and biometric success reset navigation.
grep -Fq "await app.unlock(result.passphrase); historyRef.current = []; setScreen('home');" "$APP" || fail "biometric sign-in does not route to Home"
grep -Fq "historyRef.current = []; setScreen('home'); setPassphrase(''); setConfirmPassphrase('');" "$APP" || fail "passphrase/create success does not route to Home"

# Presentation must not recreate the removed DOM patch layer.
if [ -e src/components/NearbySelfAvatarBridge.tsx ]; then
  fail "obsolete Nearby DOM avatar bridge is present"
fi
if grep -Eq 'NearbySelfAvatarBridge|document[.]querySelector.*radar-self' app/layout.tsx "$APP"; then
  fail "wallet UI contains a DOM patch layer instead of React state"
fi

printf 'VERIFIED: approved wallet screens are viewport-responsive and successful authentication always enters Home\n'
