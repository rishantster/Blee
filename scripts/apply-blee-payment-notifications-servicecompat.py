#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee payment notification service compatibility: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def method_bounds(text: str, signature: str) -> tuple[int, int, int]:
    start = text.find(signature)
    if start < 0:
        fail(f"missing method: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        fail(f"missing opening brace for {signature}")
    depth = 0
    end = -1
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        fail(f"unterminated method: {signature}")
    return start, brace, end


def app_package() -> str:
    activity = locate("MainActivity.java")
    match = re.search(r"^package\s+([A-Za-z0-9_.]+);", activity.read_text(), re.M)
    if not match:
        fail("MainActivity package missing")
    return match.group(1)


def main() -> None:
    path = locate("BleeMeshService.java")
    text = path.read_text()
    package = app_package()

    if "BLEE_IMMEDIATE_SENT_NOTIFICATION_V1" not in text:
        ledger = re.search(r'(?m)^\s*static final String ACTION_LEDGER_CHANGED = "[^"]+";', text)
        if not ledger:
            fail("ledger action constant missing")
        line = ledger.group(0)
        indent = line[: len(line) - len(line.lstrip())]
        addition = line + "\n" + indent + "// BLEE_IMMEDIATE_SENT_NOTIFICATION_V1\n" + indent + f'static final String ACTION_LOCAL_PAYMENT_SENT = "{package}.BLEE_LOCAL_PAYMENT_SENT";'
        text = text[: ledger.start()] + addition + text[ledger.end() :]

    start, brace, end = method_bounds(text, "public int onStartCommand(Intent intent, int flags, int startId)")
    block = text[start:end]
    if "BleePaymentNotifier.sent" not in block:
        handler = '''
        // BLEE_SENT_NOTIFICATION_ONSTART_COMPAT_V1
        if (intent != null && ACTION_LOCAL_PAYMENT_SENT.equals(intent.getAction())) {
            BleePaymentNotifier.sent(
                this,
                intent.getStringExtra("paymentId"),
                intent.getStringExtra("amount"),
                intent.getStringExtra("counterparty")
            );
        }
'''
        text = text[: brace + 1] + handler + text[brace + 1 :]

    start, brace, end = method_bounds(text, "private void notifyLedgerChanged(String paymentId, String type)")
    block = text[start:end]
    if "BleePaymentNotifier.delivered" not in block:
        # Keep this exact adjacency because the V2 background-notification stage
        # recognizes the canonical delivered+ledger pair structurally.
        delivered = '''
        if ("DELIVERY_ACK".equals(type)) BleePaymentNotifier.delivered(this, paymentId);
'''
        text = text[: brace + 1] + delivered + text[brace + 1 :]

    path.write_text(text)

    verify = path.read_text()
    required = (
        "BLEE_IMMEDIATE_SENT_NOTIFICATION_V1",
        "ACTION_LOCAL_PAYMENT_SENT",
        "BLEE_SENT_NOTIFICATION_ONSTART_COMPAT_V1",
        "BleePaymentNotifier.sent",
        "BleePaymentNotifier.delivered",
    )
    missing = [marker for marker in required if marker not in verify]
    if missing:
        fail(f"verification missing {missing}")

    start, _, end = method_bounds(verify, "public int onStartCommand(Intent intent, int flags, int startId)")
    if "START_STICKY" not in verify[start:end]:
        fail("existing START_STICKY lifecycle behavior was not preserved")

    print("VERIFIED: payment notification action is injected into the existing service lifecycle without replacing it")


if __name__ == "__main__":
    main()
