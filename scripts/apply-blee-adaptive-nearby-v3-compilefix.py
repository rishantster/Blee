#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def locate_service() -> Path:
    hits = list(ANDROID_JAVA.rglob("BleeMeshService.java"))
    if len(hits) != 1:
        raise SystemExit(f"Blee adaptive v3 compilefix: expected one BleeMeshService.java, found {len(hits)}")
    return hits[0]


def patch_service() -> None:
    path = locate_service()
    text = path.read_text()
    if "BLEE_ADAPTIVE_NEARBY_V3" not in text:
        raise SystemExit("Blee adaptive v3 compilefix: adaptive transport must run first")

    start = text.index("    // BLEE_ADAPTIVE_NEARBY_V3", text.index("class BleeMeshService"))
    end = text.index("    // BLEE_TRANSPORT_CORE_V2\n    // One runtime owner", start)
    adaptive = text[start:end]

    adaptive = adaptive.replace("message(error)", "nearbyError(error)")

    if "nearbyError(Throwable error)" not in adaptive:
        helper_anchor = '''        String mode() {
            if (fallbackStarting) return "nearby_starting";'''
        helper = '''        private String nearbyError(Throwable error) {
            if (error == null) return "unknown";
            String value = error.getMessage();
            return value == null || value.isEmpty() ? error.toString() : value;
        }

        String mode() {
            if ("permission_required".equals(lastNearbyStatus)) return "permission_required";
            if (fallbackStarting) return "nearby_starting";'''
        if helper_anchor not in adaptive:
            raise SystemExit("Blee adaptive v3 compilefix: mode helper anchor missing")
        adaptive = adaptive.replace(helper_anchor, helper, 1)

    if "message(error)" in adaptive:
        raise SystemExit("Blee adaptive v3 compilefix: cross-inner helper call remains")
    if "nearbyError(Throwable error)" not in adaptive:
        raise SystemExit("Blee adaptive v3 compilefix: local error helper missing")

    text = text[:start] + adaptive + text[end:]
    path.write_text(text)


def patch_runtime_copy() -> None:
    path = ROOT / "src/components/BleeRuntime.tsx"
    if not path.is_file():
        raise SystemExit("Blee adaptive v3 compilefix: generated BleeRuntime.tsx missing")
    text = path.read_text()
    text = text.replace(
        "Keep Wi-Fi off on both phones while testing. This panel refreshes automatically.",
        "Keep Bluetooth and Wi-Fi enabled. Internet can stay off. This panel refreshes automatically.",
    )
    text = text.replace(
        "Scanning and advertising over Bluetooth LE in the background.",
        "Bluetooth LE is primary; Blee can switch to a local offline fallback when needed.",
    )
    text = text.replace("Restarting Bluetooth discovery…", "Restarting nearby transport…")
    text = text.replace("Restart requested. Watching the BLE path…", "Restart requested. Watching the nearby transport…")
    text = text.replace("Restart Bluetooth discovery", "Restart nearby transport")
    text = text.replace("Open Bluetooth diagnostics", "Open nearby transport diagnostics")
    if "Internet can stay off" not in text:
        raise SystemExit("Blee adaptive v3 compilefix: adaptive test guidance was not installed")
    path.write_text(text)


def main() -> None:
    patch_service()
    patch_runtime_copy()
    print("Blee adaptive transport v3 compile path + offline test guidance hardened")


if __name__ == "__main__":
    main()
