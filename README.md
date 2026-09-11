# Blee

**Payments that keep moving, with or without the internet.**

Blee is an Android-first, self-custodial payment app with a native store-and-forward nearby mesh. Internet controls blockchain settlement; it does not control whether Blee devices can create, persist, deliver, acknowledge, notify, carry or reconcile payments locally.

The frozen protocol foundation is documented in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Blee 2.1.1 — Mesh v2 + crash-atomic signing

The settlement rule is explicit:

> **The sender funds settlement. Any Blee phone with Internet may broadcast the sender's already-signed transaction. Courier phones never spend their own funds.**

Phone A prepares an EIP-3009 payment authorization and, when valid cached chain state is available, a sender-signed EIP-1559 raw transaction that calls `transferWithAuthorization`.

```text
Phone A offline
  signs payment authorization
  signs sender-funded raw settlement tx
            │
            │ BLE / store-and-forward
            ▼
Phone B / Phone C / Phone D
            │
     any node gets Internet
            │
            │ eth_sendRawTransaction(A's bytes)
            ▼
Arc
            │
       transaction receipt
            │
            ▼
settlement receipt gossips back through Blee Mesh
```

A courier phone:

- pays **zero** gas for another user;
- signs **nothing** for another user's payment;
- never receives the sender's private key;
- cannot alter the sender's signed transaction;
- only contributes nearby transport, local storage and Internet connectivity.

If Arc mainnet later has zero or externally sponsored fees, the architecture does not change; the sender's actual network cost simply becomes zero.

## Crash-atomic signing

Blee 2.1.1 adds a native SQLite signing ledger so a wallet signature is never treated as a loose in-memory object.

### 1. Reserve before signing

Before the wallet signs, native SQLite atomically records a `SIGNING` intent containing:

```text
signing ID
process/session ID
chain ID
sender
recipient
amount
EIP-3009 authorization nonce
EOA transaction nonce (when available)
expiry
```

The `signing_intents` table is the authoritative local nonce-reservation source. JavaScript serialization is only an additional guard.

### 2. Commit the exact signed bundle

After EIP-3009 and EIP-1559 signing, a second SQLite transaction stores the authorization, raw transaction and bundle hash and moves the intent to `READY`.

`createAuthorization()` does not return the signed bundle until that durable step succeeds.

### 3. Persist payment + signing state together

When the payment journal stores the outgoing payment, the same SQLite transaction:

```text
writes the payment row
validates it against the READY signing intent
moves signing state to PERSISTED
writes SIGNATURE_BUNDLE_PERSISTED audit event
```

If one part fails, the whole transaction rolls back.

### 4. Mesh queue is atomic too

Before transmission, native Android commits the payment envelope outbox row, `QUEUED` event and settlement job together. Transmission only starts after commit.

### 5. Recipient payment + ACK are atomic

After the recipient verifies the EIP-3009 authorization, native Android commits the incoming payment, `RECIPIENT_RECEIVED` event and durable `DELIVERY_ACK` outbox entry together. The ACK cannot be transmitted for a payment that was not durably recorded.

### Crash recovery

A previous process can leave a `SIGNING` row only if it died before the signed bundle became durable. Such an incomplete row is safe to mark `ABORTED` on a later signing session because it was never eligible for the payment journal or mesh.

`READY` and `PERSISTED` bundles are never reclaimed as unfinished signing attempts.

## What 2.1.1 contains

- native Android `BleeMeshService` foreground service;
- simultaneous BLE advertising + scanning;
- native fragmented GATT packet transport;
- durable SQLite/WAL payment and event ledger;
- crash-atomic `signing_intents` ledger;
- bounded store-and-forward courier routing;
- persistent packet deduplication;
- native Android payment notifications;
- EIP-3009 verification before financial acceptance;
- cached sender nonce/EIP-1559 fee profile;
- native transaction-nonce reservation before signing;
- sender-signed `SENDER_FUNDED_RAW_TX` settlement artifact;
- automatic `eth_sendRawTransaction` by any Internet-connected mesh node;
- settlement-receipt gossip through BLE;
- connectivity callbacks that trigger settlement immediately;
- confirmed/spendable, pending-received and reserved-outgoing semantics;
- persist-before-transmit and persist-before-ACK invariants;
- supplied Blee branding, profile identity, QR receive and Activity timestamps.

## Payment authority and settlement vehicle

Blee keeps both artifacts deliberately:

```text
EIP-3009 authorization      payment authority
        +
sender-signed raw tx       sender-funded settlement vehicle
```

A third phone can broadcast the raw transaction but cannot change the amount or recipient. If the sender's cached raw transaction becomes stale because the same EOA nonce was changed elsewhere, a courier does not rescue the payment using its own wallet. The sender reconciles and creates a fresh sender-funded submission while the EIP-3009 authorization remains valid.

## Offline chain profile

An EOA cannot safely invent its account nonce while completely disconnected. Blee therefore caches:

```text
chainId
sender address
pending chain nonce
next local nonce hint
maxFeePerGas
maxPriorityFeePerGas
syncedAt
```

The native signing-intent ledger remains authoritative for already reserved local transaction nonces.

If no usable profile has ever been cached, Blee degrades to `AUTH_ONLY`: the nearby payment authorization can still be created, delivered and acknowledged, but third-phone sender-funded blockchain settlement waits until valid sender transaction state exists. Blee never guesses a nonce or charges another user's wallet.

## Offline payment flow

Both A and B can be offline:

```text
A presses Send
   ↓
reserve durable signing intent
   ↓
sign EIP-3009 + optional sender-funded raw tx
   ↓
commit exact signed bundle
   ↓
commit payment journal
   ↓
commit mesh outbox
   ↓
BLE delivery
   ↓
B verifies authorization
   ↓
commit incoming payment + ACK
   ↓
ACK travels back over BLE
```

Financial state is reconstructed from SQLite/WAL, not React memory.

## Three-phone settlement

A and B are offline, C is online:

```text
A ──BLE──► B
│          │
└── mesh ──┴──► C
               │
               │ A's sender-signed raw tx
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

C's wallet does not participate in the transaction.

## Balance semantics

Blee separates:

- **Confirmed / spendable** — independently chain-confirmed.
- **Pending received** — valid incoming authorization not yet independently confirmed.
- **Reserved outgoing** — signed outgoing value no longer treated as freely available locally.

Devices exchange signed events and settlement evidence, never arbitrary balance assertions.

## Store-and-forward limits

Initial routing defaults:

- copy budget: `3`
- hop limit: `6`
- retention: no later than authorization expiry
- persistent deduplication: enabled
- retry: bounded/exponential

Receiving the same envelope through several routes must still produce one economic payment effect.

## Native/background model

The Android service owns BLE scan/advertise, packet fragmentation/reassembly, durable courier queues, connectivity observation, automatic raw-transaction broadcasting, settlement-receipt propagation and native notifications.

Modern Android still controls permission/background policy. Blee cannot silently force Bluetooth/Wi-Fi on and a user force-stop remains authoritative.

## Persistence tables

Core tables include:

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

Normal lock/logout/restart/reboot must not erase payment history. Android Clear Storage and uninstall intentionally remove local data.

## Current development rail

The validated test rail remains **Arc Testnet**:

- chain ID: `5042002`
- RPC: `https://rpc.testnet.arc.network`
- explorer: `https://testnet.arcscan.app`
- payment token: `0x3600000000000000000000000000000000000000`
- EIP-712 name: `USDC`
- EIP-712 version: `2`

The native automatic broadcaster is pinned to this validated rail in the current build.

## Build the APK

Requirements: macOS, Node.js 22+, Java 21 and Android command-line tools. Homebrew is recommended.

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
dist/Blee-2.1.1-mesh-v2-debug.apk
```

The build verifier blocks compilation if the crash-atomic signing ledger, sender-funded settlement path, native mesh service or atomic sender/recipient persistence wiring is missing.

## Repository layout

```text
ARCHITECTURE.md                  frozen Mesh v2 architecture
bootstrap/                       versioned base source/native snapshots
professional/                    professional UX snapshot
mesh-v2/
  android/                       native mesh service/templates
  native/                        SQLite/WAL store + atomic signing ledger
  web/
    BleeRuntime.tsx              native/runtime bridge
    payments.ts.in               settlement implementation
    atomicSigning.ts.in          crash-atomic signing coordinator
scripts/
  apply-blee-mesh-v2.py          web/store overlay
  apply-blee-mesh-v2-android.py  native Android installer + atomic hardening
  verify-blee-mesh-v2.py         build-time architecture guard
build-blee.command               canonical build entrypoint
build-blee-professional.command  deterministic orchestrator
```

## Required physical regression

Before mainnet/release-quality claims, test on real Android devices:

1. kill the sender process before signing, during signing, after `READY`, after payment persistence and after outbox creation;
2. verify no duplicate EIP-3009 or EOA transaction nonce is reused incorrectly;
3. A/B online direct payment;
4. A/B offline direct nearby payment + native notification;
5. recipient backgrounded/process lifecycle recovery;
6. A/B offline + C online — C broadcasts A's raw transaction and C's balance does not change;
7. duplicate multi-route delivery — one economic effect;
8. Bluetooth off/on discovery recovery;
9. Internet loss/return triggers immediate settlement work;
10. stale sender EOA nonce fails safely without charging the courier;
11. authorization expiry stops forwarding safely;
12. reboot/package update recovers durable state;
13. same wallet used externally while Blee holds offline reservations;
14. fault injection around every SQLite transaction boundary.

## Status

Blee 2.1.1 Mesh v2 is a **test build**, not a mainnet release. The architecture now enforces database-backed signing reservations and persist-before-network boundaries, but production still requires physical fault-injection/device-matrix testing, private authenticated peer sessions, malicious-mesh testing, release signing and a dedicated wallet/protocol security review.
