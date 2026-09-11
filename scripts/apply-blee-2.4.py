#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / "ui-v4" / "parts"
ARCHIVE_SHA256 = "e7a3ab0867ae73f2d81bb23d828ec8589900e1ac86be9be67fa6f057bf3de0d2"
FILES = (
    "src/components/BleeApp.tsx",
    "src/components/BleeAdvancedSettings.tsx",
    "src/lib/networkConfig.ts",
    "app/globals.css",
)


def decode_bundle() -> tuple[Path, Path]:
    parts = sorted(PARTS.glob("part*"))
    expected = [f"part{i:02d}" for i in range(11)]
    if [p.name for p in parts] != expected:
        raise SystemExit(f"Blee 2.4: expected UI bundle parts {expected}, found {[p.name for p in parts]}")
    encoded = b"".join(b"".join(p.read_bytes().split()) for p in parts)
    try:
        archive = base64.b64decode(encoded, validate=True)
    except Exception as error:
        raise SystemExit(f"Blee 2.4: UI bundle is not valid base64: {error}") from error
    digest = hashlib.sha256(archive).hexdigest()
    if digest != ARCHIVE_SHA256:
        raise SystemExit(f"Blee 2.4: UI bundle checksum mismatch: {digest}; expected {ARCHIVE_SHA256}")
    temp = Path(tempfile.mkdtemp(prefix="blee-ui-2.4-"))
    source = temp / "source"
    source.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=__import__('io').BytesIO(archive), mode="r:gz") as tar:
        root = source.resolve()
        for member in tar.getmembers():
            target = (source / member.name).resolve()
            if target != root and not str(target).startswith(str(root) + "/"):
                raise SystemExit(f"Blee 2.4: unsafe UI bundle member: {member.name}")
        tar.extractall(source)
    return temp, source


