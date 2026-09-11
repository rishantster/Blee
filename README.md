# Blee

**Payments that keep moving, with or without the internet.**

Blee is an Android-first, self-custodial USDC payment wallet with a native store-and-forward nearby mesh. Internet is required for final blockchain settlement, but not for creating, persisting, delivering, acknowledging, notifying, carrying or reconciling nearby Blee payments.

The frozen protocol foundation is in [`ARCHITECTURE.md`](ARCHITECTURE.md). The production screen/navigation contract is in [`UI_ARCHITECTURE.md`](UI_ARCHITECTURE.md).

## Current build: Blee 2.5

Blee 2.5 keeps the frozen Mesh v2 payment architecture and the ground-up production wallet UI, then completes authentication, notifications and cold-start polish.

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
- optional fingerprint unlock backed by Android Keystore
- native payment notifications
- subtle cold-start Blee logo animation and low-volume launch chime

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

## Session and authentication

Blee does not intentionally log an unlocked user out because the app is idle or backgrounded. Explicit **Log out** remains authoritative while the app process is alive.

Android may still terminate the process under OS pressure, reboot, update or force-stop conditions. Those lifecycle events are distinct from Blee intentionally logging the user out.

The wallet passphrase remains the recovery/fallback credential. The minimum is **8 characters** in both visible validation and the underlying create/import encryption paths. Build verification fails if a 12-character rule or copy returns.

Blee 2.5 also supports optional fingerprint unlock on compatible Android devices. The passphrase is not stored in plaintext: it is wrapped with AES-GCM using a key held in `AndroidKeyStore` and gated by `BiometricPrompt`. A successful fingerprint authentication releases the wrapped passphrase only transiently so the existing wallet unlock path remains authoritative. Biometric enrollment changes invalidate the protected key and require passphrase fallback/re-enrollment.

Passphrase fields include explicit **Show / Hide** controls.

## Native notifications

Blee's native foreground mesh service owns payment notifications rather than relying on the React view being open.

Current notification plumbing covers:

- nearby payment received;
- authenticated recipient delivery ACK;
- settlement reported through the mesh;
- locally observed chain confirmation.

Android 13+ notification permission is requested at runtime. The service uses a low-priority service channel for keeping nearby delivery active and a high-priority Blee payments channel for payment events.

## Launch experience

Cold launch uses the supplied Blee wordmark at its natural aspect ratio with a restrained fade/scale/translate animation. The Android activity plays a short low-volume Blee chime once per process start. Reduced-motion preferences suppress decorative motion in the web layer.

The in-app wordmark is rendered from the supplied SVG as an image with `height: auto`; it is no longer synthesized from a standalone mark plus text or forced into a fixed-height background box.

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

## Blee 2.5 product UI

The presentation contract is frozen in [`UI_ARCHITECTURE.md`](UI_ARCHITECTURE.md).

Key rules:

- monochrome only: off-white, white, black and neutral greys
- supplied Blee wordmark once per screen header at natural aspect ratio
- no radar/orbit/halo/ring artwork
- minimalist wallet creation/unlock screens
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
git checkout blee-2.4-ui-rebuild
git reset --hard origin/blee-2.4-ui-rebuild

export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"
export PATH="$(brew --prefix openjdk@21)/bin:$PATH"

bash build-blee.command
```

Expected APK:

```text
dist/Blee-2.5.0-mesh-v2-debug.apk
```

The build verifier blocks compilation when any of the following disappear or regress:

- native crash-atomic signing
- sender-funded raw settlement transaction
- native mesh service wiring
- 8-character wallet passphrase across UI and crypto paths
- explicit-logout-only session policy
- fingerprint unlock / Android Keystore wiring
- Android notification permission and payment event plumbing
- supplied wordmark natural-aspect rendering
- Show / Hide passphrase controls
- launch animation/chime wiring
- Send / Receive wiring
- production wallet UI markers
- BLE hardening

## Repository layout

```text
ARCHITECTURE.md                   frozen Mesh v2 protocol architecture
UI_ARCHITECTURE.md                production screen/navigation contract
bootstrap/                        versioned base source/native snapshots
professional/                     professional source snapshot
brand-assets/                     supplied Blee mark + wordmark source assets
ui-v4/                            ground-up wallet UI source bundle
ui-v5/                            authentication/launch/minimal-onboarding UI bundle
mesh-v2/
  android/                        native mesh + biometric templates
  native/                         SQLite/WAL store + atomic signing ledger
  web/
    BleeRuntime.tsx               native/runtime bridge
    payments.ts.in                sender-funded settlement implementation
    atomicSigning.ts.in           crash-atomic signing coordinator
scripts/
  apply-blee-mesh-v2.py           protocol/store web overlay
  apply-blee-mesh-v2-android.py   native Android mesh installer
  apply-blee-2.2.py               atomic bridge/session/passphrase hardening
  apply-blee-2.2-android.py       Bluetooth discovery hardening
  apply-blee-2.4.py               production wallet UI foundation
  apply-blee-2.5-ui.py            biometric/minimal-auth UI bundle installer
  apply-blee-2.5.py               passphrase/UI/version hardening
  apply-blee-2.5-android.py       biometric/notification/chime native installer
  apply-blee-original-brand.py    supplied brand asset installer
  verify-blee-mesh-v2.py          final build-time protocol/product guard
build-blee.command                canonical build entrypoint
build-blee-professional.command   deterministic orchestrator
```

## Required physical regression

Before release-quality claims, test on real Android devices:

1. create/import/unlock with exactly 8-character and longer passphrases;
2. Show / Hide on create, unlock and recovery passphrase fields;
3. fingerprint enrollment, unlock, cancel/fallback, disable and biometric-enrollment invalidation;
4. explicit logout and background/foreground persistence;
5. Android 13+ notification permission allow/deny paths;
6. payment-received, delivered, settlement-reported and confirmed notifications while UI is backgrounded;
7. cold-start logo animation and one-time chime, including silent/media-volume expectations;
8. sender process kill before signing, during signing, after `READY`, after payment persistence and after outbox creation;
9. no duplicate EIP-3009 or EOA nonce reuse;
10. A/B online direct payment;
11. A/B offline nearby payment + native notification;
12. A/B offline + C online, where C broadcasts A's signed raw transaction and C's wallet balance does not change;
13. duplicate multi-route delivery produces one economic effect;
14. Bluetooth discovery on at least three Android vendors including screen-off/background cases;
15. Bluetooth off/on and scanner failure recovery;
16. Internet loss/return triggers settlement work;
17. stale sender EOA nonce fails safely without charging the courier;
18. authorization expiry stops forwarding safely;
19. reboot/package update recovers durable state;
20. visual and interaction regression of every screen in `UI_ARCHITECTURE.md`.

## Status

Blee 2.5 remains a **test build**, not a mainnet release. The codebase enforces database-backed signing reservations, persist-before-network boundaries, native biometric key protection and native notification delivery, but production still requires physical fault-injection/device-matrix testing, malicious-mesh testing, release signing and a dedicated wallet/protocol security review.
