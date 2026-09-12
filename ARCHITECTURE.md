# Blee Architecture — Canonical Protocol Foundation

Status: **canonical architecture for the Blee Android implementation**

`main` is the release/source-of-truth branch. The supported build command is `bash build-blee.command`. APK artifacts are versioned from Android `versionName`; release 2.6.0 produces only `dist/Blee-2.6.0.apk`.

Blee is an offline-first, self-custodial payment system. Internet availability controls blockchain settlement, not whether Blee devices can create, persist, deliver, acknowledge, notify, carry or reconcile payments.

## 1. Architectural rule

The native Android process is the network node. React/Capacitor renders and verifies application state; it is not responsible for keeping the mesh alive.

```text
Blee UI / wallet signing
        │
        ▼
SQLite / WAL event + signing ledger
        │
        ▼
BleeMeshService
  ├─ BLE scanner + advertiser
  ├─ GATT transport / fragmentation
  ├─ durable inbox + outbox
  ├─ bounded store-and-forward routing
  ├─ connectivity observer
  ├─ sender-funded settlement broadcaster
  └─ Android notifications
```

## 2. Settlement rule: sender pays, courier only broadcasts

A third Blee phone must never spend its owner's funds to settle somebody else's payment.

Phone A creates two cryptographic artifacts:

1. an EIP-3009 `TransferWithAuthorization` authorization; and
2. when a cached chain nonce/fee profile exists, a sender-signed EIP-1559 transaction that calls `transferWithAuthorization`.

The EVM transaction is signed by A. Therefore any network fee is charged to A. Phone C only submits already-signed bytes with `eth_sendRawTransaction`.

```text
Phone A
  signs EIP-3009 authorization
  signs EIP-1559 settlement transaction
          │
          │ BLE / store-and-forward
          ▼
Phone B / C / D
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
SETTLEMENT_RECEIPT gossips through Blee Mesh
```

### Settlement invariants

- Phone C signs nothing for A.
- Phone C never uses A's private key.
- Phone C never pays A's gas.
- Phone C cannot alter recipient, amount, calldata, chain ID, transaction nonce, gas limit or fee caps without invalidating A's signature.
- Automatic background broadcast is pinned to Blee's validated settlement rail.
- If sender-funded raw settlement cannot be prepared safely, Blee degrades to `AUTH_ONLY` rather than charging another user.

## 3. EIP-3009 remains the payment authority

The raw transaction is the settlement vehicle, not the payment authority.

```text
EIP-3009 authorization
       +
sender-signed EIP-1559 transaction
       ↓
permissionless broadcast by any online Blee node
```

If the cached raw transaction becomes stale because the sender changed the EOA nonce elsewhere, a courier does not rescue it with its own gas. The sender later reconciles and creates a fresh sender-funded submission while the authorization is still valid.

## 4. Crash-atomic signing

Blee uses two SQLite transaction boundaries around wallet signing.

### Boundary A — reserve before signing

Before either signature is allowed to become usable by the app, native SQLite reserves the signing intent:

```text
BEGIN SQLite transaction

signing_id
session_id
chain_id
sender
recipient
amount
authorization_nonce
EOA tx_nonce (when a synced profile exists)
state = SIGNING
expiry

COMMIT
```

Only after this commit may Blee ask the wallet to produce the EIP-3009 signature and sender-funded EIP-1559 signature.

`signing_intents` is the authoritative local nonce-reservation ledger. JavaScript serialization is an additional guard, not the source of truth.

### Boundary B — persist exact signatures before return

After signing succeeds, Blee commits the exact signed bundle:

```text
BEGIN SQLite transaction

verify reserved sender / recipient / amount / auth nonce
verify reserved EOA nonce matches signed raw tx
store complete authorization JSON
store complete broadcast/raw-tx JSON
store bundle hash
state = READY

COMMIT
```

`createAuthorization()` does not return the signed bundle until Boundary B succeeds.

A row left in `SIGNING` by a previous process may be abandoned because `SIGNING` rows are forbidden from entering the payment journal or mesh. Rows in `READY` or `PERSISTED` are never reclaimed that way.

## 5. Payment-journal atomicity

When the payment journal persists an outgoing payment, one SQLite transaction writes/replaces the payment row, validates the corresponding READY signing intent, promotes it to `PERSISTED`, and appends the `SIGNATURE_BUNDLE_PERSISTED` audit event.

A stale WebView payment projection must never move a payment backwards after native mesh state has advanced. Native state transitions are monotonic.

## 6. Mesh-outbox atomicity

For each outgoing payment, the generated Android `BleeMeshDb` commits the payment envelope outbox row, `QUEUED` event and settlement job atomically. Transmission begins only after that transaction commits.

## 7. Recipient ACK atomicity

The recipient validates transport integrity and the EIP-3009 authorization, then commits the incoming payment, `RECIPIENT_RECEIVED` event and durable `DELIVERY_ACK` together. ACK transmission is allowed only after commit.

## 8. Offline nonce and fee profile

Blee caches chain ID, sender address, pending chain nonce, next local nonce hint, fee caps and sync timestamp while online.

