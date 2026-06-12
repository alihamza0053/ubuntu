# ServerHub — Master Build Prompt (All Phases, Complete)

> Copy everything inside the horizontal rules below and give it to your coding
> agent (Claude Code, etc.) as a single instruction. It builds the **entire**
> application — every feature across all 5 phases — with no placeholders or
> "coming later" stubs.

---

You are an expert full-stack and DevOps engineer. Build a complete,
production-ready, self-hosted web-based server management panel called
**ServerHub**, deployed on a single Ubuntu VPS. It is a single-admin tool —
only the logged-in admin can access anything.

**Build ALL features described below. Do not skip, stub, or defer any feature.
Do not leave "Phase 2/3/4" placeholders — implement everything fully. Every
button must work, every route must be implemented, every real-time stream must
actually stream.**

If a Phase 1 codebase already exists in this repo (FastAPI backend under
`backend/`, React frontend under `frontend/`, deploy scripts under `deploy/`),
extend it rather than starting over: keep its structure, security model, and
working features, and add everything that is missing.

================================================================
GLOBAL RULES (apply to every feature)
================================================================

- **Modular code**: each feature in its own router/file/component. No giant
  files. Add clear comments to every file explaining its purpose.
- **Full error handling**: every API call returns meaningful HTTP errors;
  every frontend action shows success/failure feedback. No silent failures.
- **Security first** (details in the SECURITY section). In particular:
  - Every API route and every WebSocket requires a valid JWT.
  - All subprocess calls use **argument lists, never `shell=True`** with raw
    user input.
  - All file paths are resolved and confined to allowed roots — reject any
    path that escapes them (`../` traversal protection).
  - Use the `bcrypt` library directly for password hashing (do NOT use
    `passlib` — it is unmaintained and breaks with modern bcrypt).
- **Consistency**: shared API client, shared auth context, shared UI
  components (status badges, live-log viewer, modals, toasts).
- **Mobile-responsive** layout throughout.

================================================================
TECH STACK
================================================================

Backend:
- Python 3.11+ with FastAPI
- SQLite for the panel's own internal database (SQLAlchemy ORM)
- Supervisor for managing Streamlit dashboard processes
- APScheduler for cron-style scheduling
- WebSockets (FastAPI/asyncio) for real-time terminal, logs, script & apt output
- python-dotenv for configuration
- subprocess / asyncio.create_subprocess_exec for system commands (argument
  lists only)
- psutil for server stats
- bcrypt (directly) for password hashing; python-jose for JWT
- Selenium + headless Chromium + webdriver-manager (helper available to projects)

Frontend:
- React (Vite) + Tailwind CSS
- Axios for API calls (single instance, JWT interceptor, 401 → logout)
- React Router for navigation
- JWT stored in localStorage
- xterm.js for the in-browser terminal
- Monaco Editor (@monaco-editor/react) for in-browser code editing
- Native WebSocket for terminal/log/script/apt streaming (JWT via ?token=)
- Recharts (or similar) for live CPU/RAM/disk graphs

Auth:
- Single admin user; JWT login (username + password); bcrypt hashing
- All HTTP routes and WebSocket connections protected
- Login endpoint rate-limited per client IP

Process management:
- Supervisor controls all Streamlit dashboards; one program per dashboard;
  autorestart on crash; config files written to a panel-owned include dir
  (`/srv/serverhub/supervisor.d/`) so the panel never writes as root.
- supervisorctl invoked via restricted `sudo` NOPASSWD rule.

