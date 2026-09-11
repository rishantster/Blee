#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

EXPECTED_BRANCH="blee-professional"
EXPECTED_APK="Blee-1.3.0-professional-debug.apk"

CURRENT_BRANCH="$(git branch --show-current)"
if [ "$CURRENT_BRANCH" != "$EXPECTED_BRANCH" ]; then
  echo "ERROR: You are on branch '$CURRENT_BRANCH', expected '$EXPECTED_BRANCH'."
  echo "Run: git checkout $EXPECTED_BRANCH"
  exit 1
fi

echo "Fetching latest Blee Professional source..."
git fetch origin "$EXPECTED_BRANCH"
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$EXPECTED_BRANCH")"
if [ "$LOCAL" != "$REMOTE" ]; then
  echo "Updating local branch to latest Blee Professional..."
  git pull --ff-only origin "$EXPECTED_BRANCH"
fi

echo "Building from commit: $(git rev-parse --short HEAD)"

test -f build-blee-professional.command || { echo "ERROR: Missing professional builder."; exit 1; }
test -f scripts/apply-blee-professional.py || { echo "ERROR: Missing professional overlay script."; exit 1; }
test -f professional/parts/part00 || { echo "ERROR: Missing professional source snapshot."; exit 1; }
test -f overrides/src/lib/networkConfig.ts || { echo "ERROR: Missing configurable network support."; exit 1; }
test -f overrides/src/lib/walletRecovery.ts || { echo "ERROR: Missing wallet recovery support."; exit 1; }
test -f overrides/src/components/BleeAdvancedSettings.tsx || { echo "ERROR: Missing Blee Settings UI."; exit 1; }

python3 - <<'PYVERIFY'
import base64, hashlib, pathlib, tarfile, tempfile
parts = sorted(pathlib.Path('professional/parts').glob('part*'))
raw = base64.b64decode(b''.join(p.read_bytes() for p in parts), validate=True)
digest = hashlib.sha256(raw).hexdigest()
want = 'a698f4f239334875c96b46022582b964db69f3496c5c5aaed0691aa5632c4da6'
if digest != want:
    raise SystemExit(f'Professional source checksum mismatch: {digest}')
with tempfile.TemporaryDirectory() as tmp:
    archive = pathlib.Path(tmp) / 'overlay.tar.gz'
    archive.write_bytes(raw)
    with tarfile.open(archive, 'r:gz') as tar:
        names = set(tar.getnames())
    required = {
        'src/components/BleeApp.tsx',
        'src/components/BleeAdvancedSettings.tsx',
        'src/hooks/useBlee.ts',
        'app/globals.css',
        'app/layout.tsx',
        'native/BleeStorePlugin.java',
    }
    missing = required - names
    if missing:
        raise SystemExit(f'Professional snapshot is missing: {sorted(missing)}')
print('Professional source snapshot verified:', digest)
PYVERIFY

java_major_for() {
  local java_bin="$1"
  local version
  version="$("$java_bin" -version 2>&1 | awk -F'[\".]' '/version/ {print $2; exit}' || true)"
  printf '%s' "${version:-0}"
}

java_major() {
  if ! command -v java >/dev/null 2>&1; then
    printf '0'
    return
  fi
  java_major_for "$(command -v java)"
}

activate_java_home() {
  local home="$1"
  local java_bin="$home/bin/java"
  local major
  [ -x "$java_bin" ] || return 1
  major="$(java_major_for "$java_bin")"
  if ! [ "$major" -ge 21 ] 2>/dev/null; then
    return 1
  fi
  export JAVA_HOME="$home"
  export PATH="$JAVA_HOME/bin:$PATH"
  return 0
}

