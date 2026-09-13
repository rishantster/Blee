#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESH = ROOT / "mesh-v2"


def copy_required(source: Path, target: Path) -> None:
    if not source.exists():
        raise SystemExit(f"Missing Blee Mesh v2 source: {source.relative_to(ROOT)}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    print(f"mesh v2 overlay: {target.relative_to(ROOT)}")


def patch_store() -> None:
    copy_required(
        MESH / "native" / "BleeStorePlugin.java",
        ROOT / "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java",
    )


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    a = text.find(start)
    if a < 0:
        raise SystemExit(f"Could not locate {label} start")
    b = text.find(end, a)
    if b < 0:
        raise SystemExit(f"Could not locate {label} end")
    return text[:a] + replacement + text[b:]


def patch_payments() -> None:
    # Applied after every legacy/professional overlay. These files are the
    # canonical Blee 2.1.1 settlement/signing implementation.
    source = MESH / "web" / "payments.ts.in"
    atomic_source = MESH / "web" / "atomicSigning.ts.in"
    target = ROOT / "src/lib/payments.ts"
    atomic_target = ROOT / "src/lib/atomicSigning.ts"
    if not source.exists() or not atomic_source.exists():
        raise SystemExit("Missing Blee Mesh v2 atomic signing templates")

    text = source.read_text()
    import_anchor = "import type { TransferAuthorization } from '../types/domain';\n"
    atomic_import = "import { createAtomicAuthorization, refreshAtomicSigningProfile } from './atomicSigning';\n"
    if atomic_import not in text:
        if import_anchor not in text:
            raise SystemExit("Could not locate payments import anchor")
        text = text.replace(import_anchor, import_anchor + atomic_import, 1)

    refresh_start = "export async function refreshSenderFundedSettlementProfile(address: Address): Promise<boolean> {"
    refresh_end = "\nasync function prepareSenderFundedBroadcast("
    refresh_replacement = """export async function refreshSenderFundedSettlementProfile(address: Address): Promise<boolean> {
  return refreshAtomicSigningProfile(address);
}
"""
    text = replace_between(text, refresh_start, refresh_end, refresh_replacement, "settlement profile wrapper")

    create_start = "export async function createAuthorization(\n"
    create_end = "\nexport async function verifyAuthorization("
    create_replacement = """export async function createAuthorization(
  account: PrivateKeyAccount,
  to: Address,
  amount: string,
): Promise<TransferAuthorization> {
  // createAtomicAuthorization does not return until both native SQLite signing
  // boundaries have committed. A signed bundle therefore cannot reach the
  // payment journal or mesh from an uncommitted in-memory signing operation.
  return createAtomicAuthorization(account, to, amount);
}
"""
    text = replace_between(text, create_start, create_end, create_replacement, "atomic createAuthorization")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    atomic_target.write_text(atomic_source.read_text())
    print(f"mesh v2 overlay: {target.relative_to(ROOT)}")
    print(f"mesh v2 overlay: {atomic_target.relative_to(ROOT)}")


def patch_runtime() -> None:
    source = MESH / "web" / "BleeRuntime.tsx"
    target = ROOT / "src/components/BleeRuntime.tsx"
    text = source.read_text()
    text = text.replace("../../src/components/BleeApp", "./BleeApp")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)

    page = ROOT / "app/page.tsx"
    page.write_text(
        "'use client';\n\n"
        "import BleeRuntime from '../src/components/BleeRuntime';\n\n"
        "export default function Page() {\n"
        "  return <BleeRuntime />;\n"
        "}\n"
    )
    print("mesh v2 overlay: native runtime wrapper installed")


def patch_visible_version() -> None:
    app = ROOT / "src/components/BleeApp.tsx"
    text = app.read_text()
    for old in ("Blee 2.1", "Blee 2.0", "Blee 1.4", "Blee 1.3"):
        text = text.replace(old, "Blee 2.1.1")
    app.write_text(text)


def patch_package() -> None:
    package = ROOT / "package.json"
    data = json.loads(package.read_text())
    data["version"] = "2.1.1"
    package.write_text(json.dumps(data, indent=2) + "\n")


def patch_native_generator_version() -> None:
    path = ROOT / "scripts/configure-native.mjs"
    if not path.exists():
        return
    text = path.read_text()
    text = re.sub(r"versionCode\s+\d+", "versionCode 10", text)
    text = re.sub(r'versionName\s+"[^"]+"', 'versionName "2.1.1"', text)
    path.write_text(text)


def patch_css() -> None:
    path = ROOT / "app/globals.css"
    text = path.read_text()
    marker = "/* BLEE_MESH_V2 */"
    if marker not in text:
        text += "\n" + marker + "\n"
    path.write_text(text)


def verify() -> None:
    required = {
        "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java": (
            "BLEE_STORE_MESH_V2_ATOMIC_SIGNING_V1",
            "signing_intents",
            "reserveSigningIntent",
            "finalizeSigningIntent",
            "SIGNATURE_BUNDLE_PERSISTED",
            "setWriteAheadLoggingEnabled(true)",
        ),
        "src/lib/atomicSigning.ts": (
            "createAtomicAuthorization",
            "reserveSigningIntent",
            "finalizeSigningIntent",
            "SENDER_FUNDED_RAW_TX",
            "SIGNING_SESSION_ID",
            "bundleHash",
        ),
        "src/lib/payments.ts": (
            "createAtomicAuthorization",
            "refreshAtomicSigningProfile",
            "sendRawTransaction",
        ),
        "src/components/BleeRuntime.tsx": (
            "BleeMesh",
            "ledgerChanged",
            "ensureNotificationPermission",
            "refreshSenderFundedSettlementProfile",
        ),
        "src/components/BleeApp.tsx": ("Blee 2.1.1",),
        "app/globals.css": ("BLEE_MESH_V2",),
    }
    for rel, markers in required.items():
        path = ROOT / rel
        if not path.exists():
            raise SystemExit(f"Blee Mesh v2 missing required file: {rel}")
        text = path.read_text()
        missing = [marker for marker in markers if marker not in text]
        if missing:
            raise SystemExit(f"Blee Mesh v2 verification failed for {rel}: {missing}")

    package = json.loads((ROOT / "package.json").read_text())
    if package.get("version") != "2.1.1":
        raise SystemExit("Blee Mesh v2 package version is not 2.1.1")

    combined = "\n".join(
        (ROOT / rel).read_text()
        for rel in ("src/lib/payments.ts", "src/lib/atomicSigning.ts", "src/components/BleeRuntime.tsx")
    )
    banned = ("SPONSORED_AUTO_RELAY", "NEXT_PUBLIC_BLEE_RELAY_ENDPOINT", "configureRelay")
    found = [marker for marker in banned if marker in combined]
    if found:
        raise SystemExit(f"Obsolete sponsored-relay client markers remain: {found}")


def main() -> None:
    patch_store()
    patch_payments()
    patch_runtime()
    patch_visible_version()
    patch_package()
    patch_native_generator_version()
    patch_css()
    verify()
    print("Blee 2.1.1 Mesh v2 atomic sender-funded settlement overlay verified.")


if __name__ == "__main__":
    main()
