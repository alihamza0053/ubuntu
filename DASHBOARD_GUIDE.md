# Running Streamlit Dashboards on ServerHub

How to deploy a Streamlit dashboard (`app.py`) on the panel, and how to fix
every issue that commonly comes up. This is the runbook — keep it handy.

> **Golden rule:** every dashboard gets its **own virtualenv** at
> `/srv/projects/<name>/venv`. Do **not** run dashboards from the panel's shared
> venv (`/srv/serverhub/venv`) — Streamlit's dependencies conflict with the
> panel's FastAPI and it won't start.

---

## 1. Deploy a dashboard in 4 steps

```bash
# 1. Create the project in the panel UI (e.g. "operations").
#    This makes /srv/projects/operations/ with code/ dashboard/ data/ etc.

# 2. Upload app.py to the project's "dashboard" folder (Dashboard/Files tab).
#    The Streamlit entry file MUST be named app.py.

# 3. Create the dashboard's virtualenv with all common deps (incl. xlrd):
sudo bash /opt/serverhub-src/deploy/dashboard-venv.sh operations
#    Need extra libraries? Append them:
#    sudo bash deploy/dashboard-venv.sh operations seaborn scikit-learn

# 4. In the panel: project → Dashboard tab → Start.
#    The panel auto-points supervisor at the project venv. Done.
```

That's it. The panel regenerates the supervisor config on **Start**, so it
always uses the project venv if one exists — no manual config editing.

---

## 2. How it works (so you can reason about problems)

- Each dashboard runs as a **Supervisor program** `<name>_dashboard`, defined in
  `/srv/serverhub/supervisor.d/<name>_dashboard.conf`.
- The panel writes that config when you **create** the project and **every time
  you click Start**. It chooses the Streamlit binary like this:
  - if `/srv/projects/<name>/venv/bin/streamlit` exists → use it (per-project)
  - else → fall back to the panel's global `STREAMLIT_BIN`
- So the correct workflow is: create project → make the venv → Start.
- Data files live in `/srv/projects/<name>/data/`. Your `app.py` should read
  from there (use an absolute path or a `DATA_DIR` env var).

---

## 3. Data files & paths

- Put every Excel/CSV the dashboard reads in **`/srv/projects/<name>/data/`**
  (upload via the Data Files tab).
- In `app.py`, never use Windows paths. Use:
  ```python
  import os
  DATA_DIR = os.getenv("DATA_DIR", "/srv/projects/operations/data")
  CTS_FILE = os.path.join(DATA_DIR, "MG_Apparel_Order_Closing_Report.xls")
  ```
- Scripts that download reports must save into that same `data/` folder with the
  **exact filename** the dashboard expects.

---

## 4. Troubleshooting (every issue, with the fix)

### `supervisorctl start: <name>_dashboard: ERROR (spawn error)`

Supervisor couldn't launch the command. Find the exact reason:

```bash
sudo tail -n 30 /var/log/supervisor/supervisord.log
```

Then run the app by hand to see the real Python error (bypasses Supervisor):

```bash
cd /srv/projects/<name>/dashboard
/srv/projects/<name>/venv/bin/streamlit run app.py --server.port 8599 --server.headless true
```

Common causes & fixes:
| Reason in log | Fix |
|---|---|
| `can't find command 'streamlit'` | No project venv yet → run `deploy/dashboard-venv.sh <name>`, then Start again. |
| Config still points at `/srv/serverhub/venv/...` | Click **Start** in the panel (it regenerates the config), or `sudo supervisorctl reread && sudo supervisorctl update`. |
| `couldn't chdir ... ENOENT` | The `dashboard/` folder or `app.py` is missing — upload `app.py`. |

### `ImportError: cannot import name 'DEFAULT_EXCLUDED_CONTENT_TYPES' from 'starlette...'`

Streamlit/Starlette conflict — you're running the dashboard from the **shared
panel venv**. Create a project venv and Start again:

```bash
sudo bash /opt/serverhub-src/deploy/dashboard-venv.sh <name>
# panel → Dashboard → Start
```

### A panel shows blank / zeros, but the file is there

Almost always a **missing read engine** swallowed by a bare `except`:
- **`.xls` files need `xlrd`** (openpyxl only reads `.xlsx`). The
  `dashboard-venv.sh` script installs `xlrd`; if you built the venv by hand:
  ```bash
  /srv/projects/<name>/venv/bin/pip install xlrd
  sudo supervisorctl restart <name>_dashboard
  ```
- Confirm by reading the file directly (surfaces the hidden error):
  ```bash
  /srv/projects/<name>/venv/bin/python -c "import pandas as pd; print(pd.read_excel('/srv/projects/<name>/data/FILE.xls').head())"
  ```
- If that errors with **`Expected BOF record`**, the `.xls` is actually an HTML
  table (common from ERP exports). Either save it as real `.xlsx`, or read it
  with `pd.read_html(path)[0]` instead of `pd.read_excel`.

### `ModuleNotFoundError: No module named 'X'`

A library your app imports isn't in the project venv:

```bash
/srv/projects/<name>/venv/bin/pip install X
sudo supervisorctl restart <name>_dashboard
```

Reminder: `import streamlit_autorefresh` → the pip package is
**`streamlit-autorefresh`** (hyphen).

### Dashboard starts then keeps restarting (BACKOFF/FATAL)

```bash
sudo tail -n 50 /var/log/supervisor/<name>.err.log
```
The traceback names the problem (missing file, bad sheet name, missing import).

### Changed `app.py` but the dashboard didn't update

```bash
sudo supervisorctl restart <name>_dashboard
```
(Streamlit auto-reruns the UI, but a fresh process is the clean way after code
changes.)

### Live URL won't open

- Confirm it's running: `sudo supervisorctl status <name>_dashboard`.
- The dashboard listens on its assigned port (e.g. 8502) on **localhost only**.
  Access it through the panel's link / an assigned domain, not the raw port from
  the internet (the firewall blocks 8501+ by design).

---

## 5. Manual venv (if you don't use the helper script)

```bash
python3 -m venv /srv/projects/<name>/venv
/srv/projects/<name>/venv/bin/pip install --upgrade pip
/srv/projects/<name>/venv/bin/pip install streamlit streamlit-autorefresh plotly pandas openpyxl xlrd
sudo chown -R serverhub:serverhub /srv/projects/<name>/venv
# panel → Dashboard → Start
```

---

## 6. Quick reference

```bash
# Create / refresh a dashboard venv
sudo bash deploy/dashboard-venv.sh <name> [extra packages...]

# Control the dashboard
sudo supervisorctl status  <name>_dashboard
sudo supervisorctl restart <name>_dashboard
sudo supervisorctl stop    <name>_dashboard

# Logs
sudo tail -f /var/log/supervisor/<name>.err.log     # app errors
sudo tail -f /var/log/supervisor/<name>.out.log     # app stdout
sudo tail -n 30 /var/log/supervisor/supervisord.log # spawn errors

# Test the app directly (best way to see real errors)
cd /srv/projects/<name>/dashboard
/srv/projects/<name>/venv/bin/streamlit run app.py --server.port 8599 --server.headless true

# Add a library
/srv/projects/<name>/venv/bin/pip install <pkg> && sudo supervisorctl restart <name>_dashboard
```

> **Standard dashboard deps:** `streamlit streamlit-autorefresh plotly pandas
> openpyxl xlrd` — `openpyxl` for `.xlsx`, **`xlrd` for `.xls`**.
