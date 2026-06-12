# ServerHub — Full Deployment Guide (Ubuntu VPS)

This is the complete, step-by-step guide to install and run ServerHub on a
fresh Ubuntu server. It covers two paths:

- **Path A — Automated** (recommended): one script does everything.
- **Path B — Manual**: every command spelled out, so you understand and can
  fix each piece.

It also covers DNS, SSL, day-to-day management, updates, and troubleshooting.

> **What you end up with:** ServerHub running as a background service on
> `127.0.0.1:8765`, reverse-proxied by Nginx on your domain
> (e.g. `https://panel.yourdomain.com`), with a single admin login.

---

## 0. Before you start — what you need

| Requirement | Details |
|---|---|
| A VPS | Ubuntu **22.04 or 24.04 LTS**, 1 vCPU / 1 GB RAM minimum (2 GB+ recommended if you run Streamlit dashboards). Providers: Hetzner, DigitalOcean, Linode, Contabo, AWS Lightsail, etc. |
| Root / sudo access | You log in as `root` or a user with `sudo`. |
| A domain name | e.g. `yourdomain.com`. You'll point a subdomain like `panel.yourdomain.com` at the server. (Optional but strongly recommended — needed for SSL.) |
| SSH access | You can connect: `ssh root@YOUR_SERVER_IP` |
| The project files | This repository, uploaded to the server (covered in Step 2). |

**Check your Ubuntu version** once connected:

```bash
lsb_release -a
```

---

## 1. First-time server hardening (do this once)

Skip if your VPS provider already set this up, but it's worth doing.

```bash
# Update everything
sudo apt update && sudo apt upgrade -y

# Set the timezone (so schedules & logs match your clock)
sudo timedatectl set-timezone Asia/Karachi   # change to your timezone

# Create a non-root sudo user (optional but recommended)
sudo adduser ali
sudo usermod -aG sudo ali
# From now on you can: ssh ali@YOUR_SERVER_IP
```

### Firewall (UFW)

Only expose SSH, HTTP, and HTTPS. The panel itself stays on localhost.

```bash
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

> ⚠️ Do **not** open port `8765` (the panel) or `8501+` (Streamlit dashboards)
> to the internet. Nginx proxies to them internally. Opening them would bypass
> your login and SSL.

---

## 2. Get the project onto the server

Pick whichever you prefer.

### Option 1 — Git (if your code is in a repo)

```bash
sudo apt install -y git
cd /opt
sudo git clone <YOUR_REPO_URL> serverhub-src
cd serverhub-src
```

### Option 2 — Upload from your Windows machine with SCP

Run this **on your local Windows machine** (PowerShell), from the folder that
contains `backend/`, `frontend/`, and `deploy/`:

```powershell
# Zip it (excluding heavy/build folders) then copy up
scp -r "backend" "frontend" "deploy" "README.md" "DEPLOYMENT.md" root@YOUR_SERVER_IP:/opt/serverhub-src/
```

Or use **WinSCP** / **FileZilla** (drag-and-drop) into `/opt/serverhub-src/`.

> After this step you should have the project at `/opt/serverhub-src/` on the
> server, containing `backend/`, `frontend/`, and `deploy/`.

---

## Path A — Automated install (recommended)

This is the fast path. The script in `deploy/install.sh` does **everything** in
Section "Path B" for you, and it's safe to re-run.

```bash
cd /opt/serverhub-src
sudo bash deploy/install.sh
```

### What the script does

1. Installs system packages: `python3`, `python3-venv`, `pip`, `nginx`,
   `supervisor`, `nodejs` (18+), `curl`.
2. Creates the `serverhub` system user and the directory layout under `/srv`.
3. Copies `backend/` and `frontend/` to `/srv/serverhub/`.
4. Creates a Python virtualenv and installs backend deps + `streamlit`.
5. Builds the React frontend (`npm install && npm run build`) into
   `backend/static/`.
6. Generates `backend/.env` with a fresh random `SECRET_KEY` and points
   `PYTHON_BIN` / `STREAMLIT_BIN` at the venv.
7. Sets file ownership to the `serverhub` user.
8. Installs the restricted **sudoers** rule (`supervisorctl` only).
9. Wires Supervisor to include panel-managed dashboard configs.
10. Registers the panel itself as a Supervisor service on port 8765.
11. Installs and reloads the Nginx site.

When it finishes it prints the next 3 manual steps. Continue at
**Step A.1** below.

### Step A.1 — Create your admin login

```bash
cd /srv/serverhub/backend
sudo -u serverhub /srv/serverhub/venv/bin/python setup_admin.py
# It will prompt for a username and password (min 8 chars).
```

Non-interactive alternative:

```bash
sudo -u serverhub /srv/serverhub/venv/bin/python setup_admin.py -u admin -p 'YourStrongPassw0rd!'
```

### Step A.2 — Point your domain at the server (DNS)

In your domain registrar / DNS provider, create an **A record**:

| Type | Name | Value |
|---|---|---|
| A | `panel` | `YOUR_SERVER_IP` |

This makes `panel.yourdomain.com` resolve to your server. DNS can take a few
minutes to propagate. Verify:

```bash
dig +short panel.yourdomain.com    # should print your server IP
```

### Step A.3 — Set your domain in Nginx

```bash
sudo nano /etc/nginx/sites-available/serverhub
```

Change this line:

```nginx
server_name panel.yourdomain.com;
```

to your real subdomain, save (`Ctrl+O`, `Enter`, `Ctrl+X`), then:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

You can now open `http://panel.yourdomain.com` and log in. Next, add SSL.

