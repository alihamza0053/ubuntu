#!/usr/bin/env bash
# ============================================================
# ServerHub — Ubuntu VPS installation script (Phase 1)
# Run as root (or with sudo) on Ubuntu 22.04+.
# Re-runnable: every step is idempotent.
# ============================================================
set -euo pipefail

PANEL_USER="serverhub"
PANEL_ROOT="/srv/serverhub"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Installing system packages"
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx supervisor curl

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

echo "==> Python virtualenv + dependencies"
python3 -m venv "$PANEL_ROOT/venv"
"$PANEL_ROOT/venv/bin/pip" install --upgrade pip
"$PANEL_ROOT/venv/bin/pip" install -r "$PANEL_ROOT/backend/requirements.txt"
# Streamlit is needed to run project dashboards
"$PANEL_ROOT/venv/bin/pip" install streamlit

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
  echo "    Generated backend/.env with a fresh SECRET_KEY"
fi

echo "==> Permissions"
chown -R "$PANEL_USER:$PANEL_USER" "$PANEL_ROOT" /srv/projects /srv/websites /srv/nginx-configs
# Panel user must be able to write supervisor program logs
chown "$PANEL_USER:$PANEL_USER" /var/log/supervisor || true

echo "==> Sudoers rule (supervisorctl only)"
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
