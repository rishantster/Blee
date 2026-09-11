#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
echo "Deprecated: use ./build-blee.command"
exec bash "$ROOT/build-blee.command" "$@"
