# ServerHub — Updating an Already-Installed Panel

You've already installed ServerHub. This doc is about pushing changes afterwards:
you edited code, added a feature, or pulled a new version.

**The basics are in Section 1 — that's all you need most of the time.**
Everything after it is detail for special cases.

---

## 1. The basic update (use this every time)

### Easiest: the "Update now" button in the panel

Open the panel → **Settings → Updates**. It shows whether you're up to date and,
if you've pushed changes, how many updates are available. Click **Update now** —
it runs the same `deploy/update.sh` on the server (pull → backup → rebuild →
restart), streaming the log live. The panel restarts itself at the end and the
page reloads automatically when it's back.

> Requires the server to have a source checkout (`UPDATE_SRC`, default
> `/opt/serverhub-src`) and the sudoers rule — both are set up by
> `install.sh`/`update.sh`. If you've never run the CLI update on this server,
> run `sudo bash deploy/update.sh` once first to install the updater helper.

If you edited code locally, still **push it first** (below) so the button has
something to pull.

### If you edited code on your own computer — push it first

On your **local machine**, in the project folder:

```bash
git add -A
git commit -m "describe your change"
git push
```

### Then on the server — one command

```bash
ssh root@YOUR_SERVER_IP
cd /opt/serverhub-src
sudo bash deploy/update.sh
```

That single command does everything safely:
- pulls the latest code (`git pull`),
- **backs up** your `.env` + database first,
- copies the new backend, updates Python deps,
- rebuilds the frontend,
- restarts the panel and health-checks it.

You're done when you see:

```
==> OK — panel is healthy.
Update complete (…).
```

### Then refresh your browser

Hard-refresh with **Ctrl+Shift+R** so it loads the new frontend.

### Faster variants (optional)

```bash
sudo bash deploy/update.sh --backend-only    # you only changed Python code (skips UI build)
sudo bash deploy/update.sh --frontend-only   # you only changed React code
```

> ✅ That's the whole everyday workflow: **push → `update.sh` → hard-refresh.**
> If it says "panel is healthy", it worked. The rest of this doc is only for
> when something is unusual.

---
---

# Details (only if you need them)

## 2. The mental model

There are **two copies** of the code on your server:

```
/opt/serverhub-src/     ← SOURCE: the repo you git-cloned. You update THIS.
        │  (copy + build)
        ▼
/srv/serverhub/         ← LIVE: what actually runs. update.sh writes here.
```

You never edit `/srv/serverhub/` by hand. The flow is always: change code → get it
into `/opt/serverhub-src/` → run `update.sh`.

**Never overwritten** by an update:
- `backend/.env` — your `SECRET_KEY` and config.
- `db/serverhub.db` — your projects, websites, schedules, users.

`update.sh` also snapshots both to `/srv/serverhub/backups/<timestamp>/` before
touching anything.

---

## 3. Getting code onto the server without Git

If your source isn't a git checkout, upload the changed folders instead, then run
`update.sh --no-pull`.

**SCP from Windows/Mac** (run locally, from the folder with `backend/ frontend/ deploy/`):
```powershell
scp -r backend frontend deploy root@YOUR_SERVER_IP:/opt/serverhub-src/
```

**Only one part changed:**
```powershell
scp -r backend  root@YOUR_SERVER_IP:/opt/serverhub-src/    # backend only
scp -r frontend root@YOUR_SERVER_IP:/opt/serverhub-src/    # frontend only
```

**rsync** (macOS/Linux/WSL, sends only changed files):
```bash
rsync -avz --exclude node_modules --exclude venv --exclude .git \
  ./ root@YOUR_SERVER_IP:/opt/serverhub-src/
```

Or drag the folders in with **WinSCP / FileZilla**. Then:
```bash
cd /opt/serverhub-src && sudo bash deploy/update.sh --no-pull
```

---

## 4. What `update.sh` does, and its flags

In order: `git pull` (if a git repo) → back up `.env`+db → copy backend + pip
install → copy frontend + `npm run build` → fix ownership → restart + health
check.

```bash
sudo bash deploy/update.sh                 # full update
sudo bash deploy/update.sh --backend-only  # skip frontend rebuild
sudo bash deploy/update.sh --frontend-only # only rebuild UI
sudo bash deploy/update.sh --no-pull       # don't git pull (you uploaded manually)
sudo SRC=/opt/serverhub-src bash deploy/update.sh   # source in a different folder
```

