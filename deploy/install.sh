#!/usr/bin/env bash
# ============================================================
# ServerHub — Ubuntu VPS installation script (all phases)
# Run as root (or with sudo) on Ubuntu 22.04+.
# Re-runnable: every step is idempotent.
# ============================================================
set -euo pipefail

PANEL_USER="serverhub"
PANEL_ROOT="/srv/serverhub"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Interpreter used to build the venv. On Ubuntu 22.04 run the installer with
# PYTHON3=python3.11 so the panel gets Python 3.11 (the deadsnakes package).
PYTHON3="${PYTHON3:-python3}"

echo "==> Installing system packages"
apt-get update
# Core panel + all feature dependencies:
#   nginx/supervisor      reverse proxy + process manager
#   mysql-server          databases manager
#   php-fpm               PHP website hosting
#   certbot               Let's Encrypt SSL
apt-get install -y python3 python3-venv python3-pip nginx supervisor curl rsync wget \
  mysql-server php-fpm certbot python3-certbot-nginx unzip

# Headless browser for project Selenium scripts: install REAL Google Chrome
# (.deb), NOT snap chromium — the snap chromedriver crashes under the serverhub
# service user and can't write downloads to /srv. Selenium Manager (bundled with
# the selenium pip package) auto-downloads the matching driver at runtime.
echo "==> Installing Google Chrome (for Selenium)"
if ! command -v google-chrome >/dev/null; then
  snap remove chromium 2>/dev/null || true
  apt-get remove -y chromium-browser chromium-chromedriver 2>/dev/null || true
  TMP_DEB="$(mktemp --suffix=.deb)"
  wget -qO "$TMP_DEB" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  apt-get install -y "$TMP_DEB"
  rm -f "$TMP_DEB"
fi
google-chrome --version || true

# Node 18+ for building the frontend (skipped if node >= 18 already present)
if ! command -v node >/dev/null || [ "$(node -e 'console.log(process.versions.node.split(".")[0])')" -lt 18 ]; then
  echo "==> Installing Node.js 20"
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

echo "==> Creating panel user and directories"
id -u "$PANEL_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash "$PANEL_USER"
mkdir -p "$PANEL_ROOT"/{db,supervisor.d} /srv/projects /srv/websites /srv/nginx-configs
mkdir -p /var/log/supervisor

echo "==> Copying application code"
cp -r "$REPO_DIR/backend" "$PANEL_ROOT/"
cp -r "$REPO_DIR/frontend" "$PANEL_ROOT/"

echo "==> Python virtualenv + dependencies (using $PYTHON3)"
"$PYTHON3" -m venv "$PANEL_ROOT/venv"
"$PANEL_ROOT/venv/bin/pip" install --upgrade pip
"$PANEL_ROOT/venv/bin/pip" install -r "$PANEL_ROOT/backend/requirements.txt"
# Streamlit runs project dashboards; selenium + webdriver-manager + openpyxl
# are commonly needed by project scripts (headless Chromium, Excel data).
"$PANEL_ROOT/venv/bin/pip" install streamlit selenium webdriver-manager openpyxl pandas

echo "==> Building frontend"
cd "$PANEL_ROOT/frontend"
npm install
npm run build   # outputs to ../backend/static/

echo "==> Backend .env"
if [ ! -f "$PANEL_ROOT/backend/.env" ]; then
  cp "$PANEL_ROOT/backend/.env.example" "$PANEL_ROOT/backend/.env"
  SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET|" "$PANEL_ROOT/backend/.env"
  # Use the panel venv's binaries for project scripts and streamlit
  sed -i "s|^PYTHON_BIN=.*|PYTHON_BIN=$PANEL_ROOT/venv/bin/python|" "$PANEL_ROOT/backend/.env"
  sed -i "s|^STREAMLIT_BIN=.*|STREAMLIT_BIN=$PANEL_ROOT/venv/bin/streamlit|" "$PANEL_ROOT/backend/.env"
  # Point the in-panel "Update now" button at this source checkout
  if grep -q "^UPDATE_SRC=" "$PANEL_ROOT/backend/.env"; then
    sed -i "s|^UPDATE_SRC=.*|UPDATE_SRC=$REPO_DIR|" "$PANEL_ROOT/backend/.env"
  else
    echo "UPDATE_SRC=$REPO_DIR" >> "$PANEL_ROOT/backend/.env"
  fi
  echo "    Generated backend/.env with a fresh SECRET_KEY"