### Step A.4 — Enable HTTPS (Let's Encrypt / Certbot)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d panel.yourdomain.com
```

Follow the prompts (enter your email, agree to terms, choose **redirect HTTP→HTTPS**).
Certbot edits the Nginx config and sets up **auto-renewal**. Verify renewal works:

```bash
sudo certbot renew --dry-run
```

🎉 **Done.** Visit `https://panel.yourdomain.com` and log in.

---

## Path B — Manual install (step by step)

Use this if you want full control or the script failed partway. Every command
the automated script runs is here, explained.

### B.1 — Install system packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx supervisor curl
```

Install **Node.js 20** (needed to build the React frontend):

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version    # should be v20.x
```

### B.2 — Create the panel user and folders

The panel runs as a dedicated, unprivileged system user called `serverhub`.

```bash
sudo useradd --system --create-home --shell /bin/bash serverhub

sudo mkdir -p /srv/serverhub/db
sudo mkdir -p /srv/serverhub/supervisor.d     # panel-written dashboard configs
sudo mkdir -p /srv/projects                   # your Python workspaces live here
sudo mkdir -p /srv/websites                   # Phase 3
sudo mkdir -p /srv/nginx-configs              # Phase 3
sudo mkdir -p /var/log/supervisor
```

### B.3 — Copy the application code

```bash
sudo cp -r /opt/serverhub-src/backend  /srv/serverhub/
sudo cp -r /opt/serverhub-src/frontend /srv/serverhub/
```

### B.4 — Python virtualenv + dependencies

```bash
sudo python3 -m venv /srv/serverhub/venv
sudo /srv/serverhub/venv/bin/pip install --upgrade pip
sudo /srv/serverhub/venv/bin/pip install -r /srv/serverhub/backend/requirements.txt

# Streamlit is needed to run your project dashboards
sudo /srv/serverhub/venv/bin/pip install streamlit
```

### B.5 — Build the frontend

```bash
cd /srv/serverhub/frontend
sudo npm install
sudo npm run build       # outputs to ../backend/static/
```

(The FastAPI backend serves these static files directly — no separate web
process for the UI.)

### B.6 — Configure `backend/.env`

```bash
cd /srv/serverhub/backend
sudo cp .env.example .env
sudo nano .env
```

At minimum, set a strong random `SECRET_KEY`. Generate one:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Paste it into `SECRET_KEY=...`. Also point the interpreter at the venv so your
scripts and Streamlit use the right Python:

```ini
SECRET_KEY=<paste the 64-char hex here>
PYTHON_BIN=/srv/serverhub/venv/bin/python
STREAMLIT_BIN=/srv/serverhub/venv/bin/streamlit
```

The other defaults (paths under `/srv`, port 8765) are already correct.

### B.7 — Fix ownership

The `serverhub` user must own everything it reads/writes:

```bash
sudo chown -R serverhub:serverhub /srv/serverhub /srv/projects /srv/websites /srv/nginx-configs
sudo chown serverhub:serverhub /var/log/supervisor
```

### B.8 — Install the restricted sudoers rule

The panel needs to run `supervisorctl` (to start/stop dashboards) **without a
password**, but nothing else. This file grants exactly that:

```bash
sudo install -m 0440 /opt/serverhub-src/deploy/sudoers-serverhub /etc/sudoers.d/serverhub
sudo visudo -c        # validates; must say "parsed OK"
```

> Never edit files in `/etc/sudoers.d/` with a normal editor — a syntax error
> can lock you out of sudo. Always validate with `visudo -c`.

### B.9 — Let Supervisor include panel-managed dashboards

Each project's Streamlit dashboard gets its own Supervisor config written by the
panel into `/srv/serverhub/supervisor.d/`. Tell Supervisor to load them:

```bash
sudo nano /etc/supervisor/supervisord.conf
```

