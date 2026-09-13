#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def harden_passphrase_everywhere() -> None:
    changed = []
    for path in (ROOT / "src").rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
            continue
        text = path.read_text(errors="replace")
        if "passphrase" not in text.lower() and "12 characters" not in text.lower():
            continue
        before = text
        text = re.sub(r"(?i)use\s+(?:a\s+passphrase\s+of\s+)?at\s+least\s+12\s+characters", "Use a passphrase of at least 8 characters", text)
        text = re.sub(r"(?i)at\s+least\s+12\s+characters", "at least 8 characters", text)
        text = re.sub(r"(?i)minimum\s+12\s+characters", "minimum 8 characters", text)
        text = re.sub(r"(?i)12\+\s*characters", "8+ characters", text)
        text = re.sub(r"(?i)12\s+characters\s+minimum", "8 characters minimum", text)
        text = re.sub(r"(?i)(passphrase(?:\.trim\(\))?\.length\s*<\s*)12\b", r"\g<1>8", text)
        text = re.sub(r"(?i)(newPassphrase(?:\.trim\(\))?\.length\s*<\s*)12\b", r"\g<1>8", text)
        text = re.sub(r"(?i)(confirmPassphrase(?:\.trim\(\))?\.length\s*<\s*)12\b", r"\g<1>8", text)
        text = re.sub(r"(?i)(MIN(?:IMUM)?_?PASSPHRASE(?:_LENGTH)?\s*=\s*)12\b", r"\g<1>8", text)
        text = re.sub(r"(?i)(PASSPHRASE_MIN(?:_LENGTH)?\s*=\s*)12\b", r"\g<1>8", text)
        if text != before:
            path.write_text(text)
            changed.append(str(path.relative_to(ROOT)))

    offenders = []
    for path in (ROOT / "src").rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
            continue
        text = path.read_text(errors="replace")
        if re.search(r"(?is)(passphrase.{0,100}12\s*(?:characters|chars)|12\s*(?:characters|chars).{0,100}passphrase)", text):
            offenders.append(str(path.relative_to(ROOT)))
    if offenders:
        raise SystemExit(f"Blee 2.5.1: 12-character passphrase requirement still survives in {offenders}")

    vault = ROOT / "src/lib/vault.ts"
    recovery = ROOT / "src/lib/walletRecovery.ts"
    for path in (vault, recovery):
        if not path.is_file():
            raise SystemExit(f"Blee 2.5.1: missing {path.relative_to(ROOT)}")
        text = path.read_text(errors="replace")
        if not re.search(r"passphrase(?:\.trim\(\))?\.length\s*<\s*8", text):
            raise SystemExit(f"Blee 2.5.1: {path.relative_to(ROOT)} does not enforce the 8-character minimum")

    print("Blee 2.5.1: passphrase requirement normalized to 8 characters across UI + crypto paths")
    if changed:
        print("Blee 2.5.1 passphrase files:", ", ".join(changed))