fi

echo "==> Permissions"
mkdir -p "$PANEL_ROOT/shopify-apps"
chown -R "$PANEL_USER:$PANEL_USER" /srv/projects /srv/websites /srv/nginx-configs "$PANEL_ROOT/shopify-apps"
# $PANEL_ROOT but NOT $PANEL_ROOT/apps — Docker apps (e.g. self-hosted Supabase)
# own their data there; chowning Postgres's data dir breaks it.
find "$PANEL_ROOT" -path "$PANEL_ROOT/apps" -prune -o -exec chown "$PANEL_USER:$PANEL_USER" {} +
# Panel user must be able to write supervisor program logs
chown "$PANEL_USER:$PANEL_USER" /var/log/supervisor || true
# Selenium Manager caches its driver under the panel user's home
mkdir -p "/home/$PANEL_USER/.cache"
chown -R "$PANEL_USER:$PANEL_USER" "/home/$PANEL_USER"

echo "==> Apps installer + helpers"
mkdir -p "$PANEL_ROOT/bin" "$PANEL_ROOT/apps" "$PANEL_ROOT/backups"
install -m 0755 "$REPO_DIR/deploy/serverhub-app-install.sh" "$PANEL_ROOT/bin/serverhub-app-install"
install -m 0755 "$REPO_DIR/deploy/serverhub-webtop.sh" "$PANEL_ROOT/bin/serverhub-webtop"
install -m 0755 "$REPO_DIR/deploy/serverhub-xfce-desktop.sh" "$PANEL_ROOT/bin/serverhub-xfce-desktop"
install -m 0755 "$REPO_DIR/deploy/serverhub-self-update.sh" "$PANEL_ROOT/bin/serverhub-self-update"
install -m 0755 "$REPO_DIR/deploy/serverhub-cleanup.sh" "$PANEL_ROOT/bin/serverhub-cleanup"

echo "==> Sudoers rule"
install -m 0440 "$REPO_DIR/deploy/sudoers-serverhub" /etc/sudoers.d/serverhub
visudo -c >/dev/null   # abort if the sudoers file is invalid

echo "==> Supervisor include for panel-managed dashboards"
if ! grep -q "$PANEL_ROOT/supervisor.d" /etc/supervisor/supervisord.conf; then
  # Append our directory to the existing [include] files line
  sed -i "s|^files = .*|& $PANEL_ROOT/supervisor.d/*.conf|" /etc/supervisor/supervisord.conf
fi

echo "==> Supervisor program for the panel itself"
sed "s|{PANEL_ROOT}|$PANEL_ROOT|g; s|{PANEL_USER}|$PANEL_USER|g" \
  "$REPO_DIR/deploy/serverhub.supervisor.conf" > /etc/supervisor/conf.d/serverhub.conf
supervisorctl reread
supervisorctl update
supervisorctl restart serverhub || supervisorctl start serverhub

echo "==> Nginx site for the panel"
cp "$REPO_DIR/deploy/nginx-panel.conf" /etc/nginx/sites-available/serverhub
ln -sf /etc/nginx/sites-available/serverhub /etc/nginx/sites-enabled/serverhub
# Remove the stock "Welcome to nginx" default site — otherwise it acts as the
# default_server and Certbot can attach certs to it instead of the panel,
# leaving the domain showing the nginx welcome page.
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo
echo "============================================================"
echo " ServerHub installed."
echo
echo " 1. Create your admin user:"
echo "      cd $PANEL_ROOT/backend && sudo -u $PANEL_USER $PANEL_ROOT/venv/bin/python setup_admin.py"
echo " 2. Edit /etc/nginx/sites-available/serverhub and set your"
echo "    panel domain, then: sudo nginx -t && sudo systemctl reload nginx"
echo " 3. (Optional) SSL: sudo certbot --nginx -d panel.yourdomain.com"
echo
echo " Panel API:  http://127.0.0.1:8765"
echo "============================================================"
