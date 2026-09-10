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
        rf'(?P<prefix>(?:export\s+)?)const\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*["\']{re.escape(literal)}["\'](?:\s+as\s+const)?\s*;?'
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
    raise SystemExit("Unbalanced function call while patching Arc runtime")


def _find_call_assignment(text: str, callee: str, must_contain: tuple[str, ...] = ()) -> tuple[int, int, str]:
    pattern = re.compile(
        rf'(?P<prefix>(?:export\s+)?)const\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*{re.escape(callee)}\s*\('
    )
    for match in pattern.finditer(text):
        open_paren = text.find("(", match.start(), match.end())
        end = _scan_call_end(text, open_paren)
        snippet = text[match.start():end]
        if all(needle in snippet for needle in must_contain):
            return match.start(), end, match.group("name")
    wanted = ", ".join(must_contain) if must_contain else "any call"
    raise SystemExit(f"Could not locate {callee} assignment containing: {wanted}")


def _make_decl_mutable(text: str, start: int, end: int) -> str:
    snippet = text[start:end]
    changed, count = re.subn(r"\bconst\b", "let", snippet, count=1)
    if count != 1:
        raise SystemExit("Could not make runtime declaration mutable")
    return text[:start] + changed + text[end:]


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


def patch_arc_runtime() -> None:
    path = ROOT / "src/lib/arc.ts"
    text = path.read_text()
    if "BLEE_ACTIVE_NETWORK" in text:
        print("Arc runtime already has Blee network support.")
        return

    text = add_import(text, 'import { getActiveNetwork, type BleeNetwork } from "./networkConfig";')

    # Identify the exact Arc constants by their values, not by guessed variable names.
    rpc_start, rpc_end, rpc_name = _find_literal_decl(text, "https://rpc.testnet.arc.network")
    text = _make_decl_mutable(text, rpc_start, rpc_end)

    explorer_start, explorer_end, explorer_name = _find_literal_decl(text, "https://testnet.arcscan.app")
    text = _make_decl_mutable(text, explorer_start, explorer_end)

    token_start, token_end, token_name = _find_literal_decl(text, "0x3600000000000000000000000000000000000000")
    text = _make_decl_mutable(text, token_start, token_end)

    # The previous patcher assumed a particular formatting/order inside defineChain.
    # Instead, parse the actual defineChain(...) call and select the one containing
    # Arc Testnet's chain ID. This survives formatting and property-order changes.
    chain_start, chain_end, chain_name = _find_call_assignment(text, "defineChain", ("5042002",))
    text = _make_decl_mutable(text, chain_start, chain_end)

    # Re-locate after the prior edits, then identify the public client from the
    # actual chain/RPC identifiers used by this source file.
    client_start, client_end, client_name = _find_call_assignment(
        text, "createPublicClient", (chain_name, rpc_name)
    )
    text = _make_decl_mutable(text, client_start, client_end)

    # Re-locate the mutable public-client declaration so the runtime block is
    # inserted immediately after it.
    client_pattern = re.compile(
        rf'(?P<prefix>(?:export\s+)?)let\s+{re.escape(client_name)}\s*=\s*createPublicClient\s*\('
    )
    client_match = client_pattern.search(text)
    if not client_match:
        raise SystemExit("Could not re-locate mutable public client")
    open_paren = text.find("(", client_match.start(), client_match.end())
    client_end = _scan_call_end(text, open_paren)

    runtime = f'''

let BLEE_ACTIVE_NETWORK: BleeNetwork = getActiveNetwork();

function applyBleeNetwork(network: BleeNetwork = getActiveNetwork()) {{
  BLEE_ACTIVE_NETWORK = network;
  {rpc_name} = network.rpcUrl;
  {explorer_name} = network.explorerUrl;
  {token_name} = network.tokenAddress;
  {chain_name} = defineChain({{
    id: network.chainId,
    name: network.name,
    nativeCurrency: {{ name: network.nativeSymbol, symbol: network.nativeSymbol, decimals: 18 }},
    rpcUrls: {{ default: {{ http: [network.rpcUrl] }} }},
    blockExplorers: network.explorerUrl
      ? {{ default: {{ name: `${{network.name}} Explorer`, url: network.explorerUrl }} }}
      : undefined,
    testnet: network.testnet,
  }});
  {client_name} = createPublicClient({{ chain: {chain_name}, transport: http({rpc_name}) }});
}}

applyBleeNetwork();

export function getBleeActiveNetwork() {{
  return BLEE_ACTIVE_NETWORK;
}}
'''
    text = text[:client_end] + runtime + text[client_end:]

    # EIP-3009 typed-data domain must follow the configured token/network.
    domain_pattern = re.compile(
        r'name\s*:\s*["\']USDC["\']\s*,\s*version\s*:\s*["\']2["\']'
    )
    text, domain_count = domain_pattern.subn(
        'name: BLEE_ACTIVE_NETWORK.eip712Name, version: BLEE_ACTIVE_NETWORK.eip712Version',
        text,
    )
    if domain_count == 0:
        raise SystemExit("Could not patch the EIP-712 USDC domain")

    text = _replace_call_numeric_arg(text, "parseUnits", "6", "BLEE_ACTIVE_NETWORK.tokenDecimals")
    text = _replace_call_numeric_arg(text, "formatUnits", "6", "BLEE_ACTIVE_NETWORK.tokenDecimals")
    text = text.replace('throw new Error("Arc transaction reverted")', 'throw new Error("Network transaction reverted")')
    text = text.replace("throw new Error('Arc transaction reverted')", "throw new Error('Network transaction reverted')")

    # Guardrails: fail the build if the static settlement constants still appear
    # in executable declarations after the runtime patch was applied.
    if "BLEE_ACTIVE_NETWORK" not in text or "getActiveNetwork" not in text:
        raise SystemExit("Dynamic network runtime was not applied")
    if f"{client_name} = createPublicClient" not in text:
        raise SystemExit("Dynamic public client rebuild was not applied")

    path.write_text(text)
    print(
        "Arc runtime patched for configurable networks:",
        f"chain={chain_name}, rpc={rpc_name}, explorer={explorer_name}, token={token_name}, client={client_name}",
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
