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


def main() -> None:
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
        // Preserve the pre-existing OFFLINE -> ONLINE sender recovery path. It is
        // restricted to packets originated by this exact device; foreign packets
        // may settle only after the validated community-relay promotion gate.
        attemptLocalSenderSettlement(now);
        List<BleeRelayStore.RelayCandidate> candidates = relayStore.broadcastCandidates(now, 64);'''
    if call_anchor not in text:
        fail("community relay candidate anchor missing")
    text = text.replace(call_anchor, call_replacement, 1)

    method_anchor = "    private void confirmRelay(BleeRelayStore.RelayCandidate candidate, JSONObject packet, JSONObject auth, JSONObject receipt) throws Exception {"
    if method_anchor not in text:
        fail("confirmRelay anchor missing")

    helper = r'''    private void attemptLocalSenderSettlement(long now) {
        List<String> localCandidates = db.settlementCandidates(now, 64);
        for (String raw : localCandidates) {
            try {
                JSONObject packet = new JSONObject(raw);
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

    verified = path.read_text()
    start = verified.index("private void attemptLocalSenderSettlement")
    end = verified.index("private void confirmRelay", start)
    block = verified[start:end]
    for forbidden in ("createWalletClient", "writeContract", "PrivateKeyAccount"):
        if forbidden in block:
            fail(f"local sender background path unexpectedly contains signing primitive: {forbidden}")
    if 'deviceId.equals(packet.optString("originDeviceId", ""))' not in block:
        fail("local sender path is not origin-device restricted")
    if "sendRawTransaction(rawTx)" not in block:
        fail("local sender path does not broadcast existing raw transaction")
    print("Blee Relay V1 preserves sender background auto-settlement without opening community signer fallback")


if __name__ == "__main__":
    main()
