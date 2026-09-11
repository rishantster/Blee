# Blee

**Payments that keep moving, with or without the internet.**

Blee is an Android-first, self-custodial payment app with a native store-and-forward nearby network. Blee Mesh v2 lets devices create, persist, deliver, acknowledge, notify, carry and reconcile payments locally; Internet is needed only for blockchain settlement and independent chain verification.

The frozen protocol is in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Blee 2.1 — sender-funded Mesh v2

The settlement model is now explicit:

> **The sender pays any network fee. Any Blee phone with Internet may broadcast the sender's already-signed transaction. Courier phones never spend their own funds.**

Phone A prepares an EIP-3009 payment authorization and, when it has a cached chain nonce/fee profile, a sender-signed EIP-1559 raw transaction that calls `transferWithAuthorization`.

```text
Phone A offline
  signs payment + raw settlement transaction
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
       tx receipt
            │
            ▼
settlement receipt gossips back through Blee Mesh
```

Phone C:

- pays **zero** gas for A;
- signs **nothing** for A;
- never receives A's private key;
- cannot alter A's signed transaction;
- only contributes Bluetooth/storage/data connectivity and an RPC broadcast.

If Arc's eventual mainnet fee is zero or externally sponsored, this architecture does not change; the sender's actual fee becomes zero.

## What 2.1 contains

- native Android `BleeMeshService` foreground service;
- simultaneous BLE advertising + scanning;
- native fragmented GATT packet transport;
- durable SQLite/WAL inbox, outbox and payment journal;
- bounded store-and-forward courier routing;
- persistent packet deduplication;
- immutable `payment_events` timestamps;
- Android payment notifications;
- persistence before delivery ACK;
- EIP-3009 verification before financial acceptance;
- cached sender nonce/EIP-1559 fee profile;
- serialized local transaction-nonce reservation;
- sender-signed `SENDER_FUNDED_RAW_TX` attached to payment authorization;
- automatic `eth_sendRawTransaction` by any Internet-connected mesh node;
- settlement-receipt gossip back through BLE;
- connectivity callbacks that trigger settlement immediately;
- confirmed/spendable, pending-received and reserved-outgoing semantics;
- supplied Blee logo/wordmark, profile identity, QR receive and Activity timestamps.

## Why Blee keeps both authorization and raw transaction

The EIP-3009 authorization is the payment-level authority. The raw EIP-1559 transaction is the sender-funded settlement vehicle.

```text
EIP-3009 authorization
        +
sender-signed raw transaction
        ↓
permissionless broadcast by any Blee node
```

A courier cannot use the authorization to silently spend its own wallet balance. The courier only broadcasts sender-signed bytes.

If the raw transaction becomes stale because the sender's EOA nonce changed elsewhere, a third phone does not rescue it using its own gas. When the sender is online/unlocked again, Blee can reconcile and make a fresh sender-funded submission while the EIP-3009 authorization is still valid.

## Offline nonce/fee profile

An EOA cannot safely invent an account nonce while completely disconnected from chain state. Blee therefore caches a small settlement profile whenever the sender is online:

```text
chainId
sender address
pending account nonce
next local nonce
maxFeePerGas
maxPriorityFeePerGas
syncedAt
```

The profile is refreshed opportunistically when the app has Internet. Offline payment creation uses that cached state plus locally reserved outgoing nonces.

If no valid profile has ever been cached, Blee still creates and delivers the EIP-3009 authorization, but marks the settlement data `AUTH_ONLY`. Nearby payment delivery still works; third-phone sender-funded settlement waits until valid sender transaction state exists. Blee does not guess a nonce or make another user pay.

## Offline payment flow

Both A and B can be offline:

```text
A presses Send
   ↓
EIP-3009 authorization signed
sender-funded raw tx prepared when profile exists
   ↓
payment + outbox persisted to SQLite
   ↓
BLE delivery
   ↓
B receives native notification
   ↓
valid authorization is promoted to pending received
   ↓
DELIVERY_ACK travels back over BLE
```

The payment survives ordinary process/app restarts because financial state is not kept only in React memory.

### Background verification boundary

The native service can receive/store the envelope and notify while the UI is not visible. Financial promotion remains gated by viem EIP-712/EIP-3009 verification. In the current build, if the WebView process has been completely killed, that verification may occur when the app process resumes. The architecture deliberately does not show an unverified packet as money.

## Three-phone flow

A and B are offline, C is online:

```text
A ──BLE──► B
│          │
└── mesh ──┴──► C
               │
               │ A's signed raw tx
               ▼
              Arc
               │
               ▼
        settlement receipt
               │
         BLE mesh gossip
          ┌────┴────┐
          ▼         ▼
          A         B
```

C's wallet does not participate in the financial transaction.

## Payment states

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

`SETTLED_RELAY_REPORTED` is retained as an internal compatibility state meaning that settlement evidence arrived through the mesh. It does **not** mean the mesh relay paid gas.

