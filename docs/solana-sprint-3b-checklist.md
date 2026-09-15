# Sprint 3B — historical network isolation

Status: **implemented; local repository/build gate required**

Rollback baseline: Sprint 3A head `0aee9dde8613cd1fdb3b94968abb54d0130c3978`.

## What changed

- Durable payment history remains network-addressable through `networkId`, `railId`, asset, environment and chain-family metadata.
- When an Arc payment belongs to a network other than the release-selected Arc network, its exact EIP-3009 authorization is retained as `archivedAuthorization` for audit/history but removed from the runtime `authorization` field.
- Because the existing settlement/retry/reservation loops act only on rows with a runtime `authorization`, inactive-network history cannot be reserved, relayed, retried or settled against the current Arc network.
- Durable rewrite preserves the exact historical signed authorization; it is not discarded or rewritten for another chain.
- Cached Arc balance snapshots are now keyed by network ID + wallet address.
- Arc chain scan cursors are now keyed by network ID + wallet address.
- Legacy unscoped balance/cursor values are migrated only while Arc Testnet is the active release network. They are never reused by Arc Mainnet.
- `npm run verify` now executes a dedicated Sprint 3B network-boundary verifier after the existing source-first verifier.

## Intentionally unchanged

- BLE discovery/profile handshake.
- Existing Arc Testnet EIP-3009 signing and settlement behavior.
- UI asset/network selector.
- Solana transaction signing or durable nonce engine.
- Arc Mainnet operational parameters remain unset and release-gated.
- `main` and the frozen known-good checkpoint remain untouched.

## Gate required

1. `npm run check`
2. `npm run verify`
3. `npm run android:build`
4. Confirm existing Arc Testnet wallet unlock/activity still load.
5. Confirm one small two-phone Arc Testnet USDC send/receive still behaves as before.

Do not activate Arc Mainnet or begin the Solana nonce engine until this gate is clean.
