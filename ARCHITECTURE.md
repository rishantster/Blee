# Blee Mesh v2 — Frozen Architecture

Status: **frozen protocol foundation** for the next Android build.

Blee is an offline-first payment mesh. Internet availability controls blockchain settlement; it must not control whether Blee devices can create, persist, deliver, acknowledge, notify, carry, or reconcile payments.

## Architecture

```text
                         Arc / EVM
                            │
                    blockchain settlement
                            │
                    ┌───────▼────────┐
                    │ Settlement     │
                    │ Coordinator    │
                    └───────┬────────┘
                            │ signed settlement events
              ┌─────────────┴─────────────┐
              │                           │
       Internet transport           Local Blee mesh
                                     BLE / local LAN
              │                           │
              └─────────────┬─────────────┘
                            │
                    ┌───────▼────────┐
                    │ Local ledger   │
                    │ SQLite + WAL   │
                    └───────┬────────┘
                            │
                       Blee UI
```

Every Android installation contains a native `BleeMeshService`. The React/Capacitor UI presents local ledger state; it is not responsible for keeping the mesh alive.

## Native runtime

```text
BleeMeshService
├── DeviceIdentityManager
├── PeerDiscoveryManager
├── BluetoothTransport
├── LocalNetworkTransport
├── MeshRouter
├── CourierStore
├── DurableInbox
├── DurableOutbox
├── PaymentEventProcessor
├── ConnectivityObserver
├── SettlementCoordinator
├── ReconciliationEngine
└── NotificationEngine
```

The service is started by the native app after Blee has been opened and remains `START_STICKY` while Android permits it. Real-time BLE work belongs in the native foreground service. WorkManager may be used later for deferred recovery/retry jobs, but is not the real-time transport.

## Ledger model

Blee uses immutable payment events as the audit source of truth. Mutable payment rows are projections/cache for the UI.

Core tables:

- `payments`
- `payment_events`
- `mesh_inbox`
- `mesh_outbox`
- `mesh_seen_packets`
- `courier_envelopes`
- `peer_identities`
- `settlement_jobs`
- `settlement_receipts`
- `kv`

Every event carries a UTC epoch-millisecond timestamp. UI formatting is local-time date + hour + minute + second. Existing rows are migrated additively; payment history is never dropped during an upgrade.

## Payment lifecycle

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

Offline delivery is not chain finality.

User-facing wording can remain simpler: `Sending`, `Delivered nearby`, `Received offline`, `Settlement pending`, `Settled`, `Confirmed`.

## Balance model

Blee never collapses all money into one ambiguous number.

- **Confirmed / spendable** — independently chain-confirmed funds.
- **Pending received** — valid incoming authorization received locally but not yet chain-confirmed.
- **Reserved outgoing** — signed outgoing authorizations that must no longer be counted as freely spendable locally.

Blee devices gossip signed events and settlement evidence, **never arbitrary balance numbers**. Each phone derives its own projection from the ledger.

## Packet envelope

All mesh traffic uses a common envelope:

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
payloadHash
payload
deviceSignature
```

Initial packet types:

- `IDENTITY_HELLO`
- `PAYMENT_ENVELOPE`
- `DELIVERY_ACK`
- `SETTLEMENT_REQUEST`
- `SETTLEMENT_SUBMITTED`
- `SETTLEMENT_RECEIPT`
- `LEDGER_DIGEST`
- `EVENT_REQUEST`
- `EVENT_RESPONSE`

`messageId` provides transport deduplication. `paymentId` plus the EIP-3009 authorization nonce provides payment idempotency.

## Store-and-forward mesh

The mesh is delay-tolerant, not merely direct peer-to-peer discovery.

A sealed envelope may travel directly or through couriers:

```text
Rishant → Kumar

or

Rishant → Phone C → Phone D → Kumar
```

A device may carry an envelope and deliver it later when it encounters the destination.

Initial safety limits:

- courier copy budget: 3
- hop limit: 6
- retention: no longer than payment authorization expiry
- persistent deduplication: required
- retry: exponential backoff
- relay jitter: required

Financial traffic has priority over profile/media traffic.

## Courier vs settlement relay

These are separate capabilities.

### Mesh courier

A courier stores and forwards a sealed packet. It does not authorize the payment and does not need Internet.

### Settlement relay

A settlement relay has Internet, validates a signed payment authorization, submits it to the configured settlement path, obtains settlement evidence, and injects the resulting settlement event back into the mesh.

The production-preferred mode is **sponsored auto relay / paymaster**. A phone discovering an unsettled valid authorization sends it to the configured Blee relay service; the phone owner is not charged another user's gas.

Relay policies are explicit:

- `TESTNET_AUTO_RELAY`
- `SPONSORED_AUTO_RELAY`
- `USER_OPT_IN_RELAY`

No production build may embed a shared relayer private key inside the APK.

## Three-phone flow

If A and B are offline and C is online:

```text
A signs payment for B
       ↓ BLE
B persists + ACKs immediately
       ↓ mesh gossip
C receives authorization
       ↓ Internet
sponsored relay / Arc settlement
       ↓
C receives settlement receipt
       ↓ BLE mesh
A and B update automatically
```

A and B do not need Internet to learn the relay result if the receipt reaches them through the local mesh.

A fully offline phone records a relay receipt as `SETTLED_RELAY_REPORTED`. When it later obtains Internet itself it independently verifies the chain and advances to `CHAIN_CONFIRMED`.

## Native notifications

The recipient must not need the Activity screen open.

After a valid payment is durably persisted, Blee posts an Android notification such as:

`Payment received — Rishant sent 5 USDC · received nearby, settlement pending`

After settlement evidence arrives:

`Payment settled — 5 USDC from Rishant is now settled`

**Persist first, ACK/notify second.**

## Identity and privacy

Wallet identity and mesh device identity are separate.

```text
wallet key
   │ authorizes
   ▼
device identity key
   │
   ▼
rotating BLE identifier
```

Wallet keys authorize money. Device keys authorize mesh protocol traffic, ACKs and presence. BLE advertisements must not continuously expose the wallet address. Profile metadata is exchanged only after an authenticated peer session.

## Reconciliation

When two Blee devices meet they exchange compact ledger summaries and request only missing relevant events. The protocol is event synchronization, not database replication and not remote balance assignment.

Traffic priority:

- P0: payment authorization, delivery ACK, settlement receipt
- P1: event reconciliation, device/identity certificate
- P2: profile metadata, profile photo, historical repair

## Frozen invariants

1. Persist before transmit.
2. Persist before ACK.
3. Offline delivery is not blockchain finality.
4. Confirmed, pending received and reserved outgoing remain distinct.
5. Gossip signed events/evidence, never balance claims.
6. Every financial message is idempotent and persistently deduplicated.
7. Native service owns networking; React owns presentation.
8. Any eligible Blee device may act as a courier.
9. An online Blee device may trigger automatic settlement only under an explicit relay policy.
10. Settlement results propagate back through the mesh.
11. Every ledger transition has an immutable UTC timestamp.
12. Wallet keys authorize funds; device keys authorize mesh traffic.
13. BLE discovery must not expose raw wallet addresses as persistent identifiers.
14. Process death/restart recovers entirely from durable local state.
15. Losing Internet degrades settlement, not local payment communication.
16. Duplicate packets must never produce duplicate payment effects.
17. An ACK is sent only after the receiving transaction has committed to SQLite.
18. No app upgrade may drop payment history as a migration strategy.

These invariants are the implementation contract for Blee Mesh v2.