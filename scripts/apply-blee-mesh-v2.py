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


def patch_payments() -> None:
    # This is deliberately applied AFTER the legacy/professional overlays. It is
    # the canonical settlement implementation for Blee 2.1.
    source = MESH / "web" / "payments.ts.in"
    target = ROOT / "src/lib/payments.ts"
    if not source.exists():
        raise SystemExit("Missing Blee Mesh v2 sender-funded payments template")
    text = source.read_text()

    # nextNonce is itself persisted before the caller persists the payment. It
    # must therefore participate in the next reservation after process death,
    # otherwise a crash between signing and payment persistence could reuse an
    # EOA transaction nonce.
    old = "const txNonce = Math.max(profile.chainNonce, maxActive + 1, maxMemory + 1);"
    new = "const txNonce = Math.max(profile.chainNonce, profile.nextNonce, maxActive + 1, maxMemory + 1);"
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise SystemExit("Could not locate sender-funded transaction nonce reservation")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    print(f"mesh v2 overlay: {target.relative_to(ROOT)}")


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
    text = text.replace("Blee 2.0", "Blee 2.1")
    text = text.replace("Blee 1.4", "Blee 2.1")
    text = text.replace("Blee 1.3", "Blee 2.1")
    app.write_text(text)


def patch_package() -> None:
    package = ROOT / "package.json"
    data = json.loads(package.read_text())
    data["version"] = "2.1.0"
    package.write_text(json.dumps(data, indent=2) + "\n")


def patch_native_generator_version() -> None:
    path = ROOT / "scripts/configure-native.mjs"
    if not path.exists():
        return
    text = path.read_text()
    text = re.sub(r"versionCode\s+\d+", "versionCode 9", text)
    text = re.sub(r'versionName\s+"[^"]+"', 'versionName "2.1.0"', text)
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
            "BLEE_STORE_MESH_V2",
            "payment_events",
            "mesh_outbox",
            "settlement_receipts",
            "setWriteAheadLoggingEnabled(true)",
        ),
        "src/lib/payments.ts": (
            "SENDER_FUNDED_RAW_TX",
            "signTransaction",
            "sendRawTransaction",
            "refreshSenderFundedSettlementProfile",
            "NO_SYNCED_NONCE_OR_FEE_PROFILE",
            "profile.nextNonce",
        ),
        "src/components/BleeRuntime.tsx": (
            "BleeMesh",
            "ledgerChanged",
            "ensureNotificationPermission",
            "refreshSenderFundedSettlementProfile",
        ),
        "src/components/BleeApp.tsx": ("Blee 2.1",),
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
    if package.get("version") != "2.1.0":
        raise SystemExit("Blee Mesh v2 package version is not 2.1.0")

    combined = (ROOT / "src/lib/payments.ts").read_text() + "\n" + (ROOT / "src/components/BleeRuntime.tsx").read_text()
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
    print("Blee 2.1 Mesh v2 sender-funded settlement overlay verified.")


if __name__ == "__main__":
    main()
