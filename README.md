# Blee

Blee is an Android-first, self-custodial USDC payment wallet with native nearby/offline delivery, durable SQLite/WAL state and Arc settlement.

## Canonical source

`main` is the only release/source-of-truth branch.

There is one supported build entrypoint:

```bash
bash build-blee.command
```

Do not use historical/versioned builders or APK names. The canonical build artifact is always:

```text
dist/Blee.apk
```

A SHA-256 file is produced alongside it when the host provides `shasum` or `sha256sum`:

```text
dist/Blee.apk.sha256
```

Internal Android `versionCode` / `versionName` may still advance for upgrade compatibility. Those internal values must never change the public APK filename.

## Product scope

- Android APK
- one local self-custodial wallet
- Arc Testnet
- USDC
- Send / Receive
- nearby BLE discovery and delivery
- native foreground mesh service
- durable SQLite/WAL payment journal
- sender-funded settlement
- third-phone store-and-forward and sender-signed raw-transaction broadcast
- optional fingerprint unlock only on compatible/enrolled hardware
- native payment notifications
- encrypted wallet backup/recovery

## Settlement invariant

The sender authorizes and funds settlement. A courier phone may broadcast only the sender's already-signed transaction; it must never sign or pay gas for another user's payment.

Offline delivery and blockchain finality are separate states. Blee keeps confirmed/spendable, pending received and reserved outgoing values distinct.

## Nearby/background model

The native Android process owns nearby networking. The React/Capacitor layer presents state; it is not the reliability layer.

Android runtime permissions are required for Bluetooth scanning/connecting/advertising. Blee re-arms nearby discovery after permissions are granted and when the Bluetooth radio returns. Android force-stop remains authoritative.

## Biometric policy

Fingerprint is optional. It is surfaced only when the device has compatible fingerprint hardware, a fingerprint is enrolled and the Android Keystore authentication policy can use it. Passphrase unlock always remains the fallback/recovery path.

## Current settlement rail

- chain ID: `5042002`
- RPC: `https://rpc.testnet.arc.network`
- explorer: `https://testnet.arcscan.app`
- USDC: `0x3600000000000000000000000000000000000000`
- EIP-712 name: `USDC`
- EIP-712 version: `2`

## Build requirements

- Node.js 22+
- Java 21+
- Android command-line tools / SDK

On macOS with Homebrew JDK 21:

```bash
export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"
export PATH="$(brew --prefix openjdk@21)/bin:$PATH"
bash build-blee.command
```

The canonical build performs source reconstruction, applies the frozen Blee implementation in deterministic order, type-checks, builds the web layer, generates the Android project, installs the native mesh/biometric/notification implementation, runs protocol/product verifiers and compiles the APK.

## Release gate

A successful compile is necessary but not sufficient for a release-quality claim. Before distributing a build as production-ready, regression-test on physical Android devices at minimum:

1. create/import/unlock and encrypted backup/restore;
2. fingerprint-capable and non-fingerprint devices;
3. Bluetooth permission deny/allow, Bluetooth off/on and app background/foreground;
4. A↔B nearby discovery in both directions;
5. A→B online payment;
6. A→B fully offline delivery and ACK;
7. A→C→B store-and-forward delivery;
8. A/B offline + C online sender-signed automatic settlement, verifying C's wallet never funds gas;
9. duplicate/replayed packet handling;
10. app/process death at signing, persistence, receive and ACK boundaries;
11. reboot/package-update recovery;
12. settlement receipt replay/mismatch rejection and later independent chain confirmation;
13. activity/history/balance persistence after logout/restart;
14. notification delivery while the UI is backgrounded.

`ARCHITECTURE.md` contains the frozen protocol invariants. `UI_ARCHITECTURE.md` contains the product/navigation contract.
