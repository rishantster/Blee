#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / "overrides" / "src"
NATIVE_STORE_OVERRIDE = ROOT / "overrides" / "native" / "BleeStorePlugin.java"


def copy_overrides() -> None:
    if not OVERRIDES.exists():
        raise SystemExit("Missing overrides/src")
    for source in OVERRIDES.rglob("*"):
        if source.is_dir():
            continue
        rel = source.relative_to(OVERRIDES)
        target = ROOT / "src" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        print(f"overlay: src/{rel}")


def copy_native_store_override() -> None:
    if not NATIVE_STORE_OVERRIDE.exists():
        raise SystemExit("Missing hardened BleeStorePlugin.java override")
    target = ROOT / "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(NATIVE_STORE_OVERRIDE, target)
    print("overlay: native BleeStorePlugin.java [BLEE_STORE_SAFE_V2]")


def patch_persistence_diagnostics() -> None:
    path = ROOT / "src/lib/persistence.ts"
    text = path.read_text()
    old = 'throw new Error(`Blee SQLite initialization failed: ${detail}`);'
    new = 'throw new Error(detail.startsWith("Blee SQLite") ? detail : `Blee SQLite initialization failed: ${detail}`);'
    if old in text:
        text = text.replace(old, new)
    path.write_text(text)


def add_import(text: str, line: str) -> str:
    if line in text:
        return text
    imports = list(re.finditer(r"^import\s.+?;\s*$", text, flags=re.M))
    if imports:
        end = imports[-1].end()
        return text[:end] + "\n" + line + text[end:]
    return line + "\n" + text


