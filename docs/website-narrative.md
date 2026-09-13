# Blee Website Narrative + Experience Spec

**Status:** Website direction v1  
**Product:** Blee  
**Purpose:** Define the story, copy, visual language, motion system, information architecture, and build rules for the public Blee website.

## Core idea

Digital payments became convenient, but they also became dependent. Most payment apps are interfaces to a remote system. The wallet state, identity, transaction history, routing logic and source of truth live somewhere else. Two people can be standing one metre apart and still need a distant server, working internet and a functioning cloud path just to exchange value.

Blee changes that architecture.

**Blee is local-first and self-custodial.**

Your wallet, keys, identity, contacts, payment history and payment state live on your phone under your control. Nearby Blee devices can discover each other and exchange signed payment data directly. Internet connectivity is used for blockchain settlement when available. It is not the permission layer for the payment itself.

# Primary brand line

# NO CLOUD BETWEEN YOU AND YOUR MONEY.

Supporting line:

> **Local-first. Self-custodial. Device-to-device. Internet for settlement — not permission.**

Secondary lines:

- **The payment network is already in your pocket.**
- **Your money lives with you.**
- **Phones pay phones.**
- **Internet for settlement. Not permission.**
- **The payment is yours. The route is Blee's problem.**
- **Two phones should not need a data centre to exchange money.**
- **Built local. Settled global.**
- **Blee cannot spend your money. That is the architecture.**

Avoid generic crypto language such as “revolutionizing payments”, “future of finance”, “seamless decentralized transactions”, “next-generation blockchain wallet”, “web3 payments”, and “powered by decentralization”.

## One-sentence positioning

**Blee is a local-first, self-custodial payment network where your keys, identity, activity and payment state live on your phone, nearby payments move directly between devices, and the internet is used for settlement rather than permission.**

Short description: **A self-custodial payment network that lives on your phone.**

## Narrative sequence

1. Payments became digital.
2. Digital payments became cloud-dependent.
3. Blee removes the cloud from the critical path.
4. The phone becomes the node.
5. Everything important lives locally.
6. Nearby devices can transact directly.
7. Payments survive temporary disconnection.
8. Signed payments can be carried and relayed without custody.
9. Any suitable internet path can later broadcast settlement.
10. The sender remains the authorizer and funder.
11. Blee routes complexity away from the user.
12. The result feels like a normal payment app, not a networking experiment.

This is not a feature page. It is a manifesto that gradually proves itself technically.

## Website scale

The website should be **large**: 16–20 major scroll sections, 8,000–12,000 px desktop scroll depth minimum, multiple immersive full-screen moments, alternating white/black environments, oversized editorial typography, live network visualizations, phone UI moments, technical proof sections, architecture, use cases, security, FAQ, and a final manifesto.

## Page structure

### 01 — Hero

**NO CLOUD / BETWEEN YOU / AND YOUR MONEY.**

Blee is a local-first, self-custodial payment network. Your wallet, keys, identity, history and payment state live on your phone. Nearby payments move directly between devices. Internet is settlement — not permission.

Visual: giant Blee mark, slow mesh field, one central phone/node. No token logos, gradients or blockchain cliché.

### 02 — The broken assumption

**TWO PHONES BESIDE EACH OTHER SHOULD NOT NEED A DATA CENTRE TO EXCHANGE MONEY.**

Most payment apps are remote controls for systems that live somewhere else. Blee flips that model.

### 03 — The phone is the node

**THE SYSTEM LIVES HERE.**

Wallet, keys, identity, contacts, payment journal, nearby peers, signed authorizations and activity history collapse into one device.

### 04 — Self-custody

**BLEE CANNOT SPEND YOUR MONEY.**  
**A RELAY CANNOT CHANGE YOUR PAYMENT.**  
**YOUR KEYS DO NOT LEAVE YOUR DEVICE.**

**That is not a privacy setting. It is the architecture.**

### 05 — Nearby discovery

**PEOPLE NEAR YOU. NOT ADDRESSES TO COPY.**

Blee discovers nearby Blee devices and resolves the interaction into a human payment experience. Choose a person. Enter an amount. Pay. QR remains a universal fallback.

### 06 — Phones pay phones

**PHONES PAY PHONES.**

No remote server is required to introduce two nearby devices or to persist the signed payment locally.

### 07 — Internet disappears

**INTERNET LOST. PAYMENT STATE INTACT.**

Blee persists payment state locally using a durable device-side journal. Connectivity can disappear without erasing what happened.

Do not claim blockchain finality while offline. Use explicit states such as “received locally”, “acknowledged”, “awaiting settlement”, and “chain confirmed”.

### 08 — Payment state is real

CREATED → SIGNED → QUEUED → DELIVERED LOCALLY → ACKNOWLEDGED → SETTLEMENT SUBMITTED → CHAIN CONFIRMED

**A PAYMENT IS NOT ONE BOOLEAN.**

### 09 — Store and forward

**YOUR PAYMENT CAN MOVE BEFORE THE INTERNET RETURNS.**

Blee can carry signed payment data through nearby devices. Relays transport what the sender already authorized. They do not become the owner, signer or payer.

### 10 — Courier rule

**CARRY IT. NEVER CONTROL IT.**

A courier cannot alter recipient, spend sender funds, or pay on the sender's behalf.

### 11 — Connectivity can come from anywhere

**THE FIRST ONLINE PATH WINS.**

Once a valid sender-signed settlement transaction reaches a Blee device with internet, that device can broadcast the already-signed bytes. Courier broadcasts only; courier signs nothing and never pays gas for another user's payment.

### 12 — Settlement

**LOCAL PAYMENT. GLOBAL FINALITY.**

