"""
Self-hosted app catalog + lifecycle.

Apps are one-click-installable tools. Two kinds:
  - "service": runs on a localhost port under Supervisor (e.g. code-server,
    File Browser). Can be given a domain + SSL like a project dashboard.
  - "tool": just an install (e.g. Google Chrome) — no port/process.

The actual package install is performed by a vetted root helper script
(deploy/serverhub-app-install.sh) invoked through a single restricted sudo
rule, so the panel never runs arbitrary commands as root.
"""
import json
import re
import secrets
import subprocess
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import App
from . import supervisor_service

APP_PORT_START = 9001
INSTALLER = "/srv/serverhub/bin/serverhub-app-install"

# Catalog of installable apps. `run` is the supervisor command for service
# apps; {port} and {bin} are substituted. The install steps themselves live in
# the root helper script keyed by the same slug.
CATALOG: dict[str, dict] = {
    # Special: "run any Docker Hub image". The image/port/env are per-instance
    # (stored on the App row), so this isn't shown as a catalog card — the Apps
    # page drives it with a form. Multi-instance.
    "custom": {
        "name": "Custom image",
        "description": "Run any Docker Hub image.",
        "icon": "📦",
        "kind": "docker", "multi": True, "websocket": True,
    },
    "code-server": {
        "name": "VS Code (code-server)",
        "description": "Full VS Code in your browser — edit code on the server.",
        "icon": "🧩",
        "kind": "service",
        "bin": "/usr/bin/code-server",
        "run": "{bin} --bind-addr 127.0.0.1:{port} --auth password --disable-telemetry",
        "use_password": True,
        "websocket": True,
    },
    "filebrowser": {
        "name": "File Browser",
        "description": "Web-based file manager for the whole server.",
        "icon": "📂",
        "kind": "service",
        "bin": "/usr/local/bin/filebrowser",
        "run": "{bin} --address 127.0.0.1 --port {port} --root /srv --database /srv/serverhub/db/filebrowser.db",
        "use_password": False,
        "websocket": False,
        # Built-in login; password changeable via its CLI (against its own DB).
        "username": "admin",
        "set_password_cmd": ["{bin}", "users", "update", "admin",
                             "--password", "{password}",
                             "--database", "/srv/serverhub/db/filebrowser.db"],
    },
    "uptime-kuma": {
        "name": "Uptime Kuma",
        "description": "Self-hosted uptime monitoring dashboard.",
        "icon": "📈",
        "kind": "service",
        "bin": "/usr/bin/npx",
        "run": "/usr/bin/npx --yes uptime-kuma-server --port {port} --host 127.0.0.1",
        "use_password": False,
        "websocket": True,
    },
    "onedrive": {
        "name": "OneDrive (file sync)",
        "description": "Sync a Microsoft OneDrive account into /srv/onedrive so "
                       "projects can read files others update. Read-only by default — "
                       "authorize it, then map a folder in each project's OneDrive tab.",
        "icon": "☁️",
        "kind": "tool",
    },
    "syncthing": {
        "name": "Syncthing",
        "description": "Continuous file synchronization with a web UI.",
        "icon": "🔄",
        "kind": "service",
        "bin": "/usr/bin/syncthing",
        "run": "{bin} serve --no-browser --gui-address=127.0.0.1:{port} --home=/srv/serverhub/apps/syncthing",
        "use_password": False,
        "websocket": True,
    },
    "glances": {
        "name": "Glances",
        "description": "Live CPU / RAM / disk / network monitor in the browser.",
        "icon": "📊",
        "kind": "service",
        "bin": "/srv/serverhub/apps/glances/venv/bin/glances",
        "run": "{bin} -w --bind 127.0.0.1 --port {port}",
        "use_password": False,
        "websocket": True,
    },
    "jupyterlab": {
        "name": "JupyterLab",
        "description": "Notebooks & data science IDE in the browser.",
        "icon": "📓",
        "kind": "service",
        "bin": "/srv/serverhub/apps/jupyterlab/venv/bin/jupyter",
        "run": ("{bin} lab --ip 127.0.0.1 --port {port} --no-browser "
                "--ServerApp.token={secret} --ServerApp.root_dir=/srv"),
        "use_token": True,
        "websocket": True,
    },
    "git-github": {
        "name": "Git + GitHub CLI",
        "description": "Install git and the GitHub CLI (gh) so you can push code from "
                       "VS Code / Android Studio / the terminal. After installing, run "
                       "'gh auth login' once in the desktop terminal to connect GitHub.",
        "icon": "🐙",
        "kind": "tool",
    },
    "flutter": {
        "name": "Flutter SDK",
        "description": "Flutter SDK for building apps, installed to /opt/flutter. The "
                       "install log prints the path — in Android Studio's Flutter plugin "
                       "set the Flutter SDK path to /opt/flutter. Pairs with Android Studio.",
        "icon": "💙",
        "kind": "tool",
    },
    "android-studio": {
        "name": "Android Studio (IDE)",
        "description": "The full Android Studio IDE, installed (via snap) into the Linux "
                       "Desktop (XFCE) app — launch it from the desktop's menu. Heavy: "
                       "~8 GB+ RAM and ~15 GB disk; the emulator needs KVM. Install the "
                       "Linux Desktop app first.",
        "icon": "🤖",
        "kind": "tool",
    },
    "xfce-desktop": {
        "name": "Linux Desktop (XFCE, modern)",
        "description": "A polished XFCE Linux desktop in your browser — dark Arc theme, "
                       "Papirus icons and a macOS-style dock, with a file manager, terminal, "
                       "Chrome & Firefox. Streamed over the reliable noVNC stack (works on "
                       "HTTP and HTTPS). No Docker, no extra firewall ports.",
        "icon": "🖥️",
        "kind": "service",
        "bin": "/srv/serverhub/bin/serverhub-xfce-desktop",
        "run": "{bin} {port}",
        "use_password": True,
        "websocket": True,
    },
    "webtop": {
        "name": "Web Browser (Chrome, legacy/slow)",
        "description": "A full Chrome desktop via noVNC. Heavier & slower — prefer "
                       "the Chromium/Firefox (KasmVNC) browsers above.",
        "icon": "🌐",
        "kind": "service",
        "bin": "/srv/serverhub/bin/serverhub-webtop",
        "run": "{bin} {port}",
        "use_password": False,
        "websocket": True,
    },
    "google-chrome": {
        "name": "Google Chrome",
        "description": "Headless Chrome for Selenium scripts (no web UI).",
        "icon": "🌐",
        "kind": "tool",
    },
    "libreoffice": {
        "name": "LibreOffice (headless)",
        "description": "Headless LibreOffice Calc — lets dashboards recalculate & refresh "
                       "Excel master files on the server (e.g. the Working Capital "
                       "dashboard's Main Data Sheet) and convert xlsx/xls/csv. Installs the "
                       "'soffice' engine; no web UI.",
        "icon": "📗",
        "kind": "tool",
    },
    "chromium": {
        "name": "Chromium Browser",
        "description": "A full Chromium browser streamed to your tab over KasmVNC — "
                       "fast & smooth, much better than the noVNC desktop. Needs Docker.",
        "icon": "🧭",
        "kind": "docker", "websocket": True,
        "image": "lscr.io/linuxserver/chromium:latest", "container_port": 3000,
        "username": "abc", "secret_env": "PASSWORD",
        "env": {"PUID": "1000", "PGID": "1000", "TZ": "Etc/UTC", "CUSTOM_USER": "abc"},
        "run_args": ["--shm-size=1g", "--security-opt", "seccomp=unconfined",
                     "-v", "app_chromium_config:/config"],
        "pw_change": "env_recreate",   # PASSWORD (web login) is read from env each start
    },
    "firefox": {
        "name": "Firefox Browser",
        "description": "A full Firefox browser streamed to your tab over KasmVNC — "
                       "fast & smooth. Needs Docker.",
        "icon": "🦊",
        "kind": "docker", "websocket": True,
        "image": "lscr.io/linuxserver/firefox:latest", "container_port": 3000,
        "username": "abc", "secret_env": "PASSWORD",
        "env": {"PUID": "1000", "PGID": "1000", "TZ": "Etc/UTC", "CUSTOM_USER": "abc"},
        "run_args": ["--shm-size=1g", "--security-opt", "seccomp=unconfined",
                     "-v", "app_firefox_config:/config"],
        "pw_change": "env_recreate",
    },
    "neko-brave": {
        "name": "Brave Browser (Neko, smoothest)",
        "description": "Brave streamed over WebRTC (Neko) — the smoothest remote "
                       "browser, like watching a video. Needs Docker AND UDP ports "
                       "52000-52019 open in your firewall (UFW + cloud provider).",
        "icon": "🦁",
        "kind": "docker", "websocket": True,
        "image": "m1k1o/neko:brave", "container_port": 8080,
        "username": "neko", "secret_env": "NEKO_PASSWORD",
        # The panel injects NEKO_NAT1TO1=<server public IP> at create time, and
        # ICE-lite makes the server the controlling agent — the reliable cloud
        # config. A small EPR range publishes fast (100 ports often fails).
        "nat1to1": True,
        "env": {"NEKO_SCREEN": "1280x720@30",
                "NEKO_PASSWORD_ADMIN": "{secret}",
                "NEKO_EPR": "52000-52019",
                "NEKO_ICELITE": "1"},
        "run_args": ["--shm-size=2g",
                     "-p", "52000-52019:52000-52019/udp",
                     "-v", "app_neko_brave_data:/home/neko"],
        "pw_change": "env_recreate",   # NEKO_PASSWORD is read from env each start
    },

    # ---- Docker engine (prerequisite for the docker apps below) ----
    "docker": {
        "name": "Docker Engine",
        "description": "Container runtime — required to install the apps below.",
        "icon": "🐳",
        "kind": "tool",
    },

    # ---- Docker-based apps (single container) ----
    "portainer": {
        "name": "Portainer", "description": "Web UI to manage Docker containers.",
        "icon": "🛳️", "kind": "docker", "websocket": True,
        "image": "portainer/portainer-ce:latest", "container_port": 9000,
        "run_args": ["-v", "/var/run/docker.sock:/var/run/docker.sock",
                     "-v", "app_portainer_data:/data"],
    },
    "n8n": {
        "name": "n8n", "description": "Workflow automation (Zapier-style).",
        "icon": "🔗", "kind": "docker", "websocket": True,
        "image": "n8nio/n8n:latest", "container_port": 5678,
        "username": "admin", "secret_env": "N8N_BASIC_AUTH_PASSWORD",
        "env": {"N8N_BASIC_AUTH_ACTIVE": "true", "N8N_BASIC_AUTH_USER": "admin"},
        "run_args": ["-v", "app_n8n_data:/home/node/.n8n"],
        "pw_change": "env_recreate",   # basic-auth password is read from env each start
    },
    "nextcloud": {
        "name": "Nextcloud", "description": "Self-hosted files, calendar & office suite.",
        "icon": "☁️", "kind": "docker", "websocket": False,
        "image": "nextcloud:latest", "container_port": 80,
        "username": "admin", "secret_env": "NEXTCLOUD_ADMIN_PASSWORD",
        "env": {"NEXTCLOUD_ADMIN_USER": "admin"},
        "run_args": ["-v", "app_nextcloud_data:/var/www/html"],
    },
    "vaultwarden": {
        "name": "Vaultwarden", "description": "Bitwarden-compatible password manager.",
        "icon": "🔐", "kind": "docker", "websocket": True,
        "image": "vaultwarden/server:latest", "container_port": 80,
        "secret_env": "ADMIN_TOKEN", "secret_label": "Admin token",
        "run_args": ["-v", "app_vaultwarden_data:/data"],
        "pw_change": "env_recreate",   # ADMIN_TOKEN is read from env each start
    },
    "gitea": {
        "name": "Gitea", "description": "Lightweight self-hosted Git service.",
        "icon": "🍵", "kind": "docker", "websocket": False,
        "image": "gitea/gitea:latest", "container_port": 3000,
        "run_args": ["-v", "app_gitea_data:/data"],
    },
    "grafana": {
        "name": "Grafana", "description": "Dashboards & observability.",
        "icon": "📉", "kind": "docker", "websocket": True,
        "image": "grafana/grafana:latest", "container_port": 3000,
        "username": "admin", "secret_env": "GF_SECURITY_ADMIN_PASSWORD",
        "run_args": ["-v", "app_grafana_data:/var/lib/grafana"],
        "pw_change": "exec",
        "pw_exec_cmd": ["grafana", "cli", "admin", "reset-admin-password", "{password}"],
    },
    "metabase": {
        "name": "Metabase", "description": "Business-intelligence / analytics UI.",
        "icon": "📈", "kind": "docker", "websocket": False,
        "image": "metabase/metabase:latest", "container_port": 3000,
        "run_args": ["-v", "app_metabase_data:/metabase-data"],
        "env": {"MB_DB_FILE": "/metabase-data/metabase.db"},
    },

    # ---- Databases / backends (no web UI — ports for other apps to use) ----
    "postgres": {
        "name": "PostgreSQL", "description": "Relational database (backend service).",
        "icon": "🐘", "kind": "docker", "web_ui": False, "container_port": 5432,
        "image": "postgres:16", "username": "postgres", "secret_env": "POSTGRES_PASSWORD",
        "run_args": ["-v", "app_postgres_data:/var/lib/postgresql/data"],
        "pw_change": "exec",
        "pw_exec_cmd": ["psql", "-U", "postgres", "-c", "ALTER USER postgres PASSWORD '{password}'"],
    },
    "mariadb": {
        "name": "MariaDB", "description": "MySQL-compatible database (backend service).",
        "icon": "🐬", "kind": "docker", "web_ui": False, "container_port": 3306,
        "image": "mariadb:11", "username": "root", "secret_env": "MARIADB_ROOT_PASSWORD",
        "run_args": ["-v", "app_mariadb_data:/var/lib/mysql"],
        "pw_change": "exec",
        "pw_exec_cmd": ["mariadb-admin", "-uroot", "-p{old}", "password", "{password}"],
    },
    "redis": {
        "name": "Redis", "description": "In-memory key/value store (backend service).",
        "icon": "🧱", "kind": "docker", "web_ui": False, "container_port": 6379,
        "image": "redis:7", "run_args": ["-v", "app_redis_data:/data"],
    },
    "mongo": {
        "name": "MongoDB", "description": "Document database (backend service).",
        "icon": "🍃", "kind": "docker", "web_ui": False, "container_port": 27017,
        "image": "mongo:7", "username": "admin", "secret_env": "MONGO_INITDB_ROOT_PASSWORD",
        "env": {"MONGO_INITDB_ROOT_USERNAME": "admin"},
        "run_args": ["-v", "app_mongo_data:/data/db"],
    },

    # ---- Database UIs ----
    "adminer": {
        "name": "Adminer", "description": "Lightweight database management UI.",
        "icon": "🗄️", "kind": "docker", "container_port": 8080,
        "image": "adminer:latest",
    },
    "pgadmin": {
        "name": "pgAdmin", "description": "PostgreSQL administration UI.",
        "icon": "🐘", "kind": "docker", "container_port": 80,
        "image": "dpage/pgadmin4:latest", "username": "admin@example.com",
        "secret_env": "PGADMIN_DEFAULT_PASSWORD",
        "env": {"PGADMIN_DEFAULT_EMAIL": "admin@example.com"},
        "run_args": ["-v", "app_pgadmin_data:/var/lib/pgadmin"],
    },
    "phpmyadmin": {
        "name": "phpMyAdmin", "description": "MySQL / MariaDB administration UI.",
        "icon": "🗃️", "kind": "docker", "container_port": 80,
        "image": "phpmyadmin:latest",
        # PMA_ARBITRARY lets you type any DB host on the login screen
        "env": {"PMA_ARBITRARY": "1"},
    },

    # ---- Developer / automation ----
    "nodered": {
        "name": "Node-RED", "description": "Low-code flow-based automation.",
        "icon": "🔴", "kind": "docker", "websocket": True, "container_port": 1880,
        "image": "nodered/node-red:latest", "run_args": ["-v", "app_nodered_data:/data"],
    },
    "it-tools": {
        "name": "IT-Tools", "description": "A box of handy developer utilities.",
        "icon": "🧰", "kind": "docker", "container_port": 80,
        "image": "corentinth/it-tools:latest",
    },

    # ---- Media & library ----
    "navidrome": {
        "name": "Navidrome", "description": "Music streaming server (Subsonic-compatible).",
        "icon": "🎵", "kind": "docker", "container_port": 4533,
        "image": "deluan/navidrome:latest", "env": {"ND_MUSICFOLDER": "/music"},
        "run_args": ["-v", "app_navidrome_data:/data", "-v", "/srv:/music:ro"],
    },
    "calibre-web": {
        "name": "Calibre-Web", "description": "Browse & read your e-book library.",
        "icon": "📚", "kind": "docker", "container_port": 8083,
        "image": "lscr.io/linuxserver/calibre-web:latest",
        "run_args": ["-v", "app_calibreweb_config:/config", "-v", "/srv:/books"],
    },
    "kavita": {
        "name": "Kavita", "description": "Reading server for comics, manga & books.",
        "icon": "📖", "kind": "docker", "container_port": 5000,
        "image": "jvmilazz0/kavita:latest",
        "run_args": ["-v", "app_kavita_config:/kavita/config", "-v", "/srv:/data"],
    },
    "audiobookshelf": {
        "name": "Audiobookshelf", "description": "Audiobook & podcast media player (web).",
        "icon": "🎧", "kind": "docker", "container_port": 80,
        "image": "ghcr.io/advplyr/audiobookshelf:latest",
        "run_args": ["-v", "app_abs_config:/config", "-v", "app_abs_metadata:/metadata",
                     "-v", "/srv:/audiobooks"],
    },

    # ---- Home & productivity ----
    "memos": {
        "name": "Memos", "description": "Lightweight, privacy-first note taking.",
        "icon": "📌", "kind": "docker", "container_port": 5230,
        "image": "neosmemo/memos:stable", "run_args": ["-v", "app_memos_data:/var/opt/memos"],
    },
    "mealie": {
        "name": "Mealie", "description": "Recipe manager & meal planner.",
        "icon": "🍴", "kind": "docker", "container_port": 9000,
        "image": "ghcr.io/mealie-recipes/mealie:latest", "run_args": ["-v", "app_mealie_data:/app/data"],
    },
    "actual": {
        "name": "Actual Budget", "description": "Private, local-first budgeting.",
        "icon": "💰", "kind": "docker", "container_port": 5006,
        "image": "actualbudget/actual-server:latest", "run_args": ["-v", "app_actual_data:/data"],
    },
    "grocy": {
        "name": "Grocy", "description": "Groceries & household management (ERP for your home).",
        "icon": "🛒", "kind": "docker", "container_port": 80,
        "image": "lscr.io/linuxserver/grocy:latest", "run_args": ["-v", "app_grocy_config:/config"],
    },

    # ---- Utilities ----
    "cyberchef": {
        "name": "CyberChef", "description": "The cyber Swiss-army knife for data.",
        "icon": "🔬", "kind": "docker", "container_port": 8000,
        "image": "mpepping/cyberchef:latest",
    },
    "searxng": {
        "name": "SearXNG", "description": "Private meta search engine.",
        "icon": "🔎", "kind": "docker", "container_port": 8080,
        "image": "searxng/searxng:latest", "run_args": ["-v", "app_searxng_config:/etc/searxng"],
    },
    "changedetection": {
        "name": "Changedetection.io", "description": "Watch web pages for changes.",
        "icon": "🔭", "kind": "docker", "container_port": 5000,
        "image": "ghcr.io/dgtlmoon/changedetection.io:latest",
        "run_args": ["-v", "app_changedetection_data:/datastore"],
    },

    # ---- Productivity ----
    "trilium": {
        "name": "Trilium Notes", "description": "Hierarchical note-taking app.",
        "icon": "📝", "kind": "docker", "container_port": 8080,
        "image": "zadam/trilium:latest", "run_args": ["-v", "app_trilium_data:/home/node/trilium-data"],
    },
    "vikunja": {
        "name": "Vikunja", "description": "To-do list & project management.",
        "icon": "✅", "kind": "docker", "container_port": 3456,
        "image": "vikunja/vikunja:latest", "run_args": ["-v", "app_vikunja_files:/app/vikunja/files"],
    },
    "freshrss": {
        "name": "FreshRSS", "description": "Self-hosted RSS feed reader.",
        "icon": "📡", "kind": "docker", "container_port": 80,
        "image": "freshrss/freshrss:latest", "run_args": ["-v", "app_freshrss_data:/var/www/FreshRSS/data"],
    },
    "excalidraw": {
        "name": "Excalidraw", "description": "Virtual whiteboard for sketching diagrams.",
        "icon": "✏️", "kind": "docker", "container_port": 80,
        "image": "excalidraw/excalidraw:latest",
    },
    "drawio": {
        "name": "draw.io", "description": "Diagrams & flowcharts editor.",
        "icon": "📐", "kind": "docker", "container_port": 8080,
        "image": "jgraph/drawio:latest",
    },
    "stirling-pdf": {
        "name": "Stirling-PDF", "description": "All-in-one PDF tools (merge, split, OCR…).",
        "icon": "📄", "kind": "docker", "container_port": 8080,
        "image": "frooodle/s-pdf:latest", "run_args": ["-v", "app_stirling_data:/usr/share/tessdata"],
    },

    # ---- Monitoring / dashboards ----
    "dozzle": {
        "name": "Dozzle", "description": "Live Docker container logs in the browser.",
        "icon": "📃", "kind": "docker", "websocket": True, "container_port": 8080,
        "image": "amir20/dozzle:latest",
        "run_args": ["-v", "/var/run/docker.sock:/var/run/docker.sock"],
    },
    "homer": {
        "name": "Homer", "description": "A simple static homepage / app dashboard.",
        "icon": "🏠", "kind": "docker", "container_port": 8080,
        "image": "b4bz/homer:latest", "run_args": ["-v", "app_homer_assets:/www/assets"],
    },

    # ---- Notifications ----
    "gotify": {
        "name": "Gotify", "description": "Send & receive push notifications.",
        "icon": "🔔", "kind": "docker", "container_port": 80,
        "image": "gotify/server:latest", "username": "admin", "secret_env": "GOTIFY_DEFAULTUSER_PASS",
        "env": {"GOTIFY_DEFAULTUSER_NAME": "admin"},
        "run_args": ["-v", "app_gotify_data:/app/data"],
    },
    "ntfy": {
        "name": "ntfy", "description": "Pub/sub push notifications to your phone.",
        "icon": "📨", "kind": "docker", "container_port": 80,
        "image": "binwiederhier/ntfy:latest", "command": ["serve"],
        "run_args": ["-v", "app_ntfy_cache:/var/cache/ntfy"],
    },

    # ---- Media ----
    "jellyfin": {
        "name": "Jellyfin", "description": "Free media server (movies, music, TV).",
        "icon": "🎬", "kind": "docker", "websocket": True, "container_port": 8096,
        "image": "jellyfin/jellyfin:latest",
        "run_args": ["-v", "app_jellyfin_config:/config", "-v", "/srv:/media:ro"],
    },
    "emby": {
        "name": "Emby (media player)",
        "description": "Play your videos, music & photos in the browser — a polished "
                       "media player/server (Jellyfin's parent). Reads your files from /srv; "
                       "add a library at /media/... after setup.",
        "icon": "🎞️", "kind": "docker", "websocket": True, "container_port": 8096,
        "image": "lscr.io/linuxserver/emby:latest",
        "env": {"PUID": "1000", "PGID": "1000", "TZ": "Etc/UTC"},
        "run_args": ["-v", "app_emby_config:/config", "-v", "/srv:/media:ro"],
    },
    "qbittorrent": {
        "name": "qBittorrent", "description": "Torrent client with a web UI.",
        "icon": "🌀", "kind": "docker", "container_port": 8080,
        "image": "linuxserver/qbittorrent:latest",
        "env": {"WEBUI_PORT": "8080"},
        "run_args": ["-v", "app_qbittorrent_config:/config", "-v", "/srv/downloads:/downloads"],
    },

    # ---- CMS & CRM (compose stacks with a bundled database; multi-instance) ----
    "wordpress": {
        "name": "WordPress", "description": "The world's most popular CMS / blog. Bundled MariaDB.",
        "icon": "📰", "kind": "compose", "multi": True, "websocket": False,
        "container_port": 80,
    },
    "joomla": {
        "name": "Joomla", "description": "Flexible CMS for websites & portals. Bundled MySQL.",
        "icon": "🌐", "kind": "compose", "multi": True, "websocket": False,
        "container_port": 80,
    },
    "ghost": {
        "name": "Ghost", "description": "Modern publishing / newsletter platform. Bundled MySQL.",
        "icon": "👻", "kind": "compose", "multi": True, "websocket": False,
        "container_port": 2368,
    },
    "espocrm": {
        "name": "EspoCRM", "description": "Open-source CRM (contacts, leads, sales). Bundled MariaDB.",
        "icon": "🤝", "kind": "compose", "multi": True, "websocket": False,
        "container_port": 80, "username": "admin",
        "env_file_name": "credentials.env", "secret_env_key": "ADMIN_PASSWORD",
        "credentials": [
            ["Admin username", "ADMIN_USERNAME"],
            ["Admin password", "ADMIN_PASSWORD"],
        ],
    },

    # ---- Docker Compose stack (multi-container) ----
    "supabase": {
        "name": "Supabase", "description": "Open-source Firebase alternative (Postgres, "
                       "Auth, Storage, Studio). Large stack — experimental, 2 GB+ RAM.",
        "icon": "⚡", "kind": "compose", "websocket": True,
        "compose_dir": "/srv/serverhub/apps/supabase/docker",
        "container_port": 8000,   # Kong gateway (Studio + API)
        # Studio dashboard login (from the stack's .env, set by the installer)
        "username": "supabase",
        "env_file": "/srv/serverhub/apps/supabase/docker/.env",   # absolute (single instance)
        "secret_env_key": "DASHBOARD_PASSWORD",
        # Full credential set surfaced in the "Credentials" panel (label, env key)
        "credentials": [
            ["Studio username", "DASHBOARD_USERNAME"],
            ["Studio password", "DASHBOARD_PASSWORD"],
            ["Postgres user", None],            # always "postgres"
            ["Postgres password", "POSTGRES_PASSWORD"],
            ["Postgres database", "POSTGRES_DB"],
            ["Postgres port", "POSTGRES_PORT"],
            ["JWT secret", "JWT_SECRET"],
            ["anon key (public)", "ANON_KEY"],
            ["service_role key (admin)", "SERVICE_ROLE_KEY"],
        ],
    },
}


