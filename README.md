# Blee

**Payments that keep moving, with or without the internet.**

Blee is an Android-first, self-custodial payment app with a native store-and-forward nearby network. Blee Mesh v2 separates local payment delivery from blockchain settlement: devices can create, persist, deliver, acknowledge, notify, carry and reconcile payments without Internet; Internet is needed for final settlement and independent chain verification.

The frozen architecture is documented in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Blee 2.0 — Mesh v2

The 2.0 build keeps the existing Blee wallet/payment UX and adds the new protocol foundation:

- native Android `BleeMeshService` rather than foreground React screens owning mesh reliability;
- BLE advertising + scanning while the native service is active;
- native store-and-forward packet transport;
- persistent mesh inbox/outbox and deduplication;
- immutable `payment_events` ledger with UTC millisecond timestamps;
- Android payment notifications;
- recipient persistence before delivery ACK;
- sender persistence before transmission;
- courier envelopes for delay-tolerant forwarding;
- settlement-receipt propagation back through the mesh;
- connectivity callbacks that wake settlement work immediately when a route to the Internet appears;
- distinct confirmed/spendable, pending-received and reserved-outgoing semantics;
- supplied Blee logo/wordmark, QR receive, identity/profile UX and timestamped Activity from the 1.4 layer;
- additive SQLite migration: payment history is never dropped as an upgrade strategy.

## The core rule

**Blee devices exchange signed events and settlement evidence, never arbitrary balance numbers.**

Each phone derives its own balance projection from its local ledger.

Offline receipt is therefore visible immediately but is not falsely represented as chain-confirmed spendable money.

## Payment state

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

User-facing labels can remain simpler: `Sending`, `Delivered nearby`, `Received offline`, `Settlement pending`, `Settled`, `Confirmed`.

## Balance semantics

Blee maintains three separate concepts:

- **Confirmed / spendable** — independently chain-confirmed funds.
- **Pending received** — valid incoming payment authorization received locally but not yet chain-confirmed.
- **Reserved outgoing** — signed outgoing authorizations that should no longer be treated as freely available locally.

Example: if Kumar has 10 confirmed USDC and receives 5 USDC while both phones are offline, Blee can show 15 total visible while keeping 10 spendable and 5 pending until settlement.

## Store-and-forward mesh

The mesh is not limited to direct A → B delivery.

```text
Rishant → Kumar

or

Rishant → Phone C → Phone D → Kumar
```

Intermediate Blee devices can carry a payment envelope and forward it later. Mesh v2 uses persistent deduplication and bounded routing metadata so receiving the same payment through multiple paths does not create duplicate payment effects.

Initial routing limits are defined in `ARCHITECTURE.md`.

## Three-phone settlement

If A and B are offline while C has Internet:

```text
A signs payment for B
       ↓ BLE
B persists + acknowledges immediately
       ↓ mesh gossip
C receives the signed authorization
       ↓ Internet
sponsored relay / paymaster
       ↓
C receives settlement evidence
       ↓ BLE mesh
A and B update automatically
```

A fully offline phone records the returned evidence as `SETTLED_RELAY_REPORTED`. When that phone later has Internet it independently checks the chain and advances to `CHAIN_CONFIRMED`.

### Important: third-phone gas

Blee does **not** embed a shared relayer private key in the APK and does not silently charge Phone C's owner for other people's gas.

The production-preferred architecture is sponsored auto-relay/paymaster. Mesh v2 already includes the client path for a configured HTTPS relay endpoint. The contract is documented in [`RELAY_API.md`](RELAY_API.md).

Until a relay/paymaster endpoint is configured, offline transport, ACKs, notifications, courier forwarding and settlement-receipt gossip remain available, while autonomous background third-phone settlement is intentionally not faked.

## Native notifications

Once the recipient has durably committed a valid incoming payment to SQLite, Blee can post an Android notification such as:

> Payment received — Rishant sent 5 USDC · settlement pending

Settlement evidence can generate a second notification without requiring the Activity screen to be open.

On Android 13+, the app requests notification permission. Bluetooth/Nearby permissions still need to be granted by the user; modern Android does not allow an app to silently force Bluetooth or Wi-Fi on.

## Ledger and persistence

Blee uses native Android SQLite with write-ahead logging.

Core tables now include:

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