Current implementation: Arc Testnet, USDC, EIP-3009 payment authorization, sender-signed EIP-1559 settlement transaction when a usable fee/nonce profile exists.

### 13 — One payment experience

**NO “OFFLINE MODE.” JUST PAY.**

Choose person → enter amount → confirm → Blee decides the path.

**The payment is yours. The route is Blee's problem.**

### 14 — Everything under your control

**YOUR PHONE IS NOT A WINDOW INTO BLEE. IT IS BLEE.**

On-device: private key, encrypted wallet, profile, peer identities, payment journal, transaction state, inbox/outbox, pending settlement jobs, activity history and backup material.

### 15 — Durable by design

**RESTART THE APP. THE PAYMENT DOESN'T FORGET.**

Payment state is written to a durable SQLite/WAL journal. The native Android process owns nearby networking and background reliability. The UI renders state; it is not the source of truth.

### 16 — Security architecture

Self-custody, signed authorization, sender-funded settlement, monotonic state, persistent deduplication, bounded routing.

### 17 — Blee Mesh

**A PAYMENT NETWORK MADE OF PHONES.**

Some devices send. Some receive. Some temporarily carry signed data closer to connectivity. None need custody of someone else's money.

### 18 — Use cases

Across the table, stadium, underground, campus, travel, infrastructure outage. Avoid implying guaranteed finality without internet.

### 19 — Built for what comes next

**TODAY: USDC ON ARC. THE ARCHITECTURE IS BIGGER.**

Do not advertise unsupported networks as currently available.

### 20 — Final manifesto

**PAYMENTS BECAME DIGITAL.**  
**THEN THEY BECAME DEPENDENT.**  
**BLEE REMOVES THE DEPENDENCY.**

**NO CLOUD BETWEEN YOU AND YOUR MONEY.**

## Voice

Decisive, technically literate, consumer-readable, minimal, slightly provocative, never crypto-bro, never startup-template. Avoid “seamless”, “revolutionary”, “game-changing”, “next-gen”. Keep jargon out of the first 40% of the page.

## Visual system

Palette: #0A0A0A, #121212, #FAFAF8, #F2F1ED, #D7D7D2, #8C8C87, #4D4D49. Primarily monochrome. No crypto purple/blue gradients.

Typography: premium grotesk / neo-grotesk. Large headlines 92–180 px desktop, 52–84 px mobile. Tight tracking, disciplined line heights. Body 18–24 px desktop, 16–19 px mobile.

Geometry: very large radius, near-borderless surfaces, thin rules, large whitespace.

## Motion

Use slow parallax, scroll-linked opacity, device-to-device pulses, canvas mesh particles, sticky full-screen scenes, text reveals, line-drawing transitions, state-machine progression and restrained spring easing. Avoid excessive bouncing, blobs, fake glow and 3D crypto coins. Target 60 fps and respect prefers-reduced-motion.

## Interaction principles

Every section makes one claim; the visual proves it; the copy works without crypto knowledge. Technical detail is progressive. No critical statement depends on animation alone. Mobile is first-class. Use real Blee assets. No fake product metrics, unsupported networks or fictional trust logos.

## Technical truth constraints

Current product: Android-first, self-custodial, USDC, Arc Testnet, BLE discovery/delivery, native Android foreground mesh service, SQLite/WAL local journal, store-and-forward, sender-funded settlement, relay broadcasts sender-signed bytes, optional biometric unlock, encrypted backup/recovery.

Do not state that iOS or unsupported networks exist today, that every offline payment is immediately final, that relays spend their own gas, that Blee servers are authoritative, or that Blee can recover a lost key without backup.

## CTA language

Primary: **Get Blee**, **See how it works**.  
Secondary: **Read the architecture**, **View on GitHub**, **Explore Blee Mesh**.

Avoid “Join the revolution”, “Get started for free”, “Unlock the future”.

## Viral narrative

> We put servers between people who are standing right next to each other.
>
> Blee removes them from the critical path.
>
> Your keys, identity, payment history and payment state live on your phone. Nearby Blee devices can pay each other directly. When internet returns, settlement catches up.
>
> No cloud between you and your money.

Short social version:

> Two phones beside each other should not need a data centre to exchange money.
>
> Blee is local-first, self-custodial payments.
>
> Phones pay phones. Internet settles.
>
> No cloud between you and your money.

Demo hook: **Kill the Wi‑Fi. Kill cellular. Make the payment anyway.**

Technical hook: **A Blee relay can carry your signed payment. It cannot rewrite it. It cannot sign for you. It cannot spend your funds. It can only help the transaction find connectivity.**

## SEO

Title: **Blee — No cloud between you and your money**

Description: **Blee is a local-first, self-custodial payment network. Your wallet and payment state live on your phone, nearby devices transact directly, and internet is used for settlement rather than permission.**

## Build requirements

Static deployable site; semantic HTML; custom CSS; vanilla JS; responsive from 320 px upward; high-DPI brand assets; canvas mesh visualization; IntersectionObserver reveals; sticky narrative sections; accessible keyboard focus and contrast; reduced-motion fallback; non-blocking animation work; no external tracking by default; no fake analytics counters.

## Definition of success

Within 30 seconds a visitor should understand that Blee is self-custodial, local-first, keeps important state on-device, enables nearby phones to communicate directly, does not require internet for the local interaction, settles when connectivity is available, and allows relays to carry signed payments without custody.

Within three minutes they should also understand the distinction between local delivery and chain finality, store-and-forward, sender-funded settlement, durable local state, Arc as the current settlement rail and why the architecture can expand beyond the first network.

# Final lockup

**BLEE**

# NO CLOUD BETWEEN YOU AND YOUR MONEY.

**Local-first. Self-custodial. Device-to-device.**
