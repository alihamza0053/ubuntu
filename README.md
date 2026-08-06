# ServerHub

Self-hosted web panel to manage an Ubuntu VPS from the browser: Python project
workspaces, Streamlit dashboards, script running/scheduling, websites, Flask /
FastAPI apps, MySQL, a file manager and a built-in code editor.

**Sections:** Dashboard · Projects · Websites · Files · Recycle Bin ·
Databases · Settings.

**Status: complete.** Auth with per-tab user permissions, project workspaces,
file uploads, Monaco editor, script runner with live WebSocket output, project
pipelines, project dashboards via Supervisor (Streamlit / Flask / FastAPI,
picked automatically from the code), dashboard cards + server stats,
APScheduler cron scheduling with a visual builder, website deploys (zip + React
build + Flask/FastAPI apps run under Supervisor with the entrypoint auto-detected
from your code), automatic nginx config generation with
domain assignment + Certbot SSL, global file manager with a recycle bin, MySQL
manager (create/drop/query/import/export), OneDrive sync, backup & restore,
panel self-update and system cleanup.

## Guides

- **`DEPLOYMENT.md`** — install from zero on a fresh Ubuntu VPS (every dependency),
  plus *Deploy a Flask (or FastAPI) app* in §7.
- **`UPDATING.md`** — push code changes to an installed panel (`deploy/update.sh`).
- **`DASHBOARD_GUIDE.md`** — deploy project dashboards (Streamlit, Flask or
  FastAPI — detected from your code) + fix every common issue (per-project venv,
  spawn errors, `.xls`/`xlrd`, missing modules).
- **`SCRIPTS_GUIDE.md`** — run Python/Selenium scripts (headless Chrome, scheduling).
- **`MASTER_BUILD_PROMPT.md`** — the full feature specification.

## Stack

- **Backend** — FastAPI + SQLite (SQLAlchemy), JWT auth (bcrypt), WebSockets,
  Supervisor for dashboard processes. `backend/`
- **Frontend** — React (Vite) + Tailwind, React Router, Axios, Monaco editor.
  `frontend/` (builds into `backend/static/`)
- **Deploy** — Nginx reverse proxy + Supervisor on Ubuntu. `deploy/`

## Quick start (development)

Backend (terminal 1):

```bash
cd backend
python3 -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # edit SECRET_KEY at least
python setup_admin.py -u admin                        # prompts for password
uvicorn app.main:app --reload --port 8765
```

Frontend (terminal 2):

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 — proxies /api and /ws to :8765
```

Note: Supervisor/Streamlit features need Linux. On Windows/macOS dev machines
everything else works; dashboard start/stop will report supervisor errors.

## Production install (Ubuntu VPS)

```bash
sudo bash deploy/install.sh
```

The script installs packages, creates the `serverhub` system user, builds the
frontend, registers the panel under Supervisor on port 8765, configures nginx
and installs a restricted sudoers rule (`supervisorctl` only in Phase 1).

Afterwards:

1. `cd /srv/serverhub/backend && sudo -u serverhub /srv/serverhub/venv/bin/python setup_admin.py`
2. Set your domain in `/etc/nginx/sites-available/serverhub`, reload nginx.
3. `sudo certbot --nginx -d panel.yourdomain.com` for SSL.

## Layout on the VPS

```
/srv/serverhub/            panel (backend, frontend, venv, db, supervisor.d)
/srv/projects/<name>/      workspaces: code/ allscripts/ data/ dashboard/ logs/
/srv/websites/             deployed sites (Phase 3)
/srv/nginx-configs/        panel-generated nginx blocks (Phase 3)
/srv/apps/<key>/           Apps section: data, generated run.sh, install logs
```

Each project gets a Supervisor program `<name>_dashboard` running
`streamlit run dashboard/app.py --server.port <port>` with auto-restart.
Configs live in `/srv/serverhub/supervisor.d/` (included from
`supervisord.conf`) so the panel user can write them without root; only
`supervisorctl` goes through sudo.

## Security model

- Admin + optional restricted users (per-tab permissions); JWT (bcrypt-hashed
  password) on every API route, token as `?token=` on WebSockets; login
  rate-limited per IP.
- Projects and websites can be marked admin-only, making them invisible and
  unreachable for non-admin users.
- All subprocess calls use argument lists — never `shell=True`.
- Uploads validated by per-folder extension allow-lists; filenames sanitized.
- All file paths resolved and confined to panel-managed roots
  (`backend/app/services/paths.py`).
- Sudo restricted to specific commands via `/etc/sudoers.d/serverhub`.

## Implemented

- **Projects** — CRUD + standard folders, uploads, Monaco editor, per-project
  venv & pip packages, script runner with live logs, pipelines, Streamlit
  dashboards via Supervisor, APScheduler scheduling + visual cron builder,
  OneDrive folder mapping and a password-protected upload portal.
- **Websites** — zip deploys (static / PHP / React build) plus run-your-own
  Python services, nginx config generation, domain assignment + Certbot SSL.
- **Apps** — install and run ready-made software: **n8n** (workflow automation)
  and **Chromium** / **Brave**, which run on a virtual display (Xvfb + x11vnc +
  noVNC) so you drive a real browser from inside the panel. Each app is a
  Supervisor program `app_<key>` with start/stop/restart, live logs, domain
  assignment and Certbot SSL, exactly like a website. Installing needs root, so
  it goes through `deploy/serverhub-apps.sh` under one narrow sudoers rule —
  that helper accepts only those three app names and hard-codes every package
  list.
- **Files** — global file manager with a 24h recycle bin.
- **Databases** — MySQL create/drop/query/import/export.
- **Settings** — users & permissions, password, OneDrive sync, backup &
  restore, panel self-update, system cleanup (CPU/RAM/disk).

See `MASTER_BUILD_PROMPT.md` for the full feature specification.
