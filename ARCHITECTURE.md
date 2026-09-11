# Blee Mesh v2 — Frozen Architecture

Status: **frozen for Blee 2.1 implementation**

Blee is an offline-first, self-custodial payment system. Internet availability controls blockchain settlement, not whether Blee devices can create, persist, deliver, acknowledge, notify, carry or reconcile payments.

## 1. Architectural rule

The native Android process is the network node. React/Capacitor renders local state; it is not responsible for keeping the mesh alive.

```text
Blee UI
   │
   ▼
SQLite / WAL event ledger
   │
   ▼
BleeMeshService
   ├─ BLE scanner + advertiser
   ├─ GATT transport / fragmentation
   ├─ durable inbox + outbox
   ├─ bounded store-and-forward courier routing
   ├─ connectivity observer
   ├─ sender-funded settlement broadcaster
   └─ Android notifications
```

## 2. Settlement rule: sender pays, courier only broadcasts

A random third Blee phone must never spend its owner's funds to settle somebody else's payment.

Phone A creates two cryptographic artifacts:

1. the EIP-3009 `TransferWithAuthorization` authorization for the payment; and
2. when a cached chain nonce/fee profile is available, a **sender-signed EIP-1559 raw transaction** that calls `transferWithAuthorization`.

The raw transaction is signed by Phone A's wallet. Therefore the EVM transaction sender is A and any network fee is charged to A. Phone C merely submits the already-signed bytes with `eth_sendRawTransaction`.

```text
Phone A (offline sender)
  signs payment authorization
  signs settlement transaction
          │
          │ BLE / store-and-forward
          ▼
Phone B / Phone C / Phone D
          │
     any node gets Internet
          │
          │ eth_sendRawTransaction(rawTx)
          ▼
Arc
          │
     transaction receipt
          │
          ▼
Blee mesh gossips SETTLEMENT_RECEIPT
```

### Invariants

- Phone C signs nothing for A.
- Phone C never exposes or uses A's private key.
- Phone C never pays A's gas.
- Phone C cannot change recipient, amount, calldata, nonce or fee caps without invalidating A's transaction signature.
- Automatic mesh broadcasting is pinned to Blee's validated chain/RPC; arbitrary RPC endpoints are not accepted by the background service.
- If Arc later makes the fee zero or an external actor sponsors it, the protocol still works; sender cost simply becomes zero.

## 3. Why EIP-3009 remains

The raw transaction does not replace EIP-3009. The authorization is still the payment-level authority and gives Blee an independently verifiable payment object.

The preferred settlement path is:

```text
EIP-3009 authorization
       +
sender-signed EIP-1559 transaction
       ↓
any online phone broadcasts
```

If the cached raw transaction becomes stale because the sender used the wallet elsewhere or its account nonce changed, a third phone does **not** spend its own gas to rescue it. When the sender later comes online/unlocks, Blee can reconcile chain state and produce a fresh sender-funded submission while the authorization remains valid.

## 4. Offline nonce and fee profile

An EOA cannot create a valid future raw transaction without chain state. Therefore Blee caches a settlement profile while the sender is online:

```text
chainId
sender address
pending account nonce
next locally reserved nonce
maxFeePerGas
maxPriorityFeePerGas
syncedAt
```

`getBalance()` and the native runtime opportunistically refresh this profile whenever Internet is available.

When A later creates a payment offline, Blee:

1. serializes transaction creation;
2. checks active local outgoing payments for already-reserved transaction nonces;
3. reserves the next nonce;
4. uses conservative cached EIP-1559 fee caps;
5. signs the raw settlement transaction;
6. stores the signed payment before mesh transmission.

If no usable profile has ever been cached, Blee still creates the EIP-3009 authorization and local nearby payment envelope, but marks it `AUTH_ONLY`. Nearby delivery still works; automatic sender-funded third-phone settlement cannot be manufactured without a valid sender transaction nonce/fee profile.

This is a correctness constraint, not a UI limitation.

## 5. Durable event ledger

Financial/network state is reconstructed from durable SQLite state, not React memory.

Core tables:

- `payments`
- `payment_events`
- `mesh_inbox`
- `mesh_outbox`
- `mesh_seen_packets`
- `courier_envelopes`
- `settlement_jobs`
- `settlement_receipts`
- `peer_identities`
- `kv`

Write-ahead logging is enabled. Migrations are additive; payment data is never dropped as an upgrade strategy.

Every important transition records an immutable UTC epoch-millisecond timestamp.

## 6. Payment states

Protocol state:

```text
CREATED
  ↓
SIGNED
  ↓
QUEUED
  ↓
DELIVERED_OFFLINE
  ↓
ACKNOWLEDGED
  ↓
SETTLEMENT_SUBMITTED
  ↓
SETTLED_RELAY_REPORTED
  ↓
CHAIN_CONFIRMED
```

The historical internal name `SETTLED_RELAY_REPORTED` means settlement evidence was received through the mesh; it does **not** mean the courier paid gas.

User-facing copy may be simplified to `Sending`, `Delivered nearby`, `Received offline`, `Settlement pending`, `Settled`, `Confirmed`.

## 7. Balance semantics

Blee keeps separate concepts:

