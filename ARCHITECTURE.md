# Blee Mesh v2 — Frozen Architecture

Status: **frozen for Blee 2.1.1 implementation**

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
- If Arc later makes the fee zero or a third party sponsors it, the architecture does not change; sender cost simply becomes zero.

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

Blee 2.1.1 makes signing persistence explicit. There are two SQLite transaction boundaries around wallet signing.

### Boundary A — reserve before signing

Before either signature is allowed to become usable by the app, native SQLite reserves the signing intent:

```text
BEGIN IMMEDIATE/SQLite transaction

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

`signing_intents` is therefore the authoritative local nonce-reservation ledger. JavaScript serialization is an additional guard, not the source of truth.

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

Therefore a signed payment cannot reach the payment journal or mesh from an uncommitted in-memory signing operation.

### Process death during signing

A row left in `SIGNING` by a previous app/WebView process is safe to abandon because the architecture forbids `SIGNING` rows from entering the payment journal or mesh.

The next signing session marks old incomplete `SIGNING` rows `ABORTED`. Their EOA nonce may then be reused because no durable/transmissible raw transaction was ever committed.

Rows in `READY` or `PERSISTED` are never reclaimed this way.

## 5. Payment-journal atomicity

When the existing Blee payment journal persists an outgoing payment, one SQLite transaction performs all of the following:

```text
BEGIN

write/replace payments row
validate payment against READY signing_intent
promote signing_intent → PERSISTED
append SIGNATURE_BUNDLE_PERSISTED audit event

COMMIT
```

If any validation fails, the payment row rolls back as well.

For pre-2.1.1 durable outgoing payments, the store has an explicit one-time legacy migration path that synthesizes a `PERSISTED` signing record from the already durable payment payload. New payments always carry the atomic-signing marker.

## 6. Mesh-outbox atomicity

A durable payment is not enough by itself. The mesh must not create a partially initialized transmissible state.

For each outgoing payment, the generated Android `BleeMeshDb` commits:

```text
BEGIN

create PAYMENT_ENVELOPE outbox row
append QUEUED event
create/update settlement job

COMMIT
```

A crash cannot leave a transmissible outbox packet without its corresponding queue event and settlement job.

Transmission starts only after this transaction commits.

## 7. Recipient ACK atomicity

The recipient follows the inverse rule.

```text
receive packet
    ↓
validate transport integrity
    ↓
verify EIP-3009 authorization
    ↓
BEGIN SQLite transaction

persist incoming payment
append RECIPIENT_RECEIVED event
persist DELIVERY_ACK in outbox

COMMIT
    ↓
ACK may be transmitted
```

An ACK can never be durably queued for a payment that was not durably recorded.

The native service may notify that an envelope arrived, but financial promotion remains gated by EIP-3009 verification. An unverified packet is never presented as spendable money.

## 8. Offline nonce and fee profile

An EOA cannot safely invent a future account nonce while completely disconnected from chain state. Blee caches a settlement profile while online:

```text
chainId
sender address
pending chain nonce
next local nonce hint
maxFeePerGas
maxPriorityFeePerGas
syncedAt
```

The native `signing_intents` table remains authoritative for already reserved local nonces across crashes. The cached `nextNonce` is only a hint and may not move backwards.

When A creates an offline payment with a usable profile, Blee:

1. generates the EIP-3009 authorization nonce;
2. atomically reserves the next EOA transaction nonce;
3. signs the authorization;
4. signs the EIP-1559 settlement transaction with conservative cached fee caps;
5. atomically stores the exact signatures/raw transaction;
6. returns the bundle to the payment journal;
7. atomically persists payment + signing state;
8. atomically creates the mesh outbox state;
9. allows transmission.

If no usable chain profile has ever been cached, Blee creates `AUTH_ONLY`. Nearby payment authorization/delivery still works, but automatic third-phone sender-funded settlement cannot be fabricated without valid chain nonce/fee state.

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

Every material transition records a UTC epoch-millisecond timestamp.

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

Signing-intent state is separate:

```text
SIGNING → READY → PERSISTED
    └────→ ABORTED   (only before durable finalization)
