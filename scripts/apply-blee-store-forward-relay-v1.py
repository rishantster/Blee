#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_JAVA = ROOT / "android/app/src/main/java"
RELAY_STORE_TEMPLATE = ROOT / "relay-v1/BleeRelayStore.java.in"
PAYMENTS_FRAGMENT = ROOT / "relay-v1/payments-relay.tsfrag"


def fail(message: str) -> None:
    raise SystemExit(f"Blee relay v1: {message}")


def locate(name: str) -> Path:
    hits = list(ANDROID_JAVA.rglob(name))
    if len(hits) != 1:
        fail(f"expected one {name}, found {len(hits)}")
    return hits[0]


def app_package() -> tuple[str, Path]:
    activity = locate("MainActivity.java")
    text = activity.read_text()
    match = re.search(r"^package\s+([A-Za-z0-9_.]+);", text, re.M)
    if not match:
        fail("MainActivity package missing")
    return match.group(1), activity.parent


def once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        fail(f"missing {label} anchor")
    return text.replace(old, new, 1)


def replace_java_method(text: str, signature: str, replacement: str, label: str) -> str:
    start = text.find(signature)
    if start < 0:
        fail(f"missing {label} method")
    brace = text.find("{", start)
    if brace < 0:
        fail(f"missing {label} opening brace")
    depth = 0
    end = -1
    for i in range(brace, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        fail(f"unterminated {label} method")
    return text[:start] + replacement.rstrip() + text[end:]


def patch_payments() -> None:
    path = ROOT / "src/lib/payments.ts"
    if not path.is_file():
        fail("generated src/lib/payments.ts is missing")
    text = path.read_text()
    if "BLEE_GLOBAL_STORE_FORWARD_RELAY_WEB_V1" in text:
        return
    if not PAYMENTS_FRAGMENT.is_file():
        fail("payments relay fragment missing")

    if "decodeFunctionData," not in text:
        text = once(text, "  decodeEventLog,\n", "  decodeEventLog,\n  decodeFunctionData,\n", "viem decode import")
    if "parseTransaction," not in text:
        text = once(text, "  parseUnits,\n", "  parseUnits,\n  parseTransaction,\n", "viem transaction parse import")
    if "recoverTransactionAddress," not in text:
        text = once(text, "  recoverTypedDataAddress,\n", "  recoverTransactionAddress,\n  recoverTypedDataAddress,\n", "viem transaction recovery import")

    anchor = "export async function transactionStatus(hash: Hex): Promise<'success' | 'reverted' | 'pending'> {"
    if anchor not in text:
        fail("transactionStatus insertion anchor missing")
    fragment = PAYMENTS_FRAGMENT.read_text().rstrip() + "\n\n"
    text = text.replace(anchor, fragment + anchor, 1)
    path.write_text(text)


def materialize_relay_store(package: str, native_dir: Path) -> None:
    if not RELAY_STORE_TEMPLATE.is_file():
        fail("relay store template missing")
    target = native_dir / "BleeRelayStore.java"
    content = RELAY_STORE_TEMPLATE.read_text().replace("__BLEE_APP_PACKAGE__", package)
    target.write_text(content)


def patch_mesh_db() -> None:
    path = locate("BleeMeshDb.java")
    text = path.read_text()
    if "BLEE_RELAY_VALIDATION_GATE_V1" in text:
        return

    old = '''            // Payment envelopes continue beyond the recipient so that a third
            // online Blee node can become a settlement relay. Settlement receipts
            // are gossip events and likewise continue through the mesh.
            boolean relayEvent = "PAYMENT_ENVELOPE".equals(type) || "SETTLEMENT_RECEIPT".equals(type);
            boolean shouldForward = copyBudget > 1 && hopCount < hopLimit && (relayEvent || !forUs);'''
    new = '''            // BLEE_RELAY_VALIDATION_GATE_V1
            // PAYMENT_ENVELOPE packets are quarantined in mesh_inbox first. They
            // are not eligible for transit forwarding until the viem layer has
            // verified EIP-3009 + the exact sender-signed EIP-1559 transaction
            // and BleeRelayStore promotes them into the validated relay queue.
            boolean paymentEnvelope = "PAYMENT_ENVELOPE".equals(type);
            boolean relayEvent = "SETTLEMENT_RECEIPT".equals(type);
            boolean shouldForward = !paymentEnvelope && copyBudget > 1 && hopCount < hopLimit && (relayEvent || !forUs);'''
    text = once(text, old, new, "pre-validation forwarding gate")
    path.write_text(text)


def patch_service() -> None:
    path = locate("BleeMeshService.java")
    text = path.read_text()
    if "BLEE_GLOBAL_STORE_FORWARD_RELAY_SERVICE_V1" in text:
        return

    text = once(
        text,
        '    private static final String TRUSTED_RPC = "https://rpc.testnet.arc.network";',
        '''    private static final String TRUSTED_RPC = "https://rpc.testnet.arc.network";
    // BLEE_GLOBAL_STORE_FORWARD_RELAY_SERVICE_V1
    private static final String TRUSTED_USDC = "0x3600000000000000000000000000000000000000";
    private static final String[] TRUSTED_RPCS = new String[] {
        TRUSTED_RPC,
        "https://rpc.drpc.testnet.arc.network",
        "https://rpc.quicknode.testnet.arc.network",
        "https://rpc.blockdaemon.testnet.arc.network"
    };''',
        "trusted relay rail",
    )
    text = once(text, "    private BleeMeshDb db;", "    private BleeMeshDb db;\n    private BleeRelayStore relayStore;", "relay store field")
    text = once(text, "        db = new BleeMeshDb(this);", "        db = new BleeMeshDb(this);\n        relayStore = new BleeRelayStore(this);", "relay store init")
    text = once(
        text,
        "        if (db != null) db.close();",
        "        if (relayStore != null) relayStore.close();\n        if (db != null) db.close();",
        "relay store close",
    )
    text = once(
        text,
        "                db.bootstrapOutgoing(deviceId, publicKey);",
        "                db.bootstrapOutgoing(deviceId, publicKey);\n                if (relayStore != null) relayStore.cleanup(System.currentTimeMillis());",
        "relay cleanup loop",
    )

    replacement = r'''    private void attemptSenderFundedSettlement() {
        if (!networkAvailable || relayStore == null) return;
        long now = System.currentTimeMillis();
        List<BleeRelayStore.RelayCandidate> candidates = relayStore.broadcastCandidates(now, 64);
        for (BleeRelayStore.RelayCandidate candidate : candidates) {
            try {
                JSONObject packet = new JSONObject(candidate.packet);
                JSONObject payment = new JSONObject(packet.optString("payload", "{}"));
                JSONObject auth = payment.optJSONObject("authorization");
                if (auth == null) auth = payment.optJSONObject("auth");
                if (auth == null) { relayStore.markInvalid(candidate.messageId, "authorization missing"); continue; }
                JSONObject broadcast = auth.optJSONObject("broadcast");
                if (broadcast == null || !"SENDER_FUNDED_RAW_TX".equals(broadcast.optString("mode", ""))) {
                    relayStore.markInvalid(candidate.messageId, "sender-funded transaction missing");
                    continue;
                }
                if (broadcast.optLong("chainId", -1L) != TRUSTED_CHAIN_ID) {
                    relayStore.markInvalid(candidate.messageId, "unsupported chain");
                    continue;
                }
                if (relayAuthorizationExpired(auth, now)) {
                    relayStore.markExpired(candidate.messageId, "authorization expired");
                    continue;
                }

                String rawTx = broadcast.optString("rawTransaction", "");
                String expectedHash = broadcast.optString("txHash", "");
                String sender = auth.optString("from", "");
                String nonce = auth.optString("nonce", "");
                if (!isHex(rawTx, 4, 262144) || !isTxHash(expectedHash) || !isAddress(sender) || !isTxHash(nonce)) {
                    relayStore.markInvalid(candidate.messageId, "validated relay metadata became inconsistent");
                    continue;
                }

                JSONObject receipt = transactionReceipt(expectedHash);
                if (receipt != null) {
                    if ("0x1".equalsIgnoreCase(receipt.optString("status", ""))) {
                        confirmRelay(candidate, packet, auth, receipt);
                    } else if (authorizationStateUsed(sender, nonce)) {
                        relayStore.markAlreadySettled(candidate.messageId, "authorization already consumed");
                    } else {
                        relayStore.markInvalid(candidate.messageId, "sender-funded transaction reverted");
                    }
                    continue;
                }

                if (authorizationStateUsed(sender, nonce)) {
                    relayStore.markAlreadySettled(candidate.messageId, "authorization already consumed");
                    continue;
                }

                try {
                    relayStore.markBroadcastPending(candidate.messageId);
                    String returnedHash = sendRawTransaction(rawTx);
                    if (returnedHash != null && isTxHash(returnedHash) && !returnedHash.equalsIgnoreCase(expectedHash)) {
                        relayStore.markInvalid(candidate.messageId, "RPC returned a different transaction hash");
                        continue;
                    }
                    relayStore.markBroadcasted(candidate.messageId);
                } catch (Throwable broadcastError) {
                    String message = broadcastError.getMessage() == null ? "broadcast failed" : broadcastError.getMessage();
                    String lower = message.toLowerCase(Locale.ROOT);
                    if (isAlreadyKnownRelayError(lower)) {
                        relayStore.markBroadcasted(candidate.messageId);
                    } else if (lower.contains("nonce too low")) {
                        JSONObject nonceReceipt = transactionReceipt(expectedHash);
                        if (nonceReceipt != null && "0x1".equalsIgnoreCase(nonceReceipt.optString("status", ""))) {
                            confirmRelay(candidate, packet, auth, nonceReceipt);
                        } else if (authorizationStateUsed(sender, nonce)) {
                            relayStore.markAlreadySettled(candidate.messageId, "authorization already consumed");
                        } else {
                            relayStore.markNeedsSenderRefresh(candidate.messageId, "sender transaction nonce was consumed before relay settlement");
                        }
                    } else if (isRetryableRelayError(lower)) {
                        relayStore.markRetry(candidate.messageId, message);
                    } else {
                        relayStore.markInvalid(candidate.messageId, message);
                    }
                    continue;
                }

                try { Thread.sleep(650L); } catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
                receipt = transactionReceipt(expectedHash);
                if (receipt != null && "0x1".equalsIgnoreCase(receipt.optString("status", ""))) {
                    confirmRelay(candidate, packet, auth, receipt);
                }
            } catch (Throwable error) {
                relayStore.markRetry(candidate.messageId, error.getMessage() == null ? "relay settlement error" : error.getMessage());
                Log.d(TAG, "validated relay settlement retry: " + error.getMessage());
            }
        }
    }

    private void confirmRelay(BleeRelayStore.RelayCandidate candidate, JSONObject packet, JSONObject auth, JSONObject receipt) throws Exception {
        JSONObject evidence = new JSONObject();
        evidence.put("protocol", "blee-settlement-ack");
        evidence.put("version", 1);
        evidence.put("paymentId", candidate.paymentId);
        evidence.put("txHash", candidate.txHash);
        evidence.put("chainId", TRUSTED_CHAIN_ID);
        evidence.put("blockNumber", receipt.optString("blockNumber", ""));
        evidence.put("status", "CONFIRMED");
        evidence.put("settlementMode", "SENDER_FUNDED_RAW_TX");
        evidence.put("gasPaidBy", auth.optString("from", "sender"));
        evidence.put("confirmedAt", System.currentTimeMillis());
        evidence.put("reportedAt", System.currentTimeMillis());
        db.recordSettlementReceipt(packet, evidence, deviceId, publicKey);
        relayStore.markConfirmed(candidate.messageId, System.currentTimeMillis());
        notifyLedgerChanged(candidate.paymentId, "SETTLEMENT_RECEIPT");
    }

    private boolean authorizationStateUsed(String sender, String nonce) {
        if (!isAddress(sender) || !isTxHash(nonce)) return false;
        try {
            String addressWord = sender.substring(2).toLowerCase(Locale.ROOT);
            StringBuilder padded = new StringBuilder();
            for (int i = addressWord.length(); i < 64; i++) padded.append('0');
            padded.append(addressWord);
            String data = "0xe94a0102" + padded + nonce.substring(2).toLowerCase(Locale.ROOT);
            JSONObject call = new JSONObject();
            call.put("to", TRUSTED_USDC);
            call.put("data", data);
            Object result = rpc("eth_call", new JSONArray().put(call).put("latest"));
            if (!(result instanceof String)) return false;
            String value = ((String) result).toLowerCase(Locale.ROOT);
            if (!value.startsWith("0x")) return false;
            String compact = value.substring(2).replaceFirst("^0+", "");
            return !compact.isEmpty() && !"0".equals(compact);
        } catch (Throwable ignored) {
            return false;
        }
    }

    private static boolean relayAuthorizationExpired(JSONObject auth, long nowMs) {
        try { return Long.parseLong(auth.optString("validBefore", "0")) * 1000L <= nowMs; }
        catch (Throwable ignored) { return true; }
    }

    private static boolean isAddress(String value) {
        return value != null && value.matches("^0x[0-9a-fA-F]{40}$");
    }

    private static boolean isAlreadyKnownRelayError(String lower) {
        return lower.contains("already known") || lower.contains("known transaction") || lower.contains("already imported");
    }

    private static boolean isRetryableRelayError(String lower) {
        return lower.contains("timeout") || lower.contains("timed out") || lower.contains("network")
            || lower.contains("dns") || lower.contains("gateway") || lower.contains("rate limit")
            || lower.contains("429") || lower.contains("temporar") || lower.contains("unavailable")
            || lower.contains("connection") || lower.contains("base fee") || lower.contains("underpriced")
            || lower.contains("mempool");
    }'''
    text = replace_java_method(text, "    private void attemptSenderFundedSettlement()", replacement, "sender-funded settlement")

    rpc_replacement = r'''    private Object rpc(String method, JSONArray params) throws Exception {
        Exception last = null;
        for (String endpoint : TRUSTED_RPCS) {
            try { return rpcEndpoint(endpoint, method, params); }
            catch (Exception error) { last = error; }
        }
        if (last != null) throw last;
        throw new IllegalStateException("No trusted Arc RPC endpoint configured");
    }

    private Object rpcEndpoint(String endpoint, String method, JSONArray params) throws Exception {
        URL url = new URL(endpoint);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        connection.setRequestMethod("POST");
        connection.setConnectTimeout(7000);
        connection.setReadTimeout(12000);
        connection.setDoOutput(true);
        connection.setRequestProperty("Content-Type", "application/json");
        connection.setRequestProperty("Accept", "application/json");

        JSONObject body = new JSONObject();
        body.put("jsonrpc", "2.0");
        body.put("id", 1);
        body.put("method", method);
        body.put("params", params);
        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
        connection.setFixedLengthStreamingMode(bytes.length);
        try (OutputStream out = connection.getOutputStream()) { out.write(bytes); }

        int code = connection.getResponseCode();
        InputStream stream = code >= 200 && code < 300 ? connection.getInputStream() : connection.getErrorStream();
        StringBuilder responseText = new StringBuilder();
        if (stream != null) {
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) responseText.append(line);
            }
        }
        connection.disconnect();
        if (code < 200 || code >= 300) throw new IllegalStateException("Arc RPC HTTP " + code + ": " + responseText);

        JSONObject response = new JSONObject(responseText.toString());
        JSONObject error = response.optJSONObject("error");
        if (error != null) throw new IllegalStateException(error.optString("message", error.toString()));
        Object result = response.opt("result");
        return result == JSONObject.NULL ? null : result;
    }'''
    text = replace_java_method(text, "    private Object rpc(String method, JSONArray params)", rpc_replacement, "Arc RPC")
    path.write_text(text)


def patch_plugin() -> None:
    path = locate("BleeMeshPlugin.java")
    text = path.read_text()
    if "BLEE_RELAY_PLUGIN_V1" in text:
        return

    class_end = text.rfind("}")
    if class_end < 0:
        fail("BleeMeshPlugin class end missing")
    methods = r'''

    // BLEE_RELAY_PLUGIN_V1
    @PluginMethod
    public void pendingRelayCandidates(PluginCall call) {
        BleeRelayStore relay = new BleeRelayStore(getContext());
        try {
            List<String> pending = relay.pendingCandidates(System.currentTimeMillis(), 32);
            JSArray packets = new JSArray();
            for (String raw : pending) packets.put(raw);
            JSObject result = new JSObject();
            result.put("packets", packets);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to load pending relay candidates: " + error.getMessage());
        } finally {
            relay.close();
        }
    }

    @PluginMethod
    public void acceptValidatedRelayEnvelope(PluginCall call) {
        JSObject proof = call.getObject("proof");
        if (proof == null) { call.reject("Missing relay validation proof"); return; }
        BleeRelayStore relay = new BleeRelayStore(getContext());
        try {
            BleeRelayStore.PromotionResult promoted = relay.promoteVerified(proof, BleeDeviceIdentity.deviceId(getContext()));
            JSObject result = new JSObject();
            result.put("accepted", promoted.accepted);
            result.put("duplicate", promoted.duplicate);
            result.put("forwardQueued", promoted.forwardQueued);
            result.put("messageId", promoted.messageId);
            result.put("error", promoted.error);
            call.resolve(result);
        } catch (Throwable error) {
            call.reject("Unable to promote validated relay envelope: " + error.getMessage());
        } finally {
            relay.close();
        }
    }

    @PluginMethod
    public void rejectRelayCandidate(PluginCall call) {
        String messageId = call.getString("messageId", "");
        String reason = call.getString("reason", "invalid relay envelope");
        if (messageId.isEmpty()) { call.resolve(); return; }
        BleeRelayStore relay = new BleeRelayStore(getContext());
        try {
            relay.rejectCandidate(messageId, reason);
            call.resolve();
        } finally {
            relay.close();
        }
    }

    @PluginMethod
    public void relayDiagnostics(PluginCall call) {
        BleeRelayStore relay = new BleeRelayStore(getContext());
        try { call.resolve(JSObject.fromJSONObject(relay.diagnostics())); }
        catch (Throwable error) { call.reject("Unable to read relay diagnostics: " + error.getMessage()); }
        finally { relay.close(); }
    }
'''
    text = text[:class_end] + methods + text[class_end:]
    path.write_text(text)


def patch_runtime() -> None:
    path = ROOT / "src/components/BleeRuntime.tsx"
    if not path.is_file():
        fail("generated BleeRuntime.tsx is missing")
    text = path.read_text()
    if "BLEE_STORE_FORWARD_RELAY_RUNTIME_V1" in text:
        return

    if "validateSenderFundedRelayEnvelope" not in text:
        old_import = "refreshSenderFundedSettlementProfile, verifyAuthorization"
        if old_import not in text:
            fail("payments import anchor missing")
        text = text.replace(old_import, "refreshSenderFundedSettlementProfile, validateSenderFundedRelayEnvelope, verifyAuthorization", 1)

    type_anchor = "  pendingEnvelopes(): Promise<{ packets: string[] }>;"
    type_insert = '''  pendingEnvelopes(): Promise<{ packets: string[] }>;
  // BLEE_STORE_FORWARD_RELAY_RUNTIME_V1
  pendingRelayCandidates(): Promise<{ packets: string[] }>;
  acceptValidatedRelayEnvelope(options: { proof: Record<string, unknown> }): Promise<{ accepted: boolean; duplicate?: boolean; forwardQueued?: boolean; messageId?: string; error?: string }>;
  rejectRelayCandidate(options: { messageId: string; reason: string }): Promise<void>;
  relayDiagnostics(): Promise<Record<string, string | number | boolean | null | undefined>>;'''
    text = once(text, type_anchor, type_insert, "relay plugin type")

    validation_anchor = '''        const status = await BleeMesh.status();
        const wallet = status.wallet?.toLowerCase();'''
    validation_block = '''        const { packets: relayPackets = [] } = await BleeMesh.pendingRelayCandidates();
        for (const raw of relayPackets) {
          const validation = await validateSenderFundedRelayEnvelope(raw);
          if (validation.valid) {
            await BleeMesh.acceptValidatedRelayEnvelope({ proof: validation.proof as unknown as Record<string, unknown> });
          } else if (validation.messageId) {
            await BleeMesh.rejectRelayCandidate({ messageId: validation.messageId, reason: validation.reason });
          }
        }

        const status = await BleeMesh.status();
        const wallet = status.wallet?.toLowerCase();'''
    text = once(text, validation_anchor, validation_block, "transit relay validation")
    path.write_text(text)


def verify_generated(package: str, native_dir: Path) -> None:
    payments = (ROOT / "src/lib/payments.ts").read_text()
    runtime = (ROOT / "src/components/BleeRuntime.tsx").read_text()
    db = locate("BleeMeshDb.java").read_text()
    service = locate("BleeMeshService.java").read_text()
    plugin = locate("BleeMeshPlugin.java").read_text()
    relay_store = (native_dir / "BleeRelayStore.java").read_text()

    required = {
        "payments": (payments, (
            "BLEE_GLOBAL_STORE_FORWARD_RELAY_WEB_V1", "validateSenderFundedRelayEnvelope",
            "recoverTransactionAddress", "parseTransaction", "decodeFunctionData",
            "broadcastSenderFundedRawTransaction", "NEEDS_SENDER_REFRESH",
        )),
        "runtime": (runtime, ("BLEE_STORE_FORWARD_RELAY_RUNTIME_V1", "pendingRelayCandidates", "acceptValidatedRelayEnvelope")),
        "db": (db, ("BLEE_RELAY_VALIDATION_GATE_V1", "boolean shouldForward = !paymentEnvelope")),
        "service": (service, (
            "BLEE_GLOBAL_STORE_FORWARD_RELAY_SERVICE_V1", "BleeRelayStore", "TRUSTED_RPCS",
            "authorizationStateUsed", "eth_call", "e94a0102", "markNeedsSenderRefresh",
        )),
        "plugin": (plugin, ("BLEE_RELAY_PLUGIN_V1", "pendingRelayCandidates", "acceptValidatedRelayEnvelope", "relayDiagnostics")),
        "relayStore": (relay_store, (
            f"package {package};", "BLEE_GLOBAL_STORE_FORWARD_RELAY_V1", "relay_envelopes",
            "relay_sender_nonce_idx", "MAX_QUEUE = 256", "promoteVerified", "broadcastCandidates",
        )),
    }
    for label, (content, markers) in required.items():
        missing = [marker for marker in markers if marker not in content]
        if missing:
            fail(f"generated {label} missing {missing}")

    start = payments.index("export async function broadcastSenderFundedRawTransaction")
    end = payments.index("export async function transactionStatus", start)
    community = payments[start:end]
    if "PrivateKeyAccount" in community or "createWalletClient" in community or "writeContract" in community:
        fail("community relay broadcaster can access a signing/account fallback")
    print("Blee Relay V1 generated path installed and verified")


def main() -> None:
    package, native_dir = app_package()
    patch_payments()
    materialize_relay_store(package, native_dir)
    patch_mesh_db()
    patch_service()
    patch_plugin()
    patch_runtime()
    verify_generated(package, native_dir)


if __name__ == "__main__":
    main()
