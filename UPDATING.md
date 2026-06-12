# ServerHub — Updating an Already-Installed Panel

You've already installed ServerHub (via `DEPLOYMENT.md`). This doc is **only**
about pushing changes afterwards: you edited code, added a feature, or pulled a
new version — how do you get it onto the running server safely?

> **TL;DR:** Get the new code onto the server, then run **one command**:
> ```bash
> cd /opt/serverhub-src && sudo bash deploy/update.sh
> ```
> It backs up your `.env` + database, copies the new code, updates Python deps,
> rebuilds the frontend, restarts the panel, and health-checks it.

---

## 1. The mental model (read this once)

There are **two copies** of the code on your server:

```
/opt/serverhub-src/     ← SOURCE: the repo you uploaded / git-cloned. You update THIS.
        │  (copy + build)
        ▼
/srv/serverhub/         ← LIVE: what actually runs. The update script writes here.
```

You never edit `/srv/serverhub/` by hand. The workflow is always:

1. **Change the code** (on your local machine, or by `git pull` on the server).
2. **Get it into `/opt/serverhub-src/`** on the server.
3. **Run the update script**, which copies `/opt/serverhub-src` → `/srv/serverhub`,
   rebuilds, and restarts.

Two things are **never overwritten** by an update:
- `backend/.env` — your `SECRET_KEY` and config.
- `db/serverhub.db` — your projects, websites, schedules, users.

(The update script also snapshots both into `/srv/serverhub/backups/<timestamp>/`
before doing anything, just in case.)

---

## 2. Step 1 — Get the new code onto the server

Pick the method that matches how you installed.

### Option A — Git (if `/opt/serverhub-src` is a git checkout)

```bash
ssh root@YOUR_SERVER_IP
cd /opt/serverhub-src
git pull --ff-only
```

(The update script can also do this for you — see Section 3.)

### Option B — Upload from your Windows / Mac machine (SCP)

Run **locally**, from the folder containing `backend/`, `frontend/`, `deploy/`:

```powershell
# Windows PowerShell / macOS Terminal — copy the changed folders up
scp -r backend frontend deploy root@YOUR_SERVER_IP:/opt/serverhub-src/
```

Only changed something small? Copy just that:

```powershell
# Only a backend change:
scp -r backend  root@YOUR_SERVER_IP:/opt/serverhub-src/
# Only a frontend change:
scp -r frontend root@YOUR_SERVER_IP:/opt/serverhub-src/
```

### Option C — rsync (fastest for repeat uploads; macOS/Linux/WSL)

Only sends changed files:

```bash
rsync -avz --exclude node_modules --exclude venv --exclude .git \
  ./ root@YOUR_SERVER_IP:/opt/serverhub-src/
```

### Option D — WinSCP / FileZilla

Drag the changed folders into `/opt/serverhub-src/` and overwrite.

---

## 3. Step 2 — Apply the update (one command)

```bash
ssh root@YOUR_SERVER_IP
cd /opt/serverhub-src
sudo bash deploy/update.sh
```

What it does, in order:
1. `git pull` (if the source is a git repo).
2. Backs up `.env` + `serverhub.db` → `/srv/serverhub/backups/<timestamp>/`.
3. Copies new **backend** code (never the `.env`) and updates Python deps.
4. Copies new **frontend** code and runs `npm run build`.
5. Fixes ownership to the `serverhub` user.
6. Restarts the panel and checks `http://127.0.0.1:8765/api/health`.

If the health check fails it tells you which log to read and where the backup is.

### Faster variants

```bash
# You only changed Python/backend code — skip the (slow) frontend build:
sudo bash deploy/update.sh --backend-only

# You only changed React/frontend code:
sudo bash deploy/update.sh --frontend-only

# You already pulled/uploaded and don't want it to git-pull again:
sudo bash deploy/update.sh --no-pull

# Source is somewhere other than the repo folder:
sudo SRC=/opt/serverhub-src bash deploy/update.sh
```

---

## 4. What each kind of change needs

| You changed… | Needs | Command |
|---|---|---|
| Python code (`backend/app/**`) | copy + restart | `sudo bash deploy/update.sh --backend-only` |
| `requirements.txt` (new dep) | copy + pip + restart | `sudo bash deploy/update.sh --backend-only` |
| React code (`frontend/src/**`) | copy + `npm build` | `sudo bash deploy/update.sh --frontend-only` |
| Both backend + frontend | everything | `sudo bash deploy/update.sh` |
| `backend/.env` (config) | edit live + restart | edit `/srv/serverhub/backend/.env`, then `sudo supervisorctl restart serverhub` |
| `deploy/sudoers-serverhub` | reinstall sudoers | see Section 6 |
| `deploy/nginx-panel.conf` | recopy + reload nginx | see Section 6 |

> **Rule of thumb:** backend changes need a **restart**; frontend changes need a
> **rebuild**. The script handles both — these are just the manual equivalents.

