# Blee

**Payments that keep moving, with or without the internet.**

Blee is an Android-first, self-custodial payment app with a native store-and-forward nearby mesh. Internet controls blockchain settlement; it does not control whether Blee devices can create, persist, deliver, acknowledge, notify, carry or reconcile payments locally.

The frozen protocol foundation is documented in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Blee 2.2 — premium Mesh v2 hardening

Blee 2.2 keeps the frozen sender-funded Mesh v2 protocol and hardens the actual Android product around four areas found during physical testing:

- crash-atomic signing now accepts Capacitor numeric values safely (`chainId`, expiry and local transaction nonce);
- the app no longer intentionally logs the user out because of inactivity/backgrounding — explicit logout remains authoritative for the active app process;
- wallet passphrase minimum is **8 characters** instead of 12;
- Bluetooth discovery runs in low-latency/high-power LE mode and negotiates 1M/2M/LE Coded PHY where hardware permits;
- every screen receives a single premium monochrome design system, with restrained motion, consistent surfaces, typography and centered Blee brand treatment.

The settlement rule remains:

> **The sender funds settlement. Any Blee phone with Internet may broadcast the sender's already-signed transaction. Courier phones never spend their own funds.**

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

A courier phone pays zero gas for another user, signs nothing for another user's payment, never receives the sender's private key and cannot alter the sender's signed transaction.

## Crash-atomic signing

Blee uses a native SQLite signing ledger so a wallet signature is never treated as a loose in-memory object.

### Reserve before signing

Before the wallet signs, SQLite records a `SIGNING` intent containing the signing ID, process/session ID, chain ID, sender, recipient, amount, EIP-3009 authorization nonce, optional EOA transaction nonce and expiry.

### Commit exact signed artifacts

After EIP-3009 and EIP-1559 signing, a second SQLite transaction stores the authorization, raw transaction and bundle hash and moves the intent to `READY`.

`createAuthorization()` does not return until that durable step succeeds.

### Persist payment + signing state together

When the payment journal stores the outgoing payment, the same SQLite transaction validates the `READY` signing intent, moves it to `PERSISTED` and records `SIGNATURE_BUNDLE_PERSISTED`.

### Persist before network

Native Android commits the payment envelope outbox row, `QUEUED` event and settlement job before transmission. The recipient similarly commits the incoming payment and durable ACK before the ACK may be transmitted.

### Capacitor bridge hardening

Physical testing exposed a bridge edge case where Java's `PluginCall.getLong()` could see `chainId` as an incompatible JSON numeric representation and reject a valid Arc chain ID.

Blee 2.2 handles bridge numerics explicitly and also sends signing numerics as lossless strings from TypeScript. The native side accepts either a JSON number or numeric string before the signing transaction begins.

## Session policy

The product policy is now simple:

> **Blee does not intentionally log an unlocked user out because the app was idle or backgrounded. The user remains signed in for the lifetime of the active app process until they explicitly choose Log out.**

This removes the old inactivity/auto-lock behavior that repeatedly forced passphrase entry during normal use.

Android can still terminate an app process under OS pressure, a device reboot changes process state, and a user force-stop remains authoritative. Those OS lifecycle events are distinct from Blee intentionally logging a user out.

## Wallet passphrase

New/imported encrypted wallets now require a minimum passphrase length of **8 characters**. Existing encrypted wallet backups and PBKDF2/AES-GCM protection remain compatible.

## Bluetooth discovery

Bluetooth LE operates in the 2.4 GHz ISM band; there are no extra Bluetooth frequency bands an Android app can enable. Blee 2.2 instead uses the strongest standards-compliant discovery configuration available through Android:

- `SCAN_MODE_LOW_LATENCY`;
- aggressive matching and immediate scan delivery;
- `ADVERTISE_MODE_LOW_LATENCY`;
- high advertising transmit power;
- automatic scan restart after Android scanner failures;
- high-priority GATT connection requests;
- preference for all supported LE PHYs: 1M, 2M and LE Coded;
- larger negotiated MTU with automatic peer fallback.

The service continues simultaneous advertising + scanning inside the foreground `BleeMeshService`.

## Premium monochrome UI

Blee 2.2 keeps the existing Blee logo/wordmark and moves the product to one consistent crypto-fintech visual system:

