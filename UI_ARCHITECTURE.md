# Blee UI Architecture — Canonical Product Contract

This document defines the canonical Blee Android presentation model. It is intentionally scoped to the actual product: one wallet, Arc Testnet, USDC payments, nearby BLE delivery, durable local state and Arc settlement.

## Product rules

- No multi-asset portfolio UI.
- No token carousel.
- No duplicate navigation on Home.
- Home contains only the primary payment actions: **Send** and **Receive**.
- **Nearby**, **Activity** and **Profile** are destinations in the persistent bottom navigation.
- Settings are entered from Profile / the appropriate header control, not duplicated across Home.
- Normal in-app headers use the supplied Blee wordmark at its natural aspect ratio.
- The Android launcher and cold-launch screen use the supplied standalone Blee logo, not the wordmark and not generated/default Capacitor artwork.
- No decorative radar, orbit, halo or concentric-ring artwork.
- Monochrome only: off-white, white, black and neutral greys.
- Financial state must never be encoded by colour alone.
- Wallet passphrase minimum is 8 characters in both visible validation and encryption paths.
- Passphrase entry provides explicit Show / Hide controls.
- Fingerprint unlock is optional and is only shown when compatible fingerprint hardware is actually present and enrolled.
- Passphrase remains the biometric fallback/recovery credential.
- Blee does not intentionally auto-log-out an unlocked user because of inactivity/backgrounding while the process remains alive.
- Native payment notifications work without requiring the React screen to remain open, subject to Android notification permission.

## Cold launch

Cold launch shows the supplied standalone Blee logo only, centered with its original geometry and a restrained one-time transition. The native Blee launch chime plays when the app genuinely enters the foreground, with lifecycle debouncing to prevent duplicate playback. No decorative rings or marketing carousel.

## Screen map

### Create wallet
- Blee wordmark
- Display name
- Passphrase + Show / Hide
- Confirm passphrase + Show / Hide
- optional fingerprint setup only when supported
- Create wallet
- Import / restore

### Unlock
- Blee wordmark
- Passphrase + Show / Hide
- Unlock
- fingerprint unlock only when configured and currently available
- recovery path

### Home
- compact Blee header
- online/offline state
- USDC confirmed spendable balance
- reserved outgoing when non-zero
- pending received when non-zero
- Send
- Receive
- small Nearby preview
- small Recent activity preview
- persistent bottom navigation

### Nearby
- discovery state
- peer rows with cached identity
- address fallback when identity unavailable
- distance/recency only when reliable
- Send per peer
- discovery refresh/re-arm affordance

### Send
- recipient identity/address
- USDC amount
- confirmed spendable context
- note only if persisted/transported correctly
- Review & send

A payment may not exceed confirmed spendable minus already-reserved outgoing.

### Confirm send
- recipient
- amount
- network
- estimated/max sender-funded network reserve when available
- delivery/settlement explanation
- Confirm and send

### Send result
Possible states:
- queued nearby
- delivered nearby
- acknowledged
- settlement submitted
- settled via relay report
- chain confirmed

Offline authorization must never be labelled chain-confirmed.

### Receive
- QR code
- wallet address
- copy
- share
- nearby discoverability state

### Activity
- All / Sent / Received filters
- counterparty identity/address
- amount
- direction
- current state
- timestamp

### Activity detail
- immutable event timeline
- sender / receiver
- amount
- authorization/payment ID
- tx hash when submitted
- settlement state
- timestamps including seconds
- explorer action only when tx hash exists

### Profile
- profile image or initial
- display name
- wallet address
- Edit profile
- Backup & recovery
- Settings
- About

### Settings
- discoverability
- notifications
- fingerprint/security only when supported
- backup & recovery
- settlement network information
- about
- Log out

### Backup & recovery
Encrypted wallet material is exported/restored through the existing recovery implementation. Raw private key is never exposed by default. Imported backup structure, cryptographic parameters and payload sizes are validated before persistence.

### Network & payment setup
Current supported rail only:
- Arc Testnet
- USDC
- chain ID 5042002

Unsupported future networks/assets must not leak into current product UI.

## Notifications

Native payment notifications cover:
- nearby payment received;
- authenticated recipient delivery ACK;
- settlement receipt reported through the mesh;
- independently observed chain confirmation.

Android 13+ notification permission may suppress OS notifications, but never ledger correctness.

## Biometric security contract

- Fingerprint unlock is optional.
- Capability is based on actual fingerprint hardware + enrollment, not generic face/biometric availability.
- Android Keystore holds the wrapping key.
- The wrapping key requires biometric authentication.
- Wallet passphrase remains fallback and recovery credential.
- Passphrase is never stored plaintext at rest.
- Biometric-protected ciphertext may live in private app storage.
- Enrollment changes invalidate the protected key where supported.
- Disabling fingerprint removes the wrapped credential.

## Navigation

Primary destinations:

`Home · Nearby · Activity · Profile`

Send and Receive are actions, not permanent tabs.

## Motion

- cold-start standalone-logo transition: restrained, under ~700ms
- screen transition: 180–240ms
- sheet transition: 220–260ms
- button press: subtle scale only
- no decorative looping animations
- respect reduced-motion preference

## Build invariants

The canonical build must fail if any of these regress:

- functional 8-character passphrase rule disappears
- Show / Hide passphrase controls disappear
- biometric capability gating disappears
- notification permission/event plumbing disappears
- normal Blee wordmark is stretched/replaced by synthetic geometry
- standalone Blee logo disappears from Android launcher or cold launch
- cold-launch animation or native Blee chime disappears
- Send or Receive disappears
- inactivity/background auto-lock returns
- courier-funded settlement returns
- sender-funded raw transaction path disappears
- native atomic signing reservation disappears
- nearby runtime permissions/re-arm disappears
- monotonic native payment state protection disappears
- settlement receipts are accepted without sender-signed hash pinning
- legacy orbit/radar/halo design returns
- APK output is not the release-versioned `dist/Blee-2.6.0.apk`