ensure_java21() {
  if command -v java >/dev/null 2>&1 && [ "$(java_major)" -ge 21 ] 2>/dev/null; then
    echo "Java 21+ detected: $(java -version 2>&1 | head -n 1)"
    return 0
  fi

  echo "Java 21+ is required. Looking for an existing JDK..."

  if [ -x /usr/libexec/java_home ]; then
    local system_java
    system_java="$(/usr/libexec/java_home -v 21 2>/dev/null || true)"
    if [ -n "$system_java" ] && activate_java_home "$system_java"; then
      echo "Using Java from $JAVA_HOME"
      echo "Java: $(java -version 2>&1 | head -n 1)"
      return 0
    fi
  fi

  local candidate
  for candidate in \
    "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home" \
    "/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home" \
    "/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home" \
    "/Library/Java/JavaVirtualMachines/jdk-21.jdk/Contents/Home"; do
    if activate_java_home "$candidate"; then
      echo "Using Java from $JAVA_HOME"
      echo "Java: $(java -version 2>&1 | head -n 1)"
      return 0
    fi
  done

  if command -v brew >/dev/null 2>&1; then
    echo "Java 21 not found. Installing Homebrew openjdk@21..."
    HOMEBREW_NO_AUTO_UPDATE=1 brew install openjdk@21
    local brew_prefix
    brew_prefix="$(brew --prefix openjdk@21)"
    if activate_java_home "$brew_prefix/libexec/openjdk.jdk/Contents/Home" || activate_java_home "$brew_prefix"; then
      echo "Java installed successfully: $(java -version 2>&1 | head -n 1)"
      return 0
    fi
    echo "ERROR: Homebrew installed openjdk@21 but Blee could not locate its Java binary."
    exit 1
  fi

  echo
  echo "ERROR: Java 21 is not installed and Homebrew was not found."
  echo "Install Homebrew from https://brew.sh, then run:"
  echo "  brew install openjdk@21"
  echo "Then rerun: bash build-blee-final.command"
  exit 1
}

ensure_java21

echo "Removing stale build outputs..."
rm -rf dist android .next out
mkdir -p dist

bash build-blee-professional.command

APK="$ROOT/dist/$EXPECTED_APK"
[ -f "$APK" ] || { echo "ERROR: Expected Blee Professional APK was not produced: $APK"; exit 1; }
unzip -t "$APK" >/dev/null
SHA="$(shasum -a 256 "$APK" | awk '{print $1}')"

grep -Eq 'versionCode[[:space:]]+6' android/app/build.gradle || { echo "ERROR: Android versionCode 6 was not applied."; exit 1; }
grep -Eq 'versionName[[:space:]]+"1\.3\.0"' android/app/build.gradle || { echo "ERROR: Android versionName 1.3.0 was not applied."; exit 1; }
grep -q '@drawable/blee_launcher' android/app/src/main/AndroidManifest.xml || { echo "ERROR: Blee launcher icon is not wired into AndroidManifest.xml."; exit 1; }
grep -q 'BleeAdvancedSettings' src/components/BleeApp.tsx || { echo "ERROR: Settings UI was not wired into BleeApp."; exit 1; }
grep -q 'sendQueueRef' src/hooks/useBlee.ts || { echo "ERROR: Professional send serialization was overwritten."; exit 1; }
grep -q 'authenticatedRecipient' src/hooks/useBlee.ts || { echo "ERROR: Professional ACK authentication was overwritten."; exit 1; }
grep -q 'rememberIdentity' src/hooks/useBlee.ts || { echo "ERROR: Nearby identity synchronization is missing."; exit 1; }
grep -q 'profilePhotoRef' src/hooks/useBlee.ts || { echo "ERROR: Profile photo relay is missing."; exit 1; }
grep -q 'QRCodeSVG' src/components/BleeApp.tsx || { echo "ERROR: Receive QR implementation is missing."; exit 1; }
grep -q 'Settlement network' src/components/BleeAdvancedSettings.tsx || { echo "ERROR: Professional network settings UI is missing."; exit 1; }
grep -q 'BLEE_NETWORK_STARTUP_PROFILE' src/lib/arc.ts || { echo "ERROR: Startup network profile was not wired into settlement."; exit 1; }
grep -q 'getActiveNetwork' src/lib/arc.ts || { echo "ERROR: Active network lookup is missing from settlement runtime."; exit 1; }
grep -q 'BLEE_STORE_PRO_V3' plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java || { echo "ERROR: Professional SQLite implementation was overwritten."; exit 1; }
grep -q '"qrcode.react"' package.json || { echo "ERROR: QR dependency was not installed into the professional source."; exit 1; }

echo "Verifying Blee Professional features inside compiled APK..."
VERIFY_DIR="$(mktemp -d)"
trap 'rm -rf "$VERIFY_DIR"' EXIT
unzip -q "$APK" -d "$VERIFY_DIR"
WEB_ROOT="$VERIFY_DIR/assets/public"