---

## 5. Manual update (if you don't want the script)

Equivalent of what `update.sh` does:

```bash
# 1. New code already in /opt/serverhub-src (git pull or SCP)

# 2. Back up first
sudo cp /srv/serverhub/backend/.env   ~/serverhub-env.bak
sudo cp /srv/serverhub/db/serverhub.db ~/serverhub-db.bak

# 3. Backend (the --exclude keeps your live .env)
sudo rsync -a --exclude '.env' --exclude 'static/' --exclude '__pycache__/' \
  /opt/serverhub-src/backend/ /srv/serverhub/backend/
sudo /srv/serverhub/venv/bin/pip install -r /srv/serverhub/backend/requirements.txt

# 4. Frontend
sudo rsync -a --exclude 'node_modules/' /opt/serverhub-src/frontend/ /srv/serverhub/frontend/
cd /srv/serverhub/frontend && sudo npm install && sudo npm run build

# 5. Ownership + restart
sudo chown -R serverhub:serverhub /srv/serverhub
sudo supervisorctl restart serverhub

# 6. Verify
curl http://127.0.0.1:8765/api/health     # {"status":"ok"}
```

---

## 6. Updating deploy config (sudoers / nginx / supervisor)

These live outside `/srv/serverhub`, so the normal update doesn't touch them.
Only redo them if **those specific files** changed.

**Sudoers** (e.g. you added a new privileged command):
```bash
sudo install -m 0440 /opt/serverhub-src/deploy/sudoers-serverhub /etc/sudoers.d/serverhub
sudo visudo -c        # must say "parsed OK"
```

**Panel nginx config** (e.g. bigger upload limit):
```bash
sudo cp /opt/serverhub-src/deploy/nginx-panel.conf /etc/nginx/sites-available/serverhub
sudo nano /etc/nginx/sites-available/serverhub    # re-set your server_name!
sudo nginx -t && sudo systemctl reload nginx
```

**Panel supervisor service** (rare — only if `serverhub.supervisor.conf` changed):
```bash
sudo sed "s|{PANEL_ROOT}|/srv/serverhub|g; s|{PANEL_USER}|serverhub|g" \
  /opt/serverhub-src/deploy/serverhub.supervisor.conf \
  | sudo tee /etc/supervisor/conf.d/serverhub.conf
sudo supervisorctl reread && sudo supervisorctl update
```

---

## 7. Quick "edit directly on the server" (hotfix)

For a one-line emergency fix you can edit the live file and restart — but
**remember it will be overwritten on the next `update.sh`**, so port the same
change back into `/opt/serverhub-src` (and your repo) afterwards.

```bash
sudo nano /srv/serverhub/backend/app/routers/<file>.py
sudo chown serverhub:serverhub /srv/serverhub/backend/app/routers/<file>.py
sudo supervisorctl restart serverhub
```

Frontend hotfixes aren't worth doing live (they'd need a rebuild) — change the
source and run `--frontend-only`.

---

## 8. Verify after updating

```bash
sudo supervisorctl status serverhub          # RUNNING
curl http://127.0.0.1:8765/api/health        # {"status":"ok"}
```

Then hard-refresh the browser (**Ctrl+Shift+R**) so it loads the new frontend
assets, and click through whatever you changed. Watch logs live if anything
looks off:

```bash
sudo tail -f /var/log/supervisor/serverhub.err.log
```

---

## 9. Rollback (if an update breaks things)

Every `update.sh` run saves the previous `.env` + database under
`/srv/serverhub/backups/<timestamp>/`. To roll back:

```bash
# List backups (newest last)
ls -1 /srv/serverhub/backups/

# Restore the database (and .env if needed) from a known-good snapshot
sudo cp /srv/serverhub/backups/<timestamp>/serverhub.db /srv/serverhub/db/serverhub.db
sudo cp /srv/serverhub/backups/<timestamp>/.env        /srv/serverhub/backend/.env
sudo chown -R serverhub:serverhub /srv/serverhub
sudo supervisorctl restart serverhub
```

To roll back **code**, check out the previous version in `/opt/serverhub-src`
(`git checkout <previous-commit>` or re-upload the old folders) and run
`sudo bash deploy/update.sh` again.

---

## 10. Cheat sheet

```bash
# Standard update (code already uploaded or it'll git pull):
cd /opt/serverhub-src && sudo bash deploy/update.sh

# Backend-only (fast, no UI rebuild):
sudo bash deploy/update.sh --backend-only

# Frontend-only:
sudo bash deploy/update.sh --frontend-only

# Just changed .env:
sudo nano /srv/serverhub/backend/.env && sudo supervisorctl restart serverhub

# Upload from Windows first (local machine):
scp -r backend frontend root@YOUR_SERVER_IP:/opt/serverhub-src/

# Health check:
curl http://127.0.0.1:8765/api/health
```

That's the whole update workflow: **upload → `update.sh` → hard-refresh**.