Every ledger event records an immutable UTC epoch-millisecond timestamp. Activity renders local date + time down to seconds.

Normal app restart, wallet lock/logout and phone restart must not erase payment history. Android **Clear storage / Clear data** and uninstall intentionally remove the local database.

## Identity and privacy

The wallet key remains the authority for money. Mesh v2 also creates a device identity key in Android Keystore for mesh traffic.

```text
wallet identity
   │
   ▼
device identity
   │
   ▼
BLE transport identity
```

The payment authorization remains independently verifiable; mesh device signatures are transport evidence, not permission to move funds.

The frozen protocol requires rotating/non-wallet BLE identifiers and authenticated profile exchange before production mainnet use. The current Mesh v2 native foundation should therefore still be treated as a test build pending the final private peer-session/Noise-style transport layer and production security review.

## Settlement network

The bundled validated development network remains **Arc Testnet**:

- Chain ID: `5042002`
- RPC: `https://rpc.testnet.arc.network`
- Explorer: `https://testnet.arcscan.app`
- Payment token contract: `0x3600000000000000000000000000000000000000`
- EIP-712 token name: `USDC`
- EIP-712 version: `2`

Blee uses EIP-3009-style payment authorizations for the current settlement rail. Adding an arbitrary EVM chain does not make every ERC-20 suitable for offline authorization/settlement.

## Build the Android APK

Requirements:

- macOS
- Node.js 22+
- Homebrew recommended
- Android command-line tools are installed automatically if missing
- Java 21; the build prefers an existing Homebrew `openjdk@21` installation before using the legacy download fallback

Fresh clone:

```bash
git clone -b blee-professional --single-branch https://github.com/rishantster/Blee.git ~/Blee
cd ~/Blee
bash build-blee.command
```

Existing clone:

```bash
cd ~/Blee
git fetch origin
git checkout blee-professional
git pull --ff-only origin blee-professional
bash build-blee.command
```

Expected output:

```text
dist/Blee-2.0.0-mesh-v2-debug.apk
```

The builder reconstructs the versioned app source, restores the native plugins, applies wallet/network support, applies the professional identity/QR/profile layer, applies the supplied Blee branding and ledger timestamps, applies Mesh v2, generates Android, installs the native mesh service, compiles the APK and verifies the archive.

## Repository layout

```text
ARCHITECTURE.md               frozen Mesh v2 architecture and invariants
RELAY_API.md                  sponsored auto-relay/paymaster contract
bootstrap/                    versioned base source/native plugin snapshots
professional/                 professional UX source snapshot
mesh-v2/                      Mesh v2 native/web source templates
  android/                    foreground mesh service + Capacitor bridge
  native/                     durable SQLite event-ledger store
  web/                        runtime bridge
scripts/                      deterministic build overlays/installers
overrides/                    wallet/network/recovery compatibility layer
build-blee.command            canonical build entrypoint
build-blee-professional.command  implementation build orchestrator
build-blee-macos.command      internal base build used by the orchestrator
```

Old `build-blee-final.command` and `build-blee-gasfix.command` entrypoints were removed. Use `build-blee.command`.

## Required physical regression

Before treating a build as release-quality, test at least this matrix on real Android phones:

1. both phones online — direct send + settlement;
2. both phones offline — sender persists, recipient receives/gets notified immediately, ACK returns over BLE;
3. recipient app backgrounded — native notification still arrives;
4. sender/recipient process killed and reopened — journal survives;
5. A + B offline, C online — C carries the authorization toward the configured settlement relay, then settlement receipt gossips back;
6. duplicate delivery over several routes — exactly one economic payment effect;
7. Bluetooth loss/re-enable — service re-arms discovery;
8. Internet loss/return — connectivity callback wakes settlement/reconciliation;
9. authorization expiry — packet stops forwarding and payment resolves safely;
10. device reboot/app restart — outbox/inbox and ledger recover from SQLite.

## Current status

Blee 2.0 Mesh v2 is a **test architecture/build**, not a mainnet release. The repo now contains the native service, durable event-ledger schema, mesh courier path, notifications, settlement-receipt propagation and sponsored-relay client interface. Production deployment still requires a configured relay/paymaster, private authenticated peer-session transport, release signing, device-matrix regression and a dedicated security review.