Find the `[include]` section near the bottom and add our directory to the
`files =` line, e.g.:

```ini
[include]
files = /etc/supervisor/conf.d/*.conf /srv/serverhub/supervisor.d/*.conf
```

### B.10 — Register the panel as a Supervisor service

```bash
# Substitute the install paths into the template
sudo sed "s|{PANEL_ROOT}|/srv/serverhub|g; s|{PANEL_USER}|serverhub|g" \
  /opt/serverhub-src/deploy/serverhub.supervisor.conf \
  | sudo tee /etc/supervisor/conf.d/serverhub.conf

sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status serverhub      # should show RUNNING
```

The panel is now listening on `127.0.0.1:8765`.

### B.11 — Create the admin user

```bash
cd /srv/serverhub/backend
sudo -u serverhub /srv/serverhub/venv/bin/python setup_admin.py
```

### B.12 — Nginx reverse proxy

```bash
sudo cp /opt/serverhub-src/deploy/nginx-panel.conf /etc/nginx/sites-available/serverhub
sudo nano /etc/nginx/sites-available/serverhub      # set server_name to your subdomain
sudo ln -sf /etc/nginx/sites-available/serverhub /etc/nginx/sites-enabled/serverhub

# (optional) remove the default site so it doesn't shadow yours
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t && sudo systemctl reload nginx
```

### B.13 — DNS + SSL

Same as **Step A.2 → A.4** above: create the `A` record, then run Certbot.

---

## 3. Verify the install

```bash
# 1. Panel process is up
sudo supervisorctl status serverhub
# serverhub   RUNNING   pid 1234, uptime 0:01:23

# 2. Backend answers locally
curl http://127.0.0.1:8765/api/health
# {"status":"ok"}

# 3. Nginx serves it on your domain
curl -I https://panel.yourdomain.com
# HTTP/2 200
```

Then open `https://panel.yourdomain.com` in your browser and log in with the
admin credentials you created.

### First smoke test inside the panel

1. Go to **Projects → New Project**, name it `demo`.
2. Open the project → **Files** tab → upload a small `.py` into `code/`,
   e.g. a file that prints something.
3. **Scripts** tab → **Run Now** → you should see live output stream in.
4. (Optional) Upload `dashboard/app.py` (a Streamlit app) → **Dashboard** tab →
   **Start** → status should go to RUNNING.

---

## 4. Day-to-day management

### Panel service control

```bash
sudo supervisorctl status serverhub      # check
sudo supervisorctl restart serverhub     # restart (after config/.env changes)
sudo supervisorctl stop serverhub        # stop
sudo supervisorctl start serverhub       # start
```

### Logs

```bash
# Panel application logs
sudo tail -f /var/log/supervisor/serverhub.out.log
sudo tail -f /var/log/supervisor/serverhub.err.log

# A project dashboard's logs (also viewable in the UI)
sudo tail -f /var/log/supervisor/<project>.out.log
sudo tail -f /var/log/supervisor/<project>.err.log

# Nginx
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### Reset / change the admin password

```bash
cd /srv/serverhub/backend
sudo -u serverhub /srv/serverhub/venv/bin/python setup_admin.py -u admin
# Re-running for an existing username just resets the password.
```

### Back up the panel database

Everything the panel knows (projects, scripts, users) is in one SQLite file:

```bash
sudo cp /srv/serverhub/db/serverhub.db ~/serverhub-backup-$(date +%F).db
```

Your actual project files live in `/srv/projects/` — back those up too
(e.g. with `tar` or `rsync`).

---

## 5. Updating to a new version

When you have new code (Phase 2, 3, fixes, etc.):

```bash
# 1. Get the new code onto the server (git pull or re-upload to /opt/serverhub-src)
cd /opt/serverhub-src
git pull          # or re-SCP the folders

# 2. Copy backend + frontend over
sudo cp -r backend  /srv/serverhub/
sudo cp -r frontend /srv/serverhub/

# 3. Update Python deps (in case requirements changed)
sudo /srv/serverhub/venv/bin/pip install -r /srv/serverhub/backend/requirements.txt

# 4. Rebuild the frontend
cd /srv/serverhub/frontend && sudo npm install && sudo npm run build