def patch_component() -> None:
    path = ROOT / "src/components/BleeApp.tsx"
    text = path.read_text()
    text = add_import(text, 'import BleeAdvancedSettings from "./BleeAdvancedSettings";')
    text = add_import(text, 'import { getActiveNetwork } from "../lib/networkConfig";')

    if "const configuredNetwork = getActiveNetwork();" not in text:
        patterns = (
            r"(export\s+default\s+function\s+\w*\s*\([^)]*\)\s*\{)",
            r"(function\s+BleeApp\s*\([^)]*\)\s*\{)",
        )
        for pattern in patterns:
            text, count = re.subn(pattern, r"\1\n  const configuredNetwork = getActiveNetwork();", text, count=1)
            if count:
                break
        else:
            raise SystemExit("Could not locate BleeApp component declaration")

    if "<BleeAdvancedSettings />" not in text:
        marker = '<button className="button secondary full lock-button"'
        if marker not in text:
            raise SystemExit("Could not locate Settings insertion point")
        text = text.replace(marker, '<BleeAdvancedSettings />\n\n          ' + marker, 1)

    replacements = {
        "USDC · ARC Testnet": "{configuredNetwork.tokenSymbol} · {configuredNetwork.name}",
        "ARC Testnet · USDC": "{configuredNetwork.name} · {configuredNetwork.tokenSymbol}",
        "USDC on ARC": "Configured EVM rail",
        "This build currently settles USDC on ARC Testnet.": "This build settles the configured payment token on the active network.",
        "Blee 1.0.1 · ARC Testnet": "Blee 1.1 · configurable EVM settlement",
        "Blee 1.0 · ARC Testnet": "Blee 1.1 · configurable EVM settlement",
        "RECEIVE USDC": "RECEIVE TOKEN",
        "SEND USDC": "SEND TOKEN",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    text = text.replace('<strong>ARC Testnet</strong>', '<strong>{configuredNetwork.name}</strong>')
    text = text.replace('<span>USDC</span>', '<span>{configuredNetwork.tokenSymbol}</span>')
    path.write_text(text)


def insert_active_network(text: str) -> str:
    declaration = "const BLEE_ACTIVE_NETWORK: BleeNetwork = getActiveNetwork();"
    if declaration in text:
        return text
    imports = list(re.finditer(r"^import\s.+?;\s*$", text, flags=re.M))
    if imports:
        pos = imports[-1].end()
        return text[:pos] + "\n\n" + declaration + text[pos:]
    return declaration + "\n\n" + text


def replace_string_literal(text: str, literal: str, expression: str) -> tuple[str, int]:
    total = 0
    for quote in ('"', "'"):
        needle = f"{quote}{literal}{quote}"
        count = text.count(needle)
        if count:
            text = text.replace(needle, expression)
            total += count
    return text, total


def replace_last_numeric_arg(text: str, function_name: str, old_value: str, replacement: str) -> tuple[str, int]:
    needle = function_name + "("
    pos = 0
    pieces: list[str] = []
    changed = 0
    while True:
        start = text.find(needle, pos)
        if start < 0:
            pieces.append(text[pos:])
            break
        pieces.append(text[pos:start])
        i = start + len(needle)
        depth = 1
        quote: str | None = None
        escape = False
        while i < len(text) and depth:
            ch = text[i]
            if quote:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == quote:
                    quote = None
            else:
                if ch in ('"', "'", '`'):
                    quote = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
            i += 1
        call = text[start:i]
        rewritten, n = re.subn(rf",\s*{re.escape(old_value)}\s*\)$", f", {replacement})", call, count=1)
        changed += n
        pieces.append(rewritten)
        pos = i
    return "".join(pieces), changed


def scan_call_end(text: str, open_paren: int) -> int:
    depth = 0
    quote: str | None = None
    escape = False
    line_comment = False
    block_comment = False
    i = open_paren
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""

        if line_comment:
            if ch == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                i += 2
                continue
            i += 1
            continue
        if quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
            i += 1
            continue

        if ch == "/" and nxt == "/":
            line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            block_comment = True
            i += 2
            continue
        if ch in ('"', "'", '`'):
            quote = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i + 1
                while end < len(text) and text[end].isspace():
                    end += 1
                if end < len(text) and text[end] == ";":
                    end += 1
                return end
        i += 1
    raise SystemExit("Unbalanced defineChain call in src/lib/arc.ts")


def replace_arc_chain_definition(text: str) -> tuple[str, str]:
    pattern = re.compile(
        r"(?P<prefix>(?:export\s+)?)const\s+(?P<name>[A-Za-z_$][\w$]*)"
        r"(?:\s*:\s*[^=;\n]+)?\s*=\s*defineChain(?:\s*<[^;\n]+?>)?\s*\("
    )
    candidates: list[tuple[re.Match[str], int, str]] = []
    for match in pattern.finditer(text):
        open_paren = text.find("(", match.start(), match.end())
        end = scan_call_end(text, open_paren)
        snippet = text[match.start():end]
        candidates.append((match, end, snippet))

    if not candidates:
        raise SystemExit("Could not locate Arc defineChain declaration")

    selected = None
    for candidate in candidates:
        snippet = candidate[2]
        if any(marker in snippet for marker in ("Arc Testnet", "rpc.testnet.arc.network", "ARC_RPC", "ARC_TESTNET")):
            selected = candidate
            break
    if selected is None and len(candidates) == 1:
        selected = candidates[0]
    if selected is None:
        names = [item[0].group("name") for item in candidates]
        raise SystemExit(f"Could not uniquely identify Arc defineChain declaration. candidates={names}")

    match, end, _ = selected
    prefix = match.group("prefix") or ""
    name = match.group("name")
    replacement = f'''{prefix}const {name} = defineChain({{
  id: BLEE_ACTIVE_NETWORK.chainId,
  name: BLEE_ACTIVE_NETWORK.name,
  nativeCurrency: {{
    name: BLEE_ACTIVE_NETWORK.nativeSymbol,
    symbol: BLEE_ACTIVE_NETWORK.nativeSymbol,
    decimals: 18,
  }},
  rpcUrls: {{
    default: {{ http: [BLEE_ACTIVE_NETWORK.rpcUrl] }},
  }},
  blockExplorers: BLEE_ACTIVE_NETWORK.explorerUrl
    ? {{ default: {{ name: `${{BLEE_ACTIVE_NETWORK.name}} Explorer`, url: BLEE_ACTIVE_NETWORK.explorerUrl }} }}
    : undefined,
  testnet: BLEE_ACTIVE_NETWORK.testnet,
}});'''
    return text[:match.start()] + replacement + text[end:], name


def patch_eip712_domain(text: str) -> tuple[str, bool]:
    name_count = 0
    for literal in ("USDC", "USD Coin"):
        pattern = re.compile(rf"(\bname\s*:\s*)(?:\"{re.escape(literal)}\"|'{re.escape(literal)}')")
        text, n = pattern.subn(r"\1BLEE_ACTIVE_NETWORK.eip712Name", text)
        name_count += n

    version_pattern = re.compile(r"(\bversion\s*:\s*)(?:\"2\"|'2')")
    text, version_count = version_pattern.subn(r"\1BLEE_ACTIVE_NETWORK.eip712Version", text)

    if name_count == 0:
        pattern = re.compile(
            r"((?:export\s+)?const\s+[A-Za-z_$][\w$]*(?:DOMAIN|EIP712)[A-Za-z_$\d]*\s*=\s*)(?:\"(?:USDC|USD Coin)\"|'(?:USDC|USD Coin)')",
            flags=re.I,
        )
        text, name_count = pattern.subn(r"\1BLEE_ACTIVE_NETWORK.eip712Name", text)

    if version_count == 0:
        pattern = re.compile(
            r"((?:export\s+)?const\s+[A-Za-z_$][\w$]*(?:DOMAIN|EIP712)[A-Za-z_$\d]*VERSION[A-Za-z_$\d]*\s*=\s*)(?:\"2\"|'2')",
            flags=re.I,
        )
        text, version_count = pattern.subn(r"\1BLEE_ACTIVE_NETWORK.eip712Version", text)

    dynamic = "BLEE_ACTIVE_NETWORK.eip712Name" in text and "BLEE_ACTIVE_NETWORK.eip712Version" in text
    if dynamic:
        print(f"EIP-712 domain made configurable (name patches={name_count}, version patches={version_count}).")
    else:
        raise SystemExit("Could not safely identify the EIP-712 domain in src/lib/arc.ts")
    return text, dynamic


def patch_arc_runtime() -> None:
    path = ROOT / "src/lib/arc.ts"
    text = path.read_text()
    if "BLEE_NETWORK_STARTUP_PROFILE" in text:
        print("Settlement runtime already uses Blee network selection.")
        return

    text = add_import(text, 'import { getActiveNetwork, type BleeNetwork } from "./networkConfig";')
    text = insert_active_network(text)
    text, chain_name = replace_arc_chain_definition(text)

    text, rpc_count = replace_string_literal(text, "https://rpc.testnet.arc.network", "BLEE_ACTIVE_NETWORK.rpcUrl")
    text, explorer_count = replace_string_literal(text, "https://testnet.arcscan.app", "BLEE_ACTIVE_NETWORK.explorerUrl")
    text, token_count = replace_string_literal(
        text,
        "0x3600000000000000000000000000000000000000",
        "BLEE_ACTIVE_NETWORK.tokenAddress",
    )

    text = re.sub(
        r"(BLEE_ACTIVE_NETWORK\.(?:rpcUrl|explorerUrl|tokenAddress|chainId))\s+as\s+const",
        r"\1",
        text,
    )

    text, eip712_dynamic = patch_eip712_domain(text)
    text, parse_count = replace_last_numeric_arg(text, "parseUnits", "6", "BLEE_ACTIVE_NETWORK.tokenDecimals")
    text, format_count = replace_last_numeric_arg(text, "formatUnits", "6", "BLEE_ACTIVE_NETWORK.tokenDecimals")

    text = text.replace(
        'throw new Error("Arc transaction reverted")',
        'throw new Error("Network transaction reverted")',
    ).replace(
        "throw new Error('Arc transaction reverted')",
        "throw new Error('Network transaction reverted')",
    )

    text += """

// BLEE_NETWORK_STARTUP_PROFILE
// Network changes in Settings reload Blee. Existing viem clients are created
// from the selected profile on each fresh app load.
export function getBleeActiveNetwork() {
  return BLEE_ACTIVE_NETWORK;
}
"""

    required = (
        "BLEE_ACTIVE_NETWORK.chainId",
        "BLEE_ACTIVE_NETWORK.rpcUrl",
        "BLEE_ACTIVE_NETWORK.tokenAddress",
        "BLEE_ACTIVE_NETWORK.eip712Name",
        "BLEE_ACTIVE_NETWORK.eip712Version",
    )
    missing = [item for item in required if item not in text]
    if missing:
        raise SystemExit(f"Dynamic settlement profile incomplete: {missing}")

    path.write_text(text)
    print(
        "Settlement runtime configured from active network:",
        f"chain={chain_name}, rpc_literals={rpc_count}, explorer_literals={explorer_count}, token_literals={token_count}, parseUnits={parse_count}, formatUnits={format_count}, eip712Dynamic={eip712_dynamic}",
    )


def bump_version() -> None:
    package = ROOT / "package.json"
    data = json.loads(package.read_text())
    data["version"] = "1.1.0"
    package.write_text(json.dumps(data, indent=2) + "\n")

    configure = ROOT / "scripts/configure-native.mjs"
    if configure.exists():
        text = configure.read_text()
        text = re.sub(r"versionCode\s+\d+", "versionCode 3", text)
        text = re.sub(r'versionName\s+"[^\"]+"', 'versionName "1.1.0"', text)
        configure.write_text(text)


def main() -> None:
    copy_overrides()
    copy_native_store_override()
    patch_persistence_diagnostics()
    patch_component()
    patch_arc_runtime()
    bump_version()
    print("Blee 1.1 final submission overlays applied.")


if __name__ == "__main__":
    main()
