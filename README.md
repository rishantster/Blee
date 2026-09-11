# Blee

**Payments that keep moving, with or without the internet.**

Blee is an Android-first, self-custodial USDC payment wallet with a native store-and-forward nearby mesh. Internet is required for final blockchain settlement, but not for creating, persisting, delivering, acknowledging, notifying, carrying or reconciling nearby Blee payments.

The frozen protocol foundation is in [`ARCHITECTURE.md`](ARCHITECTURE.md). The production screen/navigation contract is in [`UI_ARCHITECTURE.md`](UI_ARCHITECTURE.md).

## Current build: Blee 2.4

Blee 2.4 keeps the frozen Mesh v2 payment architecture and replaces the old MVP/landing-page presentation with a compact production wallet system.

Current product scope is intentionally narrow:

- Android APK
- one wallet
- Arc Testnet
- USDC
- Send / Receive
- nearby BLE discovery and delivery
- durable local SQLite/WAL journal
- sender-funded settlement
- automatic third-phone broadcast of sender-signed raw transactions

Blee is **not** presented as a multi-asset portfolio or multi-network wallet in the current UI.

## Settlement rule

> **The sender funds settlement. Any Blee phone with Internet may broadcast the sender's already-signed transaction. Courier phones never spend their own funds.**

```text
Phone A offline
  signs EIP-3009 authorization
  signs sender-funded raw settlement transaction
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

A courier phone does not sign another user's payment, does not receive the sender's private key, cannot change the signed transaction and does not pay another user's gas.

## Crash-atomic signing

Blee uses a native SQLite signing ledger so signatures are not loose in-memory objects.

Before signing, SQLite records a `SIGNING` intent containing the signing/session ID, chain ID, sender, recipient, amount, EIP-3009 authorization nonce, optional EOA transaction nonce and expiry.

After EIP-3009 and EIP-1559 signing, the exact authorization + raw transaction bundle is stored durably before the caller receives it. When the payment journal stores the outgoing payment, the same native transaction validates the ready signing intent and promotes it to `PERSISTED`.

The native mesh layer commits the outbox before transmission. The recipient commits the verified incoming payment and durable ACK before transmitting that ACK.

## Balance semantics

Blee separates:

- **Confirmed / spendable** — independently chain-confirmed funds.
- **Pending received** — valid incoming authorization not yet independently confirmed.
- **Reserved outgoing** — signed outgoing value no longer considered freely available locally.

Devices exchange signed events and settlement evidence, never arbitrary balance assertions.

## Session policy

Blee does not intentionally log an unlocked user out because the app is idle or backgrounded. Explicit **Log out** remains authoritative while the app process is alive.

Android may still terminate the process under OS pressure, reboot, update or force-stop conditions. Those lifecycle events are distinct from Blee intentionally logging the user out.

## Wallet passphrase

The minimum passphrase length is **8 characters** in both:

- visible create/import/recovery UI validation; and
- the wallet encryption path.

The build verifier blocks compilation if the old 12-character rule returns or the functional crypto path stops enforcing 8 characters.

## Bluetooth discovery

Blee uses Android BLE in low-latency/high-power mode and prefers all supported LE PHYs where hardware permits:

- `SCAN_MODE_LOW_LATENCY`
- aggressive matching and immediate scan delivery
- `ADVERTISE_MODE_LOW_LATENCY`
- high advertising transmit power
- scan restart after Android scanner failure
- high-priority GATT connection requests
- 1M / 2M / LE Coded PHY preference
- larger negotiated MTU with peer fallback

The native foreground `BleeMeshService` performs simultaneous advertising + scanning and survives normal UI navigation/background transitions subject to Android platform restrictions.

## Blee 2.4 product UI

The current presentation contract is frozen in [`UI_ARCHITECTURE.md`](UI_ARCHITECTURE.md).

Key rules:

- monochrome only: off-white, white, black and neutral greys
- one compact Blee lockup per screen header
- no radar/orbit/halo/ring artwork
- Home shows wallet state + **Send** + **Receive** only as primary actions
- `Home · Nearby · Activity · Profile` is the single persistent destination navigation
- no duplicate Nearby/Activity/Profile/Settings action grid on Home
- no multi-asset token list
- no unsupported network/asset marketing
- transaction states distinguish nearby delivery from blockchain confirmation
- restrained 180–260ms screen/sheet transitions
- reduced-motion support

## Current development rail

- chain ID: `5042002`
- RPC: `https://rpc.testnet.arc.network`
- explorer: `https://testnet.arcscan.app`
- payment token: `0x3600000000000000000000000000000000000000`
- EIP-712 name: `USDC`
- EIP-712 version: `2`