# Catalog grouping for the UI (ordered). Anything not listed → "Other".
CATEGORIES = [
    ("Infrastructure", ["docker", "postgres", "mariadb", "redis", "mongo"]),
    ("Database UIs", ["adminer", "phpmyadmin", "pgadmin"]),
    ("Developer", ["code-server", "android-studio", "flutter", "git-github", "gitea", "n8n", "nodered", "jupyterlab"]),
    ("CMS & CRM", ["wordpress", "joomla", "ghost", "espocrm"]),
    ("Files & Sync", ["onedrive", "filebrowser", "nextcloud", "syncthing"]),
    ("Media & Library", ["jellyfin", "emby", "navidrome", "audiobookshelf", "calibre-web",
                         "kavita", "qbittorrent"]),
    ("Productivity", ["libreoffice", "vaultwarden", "trilium", "memos", "vikunja", "mealie",
                      "actual", "grocy", "freshrss"]),
    ("Utilities", ["it-tools", "cyberchef", "searxng", "changedetection",
                   "excalidraw", "drawio", "stirling-pdf"]),
    ("Monitoring", ["portainer", "grafana", "glances", "uptime-kuma",
                    "metabase", "dozzle", "homer"]),
    ("Notifications", ["gotify", "ntfy"]),
    ("Browsers & Misc", ["xfce-desktop", "chromium", "firefox", "neko-brave", "webtop", "google-chrome", "supabase"]),
]