def install_ui(source: Path) -> None:
    for rel in FILES:
        src, dst = source / rel, ROOT / rel
        if not src.is_file():
            raise SystemExit(f"Blee 2.4: UI bundle missing {rel}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"Blee 2.4 source replacement: {rel}")


def normalize_passphrase(text: str) -> str:
    text = re.sub(r"(?i)at\s+least\s+12\s+characters", "at least 8 characters", text)
    text = re.sub(r"(?i)minimum\s+12\s+characters", "minimum 8 characters", text)
    text = re.sub(r"(?i)12\+\s*characters", "8+ characters", text)
    text = re.sub(r"(?i)12\s+characters\s+minimum", "8 characters minimum", text)
    text = re.sub(r"(?i)(passphrase\.length\s*<\s*)12\b", r"\g<1>8", text)
    text = re.sub(r"(?i)(newPassphrase\.length\s*<\s*)12\b", r"\g<1>8", text)
    text = re.sub(r"(?i)(confirmPassphrase\.length\s*<\s*)12\b", r"\g<1>8", text)
    return text


def enforce_passphrase() -> None:
    for path in (ROOT / "src").rglob("*"):
        if path.is_file() and path.suffix in {".ts", ".tsx"} and "passphrase" in path.read_text().lower():
            text = path.read_text()
            updated = normalize_passphrase(text)
            if updated != text:
                path.write_text(updated)

    vault = ROOT / "src/lib/vault.ts"
    recovery = ROOT / "src/lib/walletRecovery.ts"
    if not vault.is_file() or not recovery.is_file():
        raise SystemExit("Blee 2.4: vault/recovery source missing")

    vault_text = normalize_passphrase(vault.read_text())
    if not re.search(r"passphrase\.length\s*<\s*8", vault_text):
        patterns = (
            r"((?:export\s+)?async\s+function\s+createVault\s*\([^)]*\bpassphrase\b[^)]*\)\s*(?::\s*[^\{]+)?\{)",
            r"((?:export\s+)?const\s+createVault\s*=\s*async\s*\([^)]*\bpassphrase\b[^)]*\)\s*(?::\s*[^=]+)?=>\s*\{)",
        )
        guard = '\n  if (passphrase.length < 8) throw new Error("Use a passphrase of at least 8 characters");'
        for pattern in patterns:
            vault_text, count = re.subn(pattern, r"\1" + guard, vault_text, count=1, flags=re.S)
            if count:
                break
        else:
            raise SystemExit("Blee 2.4: createVault(passphrase) not found")
    vault.write_text(vault_text)

    recovery_text = normalize_passphrase(recovery.read_text())
    recovery.write_text(recovery_text)
    if not re.search(r"passphrase\.length\s*<\s*8", vault_text):
        raise SystemExit("Blee 2.4: createVault lacks functional 8-character minimum")
    if not re.search(r"passphrase\.length\s*<\s*8", recovery_text):
        raise SystemExit("Blee 2.4: recovery/import lacks functional 8-character minimum")
    print("Blee 2.4: functional 8-character passphrase policy verified in create + import paths")


def verify_arc_only() -> None:
    text = (ROOT / "src/lib/networkConfig.ts").read_text()
    patterns = (
        r"chainId\s*:\s*5042002\b",
        r"tokenSymbol\s*:\s*['\"]USDC['\"]",
        r"tokenAddress\s*:\s*['\"]0x3600000000000000000000000000000000000000['\"]",
        r"return\s*\[\s*ARC_TESTNET\s*\]",
        r"return\s+ARC_TESTNET",
    )
    missing = [p for p in patterns if not re.search(p, text)]
    if missing or "Custom settlement networks are not available in Blee" not in text:
        raise SystemExit(f"Blee 2.4: Arc/USDC-only network contract incomplete: {missing}")


def patch_version() -> None:
    package = ROOT / "package.json"
    data = json.loads(package.read_text())
    data["version"] = "2.4.0"
    package.write_text(json.dumps(data, indent=2) + "\n")
    native = ROOT / "scripts/configure-native.mjs"
    if native.exists():
        text = native.read_text()
        text = re.sub(r"versionCode\s+\d+", "versionCode 13", text)
        text = re.sub(r'versionName\s+\"[^\"]+\"', 'versionName "2.4.0"', text)
        native.write_text(text)


def verify_ui() -> None:
    app = (ROOT / "src/components/BleeApp.tsx").read_text()
    css = (ROOT / "app/globals.css").read_text()
    advanced = (ROOT / "src/components/BleeAdvancedSettings.tsx").read_text()
    vault = (ROOT / "src/lib/vault.ts").read_text()
    recovery = (ROOT / "src/lib/walletRecovery.ts").read_text()

    required = (
        "useBlee", "BottomNav", "Home", "Nearby", "Activity", "Profile",
        "Confirm and send", "QRCodeSVG", "Backup & recovery", "Blee 2.4",
    )
    missing = [x for x in required if x not in app]
    if missing:
        raise SystemExit(f"Blee 2.4: rebuilt UI missing required functional markers: {missing}")

    banned = (
        "Keep this screen open", "MetaMask-style", "Add network", "Relay valid payments",
        "Payments that keep moving", "brand-orbit", "hero-ring", "signal-ring",
        "radar-ring", "brand-monument",
    )
    found = [x for x in banned if x.lower() in app.lower()]
    if found:
        raise SystemExit(f"Blee 2.4: legacy UI/copy survived: {found}")

    if not css.lstrip().startswith("/* BLEE_UI_2_4"):
        raise SystemExit("Blee 2.4: globals.css is not the ground-up replacement")
    for marker in ("grid-template-columns: repeat(4, 1fr)", ".blee-phone.with-nav", ".screen-transition", "safe-area-inset-bottom"):
        if marker not in css:
            raise SystemExit(f"Blee 2.4: production layout invariant missing: {marker}")

    if any(x in advanced for x in ("saveNetwork", "deleteNetwork", "setActiveNetwork", "Custom network")):
        raise SystemExit("Blee 2.4: custom-network controls survived in settings")
    combined = app + "\n" + vault + "\n" + recovery
    if re.search(r"(?i)12\s*(?:\+|characters)|passphrase\.length\s*<\s*12", combined):
        raise SystemExit("Blee 2.4: obsolete 12-character passphrase rule/copy remains")

    nav_match = re.search(r"function\s+BottomNav\b(?P<body>.*?)(?:\n}\n|\n}\r?\n)", app, re.S)
    if not nav_match:
        raise SystemExit("Blee 2.4: BottomNav component missing")
    nav = nav_match.group("body")
    for label in ("Home", "Nearby", "Activity", "Profile"):
        if label not in nav:
            raise SystemExit(f"Blee 2.4: BottomNav missing {label}")
    for label in ("Send", "Receive", "Settings"):
        if re.search(rf">\s*{label}\s*<", nav):
            raise SystemExit(f"Blee 2.4: {label} must not be a permanent bottom-nav destination")

    print("============================================================")
    print("VERIFIED: ground-up Blee 2.4 product UI")
    print("- fresh BleeApp + globals.css replace legacy presentation")
    print("- Home / Nearby / Activity / Profile single navigation system")
    print("- Send / confirm / receive / recovery flows remain wired")
    print("- Arc Testnet + USDC only; custom network mutation disabled")
    print("- functional 8-character minimum in create + import paths")
    print("============================================================")


def main() -> None:
    temp, source = decode_bundle()
    try:
        install_ui(source)
        enforce_passphrase()
        verify_arc_only()
        patch_version()
        verify_ui()
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    main()