The native automatic broadcaster is pinned to this validated test rail in the current build.

## Build the APK

Requirements: macOS, Node.js 22+, Java 21 and Android command-line tools.

```bash
cd ~/Blee-professional-build/Blee
git fetch origin
git checkout blee-professional
git reset --hard origin/blee-professional

export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"
export PATH="$(brew --prefix openjdk@21)/bin:$PATH"

bash build-blee.command
```

Expected APK:

```text
dist/Blee-2.4.0-mesh-v2-debug.apk
```

The build verifier blocks compilation when any of the following disappear or regress:

- native crash-atomic signing
- sender-funded raw settlement transaction
- native mesh service wiring
- 8-character wallet passphrase
- explicit-logout-only session policy
- Send / Receive wiring
- production wallet UI markers
- BLE hardening

## Repository layout

```text
ARCHITECTURE.md                   frozen Mesh v2 protocol architecture
UI_ARCHITECTURE.md                production screen/navigation contract
bootstrap/                        versioned base source/native snapshots
professional/                     professional source snapshot
mesh-v2/
  android/                        native mesh service/templates
  native/                         SQLite/WAL store + atomic signing ledger
  web/
    BleeRuntime.tsx               native/runtime bridge
    payments.ts.in                sender-funded settlement implementation
    atomicSigning.ts.in           crash-atomic signing coordinator
    production-wallet-2.4.css     current production design system
scripts/
  apply-blee-mesh-v2.py           protocol/store web overlay
  apply-blee-mesh-v2-android.py   native Android mesh installer
  apply-blee-2.2.py               atomic bridge/session/passphrase hardening
  apply-blee-2.2-android.py       Bluetooth discovery hardening
  apply-blee-2.4.py               production wallet UI/interaction overlay
  verify-blee-mesh-v2.py          build-time protocol/product guard
build-blee.command                canonical build entrypoint
build-blee-professional.command   deterministic orchestrator
```

## Required physical regression

Before release-quality claims, test on real Android devices:

1. create/import/unlock with 8-character and longer passphrases;
2. explicit logout and background/foreground persistence;
3. sender process kill before signing, during signing, after `READY`, after payment persistence and after outbox creation;
4. no duplicate EIP-3009 or EOA nonce reuse;
5. A/B online direct payment;
6. A/B offline nearby payment + native notification;
7. A/B offline + C online, where C broadcasts A's signed raw transaction and C's wallet balance does not change;
8. duplicate multi-route delivery produces one economic effect;
9. Bluetooth discovery on at least three Android vendors including screen-off/background cases;
10. Bluetooth off/on and scanner failure recovery;
11. Internet loss/return triggers settlement work;
12. stale sender EOA nonce fails safely without charging the courier;
13. authorization expiry stops forwarding safely;
14. reboot/package update recovers durable state;
15. visual and interaction regression of every screen in `UI_ARCHITECTURE.md`.

## Status

Blee 2.4 remains a **test build**, not a mainnet release. The codebase enforces database-backed signing reservations and persist-before-network boundaries, but production still requires physical fault-injection/device-matrix testing, malicious-mesh testing, release signing and a dedicated wallet/protocol security review.
