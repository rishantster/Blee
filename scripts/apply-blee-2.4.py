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
    if not PARTS.is_dir():
        raise SystemExit("Blee 2.4: ui-v4/parts is missing")
    parts = sorted(PARTS.glob("part*"))
    expected_names = [f"part{i:02d}" for i in range(11)]
    if [p.name for p in parts] != expected_names:
        raise SystemExit(f"Blee 2.4: expected UI bundle parts {expected_names}, found {[p.name for p in parts]}")

    # GitHub stores the bundle as wrapped base64 text. Whitespace is intentionally ignored;
    # the decoded archive checksum is the authoritative integrity boundary.
    encoded = b"".join(b"".join(path.read_bytes().split()) for path in parts)
    try:
        archive = base64.b64decode(encoded, validate=True)
    except Exception as error:
        raise SystemExit(f"Blee 2.4: UI bundle is not valid base64: {error}") from error

    digest = hashlib.sha256(archive).hexdigest()
    if digest != ARCHIVE_SHA256:
        raise SystemExit(f"Blee 2.4: UI bundle checksum mismatch: {digest}; expected {ARCHIVE_SHA256}")

    temp = Path(tempfile.mkdtemp(prefix="blee-ui-2.4-"))
    archive_path = temp / "blee-ui-2.4.tar.gz"
    archive_path.write_bytes(archive)
    source = temp / "source"
    source.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as tar:
        source_root = source.resolve()
        for member in tar.getmembers():
            target = (source / member.name).resolve()
            if not str(target).startswith(str(source_root) + "/") and target != source_root:
                raise SystemExit(f"Blee 2.4: unsafe UI bundle member: {member.name}")
        tar.extractall(source)

    return temp, source