- monochrome only: off-white, white, black and neutral greys;
- centered, properly spaced Blee brand placement instead of a corner-pinned logo;
- rounded premium system typography with tabular numeric treatment;
- consistent cards, sheets, inputs, buttons and bottom navigation;
- monochrome error/status surfaces instead of prototype-style coloured alerts;
- restrained press and sheet transitions;
- accessibility support for reduced motion;
- the same design tokens across Home, Nearby, Send, Receive, Activity, Profile, Settings and wallet/recovery surfaces.

## Payment authority and settlement vehicle

Blee deliberately keeps both artifacts:

```text
EIP-3009 authorization      payment authority
        +
sender-signed raw tx       sender-funded settlement vehicle
```

A third phone can broadcast the raw transaction but cannot change amount, recipient, calldata, nonce or signed fee caps. If the sender's raw transaction becomes stale because the same EOA nonce changed elsewhere, a courier does not rescue the payment using its own wallet.

## Offline chain profile

An EOA cannot safely invent its account nonce while disconnected. Blee caches:

```text
chainId
sender address
pending chain nonce
next local nonce hint
maxFeePerGas
maxPriorityFeePerGas
syncedAt
```

The native `signing_intents` ledger remains authoritative for local nonce reservations.

If no usable profile has ever been cached, Blee degrades to `AUTH_ONLY`: the nearby authorization can still be delivered and acknowledged, but automatic third-phone sender-funded blockchain settlement waits until valid sender transaction state exists.

## Offline payment flow

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

Normal app lifecycle events must not erase payment history. Android Clear Storage and uninstall intentionally remove local data.

## Current development rail

The validated test rail remains **Arc Testnet**:

- chain ID: `5042002`
- RPC: `https://rpc.testnet.arc.network`
- explorer: `https://testnet.arcscan.app`
- payment token: `0x3600000000000000000000000000000000000000`
- EIP-712 name: `USDC`
- EIP-712 version: `2`

The native automatic broadcaster is pinned to this validated rail in the current test build.

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

Expected APK:

```text
dist/Blee-2.2.0-mesh-v2-debug.apk
```

The build verifier blocks compilation when atomic signing, sender-funded settlement, the native mesh service, persistent-session policy, 8-character passphrase rule, Bluetooth hardening or the premium monochrome design layer is missing.

## Repository layout

```text
ARCHITECTURE.md                  frozen Mesh v2 protocol architecture
bootstrap/                       versioned base source/native snapshots
professional/                    professional UX snapshot
mesh-v2/
  android/                       native mesh service/templates
  native/                        SQLite/WAL store + atomic signing ledger
  web/
    BleeRuntime.tsx              native/runtime bridge
    payments.ts.in               sender-funded settlement implementation
    atomicSigning.ts.in          crash-atomic signing coordinator
    premium-monochrome.css       Blee 2.2 product design system
scripts/
  apply-blee-mesh-v2.py          protocol/store web overlay
  apply-blee-mesh-v2-android.py  native Android mesh installer
  apply-blee-2.2.py              atomic bridge/session/passphrase/UI hardening
  apply-blee-2.2-android.py      Bluetooth discovery hardening
  verify-blee-mesh-v2.py         build-time architecture/product guard
build-blee.command               canonical build entrypoint
build-blee-professional.command  deterministic orchestrator
```

## Required physical regression

Before mainnet/release-quality claims, test on real Android devices:

1. sender process kill before signing, during signing, after `READY`, after payment persistence and after outbox creation;
2. no duplicate EIP-3009 or EOA transaction nonce reuse;
3. A/B online direct payment;
4. A/B offline nearby payment + native notification;
5. inactivity/background/foreground cycle does not intentionally log the user out;
6. explicit Log out still clears the active app session;
7. 8-character passphrase create/import/unlock flows;
8. A/B offline + C online — C broadcasts A's raw transaction and C's balance does not change;
9. duplicate multi-route delivery — one economic effect;
10. Bluetooth discovery on at least three Android vendors, including screen-off/background cases;
11. Bluetooth off/on and Android scanner failure recovery;
12. Internet loss/return triggers settlement work;
13. stale sender EOA nonce fails safely without charging the courier;
14. authorization expiry stops forwarding safely;
15. reboot/package update recovers durable state;
16. same wallet used externally while Blee holds offline reservations;
17. visual regression of every screen in light monochrome UI.

## Status

Blee 2.2 Mesh v2 remains a **test build**, not a mainnet release. The architecture enforces database-backed signing reservations and persist-before-network boundaries, but production still requires physical fault-injection/device-matrix testing, authenticated private peer sessions, malicious-mesh testing, release signing and a dedicated wallet/protocol security review.
