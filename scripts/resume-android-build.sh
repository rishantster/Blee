#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Blee 2.7 uses one canonical clean production build pipeline."
echo "The old generated-tree resume path is disabled to prevent stale patch-state regressions."
echo "Running: bash build-blee.command"
echo

exec bash "$ROOT/build-blee.command"
