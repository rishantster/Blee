#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch_atomic_bridge() -> None:
    path = ROOT / "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java"
    text = path.read_text()

    helper = '''
    private static Long readLong(PluginCall call, String key) {
        try {
            Object raw = call.getData().opt(key);
            if (raw == null || raw == JSONObject.NULL) return null;
            if (raw instanceof Number) return ((Number) raw).longValue();
            String value = String.valueOf(raw).trim();
            if (value.isEmpty()) return null;
            if (value.indexOf('.') >= 0 || value.indexOf('e') >= 0 || value.indexOf('E') >= 0) {
                return (long) Double.parseDouble(value);
            }
            return Long.parseLong(value);
        } catch (Throwable ignored) {
            return null;
        }
    }
'''
    if "private static Long readLong(PluginCall call, String key)" not in text:
        anchor = '''    private static String require(PluginCall call, String key) {
        String value = call.getString(key);
        if (value == null || value.trim().isEmpty()) throw new IllegalArgumentException("Missing " + key);
        return value;
    }
'''
        if anchor not in text:
            raise SystemExit("Blee 2.2: atomic bridge require() anchor not found")
        text = text.replace(anchor, anchor + helper, 1)

    for old, new in (
        ('Long chain = call.getLong("chainId");', 'Long chain = readLong(call, "chainId");'),
        ('Long expiresAt = call.getLong("expiresAt");', 'Long expiresAt = readLong(call, "expiresAt");'),
        ('Long minTxNonce = call.getLong("minTxNonce");', 'Long minTxNonce = readLong(call, "minTxNonce");'),
    ):
        if old in text:
            text = text.replace(old, new, 1)

    text = text.replace("BLEE_STORE_MESH_V2_ATOMIC_SIGNING_V1", "BLEE_STORE_MESH_V2_ATOMIC_SIGNING_V2")
    path.write_text(text)
    print("Blee 2.2: Capacitor numeric bridge hardened for atomic signing")


def patch_atomic_signing() -> None:
    path = ROOT / "src/lib/atomicSigning.ts"
    text = path.read_text()

    text = text.replace("chainId: number;\n    sender:", "chainId: number | string;\n    sender:")
    text = text.replace("expiresAt: number;\n    minTxNonce?: number;", "expiresAt: number | string;\n    minTxNonce?: number | string;")
    text = text.replace("chainId: arcTestnet.id,\n      sender:", "chainId: String(arcTestnet.id),\n      sender:")
    text = text.replace("expiresAt: Number(validBefore) * 1000,", "expiresAt: String(Number(validBefore) * 1000),")
    text = text.replace(
        "...(profile ? { minTxNonce: Math.max(profile.chainNonce, profile.nextNonce) } : {}),",
        "...(profile ? { minTxNonce: String(Math.max(profile.chainNonce, profile.nextNonce)) } : {}),",
    )

    marker = "BLEE_ATOMIC_BRIDGE_STRING_NUMERICS"
    if marker not in text:
        text += f"\n// {marker}\n"
    path.write_text(text)
    print("Blee 2.2: atomic signing bridge uses lossless string numerics")


def patch_passphrase() -> None:
    candidates = [
        ROOT / "src/lib/walletRecovery.ts",
        ROOT / "src/components/BleeApp.tsx",
        ROOT / "src/hooks/useBlee.ts",
    ]
    replacements = (
        ("passphrase.length < 12", "passphrase.length < 8"),
        ("newPassphrase.length < 12", "newPassphrase.length < 8"),
        ("at least 12 characters", "at least 8 characters"),
        ("minimum 12 characters", "minimum 8 characters"),
        ("12+ characters", "8+ characters"),
        ("12 characters minimum", "8 characters minimum"),
    )
    changed = 0
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text()
        before = text
        for old, new in replacements:
            text = text.replace(old, new)
        text = re.sub(r"(passphrase\.length\s*<\s*)12\b", r"\g<1>8", text)
        text = re.sub(r"(newPassphrase\.length\s*<\s*)12\b", r"\g<1>8", text)
        if text != before:
            path.write_text(text)
            changed += 1
    if changed == 0:
        raise SystemExit("Blee 2.2: could not locate passphrase minimum")
    print(f"Blee 2.2: passphrase minimum reduced to 8 characters in {changed} file(s)")