_CATEGORY_OF = {slug: cat for cat, slugs in CATEGORIES for slug in slugs}


def category_of(slug: str) -> str:
    return _CATEGORY_OF.get(slug, "Other")


def get_catalog_entry(slug: str) -> dict:
    entry = CATALOG.get(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown app: {slug}")
    return entry


# NOTE: container / supervisor / nginx / compose names key off the per-instance
# `instance` id (not the catalog slug), so an app can have multiple instances.

def program_name(instance: str) -> str:
    return f"app_{instance}"


def config_path(instance: str) -> Path:
    return settings.SUPERVISOR_CONF_DIR / f"{program_name(instance)}.conf"


def log_path(instance: str, stream: str = "out") -> Path:
    return settings.SUPERVISOR_LOG_DIR / f"{program_name(instance)}.{stream}.log"


def compose_dir(app) -> str:
    """Per-instance compose directory (multi) or the catalog's fixed dir."""
    entry = get_catalog_entry(app.slug)
    if entry.get("multi"):
        return f"/srv/serverhub/apps/{app.instance}"
    return entry["compose_dir"]


def app_env_file(app) -> str | None:
    """Resolve an app's env/credentials file (absolute, or per-instance name)."""
    entry = get_catalog_entry(app.slug)
    if entry.get("env_file"):
        return entry["env_file"]
    if entry.get("env_file_name"):
        return f"{compose_dir(app)}/{entry['env_file_name']}"
    return None


def allocate_port(db: Session) -> int:
    max_port = db.query(func.max(App.port)).scalar()
    return (max_port + 1) if max_port else APP_PORT_START


def installer_cmd(slug: str, instance: str | None = None, port: int | None = None) -> list[str]:
    """The restricted sudo command that installs a catalog app (always root).
    Multi-instance compose apps also receive their instance id and port."""
    cmd = ["sudo", "-n", INSTALLER, slug]
    if instance is not None:
        cmd.append(instance)
    if port is not None:
        cmd.append(str(port))
    return cmd


def installer_ready() -> bool:
    """True if the installer helper exists and the panel can run it via sudo."""
    if not Path(INSTALLER).exists():
        return False
    try:
        result = subprocess.run(["sudo", "-n", INSTALLER, "--check"],
                                capture_output=True, text=True, timeout=15)
        # Our script exits 2 on unknown arg ("--check"), but reaching it means
        # sudo was allowed. A sudo-password failure exits 1 with that message.
        return "a password is required" not in (result.stderr + result.stdout)
    except Exception:
        return False


SUPERVISOR_TEMPLATE = """[program:{program}]
command={command}
directory=/srv/serverhub
autostart=false
autorestart=true
stopasgroup=true
killasgroup=true
{env_line}stderr_logfile={log_dir}/{program}.err.log
stdout_logfile={log_dir}/{program}.out.log
"""


def write_program(app: App) -> None:
    """Write/refresh the supervisor program for a service app."""
    entry = get_catalog_entry(app.slug)
    if entry["kind"] != "service":
        return
    settings.SUPERVISOR_CONF_DIR.mkdir(parents=True, exist_ok=True)
    command = entry["run"].format(
        bin=entry.get("bin", ""), port=app.port, secret=app.secret or "",
        instance=app.instance)

    # Build the environment= line from catalog env + an optional PASSWORD
    env_pairs = {
        k: str(v).format(port=app.port, secret=app.secret or "", instance=app.instance)
        for k, v in entry.get("env", {}).items()
    }
    if entry.get("use_password") and app.secret:
        env_pairs["PASSWORD"] = app.secret
    env_line = ""
    if env_pairs:
        joined = ",".join(f'{k}="{v}"' for k, v in env_pairs.items())
        env_line = f"environment={joined}\n"

    content = SUPERVISOR_TEMPLATE.format(
        program=program_name(app.instance),
        command=command,
        env_line=env_line,
        log_dir=settings.SUPERVISOR_LOG_DIR,
    )
    config_path(app.instance).write_text(content, encoding="utf-8")
    supervisor_service.run_supervisorctl("reread")
    supervisor_service.run_supervisorctl("update")


def remove_program(instance: str) -> None:
    supervisor_service.run_supervisorctl("stop", program_name(instance))
    path = config_path(instance)
    if path.exists():
        path.unlink()
    supervisor_service.run_supervisorctl("reread")
    supervisor_service.run_supervisorctl("update")


def set_autostart(instance: str, enabled: bool) -> None:
    """
    Persist the desired run-state into the app's conf so a running app (e.g. the
    XFCE desktop) comes back after a reboot / supervisord restart, like the
    Docker apps do. autostart is only read at supervisord boot, so we just
    rewrite the file — no reread/update needed.
    """
    path = config_path(instance)
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    new = re.sub(r"(?m)^autostart=.*$", f"autostart={'true' if enabled else 'false'}", text)
    if new != text:
        path.write_text(new, encoding="utf-8")


def control(instance: str, action: str) -> str:
    if action in ("start", "restart"):
        set_autostart(instance, True)
    result = supervisor_service.run_supervisorctl(action, program_name(instance))
    out = (result.stdout + result.stderr).strip()
    if "ERROR" in out and "already started" not in out:
        raise HTTPException(status_code=500, detail=f"supervisorctl {action}: {out}")
    if action == "stop":
        set_autostart(instance, False)
    return out


def status(instance: str) -> str:
    result = supervisor_service.run_supervisorctl("status", program_name(instance))
    raw = (result.stdout + result.stderr).upper()
    if "RUNNING" in raw or "STARTING" in raw:
        return "RUNNING"
    if "FATAL" in raw or "BACKOFF" in raw:
        return "ERROR"
    return "STOPPED"


def new_password() -> str:
    return secrets.token_urlsafe(12)


def strong_password(length: int = 20) -> str:
    """Generate a strong alphanumeric password (no symbols — safe in env/URLs)."""
    import string
    alphabet = string.ascii_letters + string.digits
    # ensure at least one lower/upper/digit
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw)):
            return pw


