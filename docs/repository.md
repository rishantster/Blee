# Repository architecture

Blee is a source-first repository. The checked-in application and native source are authoritative.

## Canonical source

- `app/` — Next.js application shell and global styles
- `src/` — React UI, wallet, payments and runtime logic
- `plugins/` — Capacitor plugins
- `android/` — Android project and native BLE/Nearby/SQLite implementation
- `public/` — application assets
- `assets/brand/` — canonical Blee identity assets
- `website/` — marketing site, independent from the Android application when present

## Build rules

1. Builds compile the tracked source directly.
2. Build scripts may generate output, but must never generate the application source itself.
3. No tar/base64 source archives, UI bundles, string-rewrite patch pipelines, or alternate source snapshots may become build dependencies.
4. There is one Android build entrypoint and one CI workflow.
5. Version name/code are defined once and verified against the produced APK.
6. `node_modules`, Next output, Android build output, APKs and local SDK/tool caches are never committed.

## Historical material

`legacy/` is temporary provenance from the pre-cleanup archive-and-patch architecture. It is not an active source root. Any useful behavior must be migrated into canonical source before `legacy/` is removed.

## Feature branches

Experimental work must live on a clearly named branch. Store-and-forward relay work is archived separately and is not part of production until deliberately reintroduced and tested.

## Change discipline

Transport, payment authorization and persistence changes require direct source review plus regression testing. Marker-only verification is not a substitute for compiling and exercising the real application.
