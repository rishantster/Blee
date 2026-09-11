# Blee

**Payments that keep moving, with or without the internet.**

Blee is an Android-first, self-custodial payment app designed to move signed payment intent across normal internet, local Wi-Fi and Bluetooth. The current professional test build settles an EIP-3009 compatible payment token on an EVM network, with Arc Testnet included as the validated default.

## Blee 1.4

The 1.4 professional build combines the two-phone reliability work from 1.3 with the supplied Blee brand system and a proper timestamped payment ledger:

- Native Android APK
- Supplied Blee mark used as the app/launcher identity
- Supplied Blee wordmark used in the in-app brand header
- Self-custodial EVM wallet
- Native SQLite + WAL payment journal
- Durable offline inbox/outbox state
- Activity entries rendered with local date **and exact time including seconds**
- Authenticated recipient acknowledgement
- Serialized sends and authorization expiry handling
- Nearby identity synchronization so Activity can resolve a known sender/recipient by display name instead of falling back to a raw address
- Profile-photo support with nearby identity relay
- Automatic nearby mesh startup while the signed-in app session is active
- Bluetooth + local Wi-Fi nearby transport
- Signed offline payment authorizations
- Pending vs confirmed/spendable balance separation
- Store-and-forward settlement when connectivity returns
- Receive screen with wallet QR and copy action
- Clean settlement-network UI with Arc Testnet included
- Wallet import, encrypted backup and private-key export

## Identity and Activity

Blee maintains a local address-to-identity mapping for peers it has authenticated/discovered. A nearby identity includes the user's display name and optional profile photo reference. Incoming and outgoing Activity uses the known identity for that wallet address and falls back to a shortened address only when Blee has never learned that peer's identity.

Activity is treated as a ledger rather than a date-only feed. The underlying stored event time remains the source value; the UI renders it in the device's local timezone with date, hour, minute and second. This makes two payments on the same date independently auditable in the interface.

Identity is presentation metadata; the wallet address remains the payment identity used for signing and settlement.

## Nearby discovery

Blee starts the nearby mesh automatically for an active signed-in session and advertises/scans for peers over the supported local transports.

Modern Android does not allow an app to silently force Bluetooth or Wi-Fi on. Blee therefore treats required radio/nearby permissions and adapter state as prerequisites: the app can request permission, detect that Bluetooth/Wi-Fi is unavailable, and guide the user to enable it. Discovery is re-armed by the app rather than relying on the user repeatedly toggling the Nearby screen.

For reliable two-phone testing, grant the requested Nearby/Bluetooth permissions on both devices and keep Bluetooth enabled. Local Wi-Fi is used as an additional transport when available; internet access is not required for nearby delivery, but network access is required for final on-chain settlement.

## Payment semantics

Blee deliberately does **not** treat an offline delivery as final on-chain settlement.

1. The sender signs a payment authorization.
2. Blee writes the outgoing payment and authorization to durable local storage.
3. The authorization can move to the recipient over Bluetooth or local Wi-Fi.
4. The recipient validates it and persists it to SQLite before acknowledging delivery.
5. While settlement is unavailable, the recipient sees the payment as pending received.
6. Once the active network is reachable, a valid authorization can be submitted.
7. The payment becomes confirmed/spendable only after network settlement is verified.

This avoids the failure mode where Activity says money was received while the spendable balance never actually changed.

## Storage model

Payment state is stored locally in native Android SQLite with write-ahead logging. It survives wallet lock/logout, app restart, phone restart and normal cache cleanup.

Android **Clear storage / Clear data** or uninstall intentionally removes the app database. Wallet recovery is separate: Blee can export an encrypted wallet backup or reveal/import the private key under explicit user control. Private keys are never uploaded by Blee.

## Settlement network

The bundled and tested settlement network is **Arc Testnet**:

- Chain ID: `5042002`
- RPC: `https://rpc.testnet.arc.network`
- Explorer: `https://testnet.arcscan.app`
- Payment token contract: `0x3600000000000000000000000000000000000000`
- EIP-712 token name: `USDC`
- EIP-712 version: `2`

Blee also supports user-supplied EVM settlement profiles. A payment token must implement the EIP-3009 authorization methods Blee uses (`transferWithAuthorization` and `authorizationState`) with the matching EIP-712 domain. Adding an arbitrary EVM network does not make every ERC-20 suitable for offline settlement.

Arc mainnet has not been validated in this test build. Official mainnet parameters should be verified before value is moved.

## Build the Android APK

On macOS with Node 22+:

```bash
git clone -b blee-professional https://github.com/rishantster/Blee.git
cd Blee
bash build-blee-professional.command
```

The professional builder reconstructs the versioned source snapshot, restores the native SQLite/nearby plugins, applies the wallet/network layer, applies the Blee 1.3 identity/QR/discovery/profile overlay, then applies the Blee 1.4 supplied-brand and ledger-timestamp overlay. It runs TypeScript checks, builds the Capacitor UI, generates the Android project, installs the supplied Blee launcher mark and compiles/verifies the debug APK.

Output:

```text
dist/Blee-1.4.0-professional-debug.apk
```

## Security notes

- Blee is self-custodial.
- Private keys are encrypted locally using a passphrase-derived AES-GCM key.
- Private-key reveal/export is explicit and temporary in the UI.
- Encrypted backup export does not upload the wallet anywhere.
- Payment history and wallet recovery are separate concerns.
- Offline incoming funds are not treated as spendable until settlement is confirmed.
- Peer names/photos are UI identity metadata; signed wallet addresses remain authoritative for payments.
- User-supplied networks and token contracts must be independently verified.

## Current status

Blee 1.4 is a professional **test build**, not a production mainnet release. Arc Testnet is the validated settlement environment. Mainnet use requires verification of official network/token parameters, release signing, device-matrix testing and a production security review.
