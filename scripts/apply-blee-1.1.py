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

    # Dynamic network labels. Keep the UI truthful after a custom network is activated.
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


def _find_decl(text: str, literal: str):
    pattern = re.compile(rf'(?P<prefix>(?:export\s+)?)const\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*["\']{re.escape(literal)}["\']\s*;?')
    match = pattern.search(text)
    if not match:
        raise SystemExit(f"Could not find declaration for {literal}")
    return match


def _replace_call_numeric_arg(text: str, func: str, old_value: str, replacement: str) -> str:
    # Replace a top-level final numeric argument in calls such as parseUnits(x, 6)
    # and formatUnits(await client.readContract({...}), 6) while respecting nesting.
    needle = func + "("
    pos = 0
    out = []
    while True:
        start = text.find(needle, pos)
        if start < 0:
            out.append(text[pos:])
            break
        out.append(text[pos:start])
        i = start + len(needle)
        depth = 1
        quote = None
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
        return

    text = add_import(text, 'import { getActiveNetwork, type BleeNetwork } from "./networkConfig";')

    rpc = _find_decl(text, "https://rpc.testnet.arc.network")
    explorer = _find_decl(text, "https://testnet.arcscan.app")
    token = _find_decl(text, "0x3600000000000000000000000000000000000000")
    rpc_name, explorer_name, token_name = rpc.group("name"), explorer.group("name"), token.group("name")

    for match in (rpc, explorer, token):
        original = match.group(0)
        text = text.replace(original, original.replace("const", "let", 1), 1)

    chain_match = re.search(
        r'(?P<prefix>(?:export\s+)?)const\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*defineChain\(\{(?P<body>.*?id\s*:\s*5042002.*?testnet\s*:\s*true.*?)\}\)\s*;?',
        text,
        flags=re.S,
    )
    if not chain_match:
        raise SystemExit("Could not locate Arc defineChain declaration")
    chain_name = chain_match.group("name")
    chain_original = chain_match.group(0)
    text = text.replace(chain_original, chain_original.replace("const", "let", 1), 1)

    client_match = re.search(
        rf'(?P<prefix>(?:export\s+)?)const\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*createPublicClient\(\{{\s*chain\s*:\s*{re.escape(chain_name)}\s*,\s*transport\s*:\s*http\(\s*{re.escape(rpc_name)}\s*\)\s*\}}\)\s*;?',
        text,
        flags=re.S,
    )
    if not client_match:
        raise SystemExit("Could not locate Arc public client declaration")
    client_name = client_match.group("name")
    client_original = client_match.group(0)
    client_mutable = client_original.replace("const", "let", 1)
    text = text.replace(client_original, client_mutable, 1)

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
    insert_at = text.find(client_mutable) + len(client_mutable)
    text = text[:insert_at] + runtime + text[insert_at:]

    # Make typed-data domain follow the selected network.
    text = re.sub(r'name\s*:\s*["\']USDC["\']\s*,\s*version\s*:\s*["\']2["\']',
                  'name: BLEE_ACTIVE_NETWORK.eip712Name, version: BLEE_ACTIVE_NETWORK.eip712Version', text)

    text = _replace_call_numeric_arg(text, "parseUnits", "6", "BLEE_ACTIVE_NETWORK.tokenDecimals")
    text = _replace_call_numeric_arg(text, "formatUnits", "6", "BLEE_ACTIVE_NETWORK.tokenDecimals")
    text = text.replace('throw new Error("Arc transaction reverted")', 'throw new Error("Network transaction reverted")')
    text = text.replace("throw new Error('Arc transaction reverted')", "throw new Error('Network transaction reverted')")

    path.write_text(text)


def bump_version() -> None:
    package = ROOT / "package.json"
    data = json.loads(package.read_text())
    data["version"] = "1.1.0"
    package.write_text(json.dumps(data, indent=2) + "\n")

    configure = ROOT / "scripts/configure-native.mjs"
    if configure.exists():
        text = configure.read_text()
        text = re.sub(r"versionCode\\s+\\d+", "versionCode 3", text)
        text = re.sub(r'versionName\\s+"[^\"]+"', 'versionName "1.1.0"', text)
        configure.write_text(text)


def main() -> None:
    copy_overrides()
    patch_component()
    patch_arc_runtime()
    bump_version()
    print("Blee 1.1 final submission overlays applied.")


if __name__ == "__main__":
    main()
