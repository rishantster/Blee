#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

rm -f dist/Blee.apk dist/Blee.apk.sha256
bash "$ROOT/build-blee-professional.command"

test -f "$ROOT/dist/Blee.apk" || { echo "ERROR: canonical build did not produce dist/Blee.apk"; exit 1; }
unzip -t "$ROOT/dist/Blee.apk" >/dev/null

echo "Canonical Blee artifact: $ROOT/dist/Blee.apk"
