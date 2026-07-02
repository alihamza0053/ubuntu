#!/usr/bin/env bash
# ============================================================
# ServerHub — one-click ONLINE installer (bootstrap).
#
# Installs the whole panel on a fresh Ubuntu server with a single command —
# it pulls the source and runs deploy/install.sh, which installs every
# dependency (nginx, supervisor, mysql, php, certbot, Google Chrome, Node,
# Python venv + pip packages) and builds the frontend. No manual setup.
#
#   curl -fsSL https://raw.githubusercontent.com/alihamza0053/ubuntu/main/deploy/get.sh | sudo bash
#
# Override defaults with env vars, e.g.:
#   curl -fsSL .../get.sh | sudo REPO_URL=https://github.com/alihamza0053/ubuntu.git BRANCH=main bash
# ============================================================
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/alihamza0053/ubuntu.git}"
BRANCH="${BRANCH:-main}"
SRC="${SRC:-/opt/serverhub-src}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run as root (use sudo)." >&2
  exit 1
fi

echo "============================================================"
echo " ServerHub one-click install"
echo "   repo:   $REPO_URL ($BRANCH)"
echo "   source: $SRC"
echo "============================================================"

# 1. git (the only prerequisite the bootstrap itself needs)
if ! command -v git >/dev/null 2>&1; then
  echo "==> Installing git"
  apt-get update -y
  apt-get install -y git
fi

# 2. Get / refresh the source
if [ -d "$SRC/.git" ]; then
  echo "==> Updating existing source at $SRC"
  git -C "$SRC" fetch --depth 1 origin "$BRANCH"
  git -C "$SRC" reset --hard "origin/$BRANCH"
else
  echo "==> Cloning into $SRC"
  rm -rf "$SRC"
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$SRC"
fi

# 3. Install everything (idempotent — safe to re-run)
echo "==> Running deploy/install.sh"
cd "$SRC"
bash deploy/install.sh

echo
echo "============================================================"
echo " Done. Next:"
echo "   1. Create your admin user:"
echo "        cd /srv/serverhub/backend && sudo -u serverhub /srv/serverhub/venv/bin/python setup_admin.py"
echo "   2. Point your panel domain in /etc/nginx/sites-available/serverhub,"
echo "      then: sudo nginx -t && sudo systemctl reload nginx"
echo "   3. (SSL) sudo certbot --nginx -d panel.yourdomain.com"
echo
echo " Re-running this same command later updates the panel in place."
echo "============================================================"
