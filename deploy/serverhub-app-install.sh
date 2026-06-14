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
