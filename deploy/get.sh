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
# It asks for the admin login, the panel domain and an email for SSL, then does
# everything: packages, panel, admin user, nginx, HTTPS, PostgreSQL, automatic
# security updates. Fully unattended instead:
#   curl -fsSL .../get.sh | sudo ADMIN_USER=hamza ADMIN_PASS='…' PANEL_DOMAIN=panel.example.com \
#        SSL_EMAIL=you@example.com bash
# Other options: INSTALL_POSTGRES=no, AUTO_UPDATES=no, REPO_URL=…, BRANCH=…
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

# 0. Ask for what isn't given (from the terminal — stdin is this script under curl | bash)
ask() {   # ask VAR "Question" [secret]
  local var="$1" q="$2" secret="${3:-}" val=""
  [ -n "${!var:-}" ] && return 0
  [ -r /dev/tty ] || return 0
  # no usable terminal (e.g. cloud-init): just skip the question
  if [ -n "$secret" ]; then { read -r -s -p "$q" val </dev/tty && echo >/dev/tty; } 2>/dev/null || true
  else { read -r -p "$q" val </dev/tty; } 2>/dev/null || true; fi
  printf -v "$var" '%s' "$val"
}
if [ -z "${UNATTENDED:-}" ]; then
  echo "Answer or press Enter to skip (everything can be set later):"
  ask ADMIN_USER   "  Admin username: "
  if [ -n "${ADMIN_USER:-}" ]; then
    for _ in 1 2 3; do
      ask ADMIN_PASS "  Admin password (min 8): " secret
      [ "${#ADMIN_PASS}" -ge 8 ] && break
      { echo "  Too short (or no terminal)." >/dev/tty; } 2>/dev/null || true
      ADMIN_PASS=""
    done
  fi
  ask PANEL_DOMAIN "  Panel domain, e.g. panel.example.com (DNS pointing here): "
  [ -n "${PANEL_DOMAIN:-}" ] && ask SSL_EMAIL "  Email for the SSL certificate: "
fi
export ADMIN_USER ADMIN_PASS PANEL_DOMAIN SSL_EMAIL INSTALL_POSTGRES AUTO_UPDATES 2>/dev/null || true

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

echo " (Re-running this command is safe; for routine updates use deploy/update.sh.)"
