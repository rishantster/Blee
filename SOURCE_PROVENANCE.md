# Blee source provenance

This branch was converted from the legacy archive-and-patch build system into a
normal source-first repository on 2026-09-13T17:59:09Z.

The tracked application/native source below is the resolved tree that existed
locally after the legacy pipeline had materialized and patched Blee. From this
point forward, product changes must be made directly to tracked source files;
archive bundles and string-rewrite patch chains are historical inputs only.

## Resolved source roots

- `app/` — Next.js application shell/styles
- `src/` — Blee React/application logic
- `plugins/` — Capacitor plugins
- `android/` — Android project and native Blee transport/persistence code
- `public/` — static application assets
- `website/` — marketing site (kept independent from the Android application)