def patch_persistent_session() -> None:
    path = ROOT / "src/hooks/useBlee.ts"
    text = path.read_text()

    # Remove only timers whose callback clearly performs wallet/session locking.
    # Retry, networking, reconciliation and UI timers are deliberately untouched.
    lock_terms = (
        r"logout", r"logOut", r"lockWallet", r"lockSession", r"clearSession",
        r"clearWalletSession", r"setAccount\(null\)", r"setWallet\(null\)",
        r"setPrivateKey\(null\)", r"setUnlocked\(false\)", r"setLocked\(true\)",
    )
    lock_union = "(?:" + "|".join(lock_terms) + ")"

    timer_pattern = re.compile(
        rf"(?P<prefix>(?:[A-Za-z_$][\w$]*(?:\.current)?\s*=\s*)?)setTimeout\(\s*\(\)\s*=>\s*\{{(?P<body>.{{0,1600}}?{lock_union}.{{0,1600}}?)\}}\s*,\s*(?P<delay>[^\)]+)\)",
        re.S,
    )
    timer_hits = 0
    def replace_timer(match: re.Match[str]) -> str:
        nonlocal timer_hits
        timer_hits += 1
        prefix = match.group("prefix")
        if prefix:
            return prefix + "undefined as unknown as ReturnType<typeof setTimeout> /* BLEE_PERSISTENT_SESSION */"
        return "void 0 /* BLEE_PERSISTENT_SESSION */"
    text = timer_pattern.sub(replace_timer, text)

    interval_pattern = re.compile(
        rf"(?P<prefix>(?:[A-Za-z_$][\w$]*(?:\.current)?\s*=\s*)?)setInterval\(\s*\(\)\s*=>\s*\{{(?P<body>.{{0,1600}}?{lock_union}.{{0,1600}}?)\}}\s*,\s*(?P<delay>[^\)]+)\)",
        re.S,
    )
    interval_hits = 0
    def replace_interval(match: re.Match[str]) -> str:
        nonlocal interval_hits
        interval_hits += 1
        prefix = match.group("prefix")
        if prefix:
            return prefix + "undefined as unknown as ReturnType<typeof setInterval> /* BLEE_PERSISTENT_SESSION */"
        return "void 0 /* BLEE_PERSISTENT_SESSION */"
    text = interval_pattern.sub(replace_interval, text)

    # Direct callback forms such as setTimeout(lockWallet, IDLE_MS).
    direct_pattern = re.compile(
        r"(?P<prefix>(?:[A-Za-z_$][\w$]*(?:\.current)?\s*=\s*)?)setTimeout\(\s*(?:logout|logOut|lockWallet|lockSession|clearSession|clearWalletSession)\s*,\s*[^\)]+\)",
    )
    direct_hits = 0
    def replace_direct(match: re.Match[str]) -> str:
        nonlocal direct_hits
        direct_hits += 1
        prefix = match.group("prefix")
        if prefix:
            return prefix + "undefined as unknown as ReturnType<typeof setTimeout> /* BLEE_PERSISTENT_SESSION */"
        return "void 0 /* BLEE_PERSISTENT_SESSION */"
    text = direct_pattern.sub(replace_direct, text)

    # Backgrounding the app may still trigger refresh/reconciliation. Only a
    # same-line explicit lock/logout action is removed.
    visibility_pattern = re.compile(
        rf"(?P<line>[^\n]*(?:visibilityState|document\.hidden|window\.blur|addEventListener\(['\"]blur['\"])[^\n]*{lock_union}[^\n]*\n)",
        re.I,
    )
    visibility_hits = 0
    def neutralize_visibility(match: re.Match[str]) -> str:
        nonlocal visibility_hits
        visibility_hits += 1
        indent = re.match(r"\s*", match.group("line")).group(0)
        return indent + "// BLEE_PERSISTENT_SESSION: backgrounding does not log the user out.\n"
    text = visibility_pattern.sub(neutralize_visibility, text)

    marker = "BLEE_PERSISTENT_SESSION: explicit logout only; no inactivity auto-lock."
    if marker not in text:
        text = f"// {marker}\n" + text

    path.write_text(text)
    print(
        "Blee 2.2: persistent session policy applied",
        f"timeouts={timer_hits}, intervals={interval_hits}, directTimers={direct_hits}, visibilityLocks={visibility_hits}",
    )


