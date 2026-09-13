#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BRANCH="$(git branch --show-current)"
if [ "$BRANCH" != "recovery/canonical-source-v1" ]; then
  echo "ERROR: run this only on recovery/canonical-source-v1 (current: ${BRANCH:-detached})" >&2
  exit 1
fi

required=(
  package.json
  src/components/BleeApp.tsx
  src/components/BleeRuntime.tsx
  src/hooks/useBlee.ts
  app/globals.css
  android/app/build.gradle
  android/app/src/main/AndroidManifest.xml
)
for path in "${required[@]}"; do
  [ -f "$path" ] || {
    echo "ERROR: resolved source is missing $path" >&2
    echo "Run the normal Blee materialization/build stages first; do not delete your local generated tree." >&2
    exit 1
  }
done

MESH_SERVICE="$(find android/app/src/main/java -name BleeMeshService.java -print -quit)"
MESH_DB="$(find android/app/src/main/java -name BleeMeshDb.java -print -quit)"
MESH_PLUGIN="$(find android/app/src/main/java -name BleeMeshPlugin.java -print -quit)"
[ -n "$MESH_SERVICE" ] && [ -n "$MESH_DB" ] && [ -n "$MESH_PLUGIN" ] || {
  echo "ERROR: resolved native Blee mesh source is incomplete" >&2
  exit 1
}

# Never commit generated build/cache output. Keep only human-editable source,
# configuration, native source and lockfiles.
rm -rf node_modules .next out dist .blee-tools
rm -rf android/.gradle android/build android/app/build
rm -f android/local.properties
find . -name .DS_Store -delete

cat > SOURCE_PROVENANCE.md <<EOF
# Blee source provenance

This branch was converted from the legacy archive-and-patch build system into a
normal source-first repository on $(date -u +%Y-%m-%dT%H:%M:%SZ).

The tracked application/native source below is the resolved tree that existed
locally after the legacy pipeline had materialized and patched Blee. From this
point forward, product changes must be made directly to tracked source files;
archive bundles and string-rewrite patch chains are historical inputs only.

## Resolved source roots

- \`app/\` — Next.js application shell/styles
- \`src/\` — Blee React/application logic
- \`plugins/\` — Capacitor plugins
- \`android/\` — Android project and native Blee transport/persistence code
- \`public/\` — static application assets
- \`website/\` — marketing site (kept independent from the Android application)
EOF

# Force-add only source/configuration paths that were historically ignored.
for path in \
  package.json package-lock.json \
  next.config.ts next.config.js tsconfig.json postcss.config.mjs \
  capacitor.config.ts capacitor.config.json \
  app src public plugins android \
  SOURCE_PROVENANCE.md; do
  if [ -e "$path" ]; then
    git add -f "$path"
  fi
done

# Explicitly unstage known generated output if a broad ignore rule changed.
git reset -q -- \
  'android/.gradle' 'android/build' 'android/app/build' \
  'node_modules' '.next' 'out' 'dist' 2>/dev/null || true

if git diff --cached --quiet; then
  echo "No resolved source changes to commit."
  exit 0
fi

git config user.name "Rish"
git config user.email "75270803+rishantster@users.noreply.github.com"
git commit -m "Materialize resolved Blee source tree"
git push origin HEAD:recovery/canonical-source-v1

echo
echo "Resolved Blee source pushed to recovery/canonical-source-v1."
echo "Do not run the legacy builder again on this branch."