```

`SETTLED_RELAY_REPORTED` means settlement evidence arrived through another mesh node. It does not imply that node paid gas.

## 11. Balance semantics

Blee keeps these concepts separate:

- **confirmed / spendable** — independently chain-confirmed funds;
- **pending received** — valid received authorization not yet independently chain-confirmed;
- **reserved outgoing** — signed outgoing value that must not be treated as freely available locally.

Devices gossip signed events/evidence, never arbitrary balance numbers. Every device derives its own projection.

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

Initial routing defaults:

- copy budget `3`
- hop limit `6`
- retention no later than payment-authorization expiry
- persistent deduplication
- bounded/exponential retry

`messageId` provides transport deduplication. Payment ID + EIP-3009 authorization nonce provide economic idempotency.

## 13. Store-and-forward behavior

Blee is delay tolerant:

```text
A → B
A → C → B
A → C      devices separate      C → B later
```

A courier stores an envelope and forwards it later. Payment envelopes may continue beyond the recipient so an Internet-connected Blee node can broadcast the sender-funded raw transaction. Settlement receipts travel back through the mesh.

## 14. Three-phone scenario

A and B are offline; C has Internet.

```text
A signs 5 USDC authorization + sender-funded raw tx
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

A fully offline phone cannot independently query canonical Arc state. Therefore:

- `SETTLED_RELAY_REPORTED` — settlement evidence arrived through another node;
- `CHAIN_CONFIRMED` — this phone independently verified chain state when Internet became available.

A future light-client/proof layer can strengthen offline finality without changing the transport architecture.

## 16. Identity and privacy

Wallet keys authorize money. Android Keystore device keys authorize mesh transport messages.

```text
wallet identity
   └─ financial authorization

device identity
   └─ ACK / courier / transport evidence
```

Production should use rotating BLE identifiers and authenticated/private peer sessions. Wallet addresses should not be continuously exposed as BLE advertising identity.

## 17. Background model

`BleeMeshService` is a native foreground service and uses Android connectivity callbacks. `START_STICKY` plus boot/package recovery re-arms ordinary service state when Android permits.

Modern Android can still restrict background work, and user force-stop is authoritative. Blee cannot silently force Bluetooth or Wi-Fi on.

## 18. Development settlement rail

Current validated rail:

- Arc Testnet
- chain ID `5042002`
- RPC `https://rpc.testnet.arc.network`
- USDC contract `0x3600000000000000000000000000000000000000`
- EIP-712 name `USDC`
- EIP-712 version `2`

The native automatic broadcaster is pinned to this rail in the current test build.

## 19. Security work before mainnet

Blee still requires:

- private authenticated peer-session transport;
- malicious packet/flooding tests;
- crash/fault-injection tests at every atomic boundary;
- nonce/fee-profile stress tests while the same wallet is used externally;
- Android vendor/background-kill matrix testing;
- release signing and reproducible-build review;
- dedicated wallet/protocol security review;
- explicit fee-estimation policy when Arc mainnet parameters are final.

## 20. Frozen invariants

1. **Reserve signing intent before wallet signing.**
2. **Do not return a signed bundle until its exact artifacts are durably committed.**
3. **Payment row and signing state commit atomically.**
4. **Mesh outbox, queue event and settlement job commit atomically.**
5. **Recipient payment and durable ACK commit atomically.**
6. Persist before transmit.
7. Persist before ACK transmission.
8. Offline delivery is not blockchain finality.
9. Devices exchange signed events/evidence, never asserted balances.
10. Every financial effect is idempotent.
11. Native Android owns network reliability; UI owns presentation.
12. Any Blee device may carry another user's signed/encrypted payment packet.
13. Any online Blee device may broadcast a valid sender-signed raw transaction.
14. **The sender funds settlement; courier devices never spend their own wallet balance.**
15. Settlement receipts propagate through the mesh.
16. Wallet keys authorize money; device keys authorize transport.
17. Recovery comes from durable SQLite/WAL state after normal process/reboot lifecycle.
18. If sender-funded raw settlement cannot be prepared safely, Blee degrades to `AUTH_ONLY` rather than inventing a nonce or charging another user.
