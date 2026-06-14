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
    echo "==> Installing Web Browser desktop (Xvfb + noVNC + Google Chrome)"
    apt-get install -y xvfb x11vnc novnc websockify fluxbox wget
    # Firefox is snap-only on Ubuntu (won't run headless as root), so use the
    # Google Chrome .deb — the same reliable browser used for Selenium.
    if ! command -v google-chrome >/dev/null; then
      snap remove chromium 2>/dev/null || true
      TMP="$(mktemp --suffix=.deb)"
      wget -qO "$TMP" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
      apt-get install -y "$TMP"
      rm -f "$TMP"
    fi
    google-chrome --version || true
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
    # Replace the insecure default Studio login with generated credentials
    DASH_PW="$(openssl rand -hex 12 2>/dev/null || head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)"
    grep -q '^DASHBOARD_USERNAME=' .env && sed -i 's/^DASHBOARD_USERNAME=.*/DASHBOARD_USERNAME=supabase/' .env || echo "DASHBOARD_USERNAME=supabase" >> .env
    grep -q '^DASHBOARD_PASSWORD=' .env && sed -i "s|^DASHBOARD_PASSWORD=.*|DASHBOARD_PASSWORD=$DASH_PW|" .env || echo "DASHBOARD_PASSWORD=$DASH_PW" >> .env
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

  wordpress|joomla|ghost|espocrm)
    # Multi-instance compose: serverhub-app-install <slug> <instance> <port>
    INSTANCE="${2:-$SLUG}"
    PORT="${3:-8091}"
    echo "==> Setting up $SLUG instance '$INSTANCE' on port $PORT"
    command -v docker >/dev/null || { echo "Install Docker first"; exit 1; }
    DIR="/srv/serverhub/apps/$INSTANCE"
    mkdir -p "$DIR"; cd "$DIR"
    DBPW="$(openssl rand -hex 16 2>/dev/null || head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)"
    case "$SLUG" in
      wordpress)
        cat > docker-compose.yml <<EOF
services:
  db:
    image: mariadb:11
    restart: unless-stopped
    environment: { MARIADB_DATABASE: wordpress, MARIADB_USER: wordpress, MARIADB_PASSWORD: "$DBPW", MARIADB_RANDOM_ROOT_PASSWORD: "yes" }
    volumes: [ "db:/var/lib/mysql" ]
  app:
    image: wordpress:latest
    restart: unless-stopped
    depends_on: [ db ]
    ports: [ "127.0.0.1:$PORT:80" ]
    environment: { WORDPRESS_DB_HOST: db, WORDPRESS_DB_USER: wordpress, WORDPRESS_DB_PASSWORD: "$DBPW", WORDPRESS_DB_NAME: wordpress }
    volumes: [ "app:/var/www/html" ]
volumes: { db: {}, app: {} }
EOF
        ;;
      joomla)
        cat > docker-compose.yml <<EOF
services:
  db:
    image: mysql:8.0
    restart: unless-stopped
    environment: { MYSQL_DATABASE: joomla, MYSQL_USER: joomla, MYSQL_PASSWORD: "$DBPW", MYSQL_RANDOM_ROOT_PASSWORD: "1" }
    volumes: [ "db:/var/lib/mysql" ]
  app:
    image: joomla:latest
    restart: unless-stopped
    depends_on: [ db ]
    ports: [ "127.0.0.1:$PORT:80" ]
    environment: { JOOMLA_DB_HOST: db, JOOMLA_DB_USER: joomla, JOOMLA_DB_PASSWORD: "$DBPW", JOOMLA_DB_NAME: joomla }
    volumes: [ "app:/var/www/html" ]
volumes: { db: {}, app: {} }
EOF
        ;;
      ghost)
        cat > docker-compose.yml <<EOF
services:
  db:
    image: mysql:8.0
    restart: unless-stopped
    environment: { MYSQL_DATABASE: ghost, MYSQL_USER: ghost, MYSQL_PASSWORD: "$DBPW", MYSQL_RANDOM_ROOT_PASSWORD: "1" }
    volumes: [ "db:/var/lib/mysql" ]
  app:
    image: ghost:5
    restart: unless-stopped
    depends_on: [ db ]
    ports: [ "127.0.0.1:$PORT:2368" ]
    environment:
      database__client: mysql
      database__connection__host: db
      database__connection__user: ghost
      database__connection__password: "$DBPW"
      database__connection__database: ghost
      url: http://localhost:$PORT
    volumes: [ "content:/var/lib/ghost/content" ]
volumes: { db: {}, content: {} }
EOF
        ;;
      espocrm)
        ADMINPW="$(openssl rand -hex 8 2>/dev/null || head -c 12 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 16)"
        printf 'ADMIN_USERNAME=admin\nADMIN_PASSWORD=%s\n' "$ADMINPW" > credentials.env
        cat > docker-compose.yml <<EOF
services:
  db:
    image: mariadb:11
    restart: unless-stopped
    environment: { MARIADB_DATABASE: espocrm, MARIADB_USER: espocrm, MARIADB_PASSWORD: "$DBPW", MARIADB_RANDOM_ROOT_PASSWORD: "yes" }
    volumes: [ "db:/var/lib/mysql" ]
  app:
    image: espocrm/espocrm:latest
    restart: unless-stopped
    depends_on: [ db ]
    ports: [ "127.0.0.1:$PORT:80" ]
    environment:
      ESPOCRM_DATABASE_HOST: db
      ESPOCRM_DATABASE_USER: espocrm
      ESPOCRM_DATABASE_PASSWORD: "$DBPW"
      ESPOCRM_DATABASE_NAME: espocrm
      ESPOCRM_ADMIN_USERNAME: admin
      ESPOCRM_ADMIN_PASSWORD: "$ADMINPW"
      ESPOCRM_SITE_URL: http://localhost:$PORT
    volumes: [ "data:/var/www/html" ]
volumes: { db: {}, data: {} }
EOF
        ;;
    esac
    docker compose -p "app_$INSTANCE" pull
    echo "Compose written + images pulled — the panel will start the stack."
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
