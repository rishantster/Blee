#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"


def fail(message: str) -> None:
    raise SystemExit(f"Blee relay sender compatibility: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def patch_db() -> None:
    path = locate("BleeMeshDb.java")
    text = path.read_text()
    marker = "BLEE_LOCAL_SENDER_SETTLEMENT_SOURCE_V1"
    if marker in text:
        return

    anchor = "    synchronized List<String> settlementCandidates(long now, int limit) {"
    helper = r'''    // BLEE_LOCAL_SENDER_SETTLEMENT_SOURCE_V1
    // Only packets backed by this installation's durable OUTGOING payment journal
    // are eligible for the sender recovery path. Foreign inbox/transit packets
    // must use BleeRelayStore after cryptographic promotion.
    synchronized List<String> localSenderSettlementCandidates(long now, int limit) {
        List<String> rows = new ArrayList<>();
        int bounded = Math.max(1, Math.min(limit, 64));
        try (Cursor c = db().rawQuery(
            "SELECT o.packet FROM mesh_outbox o "
                + "INNER JOIN payments p ON p.payment_id=o.payment_id AND p.direction='outgoing' "
                + "WHERE o.packet_type='PAYMENT_ENVELOPE' AND o.expires_at>? "
                + "ORDER BY o.created_at ASC LIMIT ?",
            new String[] { String.valueOf(now), String.valueOf(bounded) }
        )) {
            while (c.moveToNext()) rows.add(c.getString(0));
        }
        return rows;
    }

'''
    if anchor not in text:
        fail("settlementCandidates anchor missing")
    text = text.replace(anchor, helper + anchor, 1)
    path.write_text(text)


def patch_service() -> None:
    path = locate("BleeMeshService.java")
    text = path.read_text()
    marker = "BLEE_RELAY_LOCAL_SENDER_COMPAT_V1"
    if marker in text:
        return
    if "BLEE_GLOBAL_STORE_FORWARD_RELAY_SERVICE_V1" not in text:
        fail("relay service stage must run first")

    call_anchor = '''        long now = System.currentTimeMillis();
        List<BleeRelayStore.RelayCandidate> candidates = relayStore.broadcastCandidates(now, 64);'''
    call_replacement = '''        long now = System.currentTimeMillis();
        // BLEE_RELAY_LOCAL_SENDER_COMPAT_V1
        // Preserve the pre-existing OFFLINE -> ONLINE sender recovery path while
        // keeping it completely separate from foreign community-relay packets.
        attemptLocalSenderSettlement(now);
        List<BleeRelayStore.RelayCandidate> candidates = relayStore.broadcastCandidates(now, 64);'''
    if call_anchor not in text:
        fail("community relay candidate anchor missing")
    text = text.replace(call_anchor, call_replacement, 1)

    method_anchor = "    private void confirmRelay(BleeRelayStore.RelayCandidate candidate, JSONObject packet, JSONObject auth, JSONObject receipt) throws Exception {"
    if method_anchor not in text:
        fail("confirmRelay anchor missing")

    helper = r'''    private void attemptLocalSenderSettlement(long now) {
        List<String> localCandidates = db.localSenderSettlementCandidates(now, 64);
        String localWallet = db.activeWallet();
        if (localWallet == null || localWallet.isEmpty()) return;
        for (String raw : localCandidates) {
            try {
                JSONObject packet = new JSONObject(raw);
                // Defense in depth: local outbox/journal provenance is primary;
                // the device id check rejects a colliding foreign packet as well.
                if (!deviceId.equals(packet.optString("originDeviceId", ""))) continue;
                String paymentId = packet.optString("paymentId", "");
                if (paymentId.isEmpty()) continue;

                JSONObject payment = new JSONObject(packet.optString("payload", "{}"));
                JSONObject auth = payment.optJSONObject("authorization");
                if (auth == null) auth = payment.optJSONObject("auth");
                if (auth == null || relayAuthorizationExpired(auth, now)) continue;
                JSONObject broadcast = auth.optJSONObject("broadcast");
                if (broadcast == null || !"SENDER_FUNDED_RAW_TX".equals(broadcast.optString("mode", ""))) continue;
                if (broadcast.optLong("chainId", -1L) != TRUSTED_CHAIN_ID) continue;

                String sender = auth.optString("from", "");
                if (!localWallet.equalsIgnoreCase(sender)) continue;
                String rawTx = broadcast.optString("rawTransaction", "");
                String expectedHash = broadcast.optString("txHash", "");
                String nonce = auth.optString("nonce", "");
                if (!isAddress(sender) || !isHex(rawTx, 4, 262144) || !isTxHash(expectedHash) || !isTxHash(nonce)) continue;

                JSONObject receipt = transactionReceipt(expectedHash);
                if (receipt == null) {
                    try {
                        String returnedHash = sendRawTransaction(rawTx);
                        if (returnedHash != null && isTxHash(returnedHash) && !returnedHash.equalsIgnoreCase(expectedHash)) {
                            db.markSettlementAttempt(paymentId, false, "RPC returned a different transaction hash");
                            continue;
                        }
                    } catch (Throwable error) {
                        String message = error.getMessage() == null ? "broadcast failed" : error.getMessage();
                        String lower = message.toLowerCase(java.util.Locale.ROOT);
                        if (lower.contains("nonce too low")) {
                            JSONObject nonceReceipt = transactionReceipt(expectedHash);
                            if (nonceReceipt != null && "0x1".equalsIgnoreCase(nonceReceipt.optString("status", ""))) {
                                receipt = nonceReceipt;
                            } else if (!authorizationStateUsed(sender, nonce)) {
                                db.markSettlementAttempt(paymentId, false, "NEEDS_SENDER_REFRESH: sender transaction nonce was consumed");
                                continue;
                            } else {
                                db.markSettlementAttempt(paymentId, false, "authorization already consumed; awaiting canonical receipt verification");
                                continue;
                            }
                        } else if (!isAlreadyKnownRelayError(lower)) {
                            db.markSettlementAttempt(paymentId, false, message);
                            continue;
                        }
                    }
                    if (receipt == null) {
                        try { Thread.sleep(650L); } catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
                        receipt = transactionReceipt(expectedHash);
                    }
                }

                if (receipt == null) {
                    db.markSettlementAttempt(paymentId, false, "sender-funded transaction pending");
                    continue;
                }
                if (!"0x1".equalsIgnoreCase(receipt.optString("status", ""))) {
                    db.markSettlementAttempt(paymentId, false, "sender-funded transaction reverted");
                    continue;
                }

                JSONObject evidence = new JSONObject();
                evidence.put("protocol", "blee-settlement-ack");
                evidence.put("version", 1);
                evidence.put("paymentId", paymentId);
                evidence.put("txHash", expectedHash);
                evidence.put("chainId", TRUSTED_CHAIN_ID);
                evidence.put("blockNumber", receipt.optString("blockNumber", ""));
                evidence.put("status", "CONFIRMED");
                evidence.put("settlementMode", "SENDER_FUNDED_RAW_TX");
                evidence.put("gasPaidBy", sender);
                evidence.put("confirmedAt", System.currentTimeMillis());
                evidence.put("reportedAt", System.currentTimeMillis());
                db.recordSettlementReceipt(packet, evidence, deviceId, publicKey);
                db.markSettlementAttempt(paymentId, true, null);
                notifyLedgerChanged(paymentId, "SETTLEMENT_RECEIPT");
            } catch (Throwable error) {
                Log.d(TAG, "local sender settlement retry: " + error.getMessage());
            }
        }
    }

'''
    text = text.replace(method_anchor, helper + method_anchor, 1)
    path.write_text(text)


def verify() -> None:
    db = locate("BleeMeshDb.java").read_text()
    service = locate("BleeMeshService.java").read_text()
    for required in (
        "BLEE_LOCAL_SENDER_SETTLEMENT_SOURCE_V1",
        "localSenderSettlementCandidates",
        "INNER JOIN payments p",
        "p.direction='outgoing'",
    ):
        if required not in db:
            fail(f"local sender DB source missing {required}")

    start = service.index("private void attemptLocalSenderSettlement")
    end = service.index("private void confirmRelay", start)
    block = service[start:end]
    for forbidden in ("createWalletClient", "writeContract", "PrivateKeyAccount"):
        if forbidden in block:
            fail(f"local sender background path unexpectedly contains signing primitive: {forbidden}")
    for required in (
        "db.localSenderSettlementCandidates(now, 64)",
        'deviceId.equals(packet.optString("originDeviceId", ""))',
        "localWallet.equalsIgnoreCase(sender)",
        "sendRawTransaction(rawTx)",
    ):
        if required not in block:
            fail(f"local sender background path missing {required}")
    print("Blee Relay V1 preserves sender background auto-settlement from local outgoing journal only")


def main() -> None:
    patch_db()
    patch_service()
    verify()


if __name__ == "__main__":
    main()