Web server:
- Nginx already installed; panel auto-writes and reloads Nginx config blocks
- Certbot (Let's Encrypt) for SSL

================================================================
FOLDER STRUCTURE ON THE VPS
================================================================

/srv/serverhub/        Panel application root
  backend/             FastAPI backend
  frontend/            React frontend (source; build output to backend/static/)
  venv/                Python virtualenv
  db/                  SQLite database file
  supervisor.d/        Panel-generated supervisor configs (included by supervisord)

/srv/projects/         All Python workspace projects
  <name>/
    code/              Python scripts
    allscripts/        Helper/utility scripts
    data/              Excel/CSV data files
    dashboard/         Streamlit dashboard files (entry: app.py)
    logs/              Script run logs

/srv/websites/         All websites
  <name>/              React build (dist/), PHP folder, or static HTML

/srv/nginx-configs/    Auto-generated Nginx config blocks (symlinked into nginx)

================================================================
PANEL INTERNAL DATABASE (SQLite) — full schema
================================================================

users(id, username, hashed_password)
projects(id, name, folder_path, dashboard_port, dashboard_status, domain, created_at)
scripts(id, project_id, folder, filename, schedule_cron, last_run, last_status, last_log)
websites(id, name, folder_path, type[react/php/html], domain, db_name, created_at)
schedules(id, script_id, cron_expression, is_active, next_run)
nginx_configs(id, entity_type, entity_id, config_path, domain)
terminal_history(id, command, output, executed_at)
settings(id, key, value)   -- panel settings (port/subdomain, etc.)

================================================================
BACKEND API ROUTES (FastAPI) — implement ALL
================================================================

AUTH:
  POST /api/auth/login            (rate-limited)
  GET  /api/auth/me
  POST /api/auth/change-password

PROJECTS:
  GET    /api/projects                 (supports ?with_status=true for live state)
  POST   /api/projects                 create project + folder structure + supervisor cfg
  GET    /api/projects/{id}
  DELETE /api/projects/{id}            (?delete_files=true to also remove folder)

  POST /api/projects/{id}/upload-script     (folder=code|allscripts)
  POST /api/projects/{id}/upload-dashboard
  POST /api/projects/{id}/upload-data
  GET  /api/projects/{id}/files             list files across all folders
  GET  /api/projects/{id}/scripts           registered runnable scripts
  GET  /api/projects/{id}/download          (folder, filename)
  DELETE /api/projects/{id}/files           (folder, filename)

  POST /api/projects/{id}/run-script/{filename}   background run
  GET  /api/projects/{id}/logs/{filename}         last run log

  POST /api/projects/{id}/dashboard/start
  POST /api/projects/{id}/dashboard/stop
  POST /api/projects/{id}/dashboard/restart
  GET  /api/projects/{id}/dashboard/status

  POST /api/projects/{id}/assign-domain     writes nginx block + reload
  POST /api/projects/{id}/ssl               certbot for the domain

SCHEDULER:
  GET    /api/schedules
  POST   /api/schedules                 attach cron to a script
  PUT    /api/schedules/{id}
  DELETE /api/schedules/{id}
  POST   /api/schedules/{id}/toggle

WEBSITES:
  GET    /api/websites
  POST   /api/websites                  create site (type react/php/html)
  GET    /api/websites/{id}
  DELETE /api/websites/{id}
  POST   /api/websites/{id}/upload       upload zip, auto-extract (+ react build option)
  POST   /api/websites/{id}/assign-domain
  POST   /api/websites/{id}/ssl
  GET    /api/websites/{id}/files

DATABASES (MySQL):
  GET    /api/databases
  POST   /api/databases                 create db + user
  DELETE /api/databases/{name}
  POST   /api/databases/{name}/import    import .sql
  GET    /api/databases/{name}/export    download .sql dump
  POST   /api/databases/query            run SQL, return rows

NGINX:
  GET    /api/nginx/configs
  GET    /api/nginx/configs/{id}
  PUT    /api/nginx/configs/{id}
  DELETE /api/nginx/configs/{id}
  POST   /api/nginx/reload

FILE MANAGER (server-wide, confined to allowed roots):
  GET    /api/files/browse?path=
  POST   /api/files/upload
  DELETE /api/files/delete
  POST   /api/files/rename
  POST   /api/files/move
  POST   /api/files/mkdir
  GET    /api/files/download
  GET    /api/files/read                 (editor)
  POST   /api/files/write                (editor)

TERMINAL:
  WS   /ws/terminal                      full interactive shell (PTY)
  POST /api/terminal/run                 single command, return output
  GET  /api/terminal/history

SERVER & PACKAGES:
  GET  /api/server/stats                 CPU, RAM, disk, uptime
  GET  /api/server/processes             supervisor + system processes
  POST /api/server/supervisor/{name}/{action}   start/stop/restart a program
  POST /api/server/apt/update
  POST /api/server/apt/upgrade           (return changelog/preview first)
  POST /api/server/apt/install           {package}
  POST /api/server/apt/remove            {package}
  GET  /api/server/apt/search?q=

LOGS (full viewer):
  GET /api/logs/nginx/access
  GET /api/logs/nginx/error
  GET /api/logs/supervisor/{name}
  GET /api/logs/script/{id}
  GET /api/logs/system                   /var/log/syslog
  GET /api/logs/download?type=&name=     download as .txt

SETTINGS:
  GET  /api/settings
  PUT  /api/settings
  POST /api/settings/backup-db           download the panel SQLite DB

REAL-TIME WEBSOCKETS (all JWT-protected via ?token=):
  /ws/terminal                full bash/PTY session
  /ws/logs/{type}/{name}      tail -f any log live
  /ws/script/{id}/run         live output of a running script
  /ws/apt/{action}            live output of apt install/update/upgrade/remove
  /ws/server/stats            optional live stats push

================================================================
FRONTEND PAGES (React) — implement ALL, fully functional
================================================================

/login
  - Username + password; JWT stored on success; error display; redirect.

/dashboard (Home overview)
  - Server stat widgets: CPU%, RAM%, Disk%, Uptime (auto-refresh).
  - PROJECT CARDS, one per Python project, each showing:
      name; dashboard status badge (Running ✅ / Stopped 🔴 / Error ⚠️);
      domain + clickable live link; port; last script run time + pass/fail;
      next scheduled run; file counts (scripts, data, dashboard);
      quick buttons: ▶ Start ⏹ Stop 🔄 Restart ▶ Run Script 📁 Files.
  - WEBSITE CARDS, one per website, each showing:
      site name + type badge (React/PHP/HTML); domain + live link; SSL status;
      linked database name; quick buttons: 📁 Files 🔧 Edit 🗄 Database.
  - Recent logs summary; upcoming scheduled jobs.

/projects (all workspaces)
  - Grid of project cards; "New Project" button (modal → creates folders +
    supervisor entry).

/projects/{id} (tabbed detail) — ALL tabs functional:
  - Overview: all info at a glance; dashboard live URL; status badges.
  - Files: four folder panels (code | allscripts | data | dashboard) with
    upload (button + drag-and-drop), list, download, delete; click .py/.txt →
    open in Monaco; click .xlsx → info + download.
  - Code Editor: Monaco with file tree (all project files), syntax
    highlighting, find/replace, multiple tabs, Save (Ctrl+S), and a "Run this
    file" button for .py that streams output live.
  - Scripts: list scripts in code/ and allscripts/; per script Run Now,
    Schedule, View Log; expandable live log panel (WebSocket) when running.
  - Dashboard: Start/Stop/Restart Streamlit; status badge + port; assign domain
    input; SSL button; live URL; live process log stream.
  - Scheduler: visual cron builder (pick frequency/time/day); list of scheduled
    scripts with on/off toggle; last/next run; edit/delete.
  - Data Files: list Excel/CSV in data/; upload, download, last-modified.

/websites (all sites)
  - Grid of website cards; "New Website" button.

/websites/{id} (tabbed detail) — ALL tabs functional:
  - Overview: site info, domain, type, linked database.
  - Files: full file browser for the site folder; upload files or zip
    (auto-extract); delete/rename/move; open any file in Monaco.
  - Code Editor: Monaco for HTML/PHP/JS/CSS with file tree.
  - Database: linked MySQL db; import/export .sql; simple query runner.
  - Domain & SSL: current domain; reassign; SSL status + request/renew.

/terminal (full terminal page)
  - xterm.js connected to a real shell over WebSocket; run ANY command
    (apt install, pip install, nano, etc.); color support; scrollback;
    command history (up/down); session persists while tab open.

/logs (log viewer page)
  - Sidebar list of sources: nginx access, nginx error, system (syslog),
    per Streamlit dashboard, per script (last run).
  - Main panel shows selected log; "Live" toggle → real-time streaming;
    search/filter; download as .txt.

/files (global file manager)
  - Server file browser starting at /srv/; navigate dirs; upload files/folders;
    download; create folders; delete/rename/move; open any text/code file in
    Monaco.

/databases (MySQL manager)
  - List databases; create db + user; import .sql; export/download dump;
    query runner (SQL input + results table); drop db (confirm).

/nginx (config manager)
  - List managed config files; view raw; edit in Monaco; Save + Reload Nginx;
    delete config.

/server (server tools)
  - Live CPU/RAM/disk graphs (auto-refresh).
  - Supervisor process list with start/stop/restart per program.
  - APT package manager: search, install (live install log via WebSocket),
    remove, apt update, apt upgrade (preview changes first). All installs
    stream output live.

/settings
  - Change admin password; panel port/subdomain config; backup panel database.

================================================================
REAL-TIME IMPLEMENTATION NOTES
================================================================

- Backend WebSocket endpoints use asyncio subprocesses; read stdout/stderr line
  by line and push frames to the client. Client disconnect must not kill a
  running script (keep logging to disk).
- Terminal uses a real PTY (e.g. ptyprocess / pty) so interactive programs and
  colors work; resize support via control messages.
- Frontend: xterm.js for terminal; a shared <LiveLog> component (auto-scroll,
  clear, connected indicator) for log/script/apt streams.
- Auth on WebSockets: JWT passed as ?token= and validated on connect; close with
  code 1008 on failure.

================================================================
CODE EDITOR (Monaco) — required everywhere files are edited
================================================================

- Embedded Monaco via @monaco-editor/react.
- Available on: project files, website files, nginx configs, and any file opened
  from the global File Manager.
- Syntax highlighting for Python, JS/JSX/TS, HTML, PHP, CSS, YAML, JSON, SQL,
  INI/TOML, shell, markdown. Auto-indent, bracket matching, find & replace.
- Multiple open tabs; Save with Ctrl+S or a Save button; "Run" for Python files
  (streams output live). Read from disk via API, write back on save. Reject
  files outside allowed roots and oversized files.

================================================================
NGINX TEMPLATES (auto-generated; reload after writing)
================================================================

Streamlit dashboard (proxy + WebSocket upgrade):
  server { listen 80; server_name {domain};
    location / { proxy_pass http://127.0.0.1:{port};
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
      proxy_set_header Host $host; } }

React (static SPA):
  server { listen 80; server_name {domain};
    root /srv/websites/{folder}/dist; index index.html;
    location / { try_files $uri /index.html; } }

PHP:
  server { listen 80; server_name {domain};
    root /srv/websites/{folder}; index index.php index.html;
    location / { try_files $uri $uri/ =404; }
    location ~ \.php$ { include snippets/fastcgi-php.conf;
      fastcgi_pass unix:/var/run/php/php8.1-fpm.sock; } }

HTML (static):
  server { listen 80; server_name {domain};
    root /srv/websites/{folder}; index index.html; }

Write blocks into /srv/nginx-configs/, symlink into /etc/nginx/sites-enabled/,
run `nginx -t`, then reload. Domain assignment + SSL (certbot --nginx -d
{domain}) wired through the restricted sudoers rules.

================================================================
SUPERVISOR TEMPLATE (per Streamlit dashboard)
================================================================

[program:{name}_dashboard]
command={streamlit} run /srv/projects/{name}/dashboard/app.py --server.port {port} --server.headless true
directory=/srv/projects/{name}/dashboard
autostart=false
autorestart=true
stderr_logfile=/var/log/supervisor/{name}.err.log
stdout_logfile=/var/log/supervisor/{name}.out.log

Write to /srv/serverhub/supervisor.d/, then supervisorctl reread + update.
Allocate each project a unique port starting at DASHBOARD_PORT_START (8501).

================================================================
SELENIUM (headless Ubuntu) — helper available to project scripts
================================================================

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
options = Options()
options.add_argument("--headless"); options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

================================================================
SECURITY (enforce everywhere)
================================================================

- JWT on all API routes and WebSocket connections; bcrypt password hashing
  (truncate to 72 bytes; use the bcrypt library directly, not passlib).
- Subprocess calls use argument lists, never shell=True with raw user input.
  The /ws/terminal PTY is the one intentional interactive shell — still behind
  JWT, single-admin only.
- File uploads: validate extensions per destination; sanitize filenames
  (no path separators, no traversal). Reject executables except .py where
  appropriate.
- Every filesystem path resolved and confined to allowed roots; reject escapes.
- Nginx reload, certbot, supervisorctl, apt: invoked via `sudo` using a
  restricted NOPASSWD sudoers file listing ONLY those specific commands.
- Panel runs as an unprivileged system user (`serverhub`) behind Nginx on its
  own subdomain (panel.yourdomain.com), HTTPS enforced.
- Login endpoint rate-limited per IP. All command/log output sanitized before
  display.

================================================================
DEPLOYMENT (Ubuntu) — provide working scripts/configs
================================================================

Provide under deploy/:
- install.sh — idempotent installer: apt packages (python3, venv, pip, nginx,
  supervisor, mysql-server, php-fpm, certbot, chromium-browser, nodejs 18+);
  create serverhub user + /srv layout; venv + pip install; npm build frontend
  → backend/static/; generate .env with random SECRET_KEY; set ownership;
  install sudoers; wire supervisor include; register panel supervisor program
  on port 8765; install + reload nginx site.
- serverhub.supervisor.conf — panel service (uvicorn app.main:app :8765).
- nginx-panel.conf — reverse proxy with WebSocket upgrade + large upload limit.
- sudoers-serverhub — NOPASSWD for ONLY: supervisorctl, nginx -t,
  systemctl reload nginx, certbot, the specific apt-get commands, and the
  mysql/mysqldump commands used by the DB manager.
- setup_admin.py — create/update the admin user (interactive or -u/-p flags).
- A DEPLOYMENT.md guide covering DNS, SSL, management, updates, troubleshooting.

Deployment order: upload /srv/serverhub/ → run install.sh → create admin →
set domain in nginx + reload → certbot for SSL.

================================================================
BUILD ORDER (build them all; this is the recommended sequence)
================================================================

1. Core + Auth + Projects: login/JWT; project CRUD + folders; per-folder upload;
   Monaco editor; script run + live WebSocket log; Streamlit start/stop via
   Supervisor; dashboard cards on home.
2. Terminal + Full Logs + Scheduler: xterm.js PTY terminal; full log viewer with
   live streaming + search + download; APScheduler + visual cron builder.
3. Websites + Nginx + Domains: website deploy (zip upload, react build), nginx
   config auto-generation, domain assignment + SSL, global file manager.
4. Databases + Server Tools: MySQL manager (create/import/export/query/drop);
   APT package manager with live output; live server stat graphs; supervisor
   process manager.
5. Polish: full dashboard card UI, settings page (password/port/backup),
   mobile-responsive layout, consistent error handling and toasts throughout.

================================================================
DELIVERABLE
================================================================

A complete, runnable application: FastAPI backend (modular routers + services),
React frontend (all pages + tabs functional), all WebSocket streams working,
and deploy/ scripts that bring it up on a fresh Ubuntu VPS. Include a README and
DEPLOYMENT.md. Every feature listed above must be implemented and working — no
stubs, no "coming soon", no skipped routes or buttons.

---
