# Blee Mesh v2 — Sponsored Relay API

Blee Mesh v2 separates local mesh transport from chain settlement. A nearby online phone can trigger automatic settlement without spending the phone owner's gas by forwarding a valid signed payment envelope to a configured sponsored relay/paymaster.

The APK **must never contain a shared relayer private key**.

## Client configuration

The native mesh runtime reads two values from the durable Blee key/value store:

- `mesh.relay.mode`
- `mesh.relay.endpoint`

Supported modes:

- `TESTNET_AUTO_RELAY`
- `SPONSORED_AUTO_RELAY`
- `USER_OPT_IN_RELAY`

The native client only auto-calls an endpoint for `TESTNET_AUTO_RELAY` or `SPONSORED_AUTO_RELAY`. The endpoint must be HTTPS.

Until an endpoint is configured, the mesh still provides offline persistence, Bluetooth delivery, store-and-forward routing, acknowledgements, notifications and settlement-receipt propagation. Existing foreground/direct settlement remains available, but third-phone background auto-settlement requires the relay/paymaster integration.

## Request

`POST <mesh.relay.endpoint>`

```json
{
  "protocol": "blee-mesh-v2",
  "mode": "SPONSORED_AUTO_RELAY",
  "packet": {
    "version": 2,
    "messageId": "pay:<payment-id>",
    "paymentId": "<payment-id>",
    "type": "PAYMENT_ENVELOPE",
    "destinationWallet": "0x...",
    "createdAt": 0,
    "expiresAt": 0,
    "payloadHash": "...",
    "payload": "{...payment + EIP-3009 authorization...}",
    "devicePublicKey": "...",
    "deviceSignature": "..."
  }
}
```

The relay must independently validate the financial authorization. A valid mesh-device signature alone is not authority to move money.

## Required relay validation

Before broadcasting anything to the chain, the relay must validate at minimum:

1. protocol version and packet integrity;
2. payment/authorization expiry;
3. EIP-3009 typed-data signature and recovered authorizer;
4. authorization `from`, `to`, value, nonce and configured chain/token domain;
5. that the authorization has not already been consumed;
6. replay/idempotency by payment ID + authorization nonce;
7. configured network/token allow-list;
8. policy/rate/abuse limits.

The endpoint must be idempotent. Multiple phones can legitimately discover the same envelope and race to submit it. Repeated valid requests for the same authorization must resolve to the same successful settlement result or the already-settled result, never create duplicate economic effects.

## Response

Successful settlement response:

```json
{
  "txHash": "0x...",
  "chainId": 5042002,
  "blockNumber": "123456",
  "status": "success",
  "reportedAt": 0
}
```

The phone persists this response, creates a `SETTLEMENT_RECEIPT` mesh packet, and propagates it to nearby/courier nodes.

## Finality

An offline recipient receiving a settlement receipt records `SETTLED_RELAY_REPORTED`. When that phone later obtains Internet access it independently verifies the transaction against the configured chain and then advances to `CHAIN_CONFIRMED`.

A sponsored relay response is settlement evidence, not permission for Blee to overwrite a local balance with a remote balance claim.

## Production security

Production deployment should add authenticated client rate controls, relay-side transaction simulation, network/token allow-lists, observability, replay storage, abuse controls, secret rotation and production key management/HSM or paymaster infrastructure. Relayer secrets belong only on the server side.