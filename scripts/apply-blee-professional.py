#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / "professional" / "parts"
ARCHIVE_SHA256 = "ecec910512330005d630bea85951169b3e221b9f7caf4180d029c3c42435a29b"


def unpack_professional_source() -> Path:
    if not PARTS.is_dir():
        raise SystemExit("Missing professional/parts source snapshot")
    parts = sorted(PARTS.glob("part*"))
    if not parts:
        raise SystemExit("Professional source snapshot is empty")
    encoded = b"".join(part.read_bytes() for part in parts)
    try:
        archive = base64.b64decode(encoded, validate=True)
    except Exception as error:
        raise SystemExit(f"Professional source snapshot is not valid base64: {error}") from error
    digest = hashlib.sha256(archive).hexdigest()
    if digest != ARCHIVE_SHA256:
        raise SystemExit(f"Professional source checksum mismatch: {digest}")
    temp = Path(tempfile.mkdtemp(prefix="blee-professional-"))
    archive_path = temp / "overlay.tar.gz"
    archive_path.write_bytes(archive)
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(temp / "source")
    return temp


def copy_tree(source: Path, target: Path) -> None:
    if not source.exists():
        raise SystemExit(f"Missing professional source directory: {source}")
    for item in source.rglob("*"):
        if item.is_dir():
            continue
        rel = item.relative_to(source)
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)
        print(f"professional overlay: {dest.relative_to(ROOT)}")


def update_package_version() -> None:
    package = ROOT / "package.json"
    data = json.loads(package.read_text())
    data["version"] = "1.2.0"
    package.write_text(json.dumps(data, indent=2) + "\n")


def update_native_generator_version() -> None:
    path = ROOT / "scripts" / "configure-native.mjs"
    if not path.exists():
        return
    text = path.read_text()
    text = re.sub(r"versionCode\s+\d+", "versionCode 5", text)
    text = re.sub(r'versionName\s+"[^"]+"', 'versionName "1.2.0"', text)
    path.write_text(text)


def verify_markers() -> None:
    checks = {
        "src/hooks/useBlee.ts": [
            "sendQueueRef",
            "authenticatedRecipient",
            "receiver: a.address",
            "expireAuthorizations",
            "confirmed spendable balance",
        ],
        "src/components/BleeApp.tsx": [
            "CONFIRMED SPENDABLE",
            "Nearby delivery is not final settlement.",
            "Recipient acknowledgement is authenticated",
            "Blee 1.2",
        ],
        "app/globals.css": [
            ".pending-banner",
            ".status-panel",
            "prefers-reduced-motion",
        ],
        "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java": [
            "BLEE_STORE_PRO_V3",
            "setWriteAheadLoggingEnabled(true)",
        ],
    }
    for rel, markers in checks.items():
        path = ROOT / rel
        if not path.exists():
            raise SystemExit(f"Professional overlay missing required file: {rel}")
        text = path.read_text()
        missing = [marker for marker in markers if marker not in text]
        if missing:
            raise SystemExit(f"Professional overlay check failed for {rel}: {missing}")


def reject_prototype_copy() -> None:
    app = (ROOT / "src/components/BleeApp.tsx").read_text()
    banned = (
        "projectedBalance",
        "INTERNET OPTIONAL",
        "Local wallet",
        "Configured EVM rail",
        "Payment delivered nearby</strong><span>The signed authorization reached",
    )
    found = [term for term in banned if term in app]
    if found:
        raise SystemExit(f"Prototype copy still present in professional app: {found}")


def main() -> None:
    temp = unpack_professional_source()
    try:
        source = temp / "source"
        copy_tree(source / "src", ROOT / "src")
        copy_tree(source / "app", ROOT / "app")

        native = source / "native" / "BleeStorePlugin.java"
        if not native.exists():
            raise SystemExit("Professional source snapshot is missing native/BleeStorePlugin.java")
        native_target = ROOT / "plugins/blee-store/android/src/main/java/com/blee/store/BleeStorePlugin.java"
        native_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(native, native_target)
        print("professional overlay: native BleeStorePlugin.java [BLEE_STORE_PRO_V3]")

        update_package_version()
        update_native_generator_version()
        verify_markers()
        reject_prototype_copy()
        print("Blee 1.2 professional overlay verified.")
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    main()
