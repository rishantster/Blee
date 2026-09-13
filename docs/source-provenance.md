# Source provenance

Blee originally evolved through a bootstrap/archive build system in which an older application snapshot was materialized and then modified by a long sequence of source-rewrite scripts. That made it possible for clean builds to recreate stale UI or omit later work even when individual patch scripts were newer.

On 2026-09-13 the resolved application tree was exported from the working local materialized project and committed as normal source. From this point forward, `app/`, `src/`, `plugins/`, `android/`, and the root configuration files are the source of truth.

The historical pipeline has been removed from the active source branch. It remains recoverable through Git history and archive branches, including the pre-cleanup repository snapshot and separately preserved experimental transport/relay work.

No active build should consume bootstrap parts, UI bundles, `.in` templates, or `apply-blee-*` mutation scripts.