| You changed… | Command |
|---|---|
| Python code (`backend/app/**`) | `sudo bash deploy/update.sh --backend-only` |
| `requirements.txt` (new dep) | `sudo bash deploy/update.sh --backend-only` |
| React code (`frontend/src/**`) | `sudo bash deploy/update.sh --frontend-only` |
| Both backend + frontend | `sudo bash deploy/update.sh` |
| `backend/.env` (config only) | edit `/srv/serverhub/backend/.env`, then `sudo supervisorctl restart serverhub` |
| `deploy/` config files | see Section 6 |

---

## 5. Manual update (without the script)

```bash
# Back up first
sudo cp /srv/serverhub/backend/.env   ~/serverhub-env.bak
sudo cp /srv/serverhub/db/serverhub.db ~/serverhub-db.bak

# Backend (--exclude keeps your live .env)
sudo rsync -a --exclude '.env' --exclude 'static/' --exclude '__pycache__/' \
  /opt/serverhub-src/backend/ /srv/serverhub/backend/
sudo /srv/serverhub/venv/bin/pip install -r /srv/serverhub/backend/requirements.txt

# Frontend
sudo rsync -a --exclude 'node_modules/' /opt/serverhub-src/frontend/ /srv/serverhub/frontend/
cd /srv/serverhub/frontend && sudo npm install && sudo npm run build

# Ownership + restart + verify
# NOTE: never 'chown -R … /srv/serverhub' blindly — it re-owns Docker app data
# (e.g. Supabase's Postgres dir) and breaks it. Exclude apps/:
sudo find /srv/serverhub -path /srv/serverhub/apps -prune -o -exec chown serverhub:serverhub {} +
sudo supervisorctl restart serverhub
curl http://127.0.0.1:8765/api/health     # {"status":"ok"}
```

---

## 6. Updating deploy config (sudoers / nginx / supervisor)

These live outside `/srv/serverhub`, so `update.sh` doesn't touch them. Only redo
the one that changed.

**Sudoers** (new privileged command added):
```bash
sudo install -m 0440 /opt/serverhub-src/deploy/sudoers-serverhub /etc/sudoers.d/serverhub
sudo visudo -c        # must say "parsed OK"
```

**Panel nginx config:**
```bash
sudo cp /opt/serverhub-src/deploy/nginx-panel.conf /etc/nginx/sites-available/serverhub
sudo nano /etc/nginx/sites-available/serverhub    # re-set your server_name!
sudo nginx -t && sudo systemctl reload nginx
```

**Panel supervisor service** (rare):
```bash
sudo sed "s|{PANEL_ROOT}|/srv/serverhub|g; s|{PANEL_USER}|serverhub|g" \
  /opt/serverhub-src/deploy/serverhub.supervisor.conf \
  | sudo tee /etc/supervisor/conf.d/serverhub.conf
sudo supervisorctl reread && sudo supervisorctl update
```

---

## 7. Emergency hotfix directly on the server

For a one-line fix you can edit the **live** file and restart — but it gets
overwritten on the next `update.sh`, so put the same change back in
`/opt/serverhub-src` (and your repo) afterwards.

```bash
sudo nano /srv/serverhub/backend/app/routers/<file>.py
sudo chown serverhub:serverhub /srv/serverhub/backend/app/routers/<file>.py
sudo supervisorctl restart serverhub
```

---

## 8. If something breaks — verify & roll back

**Verify:**
```bash
sudo supervisorctl status serverhub          # RUNNING
curl http://127.0.0.1:8765/api/health        # {"status":"ok"}
sudo tail -f /var/log/supervisor/serverhub.err.log    # watch for errors
```

**Roll back** to the snapshot `update.sh` saved before this run:
```bash
ls -1 /srv/serverhub/backups/                # newest last
sudo cp /srv/serverhub/backups/<timestamp>/serverhub.db /srv/serverhub/db/serverhub.db
sudo cp /srv/serverhub/backups/<timestamp>/.env        /srv/serverhub/backend/.env
# Exclude apps/ so Docker app data (e.g. Supabase Postgres) isn't re-owned:
sudo find /srv/serverhub -path /srv/serverhub/apps -prune -o -exec chown serverhub:serverhub {} +
sudo supervisorctl restart serverhub
```

To roll back **code**: `git checkout <previous-commit>` in `/opt/serverhub-src`
(or re-upload the old folders), then run `update.sh` again.

---

## 9. Cheat sheet

```bash
# Everyday: push from your computer, then on the server:
cd /opt/serverhub-src && sudo bash deploy/update.sh

# Faster:
sudo bash deploy/update.sh --backend-only      # Python only
sudo bash deploy/update.sh --frontend-only     # React only

# Just changed .env:
sudo nano /srv/serverhub/backend/.env && sudo supervisorctl restart serverhub

# Health check:
curl http://127.0.0.1:8765/api/health
```