- **confirmed / spendable** — independently chain-confirmed balance;
- **pending received** — valid received authorization not yet independently chain-confirmed;
- **reserved outgoing** — signed outgoing value that must not be treated as freely spendable locally.

Devices never gossip arbitrary balance numbers. They gossip signed payment events and settlement evidence. Every phone derives its own projection.

## 8. Persist-before-network rules

Sender:

```text
sign authorization / raw tx
        ↓
SQLite transaction
        ↓
persist payment + outbox + reservation
        ↓
COMMIT
        ↓
transmit
```

Recipient:

```text
receive packet
        ↓
validate transport integrity
        ↓
verify EIP-3009 authorization
        ↓
persist incoming payment/event
        ↓
COMMIT
        ↓
send DELIVERY_ACK
```

An ACK must never precede durable financial persistence.

The current Android foundation can post a native notification as soon as the envelope reaches the device. Financial promotion of the incoming authorization remains gated by viem verification. A future fully headless verifier may move that EIP-712 verification into native code; until then a killed WebView may require the app process to resume before the pending balance projection is promoted.

## 9. Mesh packet model

Every packet carries common routing/integrity metadata:

```text
version
messageId
eventId
paymentId
type
originDeviceId
destinationWallet
createdAt
expiresAt
hopCount
hopLimit
copyBudget
payloadHash
payload
devicePublicKey
deviceSignature
```

Key packet types:

- `PAYMENT_ENVELOPE`
- `DELIVERY_ACK`
- `SETTLEMENT_RECEIPT`

Routing metadata is bounded. Initial defaults are copy budget `3`, hop limit `6`, retention until authorization expiry.

`messageId` deduplicates transport. Payment ID + EIP-3009 nonce provide economic idempotency.

## 10. Store-and-forward behavior

Blee is delay tolerant, not merely direct peer-to-peer.

```text
A → B
A → C → B
A → C   (devices separate)   C → B later
```

A courier stores an envelope in SQLite and forwards it later. PAYMENT_ENVELOPE packets continue beyond the recipient so an Internet-connected mesh member can broadcast the sender-funded raw transaction. Settlement receipts are gossip events and travel back through the mesh.

## 11. Three-phone scenario

A and B are offline; C has Internet.

```text
A signs 5 USDC payment + sender-funded raw tx
       ↓ BLE
B receives envelope and is notified
       ↓ bounded mesh forwarding
C receives same envelope
       ↓
C sees Internet
       ↓
C submits A's raw bytes to Arc
       ↓
Arc charges A according to A's signed transaction
       ↓
C receives successful transaction receipt
       ↓ BLE gossip
A and B learn settlement state
```

C's wallet is irrelevant to the transaction.

## 12. Settlement evidence and finality

An offline phone can receive a real transaction hash/block receipt through the mesh, but it cannot independently query canonical chain state while fully offline. Therefore:

- `SETTLED_RELAY_REPORTED`: chain evidence arrived through another node;
- `CHAIN_CONFIRMED`: this phone independently verified chain state when Internet became available.

A later light-client/proof design can strengthen offline finality without changing the transport model.

## 13. Identity and privacy

Wallet keys authorize money. Android Keystore device keys authorize mesh transport messages.

```text
wallet identity
   └─ financial authorization

device identity
   └─ ACK / courier / transport evidence
```

The production protocol should use rotating BLE identifiers and authenticated/private peer sessions. Wallet addresses should not be continuously exposed as BLE advertising identity.

## 14. Background model

`BleeMeshService` is a native foreground service and uses Android connectivity callbacks rather than polling for Internet state. `START_STICKY` plus the boot/package receiver rebuilds the service after ordinary process/device lifecycle events when Android permits.

Modern Android can still restrict background work, and a user force-stop is authoritative. Blee must never claim it can override OS policy or silently enable Bluetooth/Wi-Fi.

## 15. Development rail

Current validated development rail:

- Arc Testnet
- chain ID `5042002`
- RPC `https://rpc.testnet.arc.network`
- USDC contract `0x3600000000000000000000000000000000000000`
- EIP-712 name `USDC`
- EIP-712 version `2`

The native automatic broadcaster is pinned to this rail for the test build.

## 16. Security boundaries

Before mainnet release, Blee still requires:

- private authenticated peer-session transport;
- nonce/fee-profile stress testing under external-wallet use;
- malicious packet/flooding tests;
- Android vendor/background-kill matrix testing;
- release signing and reproducible-build review;
- dedicated wallet/protocol security review;
- explicit policy for fee estimation as Arc mainnet parameters become final.

## 17. Frozen invariants

1. Persist before transmit.
2. Persist before ACK.
3. Offline delivery is not blockchain finality.
4. Devices exchange events/evidence, never asserted balances.
5. Every financial effect is idempotent.
6. Native Android owns network reliability; UI owns presentation.
7. Any Blee device may carry another user's encrypted/signed payment packet.
8. Any online Blee device may broadcast a valid sender-signed raw transaction.
9. **The sender funds the transaction; courier devices never spend their own wallet balance.**
10. Settlement receipts propagate through the mesh.
11. Wallet keys authorize money; device keys authorize transport.
12. Recovery must come from durable SQLite state after normal process/reboot lifecycle.
13. If a sender-funded raw transaction cannot be prepared safely, Blee degrades to `AUTH_ONLY` rather than inventing a nonce or charging another user.
