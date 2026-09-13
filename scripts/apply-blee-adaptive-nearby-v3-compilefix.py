#!/usr/bin/env python3
import json
from pathlib import Path
import runpy

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


def patch_release_version() -> None:
    package = ROOT / "package.json"
    if not package.is_file():
        raise SystemExit("Blee 2.7 release version: package.json missing")
    data = json.loads(package.read_text())
    data["version"] = "2.7.0"
    package.write_text(json.dumps(data, indent=2) + "\n")


def run_stage(script_name: str) -> None:
    script = ROOT / "scripts" / script_name
    if not script.is_file():
        raise SystemExit(f"Blee adaptive v3 compilefix: missing chained stage {script_name}")
    runpy.run_path(str(script), run_name="__main__")


def apply_production_polish() -> None:
    # BLEE_PRODUCTION_POLISH_CHAIN_V2
    run_stage("apply-blee-production-polish.py")
    run_stage("apply-blee-production-raw-wakeup.py")
    run_stage("apply-blee-payment-notifications-dbfix.py")
    run_stage("apply-blee-payment-notifications-servicecompat.py")
    run_stage("apply-blee-payment-notifications.py")
    run_stage("apply-blee-payment-notifications-v2.py")

    # Wallet-canonical peer presence and self-healing remain the proven base.
    run_stage("apply-blee-nearby-stability-v1.py")
    run_stage("apply-blee-nearby-stability-heartbeat-v1.py")
    run_stage("apply-blee-nearby-stability-hook-v1.py")

    # Full refresh stays in-process: no WebView reload and no vault/session loss.
    run_stage("apply-blee-refresh-preclean-v2.py")
    run_stage("apply-blee-pull-refresh-v1.py")

    # Preserve the last physically proven BLE/Nearby timing contract while
    # keeping live profile/name/avatar synchronization and Activity backfill.
    run_stage("apply-blee-nearby-speed-profile-v2.py")
    run_stage("apply-blee-activity-identity-v2.py")

    # Keep durable contacts data/native APIs, but do not mutate the React
    # Activity/Home shell for the hackathon production build. This is the stable
    # UI contract: original Activity tabs + original BottomNav stay untouched.
    run_stage("apply-blee-contacts-backend-only-v2.py")
    run_stage("apply-blee-contacts-sync-v1.py")
    run_stage("apply-blee-contacts-ui-preclean-v2.py")
    run_stage("apply-blee-stability-freeze-v1.py")

    # QR is installed only after every structural/runtime stabilization stage.
    # Nothing after this point mutates the Send React tree.
    run_stage("apply-blee-qr-resume-compat-v1.py")
    run_stage("apply-blee-qr-scanner-v1.py")
    run_stage("apply-blee-qr-scanner-placement-fix.py")
    run_stage("apply-blee-qr-scanner-compilefix.py")
    run_stage("apply-blee-qr-ux-v2.py")

    # Android 13+ permission request and high-importance payment channel.
    run_stage("apply-blee-notification-permission-v1.py")

    patch_release_version()

    # One final source-of-truth gate for the production build.
    run_stage("verify-production-final-v5.py")


def main() -> None:
    patch_service()
    patch_runtime_copy()
    apply_production_polish()
    print("Blee adaptive transport v3 + stable Blee 2.7 hackathon production stack finalized")


if __name__ == "__main__":
    main()
