#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def locate_service() -> Path:
    hits = list(ANDROID_JAVA.rglob("BleeMeshService.java"))
    if len(hits) != 1:
        raise SystemExit(f"Blee raw wakeup: expected one BleeMeshService.java, found {len(hits)}")
    return hits[0]


def main() -> None:
    path = locate_service()
    text = path.read_text()
    marker = "BLEE_PRODUCTION_RAW_PAYMENT_WAKEUP_V1"
    if marker in text:
        return
    if "BLEE_PRODUCTION_EVENT_PATH_V1" not in text:
        raise SystemExit("Blee raw wakeup: production polish must run first")

    old = '''            BleeMeshDb.ProcessResult result = db.receive(raw, deviceId, publicKey);
            if (result.accepted && result.ledgerChanged) notifyLedgerChanged(result.paymentId, result.type);
            if (result.notificationTitle != null) paymentNotification(result.notificationTitle, result.notificationBody, result.paymentId);'''
    new = '''            BleeMeshDb.ProcessResult result = db.receive(raw, deviceId, publicKey);
            // BLEE_PRODUCTION_RAW_PAYMENT_WAKEUP_V1
            if (result.accepted && (result.ledgerChanged || "PAYMENT_ENVELOPE".equals(result.type))) {
                notifyLedgerChanged(result.paymentId, result.ledgerChanged ? result.type : "PAYMENT_ENVELOPE_RECEIVED");
            }
            if (result.notificationTitle != null) paymentNotification(result.notificationTitle, result.notificationBody, result.paymentId);'''
    if old not in text:
        raise SystemExit("Blee raw wakeup: canonical acceptFrame receipt path not found")
    text = text.replace(old, new, 1)
    path.write_text(text)

    verified = path.read_text()
    if marker not in verified or verified.count("PAYMENT_ENVELOPE_RECEIVED") < 2:
        raise SystemExit("Blee raw wakeup: immediate raw + Nearby payment wakeups are not both installed")
    print("Blee production: raw BLE payment envelopes now wake pending-balance projection immediately")


if __name__ == "__main__":
    main()
