#!/usr/bin/env bash
# ============================================================
# ServerHub — update / redeploy script
# Run AFTER the panel is already installed, to push new code.
#
# Usage (run as root / with sudo):
#   sudo bash deploy/update.sh                 # full update (backend + frontend)
#   sudo bash deploy/update.sh --backend-only  # skip the frontend rebuild
#   sudo bash deploy/update.sh --frontend-only # only rebuild the UI
#   sudo bash deploy/update.sh --no-pull       # don't 'git pull' first
#
# Source dir defaults to the repo this script lives in. Override with:
#   sudo SRC=/opt/serverhub-src bash deploy/update.sh
#
# It NEVER touches backend/.env (your SECRET_KEY) or the database.
# ============================================================
set -euo pipefail

PANEL_USER="serverhub"
PANEL_ROOT="/srv/serverhub"
SRC="${SRC:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

DO_BACKEND=true
DO_FRONTEND=true
DO_PULL=true

for arg in "$@"; do
  case "$arg" in
    --backend-only)  DO_FRONTEND=false ;;
    --frontend-only) DO_BACKEND=false ;;
    --no-pull)       DO_PULL=false ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run with sudo / as root." >&2
  exit 1
fi

if [ ! -d "$PANEL_ROOT/venv" ]; then
  echo "ERROR: $PANEL_ROOT/venv not found — is ServerHub installed?" >&2
  echo "       Run deploy/install.sh first." >&2
  exit 1
fi

echo "==> Source:   $SRC"
echo "==> Target:   $PANEL_ROOT"

# 1. Pull latest code if the source is a git checkout
if [ "$DO_PULL" = true ] && [ -d "$SRC/.git" ]; then
  echo "==> git pull"
  BEFORE_PULL="$(git -C "$SRC" rev-parse HEAD)"
  git -C "$SRC" pull --ff-only
  AFTER_PULL="$(git -C "$SRC" rev-parse HEAD)"
  # If the pull changed anything, THIS script file may be stale (bash keeps
  # running the copy it opened before the pull). Re-exec the freshly pulled
  # update.sh so new deploy steps (helpers, sudoers, …) actually run.
  # --no-pull on the re-exec guarantees this happens at most once.
  if [ "$BEFORE_PULL" != "$AFTER_PULL" ]; then
    echo "==> update.sh may have changed — re-running the updated copy"
    exec bash "$SRC/deploy/update.sh" --no-pull "$@"
  fi
fi

# 2. Safety: back up .env and the database before touching anything
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$PANEL_ROOT/backups/$STAMP"
mkdir -p "$BACKUP_DIR"
[ -f "$PANEL_ROOT/backend/.env" ] && cp "$PANEL_ROOT/backend/.env" "$BACKUP_DIR/.env"
[ -f "$PANEL_ROOT/db/serverhub.db" ] && cp "$PANEL_ROOT/db/serverhub.db" "$BACKUP_DIR/serverhub.db"
echo "==> Backed up .env + database to $BACKUP_DIR"

# 3. Backend
if [ "$DO_BACKEND" = true ]; then
  echo "==> Updating backend code (preserving .env)"
  # Copy app code but never overwrite the live .env
  rsync -a --delete \
    --exclude '.env' \
    --exclude 'static/' \
    --exclude '__pycache__/' \
    "$SRC/backend/" "$PANEL_ROOT/backend/"

  echo "==> Updating Python dependencies"
  "$PANEL_ROOT/venv/bin/pip" install -q -r "$PANEL_ROOT/backend/requirements.txt"
fi

# 4. Frontend
if [ "$DO_FRONTEND" = true ]; then
  echo "==> Rebuilding frontend"
  rsync -a --delete --exclude 'node_modules/' "$SRC/frontend/" "$PANEL_ROOT/frontend/"
  ( cd "$PANEL_ROOT/frontend" && npm install --no-fund --no-audit && npm run build )
fi

# 4b. Deploy helpers (Apps installer + sudoers) — keep them current
if [ -f "$SRC/deploy/serverhub-app-install.sh" ]; then
  echo "==> Updating apps installer + helpers + sudoers"
  mkdir -p "$PANEL_ROOT/bin" "$PANEL_ROOT/apps"
  install -m 0755 "$SRC/deploy/serverhub-app-install.sh" "$PANEL_ROOT/bin/serverhub-app-install"
  [ -f "$SRC/deploy/serverhub-webtop.sh" ] && install -m 0755 "$SRC/deploy/serverhub-webtop.sh" "$PANEL_ROOT/bin/serverhub-webtop"
  [ -f "$SRC/deploy/serverhub-xfce-desktop.sh" ] && install -m 0755 "$SRC/deploy/serverhub-xfce-desktop.sh" "$PANEL_ROOT/bin/serverhub-xfce-desktop"
  [ -f "$SRC/deploy/serverhub-self-update.sh" ] && install -m 0755 "$SRC/deploy/serverhub-self-update.sh" "$PANEL_ROOT/bin/serverhub-self-update"
  [ -f "$SRC/deploy/serverhub-cleanup.sh" ] && install -m 0755 "$SRC/deploy/serverhub-cleanup.sh" "$PANEL_ROOT/bin/serverhub-cleanup"
  install -m 0440 "$SRC/deploy/sudoers-serverhub" /etc/sudoers.d/serverhub
  visudo -c >/dev/null
fi

# 4c. Make sure the panel knows where to self-update from (this source dir)
if [ -f "$PANEL_ROOT/backend/.env" ]; then
  if grep -q "^UPDATE_SRC=" "$PANEL_ROOT/backend/.env"; then
    sed -i "s|^UPDATE_SRC=.*|UPDATE_SRC=$SRC|" "$PANEL_ROOT/backend/.env"
  else
    echo "UPDATE_SRC=$SRC" >> "$PANEL_ROOT/backend/.env"
  fi
fi

# 4d. Let the panel user read this (root-owned) checkout without git's
# "dubious ownership" error, so the in-panel "Check for updates" works.
sudo -u "$PANEL_USER" git config --global --add safe.directory "$SRC" 2>/dev/null || true

# 5. Ownership + restart
echo "==> Fixing ownership (excluding apps/ — Docker apps own their own data)"
# NEVER recurse into $PANEL_ROOT/apps: Docker apps (e.g. self-hosted Supabase)
# keep their data there and Postgres refuses a data dir it doesn't own. A blanket
# 'chown -R' over it breaks Postgres with "pg_filenode.map: Permission denied".
find "$PANEL_ROOT" -path "$PANEL_ROOT/apps" -prune -o -exec chown "$PANEL_USER:$PANEL_USER" {} +
mkdir -p "$PANEL_ROOT/shopify-apps"
chown -R "$PANEL_USER:$PANEL_USER" "$PANEL_ROOT/shopify-apps"

echo "==> Restarting panel"
supervisorctl restart serverhub

# 6. Health check
sleep 2
if curl -fsS http://127.0.0.1:8765/api/health >/dev/null; then
  echo "==> OK — panel is healthy."
else
  echo "!! Panel did not answer /api/health. Check logs:" >&2
  echo "   sudo tail -n 50 /var/log/supervisor/serverhub.err.log" >&2
  echo "   Restore if needed from: $BACKUP_DIR" >&2
  exit 1
fi

echo
echo "Update complete ($STAMP)."
echo "Backup of previous .env + db: $BACKUP_DIR"