# 5. Fix ownership and restart
sudo chown -R serverhub:serverhub /srv/serverhub
sudo supervisorctl restart serverhub
```

> ⚠️ Don't overwrite `backend/.env` — it holds your `SECRET_KEY`. The commands
> above copy the whole `backend/` folder; if your repo has no `.env` (it
> shouldn't — it's gitignored), your existing one is preserved. If you copy a
> `.env` by accident, restore your `SECRET_KEY` or all users get logged out.

Re-running `sudo bash deploy/install.sh` also works as an update — it's
idempotent and skips `.env` if it already exists.

---

## 6. Troubleshooting

### Panel won't start (`supervisorctl status` shows FATAL/BACKOFF)

```bash
sudo tail -n 50 /var/log/supervisor/serverhub.err.log
```

Common causes:
- **Missing dependency** → re-run the `pip install -r requirements.txt` step.
- **Bad `.env`** (e.g. malformed line) → check `backend/.env`.
- **Port 8765 already in use** → `sudo lsof -i :8765` to find the culprit.

### "502 Bad Gateway" in the browser

Nginx is up but the panel isn't answering. Check the panel is running:

```bash
sudo supervisorctl status serverhub
curl http://127.0.0.1:8765/api/health
```

If the panel is down, see the section above.

### Login works but immediately logs me out

Usually a changed `SECRET_KEY` (existing tokens become invalid). Just log in
again. If it keeps happening, the panel may be restarting — check its logs.

### Dashboard "Start" fails with a supervisor error

```bash
# Confirm the sudoers rule is active
sudo -u serverhub sudo -n supervisorctl status
```

If that asks for a password, the sudoers file isn't installed correctly —
redo **Step B.8** and check `sudo visudo -c`.

Also confirm the project actually has `dashboard/app.py` uploaded — the panel
refuses to start a dashboard without it.

### Dashboard starts then crashes (FATAL)

Look at the dashboard's own log:

```bash
sudo tail -f /var/log/supervisor/<project>.err.log
```

Usually a missing Python package your Streamlit app imports. Install it into the
panel venv:

```bash
sudo /srv/serverhub/venv/bin/pip install <package>
```

### Certbot fails ("challenge failed" / can't reach domain)

- Make sure the DNS `A` record points at the server (`dig +short panel.yourdomain.com`).
- Make sure ports 80/443 are open in UFW **and** your provider's firewall.
- Make sure Nginx is running: `sudo systemctl status nginx`.

### File uploads fail for large files

Nginx caps body size. The provided config sets `client_max_body_size 200M;` —
raise it in `/etc/nginx/sites-available/serverhub` if you need bigger, then
`sudo nginx -t && sudo systemctl reload nginx`.

---

## 7. Reference — where everything lives

```
/srv/serverhub/                  Panel root
├── backend/                     FastAPI app
│   ├── .env                     ← your secrets & config (DO NOT share)
│   ├── app/                     application code
│   ├── static/                  built React frontend (served by FastAPI)
│   └── setup_admin.py           admin user creation
├── frontend/                    React source (only needed to rebuild)
├── venv/                        Python virtualenv
├── db/serverhub.db              panel database (SQLite)
└── supervisor.d/                auto-generated dashboard configs

/srv/projects/<name>/            your Python workspaces
├── code/  allscripts/  data/  dashboard/  logs/

/etc/supervisor/conf.d/serverhub.conf      panel service definition
/etc/nginx/sites-available/serverhub       reverse proxy config
/etc/sudoers.d/serverhub                   restricted sudo (supervisorctl only)
/var/log/supervisor/                       panel + dashboard logs
```

### Key facts

| Thing | Value |
|---|---|
| Panel internal port | `8765` (localhost only) |
| Streamlit dashboard ports | `8501+` (localhost only, one per project) |
| Runs as user | `serverhub` (unprivileged system user) |
| Process manager | Supervisor |
| Reverse proxy | Nginx |
| SSL | Let's Encrypt via Certbot (auto-renew) |
| Panel database | `/srv/serverhub/db/serverhub.db` |

---

## 8. Security checklist

- [ ] UFW enabled; only 22/80/443 open. Ports 8765 / 8501+ **not** exposed.
- [ ] Strong, unique admin password (8+ chars; longer is better).
- [ ] `SECRET_KEY` in `.env` is a fresh random value (never the example).
- [ ] HTTPS enabled via Certbot; HTTP redirects to HTTPS.
- [ ] `sudo visudo -c` passes; sudoers grants only `supervisorctl`.
- [ ] `.env` is readable only by the `serverhub` user / root.
- [ ] Regular backups of `serverhub.db` and `/srv/projects/`.
- [ ] Keep the OS patched: `sudo apt update && sudo apt upgrade -y`.

> ServerHub gives full control of your server to whoever logs in. Treat the
> admin password and `SECRET_KEY` like root credentials.

---

**Need the next phases?** Phase 2 adds the in-browser terminal, full live log
viewer, and the scheduler (APScheduler + cron builder). The sudoers file already
contains commented-out rules for the Nginx/Certbot (Phase 3) and APT (Phase 4)
features — uncomment them when those ship.
