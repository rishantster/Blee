# Blee 2.4 UI Architecture

This document freezes the production presentation model for Blee. It is intentionally scoped to the actual Blee product: one wallet, one current settlement network profile, USDC payments, nearby BLE delivery, durable local state and Arc settlement.

## Product rules

- No multi-asset portfolio UI.
- No token carousel.
- No duplicate navigation on Home.
- Home contains only the primary payment actions: **Send** and **Receive**.
- **Nearby**, **Activity** and **Profile** are destinations in the persistent bottom navigation.
- Settings are entered from Profile / appropriate header control, not duplicated across Home.
- The Blee logo appears once per screen header. No pill containing a second logo, no tagline beneath the app header.
- No decorative radar, orbit, halo or concentric-ring artwork.
- Monochrome only: off-white, white, black and neutral greys.
- Error/success states stay calm and legible; financial state must never be encoded by colour alone.
- A wallet passphrase is functionally rejected below 8 characters. The UI copy and encryption validation must agree.
- Blee does not intentionally auto-log-out an unlocked user because of inactivity/backgrounding while the process remains alive. Explicit Log out is authoritative.

## Screen map

### 1. Create wallet
Purpose: create encrypted local identity and wallet.

Required controls:
- Blee brand lockup
- Display name
- Passphrase
- Confirm passphrase
- Create wallet
- Import / restore path

Functional rules:
- display name required
- passphrase minimum 8 characters
- confirmation must match
- encrypted wallet creation must complete before entering Home

### 2. Unlock
Purpose: restore the already-created encrypted local wallet into the active process.

Required controls:
- Blee brand lockup
- passphrase
- reveal/hide control if supported
- Unlock
- recovery path

### 3. Home
Purpose: at-a-glance wallet state and immediate payment actions.

Required content:
- compact Blee header
- online/offline state
- USDC confirmed spendable balance
- reserved outgoing amount when non-zero
- pending received amount when non-zero
- Send
- Receive
- small Nearby preview
- small Recent activity preview
- persistent bottom navigation

Explicitly not present:
- duplicate Nearby/Activity/Profile/Settings quick-action buttons
- multi-asset list
- second navigation system

### 4. Nearby
Purpose: discover authenticated Blee peers and start nearby payment.

Required content:
- discovery state
- peer rows with cached identity
- address fallback when identity unavailable
- distance/recency only when the platform actually has a reliable value
- Send action per peer
- refresh/discovery affordance

### 5. Send
Purpose: compose a payment to a selected peer/address.

Required controls:
- recipient identity/address
- USDC amount
- confirmed spendable context
- optional note only if persisted/transported correctly
- Review & send

Functional rules:
- cannot exceed confirmed spendable minus already-reserved outgoing
- nearby/offline delivery does not pretend to be chain finality
- signing intent is reserved atomically before signatures

### 6. Confirm send
Purpose: last human verification before signing/queueing.

Required content:
- recipient
- amount
- network
- estimated/max sender-funded network reserve when available
- delivery/settlement explanation
- Confirm and send

### 7. Send success / queued
Purpose: describe the actual payment state rather than showing a generic success animation.

Possible states:
- queued nearby
- delivered nearby
- acknowledged
- settlement submitted
- settled via relay report
- chain confirmed

The UI must not label an offline authorization as chain-confirmed.

### 8. Receive
Purpose: share the current wallet address / nearby identity.

Required content:
- QR code
- wallet address
- copy
- share
- nearby discoverability state

### 9. Activity
Purpose: immutable payment journal view.

Required content:
- All / Sent / Received filters
- counterparty identity/address
- amount
- direction
- current state
- local rendered timestamp including seconds on detail

### 10. Activity detail
Purpose: explain exactly what happened to one payment.

Required content:
- immutable event timeline
- sender / receiver
- payment amount
- authorization identifier / payment ID as appropriate
- tx hash when submitted
- settlement state
- timestamps
- explorer action only when a tx hash exists

### 11. Profile
Purpose: local identity and wallet management entry point.

Required content:
- profile image or initial
- display name
- wallet address
- Edit profile
- Backup & recovery
- Settings
- About

### 12. Edit profile
Purpose: update cached nearby identity.

Required controls:
- display name
- profile photo
- save

Identity changes must feed the signed nearby identity message / local identity cache path already used by Blee.

### 13. Settings
Purpose: product/device preferences.

Required rows:
- discoverability
- notifications
- security
- backup & recovery
- settlement network information
- about
- Log out

### 14. Backup & recovery
Purpose: export or restore the encrypted wallet material through the existing recovery implementation.

The UI must never expose a raw private key by default.

### 15. Network & payment setup
Purpose: describe the active Blee settlement rail, not advertise unsupported multi-network/multi-asset functionality.

Current product:
- Arc Testnet
- USDC
- chain ID 5042002

Any future network expansion must be introduced deliberately and must not leak into the current UI before supported end-to-end.

## Navigation

Bottom navigation is the single primary destination navigation:

`Home · Nearby · Activity · Profile`

Send and Receive are payment actions, not permanent tabs.

## Motion

- screen transition: 180–240ms, fade + 4–6px translate
- sheet transition: 220–260ms upward motion
- button press: subtle scale only
- no decorative looping animations
- respect `prefers-reduced-motion`

## Build-time invariants

The Blee build must fail if any of the following regress:

- 12-character passphrase rule/copy returns
- wallet crypto path does not enforce 8-character minimum
- Send or Receive action is missing
- inactivity/background auto-lock timer returns
- sponsored relay implementation returns
- sender-funded raw transaction path disappears
- native atomic signing reservation disappears
- legacy orbit/radar/halo design layer is not disabled