def install_biometric_capability_gate() -> None:
    """Never advertise fingerprint UI on a phone without biometric hardware.

    Native status() is authoritative. The DOM attribute is a defensive UI gate so
    every current/future fingerprint action stays hidden until Android reports
    hardware capability. The observer also covers sheets rendered after startup.
    """
    biometric = ROOT / "src/lib/biometric.ts"
    css = ROOT / "app/globals.css"
    if not biometric.is_file() or not css.is_file():
        raise SystemExit("Blee 2.5.1: biometric capability-gate inputs missing")

    text = biometric.read_text(errors="replace")
    marker = "BLEE_BIOMETRIC_CAPABILITY_GATE_V1"
    if marker not in text:
        text += r'''

// BLEE_BIOMETRIC_CAPABILITY_GATE_V1
export async function syncBleeBiometricCapability(): Promise<boolean> {
  if (typeof document === 'undefined') return false;
  const root = document.documentElement;
  let available = false;
  try {
    const status: any = await BleeBiometric.status();
    available = Boolean(status?.available);
  } catch {
    available = false;
  }
  root.dataset.bleeBiometric = available ? 'available' : 'unavailable';

  // Defensive guard for any biometric action rendered by a later sheet/screen.
  // The React UI remains authoritative; this prevents unsupported hardware from
  // ever exposing a dead fingerprint control during transitions/hydration.
  const apply = () => {
    const nodes = document.querySelectorAll<HTMLElement>('button,[role="button"],.biometric-opt-in,.biometric-unlock,.fingerprint-action');
    nodes.forEach((node) => {
      const fingerprintControl = /fingerprint/i.test(node.textContent || '')
        || node.classList.contains('biometric-opt-in')
        || node.classList.contains('biometric-unlock')
        || node.classList.contains('fingerprint-action');
      if (!fingerprintControl) return;
      node.hidden = !available;
      node.setAttribute('aria-hidden', available ? 'false' : 'true');
    });
  };
  apply();
  return available;
}

if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  queueMicrotask(() => { void syncBleeBiometricCapability(); });
  const observer = new MutationObserver(() => {
    if (document.documentElement.dataset.bleeBiometric !== 'available') {
      void syncBleeBiometricCapability();
    }
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void syncBleeBiometricCapability();
  });
}
'''
        biometric.write_text(text)

    css_text = css.read_text()
    css_marker = "BLEE_BIOMETRIC_CAPABILITY_CSS_V1"
    if css_marker not in css_text:
        css_text += r'''

/* BLEE_BIOMETRIC_CAPABILITY_CSS_V1 */
html:not([data-blee-biometric="available"]) .biometric-opt-in,
html:not([data-blee-biometric="available"]) .biometric-unlock,
html:not([data-blee-biometric="available"]) .fingerprint-action,
html[data-blee-biometric="unavailable"] .biometric-opt-in,
html[data-blee-biometric="unavailable"] .biometric-unlock,
html[data-blee-biometric="unavailable"] .fingerprint-action {
  display: none !important;
}
'''
        css.write_text(css_text)

    print("Blee 2.5.1: fingerprint UI is capability-gated by native Android biometric status")


def verify_ui_features() -> None:
    app = ROOT / "src/components/BleeApp.tsx"
    css = ROOT / "app/globals.css"
    biometric = ROOT / "src/lib/biometric.ts"
    for path in (app, css, biometric):
        if not path.is_file():
            raise SystemExit(f"Blee 2.5.1: missing {path.relative_to(ROOT)}")
    app_text = app.read_text(errors="replace")
    css_text = css.read_text(errors="replace")
    biometric_text = biometric.read_text(errors="replace")

    required_app = (
        "blee-wordmark.svg",
        "PasswordField",
        "Show passphrase",
        "Hide passphrase",
        "Fingerprint unlock",
        "BleeBiometric.unlock",
        "BleeBiometric.enroll",
        "splash-logo",
        "Create wallet",
    )
    missing = [m for m in required_app if m not in app_text]
    if missing:
        raise SystemExit(f"Blee 2.5.1 UI features missing: {missing}")
    for banned in ("SELF-CUSTODIAL · OFFLINE-READY", "One USDC wallet for Arc Testnet, online or nearby."):
        if banned in app_text:
            raise SystemExit(f"Blee 2.5.1 minimalist onboarding regression: {banned}")
    for marker in (
        ".blee-wordmark", "height: auto", ".password-input", ".biometric-opt-in", "@keyframes blee-launch-logo",
        "BLEE_BIOMETRIC_CAPABILITY_CSS_V1", 'data-blee-biometric="available"'
    ):
        if marker not in css_text:
            raise SystemExit(f"Blee 2.5.1 CSS feature missing: {marker}")
    for marker in (
        "registerPlugin<NativeBleeBiometric>('BleeBiometric')", "enroll(passphrase", "unlock():", "disable()",
        "BLEE_BIOMETRIC_CAPABILITY_GATE_V1", "syncBleeBiometricCapability", "status?.available"
    ):
        if marker not in biometric_text:
            raise SystemExit(f"Blee 2.5.1 biometric bridge incomplete: {marker}")


def patch_version() -> None:
    package = ROOT / "package.json"
    data = json.loads(package.read_text())
    data["version"] = "2.5.1"
    package.write_text(json.dumps(data, indent=2) + "\n")
    native = ROOT / "scripts/configure-native.mjs"
    if native.exists():
        text = native.read_text()
        text = re.sub(r"versionCode\s+\d+", "versionCode 15", text)
        text = re.sub(r'versionName\s+\"[^\"]+\"', 'versionName "2.5.1"', text)
        native.write_text(text)


def main() -> None:
    harden_passphrase_everywhere()
    install_biometric_capability_gate()
    verify_ui_features()
    patch_version()
    print("Blee 2.5.1 web hardening verified: exact-aspect brand, show/hide passphrase, hardware-gated biometric UI, minimalist onboarding, animated launch")


if __name__ == "__main__":
    main()