If no usable profile has ever been cached, Blee creates `AUTH_ONLY`. Nearby payment authorization/delivery still works, but third-phone automatic sender-funded settlement cannot be fabricated without valid chain nonce/fee state.

## 9. Durable ledger

Core SQLite tables:

- `payments`
- `payment_events`
- `signing_intents`
- `mesh_inbox`
- `mesh_outbox`
- `mesh_seen_packets`
- `courier_envelopes`
- `settlement_jobs`
- `settlement_receipts`
- `peer_identities`
- `kv`

Write-ahead logging is enabled. Schema changes are additive. Payment history is never dropped as an upgrade strategy.

## 10. Payment state

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

`SETTLED_RELAY_REPORTED` means settlement evidence arrived through another mesh node. It is not equivalent to local chain verification.

## 11. Balance semantics

Blee keeps these concepts separate:

- **confirmed / spendable** — independently chain-confirmed funds;
- **pending received** — valid received authorization not yet independently chain-confirmed;
- **reserved outgoing** — signed outgoing value not considered freely available locally.

Devices exchange signed events/evidence, never arbitrary balance numbers.

## 12. Mesh packet model

Common envelope fields:

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

Primary packet types:

- `PAYMENT_ENVELOPE`
- `DELIVERY_ACK`
- `SETTLEMENT_RECEIPT`

Routing is bounded by expiry, hop limit, copy budget, persistent deduplication and retry backoff. Fragment assemblies, peer caches and in-memory packet buffers must also be bounded and expired.

## 13. Store-and-forward behavior

Blee is delay tolerant:

```text
A → B
A → C → B
A → C      devices separate      C → B later
```

Payment envelopes may continue beyond the recipient so an Internet-connected Blee node can broadcast the sender-funded raw transaction. Settlement receipts travel back through the mesh.

## 14. Three-phone scenario

A and B are offline; C has Internet.

```text
A signs authorization + sender-funded raw tx
       ↓ BLE
B receives/verifies/persists and queues ACK
       ↓ bounded mesh forwarding
C receives same envelope
       ↓
C sees Internet
       ↓
C calls eth_sendRawTransaction(A's bytes)
       ↓
Arc charges A under A's signed transaction
       ↓
C observes successful receipt
       ↓ BLE gossip
A and B learn settlement state
```

C's wallet is irrelevant to the transaction.

## 15. Settlement evidence and finality

A relay-reported receipt is accepted only when its transaction hash matches the sender-signed settlement transaction committed in the payment bundle. Once a device has Internet, it independently verifies canonical chain state before promoting the payment to `CHAIN_CONFIRMED`.

## 16. Identity and privacy

Wallet keys authorize money. Android Keystore device keys authorize mesh transport messages. Wallet addresses must not be treated as permanent public BLE advertising identifiers; rotating/authenticated peer identity is the target privacy model.

## 17. Background model

`BleeMeshService` is a native foreground service and uses Android connectivity callbacks. `START_STICKY` plus boot/package recovery re-arms ordinary service state when Android permits.

Android runtime Bluetooth permissions are requested before nearby discovery can operate. Bluetooth adapter state changes must reset/re-arm scanning and advertising. The app cannot silently force Bluetooth or Wi-Fi on, and user force-stop is authoritative.

## 18. Development settlement rail

Current validated rail:

- Arc Testnet
- chain ID `5042002`
- RPC `https://rpc.testnet.arc.network`
- USDC contract `0x3600000000000000000000000000000000000000`
- EIP-712 name `USDC`
- EIP-712 version `2`

## 19. Security/release work

Before a production release, Blee still requires physical multi-device regression, malicious packet/flooding tests, crash/fault-injection at atomic boundaries, Android vendor/background-kill testing, release signing/reproducible-build review and dedicated wallet/protocol security review.

## 20. Frozen invariants

1. Reserve signing intent before wallet signing.
2. Do not return a signed bundle until exact artifacts are durably committed.
3. Payment row and signing state commit atomically.
4. Mesh outbox, queue event and settlement job commit atomically.
5. Recipient payment and durable ACK commit atomically.
6. Persist before transmit.
7. Persist before ACK transmission.
8. Offline delivery is not blockchain finality.
9. Devices exchange signed events/evidence, never asserted balances.
10. Every financial effect is idempotent.
11. Native Android owns network reliability; UI owns presentation.
12. Any Blee device may carry another user's signed/encrypted payment packet.
13. Any online Blee device may broadcast a valid sender-signed raw transaction.
14. The sender funds settlement; courier devices never spend their own wallet balance.
15. Settlement receipts are pinned to the sender-signed transaction and propagate through the mesh.
16. Wallet keys authorize money; device keys authorize transport.
17. Recovery comes from durable SQLite/WAL state after normal process/reboot lifecycle.
18. Stale UI state can never downgrade newer native ledger state.
19. Fingerprint UI appears only when compatible fingerprint hardware is actually available/enrolled.
20. The canonical public APK filename includes Android `versionName` and is `Blee-2.6.0.apk` for this release.
