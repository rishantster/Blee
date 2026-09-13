# Blee

Blee is a proximity-first payments app for sending value to people nearby without asking for wallet addresses or QR codes.

This recovery branch is being converted from the old archive-and-patch build system into a normal source-first repository. The resolved application source will live directly in `app/`, `src/`, `plugins/`, `android/`, and `public/`.

## Repository layout

- `app/` — Next.js application shell
- `src/` — React UI, payments, wallet and runtime logic
- `plugins/` — Capacitor plugins
- `android/` — Android project and native BLE/Nearby/SQLite implementation
- `public/` — application assets
- `assets/brand/` — canonical Blee brand assets
- `docs/` — architecture and product documentation
- `legacy/` — frozen historical build inputs kept only for provenance during migration

## Rule

Product code is edited directly. Do not add new archive bundles, generated source snapshots, string-rewrite patch chains, or alternate build entrypoints.

The legacy tree is temporary and will be removed once the resolved source has been verified against the final application behavior.
