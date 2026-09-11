#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
JAVA_ROOT = ROOT / "android/app/src/main/java"


def one(name: str) -> Path:
    matches = list(JAVA_ROOT.rglob(name))
    if len(matches) != 1:
        raise SystemExit(f"Blee generated Android repair: expected one {name}, found {len(matches)}")
    return matches[0]


def repair_main_activity() -> None:
    path = one("MainActivity.java")
    text = path.read_text()
    if "protected void onStart()" in text:
        text = text.replace("protected void onStart()", "public void onStart()")
        path.write_text(text)
        print("Blee repair: MainActivity.onStart changed protected -> public")
    if "public void onStart()" not in text:
        raise SystemExit("Blee repair: MainActivity.onStart is not public")


def repair_delivery_notification() -> None:
    path = one("BleeMeshDb.java")
    text = path.read_text()
    if 'notifyTitle = "Payment delivered";' in text:
        print("Blee repair: delivery notification already present")
        return

    branch = re.compile(
        r'(\} else if \("DELIVERY_ACK"\.equals\(type\) && forUs\) \{)(.*?)(\n\s*\} else if \("SETTLEMENT_RECEIPT"\.equals\(type\)\) \{)',
        re.S,
    )
    match = branch.search(text)
    if not match:
        raise SystemExit("Blee repair: DELIVERY_ACK branch not found")

    body = match.group(2)
    if 'updatePaymentState(' not in body:
        raise SystemExit("Blee repair: DELIVERY_ACK state update missing")

    body = body.rstrip() + '\n                notifyTitle = "Payment delivered";\n                notifyBody = "A nearby Blee device acknowledged durable receipt.";'
    text = text[:match.start(2)] + body + text[match.end(2):]
    path.write_text(text)
    print("Blee repair: delivery notification restored without reintroducing destructive ACK cleanup")


def verify() -> None:
    main = one("MainActivity.java").read_text()
    db = one("BleeMeshDb.java").read_text()
    if "protected void onStart()" in main or "public void onStart()" not in main:
        raise SystemExit("Blee repair verify: invalid onStart visibility")
    if 'notifyTitle = "Payment delivered";' not in db:
        raise SystemExit("Blee repair verify: delivery notification missing")
    if 'BLEE_ACK_NON_DESTRUCTIVE_V1' in db and 'db().delete("mesh_outbox", "message_id=?", new String[] { "pay:" + paymentId });' in db:
        raise SystemExit("Blee repair verify: destructive ACK cleanup returned")
    print("Blee generated Android repair verified.")


if __name__ == "__main__":
    repair_main_activity()
    repair_delivery_notification()
    verify()
