# Sprint 2 — Solana identity / encrypted vault

Status: **implementation complete; repository/build + physical regression gate still open**

Rollback baseline: `checkpoint/blee-2.7.1-known-good-2026-09-14` (`f079bfe45aeb468b8629d064fb89a743ceb0ed2d`)

Current feature head: `92148b1496791d46dbc8e22d2c99a002889b4a5e`

## Sprint 2A — identity / encrypted vault

Implemented:

- Independent `wallet.solana.v1` vault.
- Existing `wallet.vault.v2` Arc/EVM vault remains intact.
- Solana key algorithm: Ed25519 via Web Crypto.
- Persisted encryption: PBKDF2-SHA256 -> AES-256-GCM using 600,000 iterations, 16-byte random salt, 12-byte random IV.
- Public Solana address derived from the 32-byte Ed25519 public key using base58.
- On unlock, private key material is imported as a non-extractable `CryptoKey`.
- Decrypted private bytes are zeroed best-effort after import.
- Solana session preparation begins only after successful primary Arc authentication.
- Solana session preparation is non-blocking and cannot prevent an otherwise-valid Arc create/unlock.
- Solana signer lifetime is tied to the authenticated primary account object via `WeakMap`.

Validated on the prior Sprint 2A head (`93a16702a0731b0c87207c3f219874006fa4c768`):

- `npm run check`: pass.
- `npm run verify`: pass.
- Android production build pipeline: pass.
- APK produced successfully as Blee 2.7.1 / versionCode 18.
- APK SHA-256 from that gate: `7aee9acaadae4584db89ff732459f831e07d6c1b4d69ebfa9cef1b99f1b1ad14`.

## Sprint 2B — Backup v2 / restore consistency

Implemented:

- Backup v2 exports both already-encrypted wallet vault representations without decrypting private keys.
- Backup v1 import remains supported for backups produced by Blee <=2.7.1.
- Solana backup vault structure is validated before restore.
- Solana addresses are base58-decoded and required to resolve to exactly 32 bytes.
- Dual-wallet restore uses a durable SQLite-backed restore journal (`wallet.restore.v2.pending`).
- The restore journal contains encrypted vault representations only; it never contains plaintext private keys.
- Restore is roll-forward and idempotent: if the app/process dies between Solana and Arc vault writes, the journal remains and is completed before either wallet identity can be read again.
- Existing Arc-only Backup v1 restore is intentionally non-destructive toward a pre-existing Solana vault because a legacy backup contains no Solana key material and must never silently erase access to SOL funds.
- Arc and Solana vault read paths both complete any pending restore before exposing an address/signer.

## Unchanged invariants

- No payment state-machine change.
- No BLE discovery/profile/identity change.
- No Arc authorization or settlement change.
- No UI change.
- No Helius/provider secret in client source.
- No direct Solana RPC provider URL in client source.
- `main` remains untouched.

## Gate still required

Run against feature head `92148b1496791d46dbc8e22d2c99a002889b4a5e`:

1. `npm run check`
2. `npm run verify`
3. `npm run android:build`
4. Existing Arc wallet unlock on device.
5. Existing Arc USDC send/receive between the same two physical devices.
6. Logout/relaunch/unlock check to ensure existing Arc state and activity remain intact.

Do not begin Sprint 3 until this gate passes.
