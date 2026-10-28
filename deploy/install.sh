#!/usr/bin/env bash
# ============================================================
# ServerHub — Ubuntu VPS installation script (all phases)
# Run as root (or with sudo) on Ubuntu 22.04+.
# Re-runnable: every step is idempotent.
# ============================================================
set -euo pipefail

PANEL_USER="serverhub"
PANEL_ROOT="/srv/serverhub"

# Optional — set these (get.sh asks for them) and the install needs no manual steps:
#   ADMIN_USER / ADMIN_PASS   create the first admin
#   PANEL_DOMAIN              e.g. panel.example.com (DNS must point at this server)
#   SSL_EMAIL                 Let's Encrypt account email (with PANEL_DOMAIN → HTTPS)
#   INSTALL_POSTGRES=no       skip PostgreSQL (default: installed)
#   AUTO_UPDATES=no           skip automatic security updates (default: on)
ADMIN_USER="${ADMIN_USER:-}"
ADMIN_PASS="${ADMIN_PASS:-}"
PANEL_DOMAIN="${PANEL_DOMAIN:-}"
SSL_EMAIL="${SSL_EMAIL:-}"
INSTALL_POSTGRES="${INSTALL_POSTGRES:-yes}"
AUTO_UPDATES="${AUTO_UPDATES:-yes}"
# No interactive apt/needrestart screens in the middle of an install
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
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

# Node.js: the panel builds its frontend with it and n8n runs on it.
# Node 20 and older get no security fixes any more (Oct 2026 advisory); these
# are the first patched releases of the supported lines.
NODE_MAJOR=24
node_ok() {   # true when the installed node is a supported, patched release
  command -v node >/dev/null 2>&1 || return 1
  local v maj min
  v="$(node -v 2>/dev/null | sed 's/^v//')"; maj="${v%%.*}"
  case "$maj" in
    22) min=22.23.4 ;;
    24) min=24.22.1 ;;
    26) min=26.12.1 ;;
    *) [ "${maj:-0}" -gt 26 ] 2>/dev/null && return 0; return 1 ;;
  esac
  [ "$(printf '%s\n%s\n' "$min" "$v" | sort -V | head -1)" = "$min" ]
}
install_node() {
  curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - && apt-get install -y nodejs
}
if ! node_ok; then
  echo "==> Installing Node.js ${NODE_MAJOR} LTS (found: $(node -v 2>/dev/null || echo none))"
  install_node
fi

echo "==> Creating panel user and directories"
id -u "$PANEL_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash "$PANEL_USER"
mkdir -p "$PANEL_ROOT"/{db,supervisor.d} /srv/projects /srv/websites /srv/nginx-configs /srv/apps
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
chown -R "$PANEL_USER:$PANEL_USER" /srv/projects /srv/websites /srv/nginx-configs
# /srv/apps (Apps section) is chowned at the top level only — the per-app data
# directories underneath are created and owned by the installer helper, and a
# recursive chown would fight with a browser profile it is still writing.
chown "$PANEL_USER:$PANEL_USER" /srv/apps
# $PANEL_ROOT but NOT $PANEL_ROOT/apps — leftover containers from the retired
# Apps section may own data there; chowning e.g. Postgres's data dir breaks it.
find "$PANEL_ROOT" -path "$PANEL_ROOT/apps" -prune -o -exec chown "$PANEL_USER:$PANEL_USER" {} +
# Panel user must be able to write supervisor program logs
chown "$PANEL_USER:$PANEL_USER" /var/log/supervisor || true
# Selenium Manager caches its driver under the panel user's home
mkdir -p "/home/$PANEL_USER/.cache"
chown -R "$PANEL_USER:$PANEL_USER" "/home/$PANEL_USER"

echo "==> Panel helpers"
mkdir -p "$PANEL_ROOT/bin" "$PANEL_ROOT/backups"
install -m 0755 "$REPO_DIR/deploy/serverhub-self-update.sh" "$PANEL_ROOT/bin/serverhub-self-update"
install -m 0755 "$REPO_DIR/deploy/serverhub-cleanup.sh" "$PANEL_ROOT/bin/serverhub-cleanup"
install -m 0755 "$REPO_DIR/deploy/serverhub-apps.sh" "$PANEL_ROOT/bin/serverhub-apps"
install -m 0755 "$REPO_DIR/deploy/serverhub-free-port.sh" "$PANEL_ROOT/bin/serverhub-free-port"
install -m 0755 "$REPO_DIR/deploy/serverhub-postgres.sh" "$PANEL_ROOT/bin/serverhub-postgres"

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
SITE=/etc/nginx/sites-available/serverhub
# Only (re)write it when it's new or still the placeholder — on a configured
# server it holds the real domain and certbot's SSL lines, which must survive.
if [ ! -f "$SITE" ] || grep -q "panel.yourdomain.com" "$SITE"; then
  # no domain yet: answer on the server's IP (catch-all) until one is set
  sed "s|server_name panel.yourdomain.com;|server_name ${PANEL_DOMAIN:-_};|" \
    "$REPO_DIR/deploy/nginx-panel.conf" > "$SITE"
  echo "    panel site written for: ${PANEL_DOMAIN:-any address (no domain yet)}"
