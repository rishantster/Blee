# Blee

**Payments that keep moving, with or without the internet.**

Blee is an Android-first, self-custodial payment app designed to keep payment intent moving across normal internet, local Wi-Fi and Bluetooth. The current hackathon build settles an EIP-3009 compatible payment token on an EVM network, with Arc Testnet included as the tested default.

## What is working

- Native Android APK
- Self-custodial EVM wallet
- Wallet import, encrypted backup and private-key export
- Native SQLite + WAL payment journal
- Durable offline inbox/outbox state
- Nearby discovery and packet transport over Bluetooth + local Wi-Fi
- Signed offline payment authorizations
- Pending vs confirmed/spendable balance separation
- Store-and-forward settlement when connectivity returns
- User-managed EVM network profiles, similar to MetaMask's **Add network** flow
- Arc Testnet configuration included out of the box

## Payment semantics

Blee deliberately does **not** pretend that an offline payment is already final on-chain.

1. The sender signs a payment authorization.
2. Blee writes the outgoing payment and authorization to durable local storage.
3. The authorization can move to the recipient over Bluetooth or local Wi-Fi.
4. The recipient validates it and persists it to SQLite **before** acknowledging delivery.
5. While both devices are offline, the recipient sees the payment as **Pending received**.
6. Once the active network is reachable, a valid authorization can be submitted.
7. The payment becomes confirmed/spendable only after network settlement is verified.

This avoids the common failure mode where an app shows a received payment in Activity while the actual spendable balance never changed.

## Storage model

Payment state is stored locally in native Android SQLite with write-ahead logging. It survives wallet lock/logout, app restart, phone restart and normal cache cleanup.

Android **Clear storage / Clear data** or uninstall intentionally removes the app database. Wallet recovery is therefore separate: Blee can export an encrypted wallet backup or reveal/import the private key under explicit user control. Private keys are never uploaded by Blee.

## Networks

The bundled and tested network is **Arc Testnet**:

- Chain ID: `5042002`
- RPC: `https://rpc.testnet.arc.network`
- Explorer: `https://testnet.arcscan.app`
- Payment token contract: `0x3600000000000000000000000000000000000000`
- EIP-712 token name: `USDC`
- EIP-712 version: `2`

Blee 1.1 also lets a user add and activate another EVM network from inside the app by entering:

- Network name
- Chain ID
- RPC URL
- Block explorer URL
- Native currency symbol
- Payment token symbol + contract
- Token decimals
- EIP-712 token name + version

The RPC is checked against the supplied Chain ID before the profile is saved.

**Important:** adding a network does not magically make every ERC-20 compatible with offline settlement. The configured payment token must implement the EIP-3009 authorization methods Blee uses (`transferWithAuthorization` and `authorizationState`) with the matching EIP-712 domain. Arc mainnet has not been validated in this hackathon build; official mainnet parameters can be added in-app when available and should be tested with small value first.

## Build the Android APK

### macOS

```bash
git clone -b blee-v1-sqlite https://github.com/rishantster/Blee.git
cd Blee
bash build-blee-macos.command
```

The build script is intentionally reproducible. It:

1. verifies Node 22+
2. provides a private Java 21 runtime when needed
3. installs/verifies the Android command-line SDK
4. reconstructs the versioned Blee source snapshot
5. restores the native SQLite and nearby-transport plugins
6. applies the visible Blee 1.1 source overlays in `overrides/`
7. runs TypeScript checks
8. creates the production web bundle used by Capacitor
9. generates the native Android project
10. compiles a debug APK with Gradle
11. verifies the APK archive and emits its SHA-256

Output:

```text
dist/Blee-1.1.0-hackathon-debug.apk
```

No GitHub Actions runner is required to reproduce the submitted APK.

## Repository layout

```text
bootstrap/                 immutable source/native snapshots used by the reproducible builder
overrides/src/             human-readable Blee 1.1 product additions
scripts/apply-blee-1.1.py  deterministic source overlay step
build-blee-macos.command   one-command Android build
README.md                  architecture, safety and build instructions
```

The source snapshot exists because Blee was migrated from an earlier prototype during the hackathon. Current submission changes are kept as normal human-readable source under `overrides/` and applied deterministically before compilation.

## Security notes

- Blee is self-custodial.
- Private keys are encrypted locally using a passphrase-derived AES-GCM key.
- Private-key reveal/export is explicit and temporary in the UI.
- Encrypted backup export does not upload the wallet anywhere.
- Payment history and wallet recovery are separate concerns.
- Offline incoming funds are not treated as spendable until settlement is confirmed.
- Custom networks are user-supplied and should be verified before value is moved.

## Current status

This is a **hackathon/test build**, not a production release. Arc Testnet is the validated settlement environment. Mainnet use requires verification of the official network, payment-token contract and EIP-712 parameters, plus additional production security review and release signing.