## Balance semantics

Blee keeps these separate:

- **Confirmed / spendable** — independently chain-confirmed.
- **Pending received** — valid incoming authorization not yet independently confirmed.
- **Reserved outgoing** — signed outgoing value that should no longer be treated as freely available locally.

Blee devices gossip signed events and settlement evidence, never arbitrary balance numbers.

## Store-and-forward

The mesh is delay tolerant:

```text
A → B
A → C → B
A → C        then later        C → B
```

Initial routing limits:

- copy budget: `3`
- hop limit: `6`
- retention: until payment authorization expiry
- persistent dedup: enabled
- retry: bounded/exponential

Receiving the same envelope through several routes does not create several economic payments.

## Native service and notifications

The Android service owns:

- BLE scan/advertise;
- packet fragmentation/reassembly;
- durable courier queues;
- connectivity observation;
- automatic raw-transaction broadcasting;
- settlement receipt propagation;
- native Android notifications.

Modern Android still controls permission/background policy. Blee cannot silently force Bluetooth or Wi-Fi on, and a user force-stop remains authoritative.

## Persistence

Blee uses native Android SQLite with write-ahead logging.

Core tables include:

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

Normal lock/logout/restart/reboot must not erase payment history. Android Clear Storage and uninstall intentionally remove local data.

## Development settlement rail

The current validated test rail remains **Arc Testnet**:

- chain ID: `5042002`
- RPC: `https://rpc.testnet.arc.network`
- explorer: `https://testnet.arcscan.app`
- payment token contract: `0x3600000000000000000000000000000000000000`
- EIP-712 name: `USDC`
- EIP-712 version: `2`

The native automatic broadcaster is pinned to this validated chain/RPC in the 2.1 test build. An arbitrary custom EVM network is not automatically suitable for offline authorization or sender-funded background broadcasting.

## Build the APK

Requirements:

- macOS
- Node.js 22+
- Homebrew recommended
- Java 21
- Android command-line tools (builder can install if missing)

The builder prefers an existing Homebrew `openjdk@21`, so it should not re-download Temurin on a correctly configured Mac.

### Existing clone

```bash
cd ~/Blee-professional-build/Blee
git fetch origin
git checkout blee-professional
git pull --ff-only origin blee-professional

export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"
export PATH="$(brew --prefix openjdk@21)/bin:$PATH"

bash build-blee.command
```

### Fresh clone

```bash
git clone -b blee-professional --single-branch https://github.com/rishantster/Blee.git ~/Blee
cd ~/Blee

export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"
export PATH="$(brew --prefix openjdk@21)/bin:$PATH"

bash build-blee.command
```

Expected APK:

```text
dist/Blee-2.1.0-mesh-v2-debug.apk
```

The build runs a source-wiring verifier before Gradle. It fails if old sponsored-relay code (`configureRelay`, relay endpoint settings, or `attemptSponsoredSettlement`) survives into the generated app.

## Repository layout

```text
ARCHITECTURE.md                  frozen Blee Mesh v2 architecture
bootstrap/                       versioned base source/native snapshots
professional/                    professional UX snapshot
mesh-v2/
  android/                       foreground service + Capacitor bridge
  native/                        durable SQLite event store
  web/
    BleeRuntime.tsx              native/runtime bridge
    payments.ts.in               sender-funded settlement implementation
scripts/
  apply-blee-mesh-v2.py          final web/payment overlay
  apply-blee-mesh-v2-android.py  native Android installer
  verify-blee-mesh-v2.py         build-time architecture guard
build-blee.command               canonical build entrypoint
build-blee-professional.command  deterministic orchestrator
build-blee-macos.command         internal base builder
overrides/                       compatibility layer used earlier in build
```

The old sponsored relay API document has been removed because a Blee backend/paymaster is no longer required for the default third-phone settlement path.

## Required physical regression

Before calling this release-quality, test on real Android devices:

1. A/B online — direct send and settlement;
2. A/B offline — B receives native notification and nearby delivery persists;
3. recipient backgrounded — native service still receives packet;
4. process/reopen — payment journal survives;
5. A/B offline + C online — C broadcasts **A's raw transaction**, C's balance does not change, receipt returns through mesh;
6. duplicate multi-route delivery — one economic payment effect;
7. Bluetooth off/on — discovery re-arms;
8. Internet loss/return — settlement starts from connectivity callback;
9. sender raw transaction with stale EOA nonce — C does not spend its own gas; sender later reconciles;
10. authorization expiry — forwarding stops safely;
11. reboot/package update — durable mesh state recovers;
12. external use of sender wallet — nonce reconciliation behaves correctly.

## Status

Blee 2.1 Mesh v2 is still a **test build**, not a mainnet release. The sender-funded broadcaster removes the need for Phone C to pay gas, but production deployment still requires physical device-matrix testing, private authenticated peer sessions, release signing, malicious-mesh testing and a dedicated wallet/protocol security review.
