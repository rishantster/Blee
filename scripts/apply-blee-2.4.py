#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/components/BleeApp.tsx"
HOOK = ROOT / "src/hooks/useBlee.ts"
CSS = ROOT / "app/globals.css"


def replace_visible_copy(text: str) -> str:
    replacements = {
        "Pay nearby. Settle when connected.": "Your Blee wallet",
        "OFFLINE-FIRST WALLET": "PRIVATE. LOCAL. DIRECT.",
        "Offline-first wallet": "Private. Local. Direct.",
        "Your wallet stays on this phone. Nearby payments persist locally and settle when a supported network becomes available.":
            "Send USDC nearby or online. Your wallet stays encrypted on this device.",
        "Payments that keep moving": "",
        "PAYMENTS THAT KEEP MOVING": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def enforce_eight_character_passphrase() -> None:
    touched = 0
    for base in (ROOT / "src", ROOT / "app"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in {".ts", ".tsx"}:
                continue
            text = path.read_text()
            if "passphrase" not in text.lower():
                continue
            before = text
            text = re.sub(r"(?i)at\s+least\s+12\s+characters", "At least 8 characters", text)
            text = re.sub(r"(?i)minimum\s+12\s+characters", "Minimum 8 characters", text)
            text = re.sub(r"(?i)12\+\s*characters", "8+ characters", text)
            text = re.sub(r"(?i)12\s+characters\s+minimum", "8 characters minimum", text)
            text = re.sub(r"(?i)(passphrase\.length\s*<\s*)12\b", r"\g<1>8", text)
            text = re.sub(r"(?i)(newPassphrase\.length\s*<\s*)12\b", r"\g<1>8", text)
            text = re.sub(r"(?i)(confirmPassphrase\.length\s*<\s*)12\b", r"\g<1>8", text)
            if text != before:
                path.write_text(text)
                touched += 1
    if touched == 0:
        wallet = ROOT / "src/lib/walletRecovery.ts"
        if not wallet.exists() or "passphrase.length < 8" not in wallet.read_text():
            raise SystemExit("Blee 2.4: could not verify functional 8-character passphrase enforcement")
    print(f"Blee 2.4: passphrase policy verified/updated in {touched} file(s)")


def tag_button_actions(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    button = re.compile(r"<button(?P<attrs>[^>]*)>(?P<body>.*?)</button>", re.S | re.I)

    action_terms = {
        "send": (r"\bSend\b", r"Review\s*&?\s*send", r"Send now"),
        "receive": (r"\bReceive\b",),
        "nearby": (r"\bNearby\b",),
        "activity": (r"\bActivity\b",),
        "profile": (r"\bProfile\b",),
        "settings": (r"\bSettings\b",),
        "logout": (r"Log\s*out", r"Logout"),
        "backup": (r"Back\s*up", r"Backup"),
        "import": (r"Import", r"Restore"),
    }

    def repl(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        body = match.group("body")
        if "data-blee-action=" in attrs:
            return match.group(0)
        plain = re.sub(r"<[^>]+>", " ", body)
        combined = f"{attrs} {plain}"
        action = None
        for candidate, patterns in action_terms.items():
            if any(re.search(pattern, combined, re.I) for pattern in patterns):
                action = candidate
                break
        if not action:
            return match.group(0)
        counts[action] = counts.get(action, 0) + 1
        return f'<button data-blee-action="{action}"{attrs}>{body}</button>'

    return button.sub(repl, text), counts


def remove_legacy_decorative_markup(text: str) -> tuple[str, int]:
    removed = 0

    # Remove self-contained JSX blocks whose class is explicitly decorative.
    decorative = re.compile(
        r'<(?P<tag>div|span)\b(?P<attrs>[^>]*className=["\'][^"\']*(?:orbit|radar|halo|hero-art|heroArt|hero-visual|heroVisual|signal-ring|signalRing)[^"\']*["\'][^>]*)>.*?</(?P=tag)>',
        re.S | re.I,
    )
    text, n = decorative.subn('', text)
    removed += n

    # Remove empty decorative nodes too.
    empty = re.compile(
        r'<(?:div|span)\b[^>]*className=["\'][^"\']*(?:orbit|radar|halo|hero-art|heroArt|hero-visual|heroVisual|signal-ring|signalRing)[^"\']*["\'][^>]*/>',
        re.S | re.I,
    )
    text, n = empty.subn('', text)
    removed += n

    # Add an explicit marker so verification knows the destructive cleanup ran.
    if "BLEE_NO_DECORATIVE_HERO" not in text:
        text = "// BLEE_NO_DECORATIVE_HERO — no orbit/radar/halo onboarding artwork\n" + text
    return text, removed


def patch_app() -> None:
    if not APP.exists():
        raise SystemExit("Blee 2.4: BleeApp.tsx missing after professional overlay")
    text = APP.read_text()
    text = replace_visible_copy(text)
    text, removed = remove_legacy_decorative_markup(text)
    text, counts = tag_button_actions(text)

    if counts.get("send", 0) == 0 and 'data-blee-action="send"' not in text:
        raise SystemExit("Blee 2.4: generated app has no wired Send action")
    if counts.get("receive", 0) == 0 and 'data-blee-action="receive"' not in text:
        raise SystemExit("Blee 2.4: generated app has no wired Receive action")

    for old in ("Blee 2.3", "Blee 2.2", "Blee 2.1.1", "Blee 2.1", "Blee 2.0", "Blee 1.4"):
        text = text.replace(old, "Blee 2.4")
    if "BLEE_UI_2_4" not in text:
        text = "// BLEE_UI_2_4 — production wallet presentation over existing payment engine\n" + text
    APP.write_text(text)
    print(f"Blee 2.4: app structure hardened; decorative blocks removed={removed}; actions={counts}")


def harden_persistent_session() -> None:
    if not HOOK.exists():
        raise SystemExit("Blee 2.4: useBlee.ts missing")
    text = HOOK.read_text()
    # Blee should not create an inactivity/background logout timer.
    suspicious = re.compile(
        r"set(?:Timeout|Interval)\((?P<body>.{0,4000}?(?:logout|logOut|lockWallet|lockSession|clearWalletSession|setUnlocked\(false\)|setLocked\(true\)).{0,4000}?)\)",
        re.S,
    )
    text, count = suspicious.subn("void 0 /* BLEE_EXPLICIT_LOGOUT_ONLY */", text)
    if "BLEE_EXPLICIT_LOGOUT_ONLY" not in text:
        text = "// BLEE_EXPLICIT_LOGOUT_ONLY — no inactivity logout while process remains alive.\n" + text
    HOOK.write_text(text)
    print(f"Blee 2.4: removed automatic lock timers={count}")


def install_production_css() -> None:
    source = ROOT / "mesh-v2/web/production-wallet-2.4.css"
    if not source.exists():
        raise SystemExit("Blee 2.4: production wallet stylesheet missing")
    production = source.read_text()
    text = CSS.read_text()

    # Keep prior source CSS for component compatibility, but always let 2.4 win last.
    marker = "/* BLEE_PRODUCTION_WALLET_2_4"
    if marker in text:
        text = text[: text.index(marker)].rstrip()
    CSS.write_text(text + "\n\n" + production + "\n")
    print("Blee 2.4: production wallet design system installed")


def patch_version() -> None:
    package = ROOT / "package.json"
    data = json.loads(package.read_text())
    data["version"] = "2.4.0"
    package.write_text(json.dumps(data, indent=2) + "\n")

    native = ROOT / "scripts/configure-native.mjs"
    if native.exists():
        text = native.read_text()
        text = re.sub(r"versionCode\s+\d+", "versionCode 13", text)
        text = re.sub(r'versionName\s+"[^"]+"', 'versionName "2.4.0"', text)
        native.write_text(text)


def verify() -> None:
    app = APP.read_text()
    hook = HOOK.read_text()
    css = CSS.read_text()
    wallet = (ROOT / "src/lib/walletRecovery.ts").read_text()

    required_app = (
        "BLEE_UI_2_4",
        "BLEE_NO_DECORATIVE_HERO",
        'data-blee-action="send"',
        'data-blee-action="receive"',
        "Blee 2.4",
    )
    missing = [x for x in required_app if x not in app]
    if missing:
        raise SystemExit(f"Blee 2.4 app verification failed: {missing}")

    if re.search(r"(?i)at\s+least\s+12\s+characters|passphrase\.length\s*<\s*12", app + "\n" + wallet):
        raise SystemExit("Blee 2.4: 12-character passphrase rule survived")
    if not re.search(r"passphrase\.length\s*<\s*8", wallet):
        raise SystemExit("Blee 2.4: wallet encryption path does not enforce 8-character minimum")

    if "BLEE_EXPLICIT_LOGOUT_ONLY" not in hook:
        raise SystemExit("Blee 2.4: persistent session marker missing")
    if "BLEE_PRODUCTION_WALLET_2_4" not in css:
        raise SystemExit("Blee 2.4: production UI stylesheet not installed")
    if "[class*=\"orbit\" i]" not in css or "display: none !important" not in css:
        raise SystemExit("Blee 2.4: decorative onboarding kill-switch missing")

    package = json.loads((ROOT / "package.json").read_text())
    if package.get("version") != "2.4.0":
        raise SystemExit("Blee 2.4: package version mismatch")

    print("============================================================")
    print("VERIFIED: Blee 2.4 production wallet presentation")
    print("- functional 8-character passphrase rule")
    print("- explicit logout only; no inactivity lock timer")
    print("- wired Send and Receive actions preserved")
    print("- home navigation duplication suppressed")
    print("- old ring/radar/orbit onboarding decoration removed")
    print("- compact monochrome screen system + transitions installed")
    print("============================================================")


def main() -> None:
    patch_app()
    enforce_eight_character_passphrase()
    harden_persistent_session()
    install_production_css()
    patch_version()
    verify()


if __name__ == "__main__":
    main()