def read_env_value(path: str, key: str) -> str | None:
    """Read KEY=value from an env file (used to surface compose-app creds)."""
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        return None
    return None


# ============================================================
# Docker / Compose lifecycle (kind == "docker" / "compose")
# ============================================================

DOCKER = ["sudo", "-n", "docker"]


def docker_ready() -> bool:
    """True if Docker is installed and the panel can run it."""
    try:
        r = subprocess.run(DOCKER + ["version", "--format", "{{.Server.Version}}"],
                           capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def container_name(instance: str) -> str:
    return f"app_{instance}"


def _docker(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run([*DOCKER, *args], capture_output=True, text=True, timeout=timeout)


def public_ip() -> str | None:
    """Best-effort detection of the server's public IPv4 (for WebRTC NAT)."""
    import urllib.request
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"):
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                ip = r.read().decode().strip()
            parts = ip.split(".")
            if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                return ip
        except Exception:
            continue
    return None


def docker_run(app) -> None:
    """(Re)create and start a single-container app."""
    entry = get_catalog_entry(app.slug)
    cname = container_name(app.instance)
    _docker("rm", "-f", cname, timeout=60)   # replace any existing container

    # Custom-image apps carry their image/port/env on the App row; catalog apps
    # take them from the catalog entry.
    image = app.image or entry.get("image")
    container_port = app.container_port or entry.get("container_port")
    if not image or not container_port:
        raise HTTPException(status_code=400, detail="App has no image/port to run")

    fmt = dict(port=app.port, secret=app.secret or "", instance=app.instance)
    cmd = ["run", "-d", "--name", cname, "--restart", "unless-stopped",
           "-p", f"127.0.0.1:{app.port}:{container_port}"]
    for k, v in entry.get("env", {}).items():
        cmd += ["-e", f"{k}={str(v).format(**fmt)}"]
    # Extra env from a custom-image app.
    if app.env_json:
        try:
            for k, v in json.loads(app.env_json).items():
                cmd += ["-e", f"{k}={v}"]
        except (ValueError, AttributeError):
            pass
    if entry.get("secret_env") and app.secret:
        cmd += ["-e", f"{entry['secret_env']}={app.secret}"]
    # WebRTC apps (Neko): tell it the server's public IP so the video stream can
    # actually connect (otherwise you get a black screen behind cloud NAT).
    if entry.get("nat1to1"):
        ip = public_ip()
        if ip:
            cmd += ["-e", f"NEKO_NAT1TO1={ip}"]
    # KVM-based apps (Windows VM): use hardware acceleration when /dev/kvm
    # exists, otherwise fall back to slow software emulation so it still runs.
    if entry.get("kvm"):
        if Path("/dev/kvm").exists():
            cmd += ["--device=/dev/kvm"]
        else:
            cmd += ["-e", "KVM=N"]
    cmd += [str(a).format(**fmt) for a in entry.get("run_args", [])]
    cmd.append(image)
    cmd += entry.get("command", [])   # optional args after the image (e.g. ntfy serve)

    result = _docker(*cmd)
    if result.returncode != 0:
        raise HTTPException(status_code=500,
                            detail=f"docker run failed: {(result.stderr or result.stdout)[:400]}")


def docker_control(instance: str, action: str) -> str:
    result = _docker(action, container_name(instance), timeout=120)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=(result.stderr or result.stdout)[:300])
    return result.stdout.strip() or f"{action} {instance}"


def docker_status(instance: str) -> str:
    r = _docker("inspect", "-f", "{{.State.Status}}", container_name(instance), timeout=20)
    state = r.stdout.strip()
    if state == "running":
        return "RUNNING"
    if state in ("exited", "created", "paused", "dead"):
        return "STOPPED"
    return "STOPPED"   # not found / unknown


def docker_remove(instance: str) -> None:
    _docker("rm", "-f", container_name(instance), timeout=60)


def docker_exec(app, cmd_list: list[str], timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run([*DOCKER, "exec", container_name(app.instance), *cmd_list],
                          capture_output=True, text=True, timeout=timeout)


# ---- Compose (multi-container) ----

def _compose(app, *args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    base = [*DOCKER, "compose", "-f", f"{compose_dir(app)}/docker-compose.yml",
            "-p", f"app_{app.instance}"]
    return subprocess.run([*base, *args], capture_output=True, text=True, timeout=timeout)


def compose_control(app, action: str) -> str:
    mapping = {"start": ["up", "-d", "--remove-orphans"], "stop": ["stop"],
               "restart": ["restart"]}
    result = _compose(app, *mapping.get(action, ["ps"]))
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=(result.stderr or result.stdout)[:400])
    return result.stdout.strip() or f"{action} {app.slug}"


def compose_status(app) -> str:
    result = _compose(app, "ps", "--status", "running", "-q", timeout=60)
    return "RUNNING" if result.stdout.strip() else "STOPPED"


def compose_remove(app) -> None:
    _compose(app, "down", "-v", timeout=300)


# ---- Live-log command per kind (None ⇒ tail the supervisor file) ----

def logs_stream_cmd(app) -> list[str] | None:
    if app.kind == "docker":
        return [*DOCKER, "logs", "-f", "--tail", "200", container_name(app.instance)]
    if app.kind == "compose":
        return [*DOCKER, "compose", "-f", f"{compose_dir(app)}/docker-compose.yml",
                "-p", f"app_{app.instance}", "logs", "-f", "--tail", "200"]
    return None


# ---- Generic dispatch by kind ----

def control_app(app, action: str) -> str:
    if app.kind == "service":
        out = control(app.instance, action); app.status = status(app.instance); return out
    if app.kind == "docker":
        out = docker_control(app.instance, action); app.status = docker_status(app.instance); return out
    if app.kind == "compose":
        out = compose_control(app, action); app.status = compose_status(app); return out
    raise HTTPException(status_code=400, detail="This app is a tool (nothing to run)")


def live_status(app) -> str:
    if app.kind == "service":
        return status(app.instance)
    if app.kind == "docker":
        return docker_status(app.instance)
    if app.kind == "compose":
        return compose_status(app)
    return app.status


def remove_app(app) -> None:
    if app.kind == "service":
        remove_program(app.instance)
    elif app.kind == "docker":
        docker_remove(app.instance)
    elif app.kind == "compose":
        compose_remove(app)


def set_password(app, new_pw: str) -> None:
    """
    Change a service app's password. Two mechanisms:
      - env-based (code-server): store secret + rewrite the supervisor program
        (its env PASSWORD), which restarts it on `update`.
      - CLI-based (File Browser): stop, update the password in its own DB via
        its CLI, then start.
    Caller commits the App row afterwards.
    """
    entry = get_catalog_entry(app.slug)

    # code-server (env PASSWORD) or Jupyter (token in the run command): just
    # store the new secret and rewrite the program — `update` restarts it.
    if entry.get("use_password") or entry.get("use_token"):
        app.secret = new_pw
        write_program(app)
        return

    cmd_tpl = entry.get("set_password_cmd")
    if cmd_tpl:
        was_running = status(app.instance) == "RUNNING"
        if was_running:
            control(app.instance, "stop")
        cmd = [c.format(bin=entry.get("bin", ""), password=new_pw) for c in cmd_tpl]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        finally:
            if was_running:
                control(app.instance, "start")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown error").strip()
            raise HTTPException(status_code=500, detail=f"set password failed: {detail[:300]}")
        app.secret = new_pw
        return

    # Docker app whose credential env is read on every start → recreate it
    if entry.get("pw_change") == "env_recreate":
        app.secret = new_pw
        docker_run(app)
        return

    # Docker app with a CLI reset command run inside the container
    if entry.get("pw_change") == "exec":
        fmt = {"password": new_pw, "old": app.secret or ""}
        cmd = [c.format(**fmt) for c in entry["pw_exec_cmd"]]
        result = docker_exec(app, cmd)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown error").strip()
            raise HTTPException(status_code=500, detail=f"set password failed: {detail[:300]}")
        app.secret = new_pw
        return

    raise HTTPException(status_code=400, detail="This app's password can't be changed from the panel")
