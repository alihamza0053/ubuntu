# ServerHub — Complete Deployment Guide (Ubuntu VPS, zero to running)

This guide takes you from a **brand-new, empty Ubuntu server** to a fully
working ServerHub install with **every feature** enabled: Python project
workspaces, Streamlit dashboards, the in-browser terminal, live logs, the
scheduler, website hosting (React/PHP/HTML), MySQL management, the nginx
config manager, the APT package manager, the file manager, and SSL.

Nothing is assumed to be pre-installed. Every package, version check, and
config detail is spelled out.

It offers two routes:

- **Path A — Automated**: one script (`deploy/install.sh`) installs and wires
  everything. Best for most people.
- **Path B — Manual**: every command the script runs, explained one by one, so
  you understand each piece and can fix a partial install.

Read **Sections 0–2 first regardless of path** — they install the operating
system dependencies that both paths need.

---

## Table of contents

0. [What you need before starting](#0-what-you-need-before-starting)
1. [Connect to the server & first-time setup](#1-connect-to-the-server--first-time-setup)
2. [Install ALL system dependencies (from zero)](#2-install-all-system-dependencies-from-zero)
3. [Path A — Automated install](#3-path-a--automated-install)
4. [Path B — Manual install (every step)](#4-path-b--manual-install-every-step)
5. [DNS + SSL](#5-dns--ssl)
6. [Verify every feature works](#6-verify-every-feature-works)
7. [Day-to-day management](#7-day-to-day-management)
8. [Updating to a new version](#8-updating-to-a-new-version)
9. [Troubleshooting (per feature)](#9-troubleshooting-per-feature)
10. [Reference & security checklist](#10-reference--security-checklist)

---

## 0. What you need before starting

| Requirement | Details |
|---|---|
| A VPS | Ubuntu **22.04 LTS** or **24.04 LTS**. **2 GB RAM minimum** (the frontend build + MySQL + Chromium need headroom; with 1 GB you **must** add swap — see Step 1.5). 2+ vCPU and 20 GB disk recommended. |
| Root / sudo | You can log in as `root` or a user with `sudo`. |
| A domain | e.g. `yourdomain.com`. You'll point subdomains (like `panel.yourdomain.com`) at the server. Required for SSL. |
| SSH client | Built into Windows 10/11 (PowerShell), macOS, and Linux. |
| The project files | This repository (`backend/`, `frontend/`, `deploy/`), uploaded in Step 2.7. |

> **Ubuntu version note:** Ubuntu **24.04** ships Python 3.12 (perfect — no extra
> work). Ubuntu **22.04** ships Python 3.10; ServerHub wants **3.11+**, so on
> 22.04 you'll add the `deadsnakes` PPA in Step 2.1. Both are covered.

---

## 1. Connect to the server & first-time setup

### 1.1 — Connect over SSH

From your **local machine** (Windows PowerShell, macOS Terminal, or Linux):

```bash
ssh root@YOUR_SERVER_IP
```

Replace `YOUR_SERVER_IP` with the IP your provider gave you (e.g. `203.0.113.10`).
The first time, type `yes` to accept the host key. Enter the password (or it
uses your SSH key if your provider installed one).

> **Tip — passwordless SSH key (recommended).** On your local machine:
> ```bash
> ssh-keygen -t ed25519           # press Enter through the prompts
> ssh-copy-id root@YOUR_SERVER_IP # copies your key (Linux/macOS)
> ```
> On Windows without `ssh-copy-id`, copy the contents of
> `C:\Users\YOU\.ssh\id_ed25519.pub` into `~/.ssh/authorized_keys` on the server.

### 1.2 — Update the OS

```bash
sudo apt update && sudo apt upgrade -y
```

If it says a reboot is required:

```bash
sudo reboot
# wait ~30s, then reconnect: ssh root@YOUR_SERVER_IP
```

### 1.3 — Set the timezone

So schedules and log timestamps match your clock:

```bash
sudo timedatectl set-timezone Asia/Karachi    # change to your timezone
timedatectl                                   # verify
```

(List zones with `timedatectl list-timezones | grep -i <city>`.)

### 1.4 — (Recommended) Create a non-root sudo user

Working as root all the time is risky. Create a personal user:

```bash
sudo adduser ali                 # set a password when prompted
sudo usermod -aG sudo ali        # grant sudo
# Optional: copy your SSH key so you can log in as this user
sudo rsync --archive --chown=ali:ali ~/.ssh /home/ali
```

From now on you can `ssh ali@YOUR_SERVER_IP` and prefix commands with `sudo`.
(The rest of this guide uses `sudo` everywhere, so it works either way.)

### 1.5 — Add swap (REQUIRED on 1 GB RAM, recommended on 2 GB)

The Vite/Monaco frontend build and MySQL can exhaust a small server's RAM and
get killed (you'd see `Killed` mid-build). A 2 GB swap file prevents this:

```bash
# Skip if `free -h` already shows a Swap line with size > 0
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab   # persist across reboots
free -h                                                       # confirm Swap now shows 2.0Gi
```

### 1.6 — Firewall (UFW)

Expose only SSH, HTTP, and HTTPS. The panel and dashboards stay on localhost.

```bash
sudo apt install -y ufw
sudo ufw allow OpenSSH        # don't lock yourself out
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
sudo ufw status verbose
```

> ⚠️ **Never** open ports `8765` (panel) or `8501+` (Streamlit dashboards) to the
> internet. Nginx proxies to them internally over localhost. Exposing them would
> bypass your login and SSL. Also check your VPS provider's **cloud firewall**
> (DigitalOcean/AWS/etc.) allows 22/80/443.

---

## 2. Install ALL system dependencies (from zero)

This section installs every piece of software ServerHub uses. Do it on both
the automated and manual paths (the automated `install.sh` also runs most of
this, but doing it explicitly first lets you verify each piece).

### 2.1 — Python 3.11+ (interpreter, venv, pip, build tools)

**On Ubuntu 24.04** (already has Python 3.12):

```bash
sudo apt install -y python3 python3-venv python3-pip python3-dev build-essential
python3 --version    # expect 3.12.x
```

**On Ubuntu 22.04** (ships 3.10 — add deadsnakes for 3.11):

```bash
sudo apt install -y software-properties-common build-essential
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev python3-pip
python3.11 --version    # expect 3.11.x
```

> On 22.04, wherever this guide says `python3`, use **`python3.11`** instead
> when creating the panel's virtualenv (Step 4.4 / install.sh handles this if
> you set `PYTHON3=python3.11`). The venv then uses 3.11 regardless of the
> system default.

Why these packages:
- `python3`/`python3.11` — the interpreter
- `python3-venv` — to create the isolated virtualenv
- `python3-pip` — installs Python packages
- `python3-dev` + `build-essential` — compile C extensions (bcrypt, etc.)

### 2.2 — Node.js 20 (to build the React frontend)

Ubuntu's default Node is too old. Install Node 20 from NodeSource:

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node --version    # expect v20.x
npm --version     # expect 10.x
```

### 2.3 — Nginx (reverse proxy + website hosting)

```bash
sudo apt install -y nginx
sudo systemctl enable --now nginx
systemctl status nginx --no-pager    # should be active (running)
```

Visiting `http://YOUR_SERVER_IP` now shows the default nginx page — good.

### 2.4 — Supervisor (process manager for the panel + dashboards)

```bash
sudo apt install -y supervisor
sudo systemctl enable --now supervisor
supervisorctl version    # prints a version number
```

### 2.5 — MySQL server (Databases manager)

```bash
sudo apt install -y mysql-server
sudo systemctl enable --now mysql
```

**Secure it** (sets sensible defaults; takes ~30s):

```bash
sudo mysql_secure_installation
```

Answer roughly:
- VALIDATE PASSWORD component: **N** (or Y if you want strict password rules)
- Remove anonymous users: **Y**
- Disallow root login remotely: **Y**
- Remove test database: **Y**
- Reload privilege tables: **Y**

> **Important — how the panel talks to MySQL.** ServerHub runs MySQL commands as
> `sudo mysql`, relying on MySQL's default **`auth_socket`** authentication for
> the `root` user (no password needed when running as the OS root via sudo).
> **Do not** switch the MySQL `root` account to password auth — if you do,
> `sudo mysql` will prompt and the Databases page will fail. Leaving root on
> `auth_socket` (the default) is both secure and what the panel expects.

Verify it works the way the panel will use it:

```bash
sudo mysql -e "SHOW DATABASES;"    # should list databases without asking a password
```

### 2.6 — PHP-FPM (for PHP websites) — and the version gotcha

```bash
sudo apt install -y php-fpm
# Find which PHP version got installed and its FPM socket:
ls /run/php/
# e.g. on 24.04 → php8.3-fpm.sock ; on 22.04 → php8.1-fpm.sock
php -v
```

> ⚠️ **PHP socket version must match the nginx template.** ServerHub's generated
> PHP site config points at `unix:/var/run/php/php8.1-fpm.sock`. If your server
> installed a **different** version (e.g. `php8.3` on Ubuntu 24.04), you have two
> options:
>
> **Option 1 (simplest):** install PHP 8.1 explicitly so the socket matches:
> ```bash
> sudo add-apt-repository -y ppa:ondrej/php
> sudo apt update
> sudo apt install -y php8.3-fpm
> sudo systemctl enable --now php8.3-fpm
> ```
>
> **Option 2:** after you assign a domain to a PHP site in the panel, open
> **Nginx → Edit** on that config and change `php8.1-fpm.sock` to your actual
> version (e.g. `php8.3-fpm.sock`), then **Save** (it reloads nginx).
>
> If you only host React/HTML sites and Python projects, you can skip PHP-FPM
> entirely.

### 2.7 — Certbot (free SSL via Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx
certbot --version
```

### 2.8 — Google Chrome (headless Selenium for project scripts)

If your project scripts use Selenium, install a **real browser + driver**. Skip
this section entirely if none of your scripts do browser automation.

> ⚠️ **Use Google Chrome (.deb), NOT apt/snap `chromium`.** On Ubuntu 22.04 and
> 24.04 the apt `chromium-browser` / `chromium-chromedriver` are **snap wrappers**.
> The snap chromedriver **crashes when launched by the unprivileged `serverhub`
> service user** — you get:
> ```
> selenium...WebDriverException: Message: Service /usr/bin/chromedriver
> unexpectedly exited. Status code was: 1
> ```
> Snap Chromium also **cannot write downloads to `/srv/...`** (it's sandboxed),
> so download scripts silently fail. The Google Chrome `.deb` avoids both.

**Recommended — Google Chrome `.deb`:**

```bash
# Remove any snap chromium first (ignore errors if not present)
sudo snap remove chromium 2>/dev/null
sudo apt remove -y chromium-browser chromium-chromedriver 2>/dev/null

# Install real Google Chrome
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y ./google-chrome-stable_current_amd64.deb

# Verify
google-chrome --version       # e.g. "Google Chrome 1xx.x.x.x"
which google-chrome           # /usr/bin/google-chrome
```

You do **not** need to install a chromedriver: Selenium 4.6+ ("Selenium Manager",
bundled with the `selenium` pip package) auto-downloads the matching driver on
first run. Make sure the panel user can write its cache:

```bash
sudo mkdir -p /home/serverhub/.cache && sudo chown -R serverhub:serverhub /home/serverhub
```

> Your scripts should use the headless flags from `SCRIPTS_GUIDE.md`
> (`--headless=new --no-sandbox --disable-dev-shm-usage`) and set
> `options.binary_location = "/usr/bin/google-chrome"`. The included
> `P2P Custom.py` is a working template.

### 2.9 — Misc tools (zip handling, git, curl, rsync)

```bash
sudo apt install -y unzip git curl rsync
```

(`rsync` is used by the update workflow in `UPDATING.md`.)

### 2.10 — Upload the ServerHub source to the server

Pick one.

**Option 1 — Git** (if your code is in a repo):

```bash
cd /opt
sudo git clone https://github.com/alihamza0053/ubuntu.git serverhub-src
```

**Option 2 — SCP from your Windows/Mac machine.** Run **locally** from the folder
containing `backend/`, `frontend/`, `deploy/`:

```powershell
# Windows PowerShell / macOS Terminal
scp -r backend frontend deploy README.md DEPLOYMENT.md MASTER_BUILD_PROMPT.md `
  root@YOUR_SERVER_IP:/opt/serverhub-src/
```

(Or drag-and-drop the folders into `/opt/serverhub-src/` with **WinSCP** or
**FileZilla**.)

You should now have `/opt/serverhub-src/` containing `backend/`, `frontend/`,
and `deploy/`.

✅ **All system dependencies are installed.** Now choose Path A (automated) or
Path B (manual).

---

## 3. Path A — Automated install

The script does everything in Path B for you and is safe to re-run.

```bash
cd /opt/serverhub-src

# On Ubuntu 22.04, tell it to build the venv with Python 3.11:
sudo PYTHON3=python3.11 bash deploy/install.sh
# On Ubuntu 24.04, just:
sudo bash deploy/install.sh
```

### What the script does

1. Installs system packages (re-confirms everything from Section 2, incl. MySQL,
   PHP-FPM, Certbot, Chromium).
2. Creates the unprivileged `serverhub` system user and the `/srv` layout.
3. Copies `backend/` and `frontend/` to `/srv/serverhub/`.
4. Creates the Python virtualenv and installs backend deps + `streamlit`,
   `selenium`, `webdriver-manager`, `pandas`, `openpyxl`.
5. Builds the React frontend into `backend/static/`.
6. Generates `backend/.env` with a fresh random `SECRET_KEY`, pointing
   `PYTHON_BIN`/`STREAMLIT_BIN` at the venv.
7. Sets ownership to `serverhub`.
8. Installs the restricted **sudoers** file (supervisorctl, nginx, certbot, apt,
   mysql — see Step 4.8).
9. Wires Supervisor to include panel-managed dashboard configs.
10. Registers the panel itself as a Supervisor service on port 8765.
11. Installs and reloads the nginx site.

When it finishes it prints the next manual steps. Continue at:

- **Step 3.1** — create the admin user
- **Section 5** — DNS + SSL

### Step 3.1 — Create your admin login

```bash
cd /srv/serverhub/backend
sudo -u serverhub /srv/serverhub/venv/bin/python setup_admin.py
# prompts for username + password (min 8 chars)
```

Non-interactive:

```bash
sudo -u serverhub /srv/serverhub/venv/bin/python setup_admin.py -u admin -p 'YourStrongPassw0rd!'
```

Now jump to **[Section 5 — DNS + SSL](#5-dns--ssl)**.

---

## 4. Path B — Manual install (every step)

Every command the script runs, explained. (Section 2 dependencies must already
be installed.)

### 4.1 — Create the panel user and folders

```bash
sudo useradd --system --create-home --shell /bin/bash serverhub

sudo mkdir -p /srv/serverhub/db
sudo mkdir -p /srv/serverhub/supervisor.d     # panel-written dashboard configs
sudo mkdir -p /srv/projects                   # Python workspaces
sudo mkdir -p /srv/websites                   # websites
sudo mkdir -p /srv/nginx-configs              # panel-generated nginx blocks
sudo mkdir -p /var/log/supervisor
```

### 4.2 — Copy the application code

```bash
sudo cp -r /opt/serverhub-src/backend  /srv/serverhub/
sudo cp -r /opt/serverhub-src/frontend /srv/serverhub/
```

### 4.3 — Create the Python virtualenv

**Ubuntu 24.04:**
```bash
sudo python3 -m venv /srv/serverhub/venv
```
**Ubuntu 22.04 (use 3.11):**
```bash
sudo python3.11 -m venv /srv/serverhub/venv
```

### 4.4 — Install Python dependencies

```bash
sudo /srv/serverhub/venv/bin/pip install --upgrade pip
sudo /srv/serverhub/venv/bin/pip install -r /srv/serverhub/backend/requirements.txt

# Runtimes for project dashboards + common script needs:
sudo /srv/serverhub/venv/bin/pip install streamlit selenium webdriver-manager pandas openpyxl
```

`requirements.txt` installs: fastapi, uvicorn, sqlalchemy, python-jose,
bcrypt, python-multipart, python-dotenv, aiofiles, psutil, APScheduler,
websockets.

### 4.5 — Build the frontend

```bash
cd /srv/serverhub/frontend
sudo npm install
sudo npm run build       # outputs to ../backend/static/
```

(If `npm run build` is `Killed`, you ran out of RAM — add swap, Step 1.5.)

### 4.6 — Configure `backend/.env`

```bash
cd /srv/serverhub/backend
sudo cp .env.example .env
```

Generate a secret and edit:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"   # copy the output
sudo nano .env
```
455070ea33cfdee75676cf8885b5d85416bd712ed07996c1c693b489a54fcc11
Set at least:

```ini
SECRET_KEY=<paste the 64-char hex here>
PYTHON_BIN=/srv/serverhub/venv/bin/python
STREAMLIT_BIN=/srv/serverhub/venv/bin/streamlit
```

The remaining defaults (paths under `/srv`, port 8765, supervisor dir, MySQL via
sudo) are already correct. Save with `Ctrl+O`, `Enter`, `Ctrl+X`.

### 4.7 — Fix ownership

```bash
sudo chown -R serverhub:serverhub /srv/serverhub /srv/projects /srv/websites /srv/nginx-configs
sudo chown serverhub:serverhub /var/log/supervisor
```

### 4.8 — Install the restricted sudoers rule

The panel runs as the unprivileged `serverhub` user but needs to run a few
specific privileged commands **without a password**: `supervisorctl`, `nginx -t`,
`systemctl reload nginx`, `certbot`, the symlink/rm for nginx sites, the specific
`apt-get` actions, and `mysql`/`mysqldump`. The provided file grants exactly
those and nothing else:

```bash
sudo install -m 0440 /opt/serverhub-src/deploy/sudoers-serverhub /etc/sudoers.d/serverhub
sudo visudo -c        # MUST print ".../serverhub: parsed OK"
```

> ⚠️ Never edit files in `/etc/sudoers.d/` with a plain editor — a syntax error
> can lock you out of sudo. Always validate with `visudo -c`.

### 4.9 — Let Supervisor include panel-managed dashboards

Each Streamlit dashboard gets a Supervisor config written by the panel into
`/srv/serverhub/supervisor.d/`. Tell Supervisor to load that directory:

```bash
sudo nano /etc/supervisor/supervisord.conf
```

Find the `[include]` section at the bottom and ensure the `files =` line
includes our directory:

```ini
[include]
files = /etc/supervisor/conf.d/*.conf /srv/serverhub/supervisor.d/*.conf
```

### 4.10 — Register the panel as a Supervisor service

```bash
sudo sed "s|{PANEL_ROOT}|/srv/serverhub|g; s|{PANEL_USER}|serverhub|g" \
  /opt/serverhub-src/deploy/serverhub.supervisor.conf \
  | sudo tee /etc/supervisor/conf.d/serverhub.conf

sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status serverhub      # expect RUNNING
```

The panel now listens on `127.0.0.1:8765`.

### 4.11 — Create the admin user

```bash
cd /srv/serverhub/backend
sudo -u serverhub /srv/serverhub/venv/bin/python setup_admin.py
```

### 4.12 — Nginx reverse proxy for the panel

```bash
sudo cp /opt/serverhub-src/deploy/nginx-panel.conf /etc/nginx/sites-available/serverhub
sudo nano /etc/nginx/sites-available/serverhub     # set server_name to your subdomain
sudo ln -sf /etc/nginx/sites-available/serverhub /etc/nginx/sites-enabled/serverhub

# Optional: drop the default site so it doesn't shadow yours
sudo rm -f /etc/nginx/sites-enabled/default

sudo nginx -t && sudo systemctl reload nginx
```

Continue to DNS + SSL.

---

## 5. DNS + SSL

### 5.1 — Point your domain at the server (DNS)

At your domain registrar / DNS host, create an **A record**:

| Type | Name | Value |
|---|---|---|
| A | `panel` | `YOUR_SERVER_IP` |

This makes `panel.yourdomain.com` resolve to your server. (Create more A records
later for each website/dashboard domain you assign, e.g. `app`, `shop`, etc.)

Verify (may take a few minutes to propagate):

```bash
dig +short panel.yourdomain.com     # should print YOUR_SERVER_IP
```

### 5.2 — Set the panel domain in nginx (if you didn't already)

```bash
sudo nano /etc/nginx/sites-available/serverhub   # server_name panel.yourdomain.com;
sudo nginx -t && sudo systemctl reload nginx
```

Open `http://panel.yourdomain.com` — you should see the ServerHub login.

### 5.3 — Enable HTTPS

```bash
sudo certbot --nginx -d panel.yourdomain.com
```

Enter your email, agree to the terms, and choose **redirect HTTP→HTTPS**.
Certbot edits the nginx config and sets up auto-renewal. Test renewal:

```bash
sudo certbot renew --dry-run
```

🎉 Visit `https://panel.yourdomain.com` and log in.

> **SSL for dashboards/websites** is done from inside the panel: assign a domain
> (creates the nginx block), then click **Request SSL** (runs certbot for that
> domain). The DNS A record for that domain must exist first.

---

## 6. Verify every feature works

Log in, then walk through each area. This confirms all dependencies are wired.

| Feature | Test | Expected |
|---|---|---|
| **Server stats** | Open Dashboard | CPU/RAM/Disk/Uptime widgets populate |
| **Projects** | Projects → New Project `demo` | Folders created; card appears |
| **File upload** | Project → Files → upload a `.py` to `code/` | File listed |
| **Code editor** | Click the `.py` → edit → Ctrl+S | "Saved ✓" |
| **Script run** | Scripts tab → Run Now | Live output streams; status SUCCESS |
| **Streamlit** | Upload `dashboard/app.py` → Dashboard → Start | Status RUNNING; live URL opens |
| **Scheduler** | Scheduler tab → build a cron → Add | Schedule listed with next-run time |
| **Terminal** | Terminal page | A real shell prompt; run `ls`, `htop`, `pip --version` |
| **Logs** | Logs page → pick a source → Live | Lines stream; search + download work |
| **Files** | Files page → browse `/srv` | Navigate, upload, rename, edit |
| **Websites** | Websites → New → upload a `.zip` | Files extract; assign domain works |
| **MySQL** | Databases → New Database | Appears in list; query runner returns rows |
| **Nginx** | Assign a domain to a project | Config appears under Nginx page |
| **APT** | Server page → search a package → install | Live install log streams |
| **Supervisor** | Server page | Programs listed; start/stop/restart work |
| **Settings** | Settings → change password / backup DB | Works; DB downloads |

Quick command-line sanity checks:

```bash
sudo supervisorctl status serverhub        # RUNNING
curl http://127.0.0.1:8765/api/health      # {"status":"ok"}
curl -I https://panel.yourdomain.com       # HTTP/2 200
sudo -u serverhub sudo -n supervisorctl status   # no password prompt
sudo -u serverhub sudo -n mysql -e "SELECT 1;"   # no password prompt → MySQL OK
```

---

## 7. Day-to-day management

### Panel service control

```bash
sudo supervisorctl status serverhub      # check
sudo supervisorctl restart serverhub     # after editing .env or backend code
sudo supervisorctl stop serverhub
sudo supervisorctl start serverhub
```

### Logs

```bash
# Panel itself
sudo tail -f /var/log/supervisor/serverhub.out.log
sudo tail -f /var/log/supervisor/serverhub.err.log

# A project dashboard (also in the UI: Logs page / Dashboard tab)
sudo tail -f /var/log/supervisor/<project>.out.log
sudo tail -f /var/log/supervisor/<project>.err.log

# Nginx
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### Change the admin password

Either in the UI (**Settings → Change Password**) or from the CLI:

```bash
cd /srv/serverhub/backend
sudo -u serverhub /srv/serverhub/venv/bin/python setup_admin.py -u admin
# re-running for an existing user just resets the password
```

### Backups

```bash
# Panel database (projects, scripts, websites, schedules, users, settings)
sudo cp /srv/serverhub/db/serverhub.db ~/serverhub-backup-$(date +%F).db
# Or from the UI: Settings → Download database backup

# Your project files and websites
sudo tar czf ~/srv-backup-$(date +%F).tar.gz /srv/projects /srv/websites

# A specific MySQL database (or use the UI Export button)
sudo mysqldump --databases mydb > ~/mydb-$(date +%F).sql
```

### Install a package your script/dashboard needs

```bash
sudo /srv/serverhub/venv/bin/pip install <package>
sudo supervisorctl restart <project>_dashboard   # if a dashboard needs it
```

---

## 8. Updating to a new version

> For the full update workflow (uploading changes from your machine, the
> one-command `deploy/update.sh`, backend-only vs frontend-only, and rollback),
> see **`UPDATING.md`**. The short version is below.

```bash
# Easiest: one command (backs up .env + db, rebuilds, restarts, health-checks)
cd /opt/serverhub-src && sudo bash deploy/update.sh
```

Or do it by hand:

```bash
# 1. Get the new code
cd /opt/serverhub-src && git pull         # or re-SCP the folders

# 2. Copy backend + frontend
sudo cp -r backend  /srv/serverhub/
sudo cp -r frontend /srv/serverhub/

# 3. Update Python deps
sudo /srv/serverhub/venv/bin/pip install -r /srv/serverhub/backend/requirements.txt

# 4. Rebuild the frontend
cd /srv/serverhub/frontend && sudo npm install && sudo npm run build

# 5. Re-fix ownership and restart
sudo chown -R serverhub:serverhub /srv/serverhub
sudo supervisorctl restart serverhub
```

> ⚠️ Don't overwrite `backend/.env` — it holds your `SECRET_KEY`. It's gitignored,
> so a copy won't include one; but if you accidentally clobber it, restore your
> `SECRET_KEY` or every session is logged out.

Re-running `sudo bash deploy/install.sh` also works as an update — it's
idempotent and preserves an existing `.env`.

---

## 9. Troubleshooting (per feature)

### Panel won't start (supervisor shows FATAL/BACKOFF)

```bash
sudo tail -n 60 /var/log/supervisor/serverhub.err.log
```

- **ModuleNotFoundError** → `sudo /srv/serverhub/venv/bin/pip install -r /srv/serverhub/backend/requirements.txt`
- **Bad `.env`** (malformed line) → fix `backend/.env`
- **Port 8765 in use** → `sudo lsof -i :8765`

### 502 Bad Gateway

Nginx is up but the panel isn't answering:

```bash
sudo supervisorctl status serverhub
curl http://127.0.0.1:8765/api/health
```

### Logged out immediately after login

Usually `SECRET_KEY` changed (old tokens invalid). Log in again. If it repeats,
the panel is restart-looping — check its err log.

### Terminal page won't connect / "PTY only on Linux"

- The PTY needs Linux (your VPS) — it cannot run on a Windows dev box.
- Check the panel is healthy and that nginx forwards WebSockets (the provided
  `nginx-panel.conf` sets the `Upgrade`/`Connection` headers — don't remove them).

### Dashboard "Start" fails

```bash
sudo -u serverhub sudo -n supervisorctl status   # must NOT prompt for a password
```
If it prompts, the sudoers file is wrong — redo Step 4.8 (`visudo -c`).
Also ensure the project has `dashboard/app.py` uploaded.

### Dashboard starts then crashes (FATAL)

```bash
sudo tail -f /var/log/supervisor/<project>.err.log
```
Usually a missing import → install it into the venv (see Section 7).

### Databases page errors / "mysql client not installed" / password prompt

- Confirm MySQL is running: `systemctl status mysql`.
- Confirm sudo socket auth: `sudo -u serverhub sudo -n mysql -e "SELECT 1;"`
  must return without a password. If it prompts, MySQL root was switched off
  `auth_socket` — revert it, or the panel can't manage databases.
- Confirm the sudoers file includes the `mysql`/`mysqldump` lines (Step 4.8).

### PHP website shows "502" or downloads the .php file

The PHP-FPM socket version in the generated nginx config doesn't match your
installed PHP. Fix per Step 2.6 (install `php8.1-fpm`, **or** edit the site's
config on the **Nginx** page to your actual `phpX.Y-fpm.sock`).

### APT install in the panel does nothing / permission denied

The sudoers file must include the `apt-get` lines (Step 4.8). Validate with
`sudo visudo -c`. Some packages prompt interactively — the panel uses `-y`, but a
few configs still pause; run those from the **Terminal** page instead.

### Certbot fails ("challenge failed")

- DNS A record must point at the server: `dig +short the.domain.com`.
- Ports 80/443 open in UFW **and** the provider firewall.
- Nginx running: `sudo systemctl status nginx`.

### Website "npm build" (React) fails or is Killed

Out of memory — add swap (Step 1.5). Or build locally and upload the `dist/`
inside your zip, then assign the domain without rebuilding.

### File uploads fail for large files

Raise `client_max_body_size` in `/etc/nginx/sites-available/serverhub`
(default `200M`), then `sudo nginx -t && sudo systemctl reload nginx`.

---

## 10. Reference & security checklist

### Where everything lives

```
/srv/serverhub/                  Panel root
├── backend/
│   ├── .env                     ← secrets & config (DO NOT share)
│   ├── app/                     FastAPI application code
│   ├── static/                  built React frontend (served by FastAPI)
│   └── setup_admin.py           admin user creation
├── frontend/                    React source (only needed to rebuild)
├── venv/                        Python virtualenv
├── db/serverhub.db              panel database (SQLite)
└── supervisor.d/                auto-generated dashboard configs

/srv/projects/<name>/            Python workspaces: code/ allscripts/ data/ dashboard/ logs/
/srv/websites/<name>/            deployed sites (React dist/, PHP, or static HTML)
/srv/nginx-configs/              panel-generated nginx blocks (symlinked into sites-enabled)

/etc/supervisor/conf.d/serverhub.conf      panel service definition
/etc/supervisor/supervisord.conf           includes /srv/serverhub/supervisor.d/*.conf
/etc/nginx/sites-available/serverhub        panel reverse-proxy config
/etc/sudoers.d/serverhub                    restricted sudo rules
/var/log/supervisor/                        panel + dashboard logs
```

### Key facts

| Thing | Value |
|---|---|
| Panel internal port | `8765` (localhost only) |
| Streamlit dashboard ports | `8501+` (localhost only, one per project) |
| Runs as user | `serverhub` (unprivileged system user) |
| Process manager | Supervisor |
| Reverse proxy | Nginx |
| Databases | MySQL (root via `auth_socket`, used through `sudo`) |
| PHP | PHP-FPM (match the socket version!) |
| SSL | Let's Encrypt via Certbot (auto-renew) |
| Panel database | `/srv/serverhub/db/serverhub.db` |

### Privileged commands the panel may run (via sudoers)

`supervisorctl *`, `nginx -t`, `systemctl reload nginx`,
`ln -sf /srv/nginx-configs/* /etc/nginx/sites-enabled/*`,
`rm -f /etc/nginx/sites-enabled/*`, `certbot *`,
`apt-get update|upgrade|install|remove`, `mysql *`, `mysqldump *`.
**Nothing else** runs as root.

### Security checklist

- [ ] UFW enabled; only 22/80/443 open. Ports 8765 / 8501+ **not** exposed.
- [ ] Provider cloud firewall also limited to 22/80/443.
- [ ] Strong, unique admin password (8+ chars).
- [ ] `SECRET_KEY` in `.env` is a fresh random value (never the example).
- [ ] HTTPS enabled via Certbot; HTTP redirects to HTTPS.
- [ ] `sudo visudo -c` passes; sudoers grants only the commands listed above.
- [ ] MySQL root stays on `auth_socket` (no remote root, no test DB).
- [ ] `.env` readable only by `serverhub`/root (`sudo chmod 600 /srv/serverhub/backend/.env`).
- [ ] Regular backups of `serverhub.db`, `/srv/projects`, `/srv/websites`, and MySQL dumps.
- [ ] OS patched: `sudo apt update && sudo apt upgrade -y` (and reboot when kernel updates).
- [ ] Swap configured on small servers so builds/MySQL don't OOM.

> ServerHub gives full control of your server (terminal, file system, packages,
> databases) to whoever logs in. Treat the admin password and `SECRET_KEY` like
> root credentials. Keep the panel behind HTTPS on its own subdomain.

---

**That's the whole thing — from an empty Ubuntu server to every ServerHub
feature running.** If a feature misbehaves, find it in Section 9; almost every
issue is a missing dependency, an ownership/permission gap, or the PHP/MySQL
auth details above.