def patch_premium_ui() -> None:
    css_source = ROOT / "mesh-v2/web/premium-monochrome.css"
    css_target = ROOT / "app/globals.css"
    premium = css_source.read_text()
    text = css_target.read_text()
    marker = "/* BLEE_PREMIUM_MONOCHROME_2_2 */"
    if marker in text:
        text = text[: text.index(marker)]
    text = text.rstrip() + "\n\n" + marker + "\n" + premium + "\n"
    css_target.write_text(text)

    app = ROOT / "src/components/BleeApp.tsx"
    app_text = app.read_text()
    for old in ("Blee 2.1.1", "Blee 2.1", "Blee 2.0", "Blee 1.4", "Blee 1.3"):
        app_text = app_text.replace(old, "Blee 2.2")
    app_text = app_text.replace("#dc2626", "#111111").replace("#16a34a", "#111111").replace("#ef4444", "#111111")
    app.write_text(app_text)
    print("Blee 2.2: premium monochrome UI system applied across screens")


def patch_package_version() -> None:
    package = ROOT / "package.json"
    data = json.loads(package.read_text())
    data["version"] = "2.2.0"
    package.write_text(json.dumps(data, indent=2) + "\n")

    native = ROOT / "scripts/configure-native.mjs"
    if native.exists():
        text = native.read_text()
        text = re.sub(r"versionCode\s+\d+", "versionCode 11", text)
        text = re.sub(r'versionName\s+\"[^\"]+\"', 'versionName "2.2.0"', text)
        native.write_text(text)


def verify() -> None:
    store = (ROOT / "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java").read_text()
    atomic = (ROOT / "src/lib/atomicSigning.ts").read_text()
    wallet = (ROOT / "src/lib/walletRecovery.ts").read_text()
    hook = (ROOT / "src/hooks/useBlee.ts").read_text()
    css = (ROOT / "app/globals.css").read_text()

    required = {
        "store": ("readLong(PluginCall call, String key)", "BLEE_STORE_MESH_V2_ATOMIC_SIGNING_V2"),
        "atomic": ("BLEE_ATOMIC_BRIDGE_STRING_NUMERICS", 'chainId: String(arcTestnet.id)'),
        "wallet": ("passphrase.length < 8", "at least 8 characters"),
        "hook": ("BLEE_PERSISTENT_SESSION",),
        "css": ("BLEE_PREMIUM_MONOCHROME_2_2", "--blee-bg", "premium monochrome"),
    }
    blobs = {"store": store, "atomic": atomic, "wallet": wallet, "hook": hook, "css": css}
    for name, markers in required.items():
        missing = [marker for marker in markers if marker not in blobs[name]]
        if missing:
            raise SystemExit(f"Blee 2.2 verification failed for {name}: {missing}")

    if "passphrase.length < 12" in wallet or "at least 12 characters" in wallet:
        raise SystemExit("Blee 2.2 verification: old 12-character passphrase rule remains")

    package = json.loads((ROOT / "package.json").read_text())
    if package.get("version") != "2.2.0":
        raise SystemExit("Blee 2.2 package version mismatch")

    print("Blee 2.2 web/product hardening verified.")


def main() -> None:
    patch_atomic_bridge()
    patch_atomic_signing()
    patch_passphrase()
    patch_persistent_session()
    patch_premium_ui()
    patch_package_version()
    verify()


if __name__ == "__main__":
    main()
