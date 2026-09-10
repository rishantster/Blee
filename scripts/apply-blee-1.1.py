#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / "overrides" / "src"


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
            text, count = re.subn(
                pattern,
                r"\1\n  const configuredNetwork = getActiveNetwork();",
                text,
                count=1,
            )
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
    # Handles nested calls and only rewrites the final numeric argument of the
    # named call. This avoids touching unrelated numeric literals in arc.ts.
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
        rewritten, n = re.subn(
            rf",\s*{re.escape(old_value)}\s*\)$",
            f", {replacement})",
            call,
            count=1,
        )
        changed += n
        pieces.append(rewritten)
        pos = i
    return "".join(pieces), changed


def patch_eip712_domain(text: str) -> tuple[str, bool]:
    # The historical source has existed in more than one formatting variant.
    # Patch domain fields independently rather than assuming name/version are
    # adjacent or that a particular domain variable exists.
    name_count = 0
    for literal in ("USDC", "USD Coin"):
        pattern = re.compile(
            rf"(\bname\s*:\s*)(?:\"{re.escape(literal)}\"|'{re.escape(literal)}')"
        )
        text, n = pattern.subn(r"\1BLEE_ACTIVE_NETWORK.eip712Name", text)
        name_count += n

    version_pattern = re.compile(r"(\bversion\s*:\s*)(?:\"2\"|'2')")
    text, version_count = version_pattern.subn(
        r"\1BLEE_ACTIVE_NETWORK.eip712Version", text
    )

    # Some revisions keep domain strings in named constants instead of inline.
    if name_count == 0:
        pattern = re.compile(
            r"((?:export\s+)?const\s+[A-Za-z_$][\w$]*(?:DOMAIN|EIP712)[A-Za-z_$\d]*\s*=\s*)(?:\"(?:USDC|USD Coin)\"|'(?:USDC|USD Coin)')",
            flags=re.I,
        )
        text, name_count = pattern.subn(
            r"\1BLEE_ACTIVE_NETWORK.eip712Name", text
        )

    if version_count == 0:
        pattern = re.compile(
            r"((?:export\s+)?const\s+[A-Za-z_$][\w$]*(?:DOMAIN|EIP712)[A-Za-z_$\d]*VERSION[A-Za-z_$\d]*\s*=\s*)(?:\"2\"|'2')",
            flags=re.I,
        )
        text, version_count = pattern.subn(
            r"\1BLEE_ACTIVE_NETWORK.eip712Version", text
        )

    dynamic = (
        "BLEE_ACTIVE_NETWORK.eip712Name" in text
        and "BLEE_ACTIVE_NETWORK.eip712Version" in text
    )
    if dynamic:
        print(f"EIP-712 domain made configurable (name patches={name_count}, version patches={version_count}).")
    else:
        # Do not kill an otherwise valid Arc-mainnet-capable build merely because
        # the baseline source encodes the domain through a different abstraction.
        # Arc USDC uses the tested USDC / version 2 profile. The Settings UI keeps
        # custom domain fields for forward compatibility, but other token domains
        # must be validated before being relied on.
        print("NOTE: EIP-712 domain was not safely identifiable; retaining the tested Arc USDC domain for this build.")
    return text, dynamic


def patch_arc_runtime() -> None:
    path = ROOT / "src/lib/arc.ts"
    text = path.read_text()
    if "BLEE_NETWORK_STARTUP_PROFILE" in text:
        print("Settlement runtime already uses Blee network selection.")
        return

    text = add_import(text, 'import { getActiveNetwork, type BleeNetwork } from "./networkConfig";')
    text = insert_active_network(text)

    text, rpc_count = replace_string_literal(
        text,
        "https://rpc.testnet.arc.network",
        "BLEE_ACTIVE_NETWORK.rpcUrl",
    )
    text, explorer_count = replace_string_literal(
        text,
        "https://testnet.arcscan.app",
        "BLEE_ACTIVE_NETWORK.explorerUrl",
    )
    text, token_count = replace_string_literal(
        text,
        "0x3600000000000000000000000000000000000000",
        "BLEE_ACTIVE_NETWORK.tokenAddress",
    )

    chain_count = len(re.findall(r"(?<![\w.])5042002(?![\w.])", text))
    text = re.sub(
        r"(?<![\w.])5042002(?![\w.])",
        "BLEE_ACTIVE_NETWORK.chainId",
        text,
    )

    # Keep chain metadata truthful where the baseline uses this literal as the
    # defineChain name. Property-scoped replacement avoids touching prose/errors.
    text = re.sub(
        r"(\bname\s*:\s*)(?:\"Arc Testnet\"|'Arc Testnet')",
        r"\1BLEE_ACTIVE_NETWORK.name",
        text,
    )

    text, eip712_dynamic = patch_eip712_domain(text)
    text, parse_count = replace_last_numeric_arg(
        text, "parseUnits", "6", "BLEE_ACTIVE_NETWORK.tokenDecimals"
    )
    text, format_count = replace_last_numeric_arg(
        text, "formatUnits", "6", "BLEE_ACTIVE_NETWORK.tokenDecimals"
    )

    text = text.replace(
        'throw new Error("Arc transaction reverted")',
        'throw new Error("Network transaction reverted")',
    ).replace(
        "throw new Error('Arc transaction reverted')",
        "throw new Error('Network transaction reverted')",
    )

    text += """

// BLEE_NETWORK_STARTUP_PROFILE
// Network changes in Settings reload Blee. viem clients are therefore created
// from this profile on each fresh app load.
export function getBleeActiveNetwork() {
  return BLEE_ACTIVE_NETWORK;
}
"""

    # These are the settlement-critical pieces required for Arc mainnet switching.
    # Fail only when a known baseline value was not found at all.
    failures = []
    if rpc_count == 0 and "BLEE_ACTIVE_NETWORK.rpcUrl" not in text:
        failures.append("RPC")
    if token_count == 0 and "BLEE_ACTIVE_NETWORK.tokenAddress" not in text:
        failures.append("payment token")
    if chain_count == 0 and "BLEE_ACTIVE_NETWORK.chainId" not in text:
        failures.append("chain ID")
    if failures:
        raise SystemExit("Could not make settlement runtime configurable: " + ", ".join(failures))

    path.write_text(text)
    print(
        "Settlement runtime configured from active network:",
        f"rpc={rpc_count}, explorer={explorer_count}, token={token_count}, chainId={chain_count}, parseUnits={parse_count}, formatUnits={format_count}, eip712Dynamic={eip712_dynamic}",
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