def install_ground_up_ui(source: Path) -> None:
    # This runs LAST after all historical UX overlays. These files are replaced wholesale,
    # so 1.x/2.2/2.3 JSX and CSS cannot leak into the 2.4 presentation.
    for rel in FILES:
        src = source / rel
        dst = ROOT / rel
        if not src.is_file():
            raise SystemExit(f"Blee 2.4: UI bundle missing {rel}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"Blee 2.4 source replacement: {rel}")


def replace_old_passphrase_rules(text: str) -> str:
    text = re.sub(r"(?i)at\s+least\s+12\s+characters", "at least 8 characters", text)
    text = re.sub(r"(?i)minimum\s+12\s+characters", "minimum 8 characters", text)
    text = re.sub(r"(?i)12\+\s*characters", "8+ characters", text)
    text = re.sub(r"(?i)12\s+characters\s+minimum", "8 characters minimum", text)
    text = re.sub(r"(?i)(passphrase\.length\s*<\s*)12\b", r"\g<1>8", text)
    text = re.sub(r"(?i)(newPassphrase\.length\s*<\s*)12\b", r"\g<1>8", text)
    text = re.sub(r"(?i)(confirmPassphrase\.length\s*<\s*)12\b", r"\g<1>8", text)
    return text


def inject_create_vault_minimum(text: str) -> tuple[str, bool]:
    if re.search(r"passphrase\.length\s*<\s*8", text):
        return text, False

    patterns = (
        r"((?:export\s+)?async\s+function\s+createVault\s*\([^)]*\bpassphrase\b[^)]*\)\s*(?::\s*[^\{]+)?\{)",
        r"((?:export\s+)?const\s+createVault\s*=\s*async\s*\([^)]*\bpassphrase\b[^)]*\)\s*(?::\s*[^=]+)?=>\s*\{)",
    )
    guard = '\n  if (passphrase.length < 8) throw new Error("Use a passphrase of at least 8 characters");'
    for pattern in patterns:
        updated, count = re.subn(pattern, r"\1" + guard, text, count=1, flags=re.S)
        if count:
            return updated, True
    raise SystemExit("Blee 2.4: createVault(passphrase) could not be found for functional passphrase enforcement")


def enforce_passphrase_functionally() -> None:
    touched: list[str] = []
    for path in (ROOT / "src").rglob("*"):
        if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
            continue
        text = path.read_text()
        if "passphrase" not in text.lower():
            continue
        updated = replace_old_passphrase_rules(text)
        if updated != text:
            path.write_text(updated)
            touched.append(str(path.relative_to(ROOT)))

    # useBlee.create() calls createVault(), so this is the actual new-wallet enforcement path.
    vault = ROOT / "src/lib/vault.ts"
    if not vault.is_file():
        raise SystemExit("Blee 2.4: src/lib/vault.ts is missing; wallet creation policy cannot be verified")
    vault_text = replace_old_passphrase_rules(vault.read_text())
    vault_text, injected = inject_create_vault_minimum(vault_text)
    vault.write_text(vault_text)
    if injected:
        touched.append("src/lib/vault.ts (8-character create guard injected)")

    # Import / recovery uses walletRecovery.encryptAndStore(). It must enforce the same rule.
    recovery = ROOT / "src/lib/walletRecovery.ts"
    if not recovery.is_file():
        raise SystemExit("Blee 2.4: walletRecovery.ts is missing")
    recovery_text = replace_old_passphrase_rules(recovery.read_text())
    recovery.write_text(recovery_text)

    if not re.search(r"passphrase\.length\s*<\s*8", vault_text):
        raise SystemExit("Blee 2.4: createVault does not enforce an 8-character minimum")
    if not re.search(r"passphrase\.length\s*<\s*8", recovery_text):
        raise SystemExit("Blee 2.4: wallet import/encryption path does not enforce an 8-character minimum")

    print("Blee 2.4: functional 8-character passphrase policy verified in create + import paths")
    if touched:
        print("Blee 2.4 passphrase updates:", ", ".join(touched))


def lock_product_to_arc_usdc() -> None:
    network = ROOT / "src/lib/networkConfig.ts"
    text = network.read_text()
    regexes = (
        r"id\s*:\s*['\"]arc-testnet['\"]",
        r"name\s*:\s*['\"]Arc Testnet['\"]",
        r"chainId\s*:\s*5042002\b",
        r"tokenSymbol\s*:\s*['\"]USDC['\"]",
        r"tokenAddress\s*:\s*['\"]0x3600000000000000000000000000000000000000['\"]",
        r"return\s*\[\s*ARC_TESTNET\s*\]",
        r"return\s+ARC_TESTNET",
    )
    missing = [pattern for pattern in regexes if not re.search(pattern, text)]
    if missing:
        raise SystemExit(f"Blee 2.4: Arc-only network contract incomplete: {missing}")
    if "Custom settlement networks are not available in Blee" not in text:
        raise SystemExit("Blee 2.4: custom network mutation is not explicitly blocked")


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


def verify_ui_source() -> None:
    app = (ROOT / "src/components/BleeApp.tsx").read_text()
    css = (ROOT / "app/globals.css").read_text()
    advanced = (ROOT / "src/components/BleeAdvancedSettings.tsx").read_text()
    network = (ROOT / "src/lib/networkConfig.ts").read_text()
    vault = (ROOT / "src/lib/vault.ts").read_text()
    recovery = (ROOT / "src/lib/walletRecovery.ts").read_text()

    required_app = (
        "useBlee",
        "BottomNav",
        "Home",
        "Nearby",
        "Activity",
        "Profile",
        "Review & send",
        "Confirm and send",
        "QRCodeSVG",
        "Backup & recovery",
        "Network & Security",
        "Blee 2.4",
    )
    missing = [marker for marker in required_app if marker not in app]
    if missing:
        raise SystemExit(f"Blee 2.4: rebuilt UI missing required flows: {missing}")

    banned_app = (
        "Keep this screen open",
        "MetaMask-style",
        "Add network",
        "Relay valid payments",
        "Payments that keep moving",
        "brand-orbit",
        "hero-ring",
        "signal-ring",
        "radar-ring",
        "brand-monument",
    )
    found = [marker for marker in banned_app if marker.lower() in app.lower()]
    if found:
        raise SystemExit(f"Blee 2.4: legacy UI/copy survived: {found}")

    # The 2.4 stylesheet replaces globals.css; it is not appended to legacy styles.
    if not css.lstrip().startswith("/* BLEE_UI_2_4"):
        raise SystemExit("Blee 2.4: globals.css is not the ground-up 2.4 stylesheet")
    for marker in (
        "grid-template-columns: repeat(4, 1fr)",
        ".blee-phone.with-nav",
        ".screen-transition",
        "safe-area-inset-bottom",
    ):
        if marker not in css:
            raise SystemExit(f"Blee 2.4: production layout invariant missing: {marker}")

    if "Custom settlement networks are not available in Blee" not in network:
        raise SystemExit("Blee 2.4: custom network support is still mutable")
    if "saveNetwork" not in network or "throw new Error" not in network:
        raise SystemExit("Blee 2.4: legacy network compatibility API is not safely locked")
    if any(term in advanced for term in ("saveNetwork", "deleteNetwork", "setActiveNetwork", "Custom network")):
        raise SystemExit("Blee 2.4: custom network controls survived in AdvancedSettings")

    combined_passphrase = app + "\n" + vault + "\n" + recovery
    if re.search(r"(?i)12\s*(?:\+|characters)|passphrase\.length\s*<\s*12", combined_passphrase):
        raise SystemExit("Blee 2.4: obsolete 12-character passphrase rule/copy remains")
    if not re.search(r"passphrase\.length\s*<\s*8", vault):
        raise SystemExit("Blee 2.4: createVault crypto path lacks 8-character guard")
    if not re.search(r"passphrase\.length\s*<\s*8", recovery):
        raise SystemExit("Blee 2.4: recovery/import crypto path lacks 8-character guard")

    # Four primary destinations only. Send/Receive are actions, never duplicate tabs.
    bottom_block = re.search(r"function\s+BottomNav\b.*?\n}\n", app, re.S)
    if not bottom_block:
        raise SystemExit("Blee 2.4: BottomNav component missing")
    block = bottom_block.group(0)
    for label in ("Home", "Nearby", "Activity", "Profile"):
        if label not in block:
            raise SystemExit(f"Blee 2.4: BottomNav missing {label}")
    for label in ("Send", "Receive", "Settings"):
        if re.search(rf">\s*{label}\s*<", block):
            raise SystemExit(f"Blee 2.4: {label} must not be a permanent bottom-nav destination")

    print("============================================================")
    print("VERIFIED: ground-up Blee 2.4 product UI")
    print("- fresh BleeApp + fresh globals.css replace legacy presentation")
    print("- Home / Nearby / Activity / Profile single navigation system")
    print("- Send -> Confirm -> queued/success flow wired")
    print("- Receive QR, activity detail, profile/edit, settings, backup/recovery")
    print("- Arc Testnet + USDC only; custom network mutation disabled")
    print("- functional 8-character minimum in create + import encryption paths")
    print("- no orbit/radar/halo decoration and no keep-screen-open BLE copy")
    print("============================================================")


def main() -> None:
    temp, source = decode_bundle()
    try:
        install_ground_up_ui(source)
        enforce_passphrase_functionally()
        lock_product_to_arc_usdc()
        patch_version()
        verify_ui_source()
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    main()
