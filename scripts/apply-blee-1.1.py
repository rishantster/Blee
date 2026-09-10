#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / "overrides"


def copy_overrides() -> None:
    src = OVERRIDES / "src"
    if not src.exists():
        raise SystemExit("Missing overrides/src")
    for path in src.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(src)
        target = ROOT / "src" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        print(f"overlay: src/{rel}")


def add_import(text: str, line: str) -> str:
    if line in text:
        return text
    imports = list(re.finditer(r"^import\s.+?;\s*$", text, flags=re.M))
    if not imports:
        return line + "\n" + text
    end = imports[-1].end()
    return text[:end] + "\n" + line + text[end:]


def patch_component() -> None:
    path = ROOT / "src/components/BleeApp.tsx"
    text = path.read_text()
    text = add_import(text, 'import BleeAdvancedSettings from "./BleeAdvancedSettings";')
    text = add_import(text, 'import { getActiveNetwork } from "../lib/networkConfig";')

    if "const configuredNetwork = getActiveNetwork();" not in text:
        patterns = [
            r"(export\s+default\s+function\s+\w*\s*\([^)]*\)\s*\{)",
            r"(function\s+BleeApp\s*\([^)]*\)\s*\{)",
        ]
        for pattern in patterns:
            updated, count = re.subn(pattern, r"\1\n  const configuredNetwork = getActiveNetwork();", text, count=1)
            if count:
                text = updated
                break
        else:
            raise SystemExit("Could not locate BleeApp component declaration")

    if "<BleeAdvancedSettings />" not in text:
        marker = '<button className="button secondary full lock-button"'
        if marker not in text:
            raise SystemExit("Could not locate profile lock button for advanced settings insertion")
        text = text.replace(marker, '<BleeAdvancedSettings />\n\n          ' + marker, 1)

    replacements = {
        "USDC · ARC Testnet": "{configuredNetwork.tokenSymbol} · {configuredNetwork.name}",
        "ARC Testnet · USDC": "{configuredNetwork.name} · {configuredNetwork.tokenSymbol}",
        "USDC on ARC": "Configured EVM rail",
        "This build currently settles USDC on ARC Testnet.": "This build settles the configured payment token on the active network.",
        "Blee 1.0.1 · ARC Testnet": "Blee 1.1 · configurable EVM settlement",
        "Blee 1.0 · ARC Testnet": "Blee 1.1 · configurable EVM settlement",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    text = text.replace('<strong>ARC Testnet</strong>', '<strong>{configuredNetwork.name}</strong>')
    text = text.replace('<span>USDC</span>', '<span>{configuredNetwork.tokenSymbol}</span>')
    text = text.replace('RECEIVE USDC', 'RECEIVE TOKEN')
    text = text.replace('SEND USDC', 'SEND TOKEN')
    path.write_text(text)


def _find_literal_decl(text: str, literal: str) -> tuple[int, int, str]:
    pattern = re.compile(
        rf'(?P<prefix>(?:export\s+)?)const\s+(?P<name>[A-Za-z_$][\w$]*)'
        rf'(?:\s*:\s*[^=;\n]+)?\s*=\s*["\']{re.escape(literal)}["\'](?:\s+as\s+const)?\s*;?'
    )
    match = pattern.search(text)
    if not match:
        raise SystemExit(f"Could not find declaration for {literal}")
    return match.start(), match.end(), match.group("name")


def _scan_call_end(text: str, open_paren: int) -> int:
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
    raise SystemExit("Unbalanced function call while patching network runtime")


def _find_call_assignment(
    text: str,
    callee: str,
    must_contain: tuple[str, ...] = (),
    any_of: tuple[str, ...] = (),
) -> tuple[int, int, str]:
    pattern = re.compile(
        rf'(?P<prefix>(?:export\s+)?)const\s+(?P<name>[A-Za-z_$][\w$]*)'
        rf'(?:\s*:\s*[^=;\n]+)?\s*=\s*{re.escape(callee)}(?:\s*<[^;\n]+?>)?\s*\('
    )
    inspected: list[str] = []
    for match in pattern.finditer(text):
        open_paren = text.find("(", match.start(), match.end())
        end = _scan_call_end(text, open_paren)
        snippet = text[match.start():end]
        inspected.append(match.group("name"))
        if not all(needle in snippet for needle in must_contain):
            continue
        if any_of and not any(marker in snippet for marker in any_of):
            continue
        return match.start(), end, match.group("name")
    detail = f" candidates={inspected}" if inspected else " no candidates found"
    raise SystemExit(f"Could not locate {callee} assignment.{detail}")


def _replace_call_numeric_arg(text: str, func: str, old_value: str, replacement: str) -> str:
    needle = func + "("
    pos = 0
    out: list[str] = []
    while True:
        start = text.find(needle, pos)
        if start < 0:
            out.append(text[pos:])
            break
        out.append(text[pos:start])
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
        call = re.sub(rf',\s*{re.escape(old_value)}\s*\)$', f', {replacement})', call)
        out.append(call)
        pos = i
    return "".join(out)


def _decl_prefix(snippet: str) -> str:
    return "export " if re.match(r"\s*export\s+", snippet) else ""


def _replace_literal_decl(text: str, literal: str, expression: str) -> tuple[str, str]:
    start, end, name = _find_literal_decl(text, literal)
    prefix = _decl_prefix(text[start:end])
    replacement = f"{prefix}const {name} = {expression};"
    return text[:start] + replacement + text[end:], name


def _insert_startup_network(text: str) -> str:
    marker = "const BLEE_ACTIVE_NETWORK: BleeNetwork = getActiveNetwork();"
    if marker in text:
        return text
    imports = list(re.finditer(r"^import\s.+?;\s*$", text, flags=re.M))
    if not imports:
        return marker + "\n\n" + text
    end = imports[-1].end()
    return text[:end] + "\n\n" + marker + text[end:]


def patch_arc_runtime() -> None:
    path = ROOT / "src/lib/arc.ts"
    text = path.read_text()
    if "BLEE_NETWORK_STARTUP_PROFILE" in text:
        print("Settlement runtime already uses the Blee startup network profile.")
        return

    # Network activation in Settings reloads the app. That means all viem clients
    # can be built correctly from the selected profile at module startup; we do
    # not need to find or mutate a particular createPublicClient declaration.
    text = add_import(text, 'import { getActiveNetwork, type BleeNetwork } from "./networkConfig";')
    text = _insert_startup_network(text)

    text, rpc_name = _replace_literal_decl(text, "https://rpc.testnet.arc.network", "BLEE_ACTIVE_NETWORK.rpcUrl")
    text, explorer_name = _replace_literal_decl(text, "https://testnet.arcscan.app", "BLEE_ACTIVE_NETWORK.explorerUrl")
    text, token_name = _replace_literal_decl(
        text,
        "0x3600000000000000000000000000000000000000",
        "BLEE_ACTIVE_NETWORK.tokenAddress",
    )

    chain_start, chain_end, chain_name = _find_call_assignment(
        text,
        "defineChain",
        any_of=("5042002", rpc_name, "Arc Testnet"),
    )
    prefix = _decl_prefix(text[chain_start:chain_end])
    dynamic_chain = f'''{prefix}const {chain_name} = defineChain({{
  id: BLEE_ACTIVE_NETWORK.chainId,
  name: BLEE_ACTIVE_NETWORK.name,
  nativeCurrency: {{
    name: BLEE_ACTIVE_NETWORK.nativeSymbol,
    symbol: BLEE_ACTIVE_NETWORK.nativeSymbol,
    decimals: 18,
  }},
  rpcUrls: {{ default: {{ http: [BLEE_ACTIVE_NETWORK.rpcUrl] }} }},
  blockExplorers: BLEE_ACTIVE_NETWORK.explorerUrl
    ? {{ default: {{ name: `${{BLEE_ACTIVE_NETWORK.name}} Explorer`, url: BLEE_ACTIVE_NETWORK.explorerUrl }} }}
    : undefined,
  testnet: BLEE_ACTIVE_NETWORK.testnet,
}});'''
    text = text[:chain_start] + dynamic_chain + text[chain_end:]

    domain_pattern = re.compile(
        r'name\s*:\s*["\']USDC["\']\s*,\s*version\s*:\s*["\']2["\']',
        flags=re.S,
    )
    text, domain_count = domain_pattern.subn(
        'name: BLEE_ACTIVE_NETWORK.eip712Name, version: BLEE_ACTIVE_NETWORK.eip712Version',
        text,
    )
    if domain_count == 0 and "BLEE_ACTIVE_NETWORK.eip712Name" not in text:
        raise SystemExit("Could not patch the EIP-712 payment-token domain")

    # Catch any direct chain-id literals outside the chain definition (for
    # example a typed-data domain) and make token precision profile-driven.
    text = re.sub(r"(?<![\w.])5042002(?![\w.])", "BLEE_ACTIVE_NETWORK.chainId", text)
    text = _replace_call_numeric_arg(text, "parseUnits", "6", "BLEE_ACTIVE_NETWORK.tokenDecimals")
    text = _replace_call_numeric_arg(text, "formatUnits", "6", "BLEE_ACTIVE_NETWORK.tokenDecimals")
    text = text.replace('throw new Error("Arc transaction reverted")', 'throw new Error("Network transaction reverted")')
    text = text.replace("throw new Error('Arc transaction reverted')", "throw new Error('Network transaction reverted')")

    text += '''\n\n// BLEE_NETWORK_STARTUP_PROFILE\n// Settings reloads the app after a network switch. Existing viem clients are\n// therefore instantiated from the selected profile on every fresh app load.\nexport function getBleeActiveNetwork() {\n  return BLEE_ACTIVE_NETWORK;\n}\n'''

    required = [
        "BLEE_ACTIVE_NETWORK.rpcUrl",
        "BLEE_ACTIVE_NETWORK.chainId",
        "BLEE_ACTIVE_NETWORK.tokenAddress",
        "BLEE_ACTIVE_NETWORK.eip712Name",
        "BLEE_ACTIVE_NETWORK.tokenDecimals",
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise SystemExit(f"Dynamic settlement profile incomplete: {missing}")

    path.write_text(text)
    print(
        "Settlement runtime patched using startup-selected network:",
        f"chain={chain_name}, rpc={rpc_name}, explorer={explorer_name}, token={token_name}",
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
    patch_component()
    patch_arc_runtime()
    bump_version()
    print("Blee 1.1 final submission overlays applied.")


if __name__ == "__main__":
    main()
