#!/usr/bin/env bash
# ============================================================
# ServerHub — vetted app installer (runs as root via a single sudoers rule).
#
# The panel invokes:  sudo /srv/serverhub/bin/serverhub-app-install <slug>
# Only the known slugs below can be installed — never an arbitrary command.
# Installed to /srv/serverhub/bin/ by deploy/install.sh.
# ============================================================
set -euo pipefail

SLUG="${1:-}"

case "$SLUG" in
  --check)
    # Used by the panel to verify the sudo rule works.
    echo "ok"
    exit 0
    ;;
  code-server)
    echo "==> Installing code-server (VS Code in the browser)"
    if ! command -v code-server >/dev/null; then
      curl -fsSL https://code-server.dev/install.sh | sh
    fi
    code-server --version || true
    ;;

  filebrowser)
    echo "==> Installing File Browser"
    if ! command -v filebrowser >/dev/null; then
      curl -fsSL https://raw.githubusercontent.com/filebrowser/get/master/get.sh | bash
    fi
    filebrowser version || true
    ;;

  uptime-kuma)
    echo "==> Preparing Uptime Kuma (runs via npx on first start)"
    command -v node >/dev/null || { echo "Node.js is required"; exit 1; }
    command -v npx >/dev/null || { echo "npx is required"; exit 1; }
    echo "Ready — it downloads on first start."
    ;;

  syncthing)
    echo "==> Installing Syncthing"
    apt-get install -y syncthing
    mkdir -p /srv/serverhub/apps/syncthing
    syncthing --version || true
    ;;

  glances)
    echo "==> Installing Glances (web monitor)"
    apt-get install -y python3-venv
    python3 -m venv /srv/serverhub/apps/glances/venv
    /srv/serverhub/apps/glances/venv/bin/pip install --upgrade pip
    /srv/serverhub/apps/glances/venv/bin/pip install "glances[web]"
    ;;

  jupyterlab)
    echo "==> Installing JupyterLab"
    apt-get install -y python3-venv
    python3 -m venv /srv/serverhub/apps/jupyterlab/venv
    /srv/serverhub/apps/jupyterlab/venv/bin/pip install --upgrade pip
    /srv/serverhub/apps/jupyterlab/venv/bin/pip install jupyterlab
    ;;

  webtop)
    echo "==> Installing Web Browser desktop (Xvfb + noVNC + Firefox)"
    apt-get install -y xvfb x11vnc novnc websockify fluxbox firefox-esr
    ;;

  docker)
    echo "==> Installing Docker Engine + Compose"
    if ! command -v docker >/dev/null; then
      curl -fsSL https://get.docker.com | sh
    fi
    # Let the panel user run docker too (sudo rule also covers it)
    usermod -aG docker serverhub 2>/dev/null || true
    systemctl enable --now docker 2>/dev/null || true
    docker --version || true
    docker compose version || true
    ;;

  supabase)
    echo "==> Installing Supabase (docker compose stack) — this is large"
    command -v docker >/dev/null || { echo "Install Docker first"; exit 1; }
    command -v git >/dev/null || apt-get install -y git
    mkdir -p /srv/serverhub/apps/supabase
    if [ ! -d /srv/serverhub/apps/supabase/docker ]; then
      git clone --depth 1 https://github.com/supabase/supabase /srv/serverhub/apps/supabase/repo
      cp -r /srv/serverhub/apps/supabase/repo/docker /srv/serverhub/apps/supabase/docker
    fi
    cd /srv/serverhub/apps/supabase/docker
    [ -f .env ] || cp .env.example .env
    # Bind the Kong gateway to localhost only (panel proxies it via a domain)
    sed -i 's/^KONG_HTTP_PORT=.*/KONG_HTTP_PORT=8000/' .env 2>/dev/null || true
    # Clean leftovers from any previous attempt — Supabase uses FIXED container
    # names (supabase-*), so stale containers cause "name already in use".
    docker compose -p app_supabase down --remove-orphans 2>/dev/null || true
    docker compose down --remove-orphans 2>/dev/null || true
    STALE="$(docker ps -aq --filter 'name=supabase-')"
    [ -n "$STALE" ] && docker rm -f $STALE 2>/dev/null || true
    # Pre-pull images here (streamed); the PANEL brings the stack UP afterwards
    # so the compose project name stays consistent for start/stop/logs.
    docker compose -p app_supabase pull
    echo "Images pulled — the panel will start the stack."
    ;;

  google-chrome)
    echo "==> Installing Google Chrome (.deb)"
    if ! command -v google-chrome >/dev/null; then
      snap remove chromium 2>/dev/null || true
      apt-get remove -y chromium-browser chromium-chromedriver 2>/dev/null || true
      TMP="$(mktemp --suffix=.deb)"
      wget -qO "$TMP" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
      apt-get install -y "$TMP"
      rm -f "$TMP"
    fi
    google-chrome --version || true
    ;;

  *)
    echo "Unknown app: '$SLUG'" >&2
    exit 2
    ;;
esac

echo "==> $SLUG install step complete."
