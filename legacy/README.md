# Legacy Blee build system

This directory is a frozen archive of the pre-cleanup Blee build system.

It contains the old bootstrap archives, UI bundles, template trees, overrides and source-rewrite scripts that were previously used to reconstruct the app during every build. They are retained temporarily for provenance and feature recovery only.

## Rules

- Do not build Blee from this directory.
- Do not add new product changes here.
- Do not reintroduce archive bundles or patch-chain source generation into the active repository.
- If a behavior exists only here, port it into the tracked source tree and test it there.

After the source-first tree is verified, this directory can be removed. The pre-cleanup history remains preserved on `archive/pre-source-cleanup-2026-09-13`.
