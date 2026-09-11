#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/components/BleeApp.tsx"
HOOK = ROOT / "src/hooks/useBlee.ts"
CSS = ROOT / "app/globals.css"


def replace_function_body(text: str, name: str, body: str) -> tuple[str, bool]:
    start = text.find(f"function {name}")
    if start < 0:
        return text, False
    paren = text.find("(", start)
    if paren < 0:
        return text, False
    pdepth = 0
    quote = None
    escaped = False
    i = paren
    body_start = -1
    while i < len(text):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
        elif ch == "(":
            pdepth += 1
        elif ch == ")":
            pdepth -= 1
            if pdepth == 0:
                body_start = text.find("{", i + 1)
                break
        i += 1
    if body_start < 0:
        return text, False
    depth = 0
    quote = None
    escaped = False
    i = body_start
    while i < len(text):
        ch = text[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[:body_start] + body + text[i + 1 :], True
        i += 1
    return text, False


def patch_brand_and_product_copy() -> None:
    text = APP.read_text()
    brand_body = '''{
  return (
    <div className="blee-brand-lockup" aria-label="Blee">
      <LogoMark size={30} />
      <BleeWordmark height={25} />
    </div>
  );
}'''
    text, replaced = replace_function_body(text, "Brand", brand_body)
    if not replaced:
        raise SystemExit("Blee 2.3: could not replace Brand() lockup")

    copy_replacements = {
        "PAYMENTS, EVEN WHEN THE INTERNET IS NOT THERE": "OFFLINE-FIRST WALLET",
        "Payments, even when the internet is not there": "Offline-first wallet",
        "Your wallet for nearby and online payments.": "Pay nearby. Settle when connected.",
        "Create a local encrypted wallet. Nearby payments are stored durably and settle when a supported network is available.":
            "Your wallet stays on this phone. Nearby payments persist locally and settle when a supported network becomes available.",
        "Payments that keep moving": "",
    }
    for old, new in copy_replacements.items():
        text = text.replace(old, new)

    for old in ("Blee 2.2", "Blee 2.1.1", "Blee 2.1", "Blee 2.0", "Blee 1.4"):
        text = text.replace(old, "Blee 2.3")

    if "BLEE_UI_2_3" not in text:
        text = "// BLEE_UI_2_3 — structural premium wallet UI\n" + text

    APP.write_text(text)
    print("Blee 2.3: compact centered brand + wallet-first product copy applied")


def patch_passphrase_everywhere() -> None:
    changed = 0
    for path in (ROOT / "src").rglob("*"):
        if path.suffix not in {".ts", ".tsx"} or not path.is_file():
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
            changed += 1
    if changed == 0:
        raise SystemExit("Blee 2.3: passphrase rule was not found in generated source")
    print(f"Blee 2.3: 8-character passphrase rule applied in {changed} generated source file(s)")


def tag_payment_actions() -> None:
    text = APP.read_text()
    button = re.compile(r"<button(?P<attrs>[^>]*)>(?P<body>.*?)</button>", re.S | re.I)
    send_count = 0
    receive_count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal send_count, receive_count
        attrs = match.group("attrs")
        body = match.group("body")
        plain = re.sub(r"<[^>]+>", " ", body)
        combined = f"{attrs} {plain}"
        tag = None
        if re.search(r"\bSend\b", combined, re.I):
            tag = "send"
            send_count += 1
        elif re.search(r"\bReceive\b", combined, re.I):
            tag = "receive"
            receive_count += 1
        if not tag or "data-blee-action=" in attrs:
            return match.group(0)
        return f'<button data-blee-action="{tag}"{attrs}>{body}</button>'

    text = button.sub(repl, text)
    if send_count == 0:
        raise SystemExit("Blee 2.3: generated wallet has no Send button to promote")
    APP.write_text(text)
    print(f"Blee 2.3: tagged payment actions send={send_count}, receive={receive_count}")


def harden_persistent_session() -> None:
    text = HOOK.read_text()
    lock_union = r"(?:logout|logOut|lockWallet|lockSession|clearSession|clearWalletSession|setAccount\(null\)|setWallet\(null\)|setPrivateKey\(null\)|setUnlocked\(false\)|setLocked\(true\))"

    patterns = [
        re.compile(rf"(?P<prefix>(?:[A-Za-z_$][\w$]*(?:\.current)?\s*=\s*)?)setTimeout\(\s*\(\)\s*=>\s*\{{(?P<body>.{{0,2000}}?{lock_union}.{{0,2000}}?)\}}\s*,\s*[^\)]+\)", re.S),
        re.compile(rf"(?P<prefix>(?:[A-Za-z_$][\w$]*(?:\.current)?\s*=\s*)?)setInterval\(\s*\(\)\s*=>\s*\{{(?P<body>.{{0,2000}}?{lock_union}.{{0,2000}}?)\}}\s*,\s*[^\)]+\)", re.S),
        re.compile(r"(?P<prefix>(?:[A-Za-z_$][\w$]*(?:\.current)?\s*=\s*)?)setTimeout\(\s*(?:logout|logOut|lockWallet|lockSession|clearSession|clearWalletSession)\s*,\s*[^\)]+\)", re.S),
    ]
    hits = 0
    for pattern in patterns:
        def remove_timer(match: re.Match[str]) -> str:
            nonlocal hits
            hits += 1
            prefix = match.groupdict().get("prefix") or ""
            if prefix:
                return prefix + "undefined as unknown as ReturnType<typeof setTimeout> /* BLEE_EXPLICIT_LOGOUT_ONLY */"
            return "void 0 /* BLEE_EXPLICIT_LOGOUT_ONLY */"
        text = pattern.sub(remove_timer, text)

    # Neutralize direct visibility/blur lock lines while preserving refresh logic.
    visibility = re.compile(rf"(?m)^(?P<indent>\s*)[^\n]*(?:visibilityState|document\.hidden|addEventListener\(['\"]blur['\"]|window\.onblur)[^\n]*{lock_union}[^\n]*$")
    text, visibility_hits = visibility.subn(r"\g<indent>// BLEE_EXPLICIT_LOGOUT_ONLY: backgrounding never logs out.", text)

    marker = "BLEE_EXPLICIT_LOGOUT_ONLY"
    if marker not in text:
        text = f"// {marker}: wallet remains unlocked until explicit logout while process is alive.\n" + text
    HOOK.write_text(text)
    print(f"Blee 2.3: persistent session hardened timers={hits}, backgroundLocks={visibility_hits}")


def install_css() -> None:
    premium = (ROOT / "mesh-v2/web/premium-monochrome-2.3.css").read_text()
    text = CSS.read_text()
    marker = "/* BLEE_PREMIUM_MONOCHROME_2_3"
    if marker in text:
        text = text[: text.index(marker)]
    text = text.rstrip() + "\n\n" + premium + "\n"
    CSS.write_text(text)
    print("Blee 2.3: premium monochrome design system installed")


def patch_version() -> None:
    package = ROOT / "package.json"
    data = json.loads(package.read_text())
    data["version"] = "2.3.0"
    package.write_text(json.dumps(data, indent=2) + "\n")

    native = ROOT / "scripts/configure-native.mjs"
    if native.exists():
        text = native.read_text()
        text = re.sub(r"versionCode\s+\d+", "versionCode 12", text)
        text = re.sub(r'versionName\s+\"[^\"]+\"', 'versionName "2.3.0"', text)
        native.write_text(text)


def verify() -> None:
    app = APP.read_text()
    hook = HOOK.read_text()
    css = CSS.read_text()
    wallet = (ROOT / "src/lib/walletRecovery.ts").read_text()

    required_app = (
        "BLEE_UI_2_3",
        "blee-brand-lockup",
        "Pay nearby. Settle when connected.",
        'data-blee-action="send"',
        "Blee 2.3",
    )
    missing = [m for m in required_app if m not in app]
    if missing:
        raise SystemExit(f"Blee 2.3 UI verification failed: {missing}")

    joined = app + "\n" + wallet
    if re.search(r"(?i)at\s+least\s+12\s+characters|passphrase\.length\s*<\s*12", joined):
        raise SystemExit("Blee 2.3 verification failed: 12-character passphrase rule/copy remains")
    if not re.search(r"passphrase\.length\s*<\s*8", wallet):
        raise SystemExit("Blee 2.3 verification failed: wallet encryption path is not enforcing 8-character minimum")

    if "BLEE_EXPLICIT_LOGOUT_ONLY" not in hook:
        raise SystemExit("Blee 2.3 verification failed: persistent-session policy missing")

    # Fail if obvious automatic wallet-lock timers survived our rewrite.
    for timer in re.finditer(r"set(?:Timeout|Interval)\((.{0,3500}?)\)", hook, re.S):
        segment = timer.group(1)
        if re.search(r"logout|lockWallet|lockSession|clearWalletSession|setUnlocked\(false\)|setLocked\(true\)", segment):
            raise SystemExit("Blee 2.3 verification failed: inactivity/background wallet-lock timer remains")

    if "BLEE_PREMIUM_MONOCHROME_2_3" not in css:
        raise SystemExit("Blee 2.3 verification failed: premium UI CSS missing")

    package = json.loads((ROOT / "package.json").read_text())
    if package.get("version") != "2.3.0":
        raise SystemExit("Blee 2.3 verification failed: package version mismatch")

    print("============================================================")
    print("VERIFIED: Blee 2.3 product UI + interaction policy")
    print("- centered compact Blee brand lockup")
    print("- wallet-first onboarding copy/layout styling")
    print("- explicit Send action present and tagged")
    print("- passphrase minimum is 8 characters in UI and encryption path")
    print("- no obvious inactivity wallet-lock timer survives")
    print("============================================================")


def main() -> None:
    patch_brand_and_product_copy()
    patch_passphrase_everywhere()
    tag_payment_actions()
    harden_persistent_session()
    install_css()
    patch_version()
    verify()


if __name__ == "__main__":
    main()