else
  echo "    keeping the existing panel site ($(grep -m1 -o 'server_name [^;]*' "$SITE"))"
fi
ln -sf "$SITE" /etc/nginx/sites-enabled/serverhub
# Remove the stock "Welcome to nginx" default site — otherwise it acts as the
# default_server and Certbot can attach certs to it instead of the panel,
# leaving the domain showing the nginx welcome page.
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# ---------------------------------------------------------------------------
# Finishing steps — each one warns instead of aborting, so the panel itself is
# always installed even if e.g. DNS isn't pointing here yet.
# ---------------------------------------------------------------------------
WARNINGS=()

echo "==> Admin user"
if [ -n "$ADMIN_USER" ] && [ -n "$ADMIN_PASS" ]; then
  ( cd "$PANEL_ROOT/backend" && sudo -u "$PANEL_USER" "$PANEL_ROOT/venv/bin/python" setup_admin.py \
      -u "$ADMIN_USER" -p "$ADMIN_PASS" ) || WARNINGS+=("admin user not created — run setup_admin.py (below)")
else
  echo "    skipped (no ADMIN_USER/ADMIN_PASS given)"
  WARNINGS+=("create your admin: cd $PANEL_ROOT/backend && sudo -u $PANEL_USER $PANEL_ROOT/venv/bin/python setup_admin.py")
fi

echo "==> HTTPS for the panel"
if [ -n "$PANEL_DOMAIN" ] && [ -n "$SSL_EMAIL" ]; then
  if grep -q "ssl_certificate" "$SITE"; then
    echo "    already has a certificate"
  else
    SERVER_IP="$(curl -4 -fsS --max-time 8 https://api.ipify.org 2>/dev/null || true)"
    DNS_IP="$(getent ahostsv4 "$PANEL_DOMAIN" 2>/dev/null | awk 'NR==1 {print $1}')"
    if [ -n "$SERVER_IP" ] && [ "$DNS_IP" != "$SERVER_IP" ]; then
      WARNINGS+=("SSL skipped: $PANEL_DOMAIN points to ${DNS_IP:-nothing}, this server is $SERVER_IP — fix DNS, then: sudo certbot --nginx -d $PANEL_DOMAIN")
    elif certbot --nginx -d "$PANEL_DOMAIN" --non-interactive --agree-tos -m "$SSL_EMAIL" --redirect; then
      echo "    https://$PANEL_DOMAIN is ready"
    else
      WARNINGS+=("certbot failed — retry: sudo certbot --nginx -d $PANEL_DOMAIN")
    fi
  fi
elif [ -n "$PANEL_DOMAIN" ]; then
  WARNINGS+=("no SSL_EMAIL given — for HTTPS run: sudo certbot --nginx -d $PANEL_DOMAIN")
else
  echo "    skipped (no domain) — the panel answers on http://<server-ip>/"
fi

echo "==> PostgreSQL"
if [ "$INSTALL_POSTGRES" != "no" ]; then
  if ls /etc/postgresql/*/main/conf.d/serverhub.conf >/dev/null 2>&1 \
     && "$PANEL_ROOT/bin/serverhub-postgres" status | grep -q "running=yes"; then
    echo "    already installed and running"
  else
    "$PANEL_ROOT/bin/serverhub-postgres" install \
      || WARNINGS+=("PostgreSQL setup failed — open Databases → PostgreSQL in the panel to see why")
  fi
else
  echo "    skipped (INSTALL_POSTGRES=no) — installable later from Databases → PostgreSQL"
fi

echo "==> Automatic security updates"
if [ "$AUTO_UPDATES" != "no" ]; then
  apt-get install -y unattended-upgrades >/dev/null \
    && printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
         > /etc/apt/apt.conf.d/20auto-upgrades \
    && echo "    on (security fixes install daily)" \
    || WARNINGS+=("could not enable unattended-upgrades")
fi

URL="http://$(curl -4 -fsS --max-time 8 https://api.ipify.org 2>/dev/null || echo '<server-ip>')/"
if [ -n "$PANEL_DOMAIN" ]; then
  URL="http://$PANEL_DOMAIN/"
  grep -q "ssl_certificate" "$SITE" 2>/dev/null && URL="https://$PANEL_DOMAIN/"
fi

echo
echo "============================================================"
echo " ServerHub installed."
echo
echo "   Panel:  $URL"
[ -n "$ADMIN_USER" ] && echo "   Login:  $ADMIN_USER"
echo
if [ "${#WARNINGS[@]}" -gt 0 ]; then
  echo " Still to do:"
  for w in "${WARNINGS[@]}"; do echo "   - $w"; done
  echo
fi
echo " Update later with:  sudo bash $REPO_DIR/deploy/update.sh"
echo "============================================================"
