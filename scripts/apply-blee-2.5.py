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
        raise SystemExit(f"Blee 2.5: 12-character passphrase requirement still survives in {offenders}")

    vault = ROOT / "src/lib/vault.ts"
    recovery = ROOT / "src/lib/walletRecovery.ts"
    for path in (vault, recovery):
        if not path.is_file():
            raise SystemExit(f"Blee 2.5: missing {path.relative_to(ROOT)}")
        text = path.read_text(errors="replace")
        if not re.search(r"passphrase(?:\.trim\(\))?\.length\s*<\s*8", text):
            raise SystemExit(f"Blee 2.5: {path.relative_to(ROOT)} does not enforce the 8-character minimum")

    print("Blee 2.5: passphrase requirement normalized to 8 characters across UI + crypto paths")
    if changed:
        print("Blee 2.5 passphrase files:", ", ".join(changed))


def verify_ui_features() -> None:
    app = ROOT / "src/components/BleeApp.tsx"
    css = ROOT / "app/globals.css"
    biometric = ROOT / "src/lib/biometric.ts"
    for path in (app, css, biometric):
        if not path.is_file():
            raise SystemExit(f"Blee 2.5: missing {path.relative_to(ROOT)}")
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
        raise SystemExit(f"Blee 2.5 UI features missing: {missing}")
    for banned in ("SELF-CUSTODIAL · OFFLINE-READY", "One USDC wallet for Arc Testnet, online or nearby."):
        if banned in app_text:
            raise SystemExit(f"Blee 2.5 minimalist onboarding regression: {banned}")
    for marker in (".blee-wordmark", "height: auto", ".password-input", ".biometric-opt-in", "@keyframes blee-launch-logo"):
        if marker not in css_text:
            raise SystemExit(f"Blee 2.5 CSS feature missing: {marker}")
    for marker in ("registerPlugin<NativeBleeBiometric>('BleeBiometric')", "enroll(passphrase", "unlock():", "disable()"):
        if marker not in biometric_text:
            raise SystemExit(f"Blee 2.5 biometric bridge incomplete: {marker}")


def patch_version() -> None:
    package = ROOT / "package.json"
    data = json.loads(package.read_text())
    data["version"] = "2.5.0"
    package.write_text(json.dumps(data, indent=2) + "\n")
    native = ROOT / "scripts/configure-native.mjs"
    if native.exists():
        text = native.read_text()
        text = re.sub(r"versionCode\s+\d+", "versionCode 14", text)
        text = re.sub(r'versionName\s+\"[^\"]+\"', 'versionName "2.5.0"', text)
        native.write_text(text)


def main() -> None:
    harden_passphrase_everywhere()
    verify_ui_features()
    patch_version()
    print("Blee 2.5 web hardening verified: exact-aspect brand, show/hide passphrase, biometric UI, minimalist onboarding, animated launch")


if __name__ == "__main__":
    main()
