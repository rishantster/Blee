#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_PATCHER = ROOT / "scripts/apply-blee-1.1.py"

spec = importlib.util.spec_from_file_location("blee_patcher", LEGACY_PATCHER)
if spec is None or spec.loader is None:
    raise SystemExit("Could not load Blee 1.1 patch helpers")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def declaration_prefix(snippet: str) -> str:
    return "export " if re.match(r"\s*export\s+", snippet) else ""


def insert_runtime_after_imports(text: str) -> str:
    marker = "const BLEE_ACTIVE_NETWORK: BleeNetwork = getActiveNetwork();"
    if marker in text:
        return text
    imports = list(re.finditer(r"^import\s.+?;\s*$", text, flags=re.M))
    if not imports:
        return marker + "\n\n" + text
    end = imports[-1].end()
    return text[:end] + "\n\n" + marker + text[end:]


def replace_literal_declaration(text: str, literal: str, expression: str) -> tuple[str, str]:
    start, end, name = mod._find_literal_decl(text, literal)
    snippet = text[start:end]
    prefix = declaration_prefix(snippet)
    replacement = f"{prefix}const {name} = {expression};"
    return text[:start] + replacement + text[end:], name


def patch_arc_runtime_startup() -> None:
    """Patch Arc settlement once at module startup.

    Network switching in Blee intentionally reloads the app. Therefore the
    settlement module does not need to mutate or rediscover createPublicClient
    at runtime. On each reload it builds all existing Arc clients from the
    selected network profile. This is both simpler and much less brittle than
    trying to parse the exact client declaration style in the prototype.
    """
    path = ROOT / "src/lib/arc.ts"
    text = path.read_text()

    if "BLEE_NETWORK_STARTUP_PROFILE" in text:
        print("Settlement runtime already uses the Blee startup network profile.")
        return

    text = mod.add_import(text, 'import { getActiveNetwork, type BleeNetwork } from "./networkConfig";')
    text = insert_runtime_after_imports(text)

    text, rpc_name = replace_literal_declaration(
        text,
        "https://rpc.testnet.arc.network",
        "BLEE_ACTIVE_NETWORK.rpcUrl",
    )
    text, explorer_name = replace_literal_declaration(
        text,
        "https://testnet.arcscan.app",
        "BLEE_ACTIVE_NETWORK.explorerUrl",
    )
    text, token_name = replace_literal_declaration(
        text,
        "0x3600000000000000000000000000000000000000",
        "BLEE_ACTIVE_NETWORK.tokenAddress",
    )

    chain_start, chain_end, chain_name = mod._find_call_assignment(
        text,
        "defineChain",
        any_of=("5042002", rpc_name, "Arc Testnet"),
    )
    chain_snippet = text[chain_start:chain_end]
    prefix = declaration_prefix(chain_snippet)
    dynamic_chain = f'''{prefix}const {chain_name} = defineChain({{
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
    text = text[:chain_start] + dynamic_chain + text[chain_end:]

    # EIP-3009 typed-data signatures are bound to chain, token contract and
    # domain. Keep every one of those values tied to the selected profile.
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

    # Any remaining literal chain-id references in this settlement module must
    # follow the selected profile as well.
    text = re.sub(r"(?<![\w.])5042002(?![\w.])", "BLEE_ACTIVE_NETWORK.chainId", text)
    text = mod._replace_call_numeric_arg(text, "parseUnits", "6", "BLEE_ACTIVE_NETWORK.tokenDecimals")
    text = mod._replace_call_numeric_arg(text, "formatUnits", "6", "BLEE_ACTIVE_NETWORK.tokenDecimals")
    text = text.replace('throw new Error("Arc transaction reverted")', 'throw new Error("Network transaction reverted")')
    text = text.replace("throw new Error('Arc transaction reverted')", "throw new Error('Network transaction reverted')")

    marker = '''\n\n// BLEE_NETWORK_STARTUP_PROFILE\n// Network changes reload Blee; existing viem clients are therefore created\n// from these startup-selected constants on every app load.\nexport function getBleeActiveNetwork() {\n  return BLEE_ACTIVE_NETWORK;\n}\n'''
    text += marker

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


def main() -> None:
    mod.copy_overrides()
    mod.patch_component()
    patch_arc_runtime_startup()
    mod.bump_version()
    print("Blee 1.1 final submission overlays applied.")


if __name__ == "__main__":
    main()
