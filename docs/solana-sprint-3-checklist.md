# Sprint 3 — Network model / Arc Mainnet readiness

Status: **Sprint 3A implementation ready for repository/build regression**

Rollback baseline: `checkpoint/blee-2.7.1-known-good-2026-09-14` (`f079bfe45aeb468b8629d064fb89a743ceb0ed2d`)

Sprint 2 physical gate: **passed** on APK SHA-256 `87665f0176610ed5ca2f4916d966993de8cccefd1557d42c710d518b144e8f0b`.

## Sprint 3A implemented

- Payment domain now has explicit `railId`, `networkId`, `assetId`, `assetSymbol`, `environment`, and `chainFamily` metadata.
- Legacy payment rows without network metadata are permanently interpreted as `arc-testnet`; they are never reinterpreted based on a future active network.
- New payment rows without explicit metadata inherit the release-selected active Arc network before their first durable write.
- Arc Testnet configuration remains the only operational Arc profile.
- Arc Mainnet has a pre-registered approved profile slot but remains `operational: false` with unknown launch parameters represented as `null` rather than guessed values.
- The active Arc network is controlled by a single release selector: `ACTIVE_ARC_NETWORK_ID`.
- `arc.ts` no longer hardcodes chain ID, token decimals, RPC, explorer, EIP-712 name/version, or USDC contract independently from the approved network profile.
- `arc-usdc` declares support for both `arc-testnet` and `arc-mainnet`, while its current active network still resolves to Testnet.
- Arbitrary custom RPC/contract profiles remain forbidden.

## Mainnet safety rule

Do not set `ACTIVE_ARC_NETWORK_ID` to `arc-mainnet` until all required operational values are published by an official Circle/Arc source and independently verified:

- chain ID
- RPC endpoint selected for Blee production use
- explorer URL
- native currency decimals
- USDC contract/address semantics
- USDC token decimals
- EIP-712 domain name/version used by `transferWithAuthorization`

Third-party chain lists, social posts, unofficial explorers, or guessed launch values are not sufficient for Blee signing configuration.

## Historical-payment invariant

A payment created on Arc Testnet remains an Arc Testnet payment forever. After a future Mainnet cutover, explorer links, reconciliation, settlement and activity rendering must use the `networkId` stored with that payment rather than the currently active network.

## Intentionally unchanged in Sprint 3A

- BLE discovery/profile characteristic and transport.
- EIP-3009 authorization structure.
- Existing Arc settlement state machine.
- Solana payment signing/nonce behavior.
- Current UI layout and send flow.
- Mainnet activation.

## Gate before Sprint 3B

1. `npm run check`
2. `npm run verify`
3. `npm run android:build`
4. Existing wallet upgrade/unlock regression.
5. Arc Testnet send/receive regression on the same two physical devices.
6. Confirm old activity remains present after install and still represents Testnet history.

Sprint 3B should address network-aware rendering/reconciliation boundaries before any Arc Mainnet activation is allowed.