grep -R -q 'Wallet recovery' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing Wallet recovery UI."; exit 1; }
grep -R -q 'Add network' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing Add network UI."; exit 1; }
grep -R -q 'Settlement network' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing the redesigned settlement-network UI."; exit 1; }
grep -R -q 'Final after settlement' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing the redesigned How Blee works UI."; exit 1; }
grep -R -q 'Profile photo' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing profile photo controls."; exit 1; }
grep -R -q 'Scan to copy this wallet address' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing the Receive QR UI."; exit 1; }
grep -R -q 'blee.networks.v1' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing persistent network profiles."; exit 1; }
grep -R -q 'blee.active-network.v1' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing active-network persistence."; exit 1; }
grep -R -q 'wallet.vault.v2' "$WEB_ROOT" || { echo "ERROR: Compiled APK wallet recovery is not using the encrypted Blee vault."; exit 1; }
grep -R -q 'Blee 1.3' "$WEB_ROOT" || { echo "ERROR: Compiled APK does not identify itself as Blee 1.3."; exit 1; }
grep -R -q 'CONFIRMED SPENDABLE' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing confirmed-spendable balance UX."; exit 1; }
grep -R -q 'Nearby delivery is not final settlement' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing nearby-vs-settlement disclosure."; exit 1; }
grep -R -q 'Recipient acknowledgement is authenticated' "$WEB_ROOT" || { echo "ERROR: Compiled APK is missing authenticated ACK disclosure."; exit 1; }
grep -R -q 'Network transaction reverted' "$WEB_ROOT" || { echo "ERROR: Configurable settlement runtime was not compiled into the APK."; exit 1; }
grep -R -q 'Blee SQLite initialization failed' "$WEB_ROOT" || { echo "ERROR: SQLite error handling was not compiled into the APK."; exit 1; }
if grep -R -q 'ARC DROP' "$WEB_ROOT"; then
  echo "ERROR: Old ARC DROP branding still exists in packaged web assets."
  exit 1
fi
if grep -R -q 'INTERNET OPTIONAL' "$WEB_ROOT"; then
  echo "ERROR: Prototype connectivity copy still exists in packaged web assets."
  exit 1
fi
if grep -R -q 'MetaMask-style' "$WEB_ROOT"; then
  echo "ERROR: Old MetaMask-style network copy still exists in packaged web assets."
  exit 1
fi

grep -q 'com.blee.store.BleeStorePlugin' "$VERIFY_DIR/assets/capacitor.plugins.json" || { echo "ERROR: Capacitor did not register BleeStorePlugin in the APK."; exit 1; }

DEX_STRINGS="$VERIFY_DIR/blee-dex-strings.txt"
find "$VERIFY_DIR" -maxdepth 1 -name 'classes*.dex' -print0 | xargs -0 strings > "$DEX_STRINGS"
grep -q 'BleeStorePlugin' "$DEX_STRINGS" || { echo "ERROR: Native BleeStorePlugin missing from APK."; exit 1; }
grep -q 'BleeNearbyPlugin' "$DEX_STRINGS" || { echo "ERROR: Native BleeNearbyPlugin missing from APK."; exit 1; }
grep -q 'SQLiteOpenHelper' "$DEX_STRINGS" || { echo "ERROR: SQLite implementation missing from APK."; exit 1; }
grep -q 'BLEE_STORE_PRO_V3' "$DEX_STRINGS" || { echo "ERROR: APK contains an older SQLite plugin, not the professional store."; exit 1; }
if grep -q 'PRAGMA journal_mode=WAL' "$DEX_STRINGS"; then
  echo "ERROR: APK contains the unsafe forced WAL initialization path."
  exit 1
fi

rm -rf "$VERIFY_DIR"
trap - EXIT

echo
echo "============================================================"
echo "✅ VERIFIED BLEE 1.3.0 PROFESSIONAL APK"
echo "File: $APK"
echo "SHA-256: $SHA"
echo "Version: 1.3.0 (Android versionCode 6)"
echo "Verified: durable SQLite + authenticated ACKs + serialized sends + identity/name/photo relay + auto nearby discovery + Receive QR + wallet recovery + clean network/settings UX"
echo "============================================================"
echo
open "$ROOT/dist" 2>/dev/null || true
