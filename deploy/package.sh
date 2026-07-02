#!/usr/bin/env bash
# ============================================================
# ServerHub — build a clean, release-ready bundle.
#
# Produces:
#   dist/serverhub/              ← the folder to upload to hosting / push to git
#   dist/serverhub-<date>.tar.gz ← a single archive of the same
#
# It builds the frontend, then copies ONLY the files needed to deploy —
# excluding venvs, node_modules, secrets (.env), databases, caches and the
# private automation scripts.
#
# Run locally (needs Node + npm):   bash deploy/package.sh
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/dist/serverhub"
STAMP="$(date +%Y%m%d)"

echo "==> Building frontend"
( cd "$ROOT/frontend" && npm install --no-fund --no-audit && npm run build )
#  ^ outputs to backend/static/

echo "==> Assembling bundle at $OUT"
rm -rf "$ROOT/dist"
mkdir -p "$OUT/backend" "$OUT/frontend"

# Backend (app code + built static + requirements + setup) — copy, then strip junk
cp -r "$ROOT/backend/." "$OUT/backend/"
rm -rf "$OUT/backend/venv" "$OUT/backend/.venv-test" "$OUT/backend/.env" \
       "$OUT/backend/db" "$OUT/backend/backups" 2>/dev/null || true
find "$OUT/backend" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT/backend" -maxdepth 1 -type d -name 'db-*' -exec rm -rf {} + 2>/dev/null || true

# Frontend SOURCE only (so it can be rebuilt) — no node_modules / build output
cp -r "$ROOT/frontend/src" "$OUT/frontend/src"
for f in index.html package.json package-lock.json vite.config.js \
         tailwind.config.js postcss.config.js; do
  [ -f "$ROOT/frontend/$f" ] && cp "$ROOT/frontend/$f" "$OUT/frontend/$f"
done

# Deploy scripts + docs + project front matter
cp -r "$ROOT/deploy" "$OUT/deploy"
cp "$ROOT/.gitignore" "$OUT/.gitignore"
for f in README.md DEPLOYMENT.md UPDATING.md DASHBOARD_GUIDE.md \
         SCRIPTS_GUIDE.md PACKAGING.md MASTER_BUILD_PROMPT.md LICENSE; do
  [ -f "$ROOT/$f" ] && cp "$ROOT/$f" "$OUT/$f"
done

# Ship the example env, never a real one
[ -f "$ROOT/backend/.env.example" ] && cp "$ROOT/backend/.env.example" "$OUT/backend/.env.example"

echo "==> Creating archive"
( cd "$ROOT/dist" && tar czf "serverhub-$STAMP.tar.gz" serverhub )

echo
echo "============================================================"
echo " Bundle ready:"
echo "   $OUT"
echo "   $ROOT/dist/serverhub-$STAMP.tar.gz"
echo
echo " Upload to hosting:  scp dist/serverhub-$STAMP.tar.gz user@host:/opt/"
echo "                     then: tar xzf serverhub-$STAMP.tar.gz && sudo bash serverhub/deploy/install.sh"
echo " Push to git:        see PACKAGING.md"
echo "============================================================"
