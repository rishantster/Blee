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
- Pull-to-refresh is non-destructive: it refreshes Blee state without reloading the WebView or clearing the unlocked wallet session.
- Contacts remain durable local Blee records keyed by wallet address in SQLite/native APIs, but the hackathon production UI does not expose experimental Contacts/Filter controls.
- The same EVM wallet is rendered with one stable canonical address presentation; checksum/lowercase flicker is not acceptable.

## Cold launch

Cold launch shows the supplied standalone Blee logo only, centered with its original geometry and a restrained one-time transition. The native Blee launch chime plays when the app genuinely enters the foreground, with lifecycle debouncing to prevent duplicate playback. No decorative rings or marketing carousel.

## Refresh

Pulling the app down from the top performs a full in-process state refresh. The funds-card refresh affordance invokes the same path.

Refresh wakes/re-queries confirmed balance/network state, durable payment journal and pending envelopes, nearby peers, peer identity/name/avatar projection and Activity projection. Contacts persistence remains native and durable.

Refresh must never call `window.location.reload()`, clear the wallet vault, log the user out, or destroy the in-memory unlocked session. While refreshing, Blee shows a brief centered Blee logo animation with a soft swish.

## Screen map

### Create wallet
- Blee wordmark
- Display name
- Passphrase + Show / Hide
- Confirm passphrase + Show / Hide
- optional fingerprint setup only when supported
- Create wallet
- Import / restore

No QR scanner appears in passphrase fields.

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

Home does **not** contain Activity contact filters, `All activity` selectors or permanent Contacts controls.

### Nearby
- discovery state
- peer rows with cached identity
- display name + profile image when known
- address fallback only when identity is unavailable
- Send per peer
- discovery self-healing/re-arm behavior

Nearby discovery is local transport behavior; Internet is not required to discover another Blee phone. The production transport keeps the last physically proven BLE/Nearby timing contract rather than abandoning BLE aggressively.

### Send
- recipient identity/address
- **one QR scan icon inside the Recipient input**
- USDC amount
- confirmed spendable context
- note only if persisted/transported correctly
- Review & send

The QR scanner is icon-only, portrait-oriented and presented as a focused scanner surface rather than a landscape full-screen takeover. QR decoding works from the bundled scanner without requiring Internet.

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
- persistent primary bottom navigation remains visible
- All / Sent / Received filters
- resolved counterparty Blee name/avatar when available
- address fallback only when identity is unavailable
- amount
- direction
- current state
- timestamp

No experimental Contacts or contact-filter controls are added to Activity in the hackathon production build. Activity must stay on the original React navigation shell and must never be mutated by a MutationObserver or arbitrary DOM injection.

### Contacts backend
Contacts are local-first metadata backed by SQLite and keyed by canonical wallet address. The native APIs for list/save/delete/candidates remain part of the app and saved aliases remain presentation metadata only. They never modify EIP-3009 authorization, payment signatures or settlement data. Visible contact-management UI is intentionally deferred until it can be integrated without destabilizing Activity navigation.

### Activity detail
- counterparty name/avatar when resolved
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

Profile name/avatar changes are synchronized to connected nearby Blee peers and should backfill Activity presentation without changing payment authorization.

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

Native payment notifications cover the user-visible payment lifecycle:
- payment sent after durable outgoing persistence;
- nearby payment detected while verification begins when applicable;
- cryptographically verified payment received / pending settlement;
- authenticated recipient delivery ACK / delivered state.

Android 13+ notification permission is requested at runtime. Permission denial may suppress OS notifications, but never ledger correctness.

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

Send and Receive are actions, not permanent tabs. The bottom navigation is owned by the primary React shell and must remain present on Home, Nearby, Activity and Profile.

## Motion

- cold-start standalone-logo transition: restrained, under ~700ms
- refresh Blee-logo/swish transition: brief and deliberate
- screen transition: 180–240ms
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
- QR scanner is missing, duplicated, placed outside Send Recipient, or leaks into passphrase UI
- destructive WebView reload returns to refresh
- inactivity/background auto-lock returns
- Activity bottom navigation disappears
- Contacts/Activity controls leak onto Home or Activity
- legacy MutationObserver/DOM-injected Contacts UI returns
- wallet address case flicker returns
- courier-funded settlement returns
- sender-funded raw transaction path disappears
- native atomic signing reservation disappears
- nearby runtime permissions/re-arm disappears
- last physically proven BLE/Nearby timing contract is replaced by aggressive fallback values
- monotonic native payment state protection disappears
- settlement receipts are accepted without sender-signed hash pinning
- legacy orbit/radar/halo design returns
- APK output is not the release-versioned `dist/Blee-2.7.0.apk`
