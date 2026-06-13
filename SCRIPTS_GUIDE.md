# Running Python Scripts (and Selenium) on ServerHub

How to take a Python script that worked on your Windows PC and run it on the
ServerHub panel — including headless Selenium browser-automation scripts like
`P2P Custom.py`.

---

## 1. The 6 things to change for a script to run on the server

| # | Windows habit | On the server |
|---|---|---|
| 1 | Visible Chrome window | **Headless Chrome** (no display exists) |
| 2 | `webdriver.Chrome(options)` finds Chrome itself | Point at the server's **Chromium/Chrome + chromedriver** |
| 3 | Download to `C:\Users\...` or `/var/www/...` | Download to the project's **`data/` folder** (writable by the panel user) |
| 4 | Headless downloads "just work" | Must **explicitly allow downloads** in headless mode |
| 5 | You close the window manually | **Always `driver.quit()`** in a `finally:` block |
| 6 | Hard-coded passwords | Prefer **environment variables** |

`P2P Custom.py` in this repo already has all six applied — use it as a template.

---

## 2. The exact code changes (copy these patterns)

### (1)+(2) Headless + find the browser

```python
import shutil
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

options = Options()
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,1080")

chrome = shutil.which("google-chrome") or shutil.which("chromium-browser") or shutil.which("chromium")
if chrome:
    options.binary_location = chrome

driver_path = shutil.which("chromedriver")
driver = (webdriver.Chrome(service=Service(driver_path), options=options)
          if driver_path else webdriver.Chrome(options=options))
```

> If `chromedriver` isn't found, Selenium 4.6+ auto-downloads a matching driver
> ("Selenium Manager"), so the fallback still works.

### (3) Download into the project's data folder

```python
import os
download_dir = os.getenv("DOWNLOAD_DIR", "/srv/projects/YOUR-PROJECT/data")
os.makedirs(download_dir, exist_ok=True)
```

`/srv/projects/<name>/data/` is writable by the panel and shows up in the
project's **Data Files** tab. Never use `/var/www/...` (root-owned) or a Windows
path.

### (4) Allow downloads in headless mode

```python
driver.execute_cdp_cmd("Page.setDownloadBehavior", {
    "behavior": "allow",
    "downloadPath": download_dir,
})
```

Without this, headless Chrome silently refuses the download — the file never
appears and your wait-loop times out.

### (5) Always quit the driver

```python
try:
    # ... all your automation steps ...
finally:
    driver.quit()
```

A run that errors without `quit()` leaves a zombie Chrome eating RAM. After a
few failed runs an unprotected script can take the whole server down.

### (6) Credentials from environment variables

```python
ORACLE_USER = os.getenv("ORACLE_USER", "fallback-user")
ORACLE_PASS = os.getenv("ORACLE_PASS", "fallback-pass")
```

Set them once on the server (see Section 5) instead of committing passwords.

---

## 2b. Convert one of YOUR existing download scripts (drop-in recipe)

Most of the operations scripts use the `webdriver.ChromeOptions()` + `prefs`
style. Here's the exact recipe used to convert them — follow these 5 edits on
any new script and it will run headless on the server.

### Edit 1 — top of file: imports, output folder, credentials, browser path

Replace your Windows config block with this (change `operations` to your project
and the env-var names to suit the login):

```python
import os, shutil, atexit   # add these to your existing imports

# Save where the dashboard reads. Override with DOWNLOAD_DIR if needed.
download_directory = os.getenv("DOWNLOAD_DIR", "/srv/projects/operations/data")
os.makedirs(download_directory, exist_ok=True)

# Credentials from env vars (fallback keeps it working immediately)
LOGIN_USER = os.getenv("ORACLE_USER", "HOD.ERP")
LOGIN_PASS = os.getenv("ORACLE_PASS", "UKMST@123")

# Find the server's Chrome/Chromium binary
CHROME_BINARY = next((p for p in [
    shutil.which("google-chrome"), shutil.which("chromium-browser"),
    shutil.which("chromium"), "/usr/bin/google-chrome"] if p and os.path.exists(p)), None)
```

### Edit 2 — the ChromeOptions block: add headless + binary, fix the path

```python
chrome_options = webdriver.ChromeOptions()
prefs = {
    "download.default_directory": download_directory,   # NOT .replace('/','\\')
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "profile.default_content_setting_values.automatic_downloads": 1,
}
chrome_options.add_experimental_option("prefs", prefs)
# --- headless server flags (the important part) ---
chrome_options.add_argument("--headless=new")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--window-size=1920,1080")
if CHROME_BINARY:
    chrome_options.binary_location = CHROME_BINARY
# keep any of your other options (excludeSwitches, etc.)
```

> Remove `--start-maximized` and `driver.maximize_window()` — they don't work
> headless (there's no window to maximize).

### Edit 3 — right after creating the driver: cleanup + allow downloads

```python
driver = webdriver.Chrome(options=chrome_options)

def _cleanup():
    try:
        driver.quit()
    except Exception:
        pass
atexit.register(_cleanup)   # closes Chrome even if the script crashes

driver.execute_cdp_cmd("Page.setDownloadBehavior",
                       {"behavior": "allow", "downloadPath": download_directory})
```

> `atexit` is the easy way to guarantee cleanup without wrapping the whole
> linear script in `try/finally`. (If your script already has a `try/finally`,
> just put `driver.quit()` in the `finally` instead.)

### Edit 4 — use the credential variables at login

```python
username.send_keys(LOGIN_USER)
password.send_keys(LOGIN_PASS)
```

### Edit 5 — make the output filename match the dashboard

If a dashboard reads this file, save it with the **exact name** the dashboard
expects, in `data/`. Check the dashboard's `CONFIG` section for the filename.

| If the dashboard reads… | your script must produce in `data/`… |
|---|---|
| `pd.read_excel(".../Foo.xlsx")` | `Foo.xlsx` (same name, same folder) |
| an `.xls` file | save `.xls` (the dashboard needs `xlrd` — see Section 3) |

### Conversion checklist

- [ ] `download_directory` → `/srv/projects/<project>/data` via `DOWNLOAD_DIR`.
- [ ] Removed Windows paths and any `.replace('/', '\\')`.
- [ ] Added the 5 headless flags + `binary_location`.
- [ ] Removed `--start-maximized` / `maximize_window()`.
- [ ] `setDownloadBehavior` CDP call after creating the driver.
- [ ] `atexit` cleanup (or `driver.quit()` in `finally`).
- [ ] Credentials via `os.getenv(...)`.
- [ ] Output filename matches what the dashboard reads.
- [ ] Tested from the **Terminal**, then **Scripts → Run Now**.

> A second login system? Use different env-var names, e.g. the OQL report uses
> `OQL_USER` / `OQL_PASS` while the Oracle Fusion reports use
> `ORACLE_USER` / `ORACLE_PASS`. Set them all in the supervisor `environment=`
> line (Section 5).

---

## 3. One-time server setup for Selenium

> ⚠️ **Use Google Chrome (.deb), NOT apt/snap `chromium`.** On Ubuntu 22.04/24.04
> the apt `chromium-browser`/`chromium-chromedriver` are **snap wrappers**. The
> snap chromedriver **crashes** under the unprivileged `serverhub` user with:
> ```
> WebDriverException: Message: Service /usr/bin/chromedriver
> unexpectedly exited. Status code was: 1
> ```
> and snap Chromium **can't write downloads to `/srv`**. Google Chrome `.deb`
> fixes both.

Install the real browser (once per server):

```bash
# Remove snap chromium if present (ignore errors)
sudo snap remove chromium 2>/dev/null
sudo apt remove -y chromium-browser chromium-chromedriver 2>/dev/null

# Install Google Chrome .deb
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y ./google-chrome-stable_current_amd64.deb
google-chrome --version            # confirm it installed
```

Install Selenium (+ the common data libraries your scripts use) into the panel's
venv. Scripts run with `/srv/serverhub/venv/bin/python`, so anything they
`import` must be installed there. The `selenium` package includes **Selenium
Manager**, which auto-downloads the matching driver — you do **not** need a
separate chromedriver:

```bash
sudo /srv/serverhub/venv/bin/pip install selenium pandas openpyxl xlrd
```

> `openpyxl` = read/write `.xlsx`; **`xlrd` = read/convert `.xls`** (e.g.
> `cut-to-pack.py` converts an `.xls` export to `.xlsx`). Add any other library
> a script imports the same way.

Let the panel user write the driver cache:

```bash
sudo mkdir -p /home/serverhub/.cache
sudo chown -R serverhub:serverhub /home/serverhub
```

> A fresh `deploy/install.sh` already does all of the above (Google Chrome +
> selenium + cache dir). This section is for confirming or fixing an existing
> server.

---

## 4. How to get your script onto the panel and run it

1. **Upload** — In the panel: open your project → **Files** tab → upload the
   `.py` into the **`code/`** folder (or `allscripts/` for helpers).
   It auto-registers on the **Scripts** tab.
2. **Test it first from the Terminal** (you see errors immediately):
   ```bash
   /srv/serverhub/venv/bin/python "/srv/projects/YOUR-PROJECT/code/P2P Custom.py"
   ```
3. **Run from the UI** — **Scripts** tab → **Run Now**. Output streams live; the
   final status shows SUCCESS/FAILED. Re-open the log anytime with **View Log**.
4. **Find the output** — the downloaded `.xlsx` appears under the project's
   **Data Files** tab (it's in `data/`).

---

## 5. Setting credentials / config (environment variables)

Scripts started by the panel inherit the environment of the panel process.
The clean way to provide secrets is the panel's `.env` plus a tiny change, or —
simplest — put them in the script's own folder as a config the script reads.

**Quick option (per-server, applies to all scripts):** add them to the panel's
service environment.

```bash
sudo nano /etc/supervisor/conf.d/serverhub.conf
```
Add an `environment=` line inside the `[program:serverhub]` block:
```ini
environment=ORACLE_USER="HOD.ERP",ORACLE_PASS="yourpassword"
```
Then:
```bash
sudo supervisorctl reread && sudo supervisorctl update && sudo supervisorctl restart serverhub
```

**Or** just run from the Terminal page with them inline for a one-off:
```bash
ORACLE_USER="HOD.ERP" ORACLE_PASS="secret" \
  /srv/serverhub/venv/bin/python "/srv/projects/YOUR-PROJECT/code/P2P Custom.py"
```

---

## 6. Scheduling the script

In the panel: project → **Scheduler** tab → pick the script → choose a
frequency in the visual cron builder (e.g. **Daily at 06:00**) → **Add
schedule**. The panel runs it via APScheduler and records each run's log and
status. Toggle it on/off or delete it from the same table.

> Scheduled runs use the same environment as the panel, so set credentials as in
> Section 5 (the inline-Terminal method won't apply to scheduled runs).

---

## 7. Troubleshooting Selenium on the server

| Symptom | Cause / fix |
|---|---|
| **`javascript error: Cannot convert undefined or null to object`** (inside a `WebDriverWait(...).until(...)`) | Selenium's `is_displayed()` JS atom is broken on **very new Chrome (149+)**. `element_to_be_clickable` / `visibility_of` call it. Add the `is_displayed` workaround below — or use `presence_of_element_located` + a JS click instead. |
| **`Service /usr/bin/chromedriver unexpectedly exited. Status code was: 1`** | You're on **snap Chromium** — the snap chromedriver can't run as the `serverhub` user. Switch to Google Chrome `.deb` and remove the snap driver (Section 3). Then `CHROMEDRIVER` is `None` and Selenium Manager supplies the right driver. |
| `WebDriverException: unable to discover open pages` / `session not created` | Browser not found or not headless. Confirm `google-chrome --version` works; ensure the headless args are set. |
| `... cannot find Chrome binary` | Set `options.binary_location` to the path from `which google-chrome`. |
| `... cannot create default profile directory` / cache errors | Panel user can't write its home. `sudo mkdir -p /home/serverhub/.cache && sudo chown -R serverhub:serverhub /home/serverhub`. |
| Script runs but **no file downloads** | Missing the `Page.setDownloadBehavior` CDP call, **or** snap Chromium can't write to `/srv`. Use the Chrome `.deb` (Section 3). |
| `TimeoutError: Excel file did not download` | Same as above, or the report genuinely took longer — raise the `wait_for_new_excel` timeout. |
| Works in Terminal but **fails when scheduled** | Credentials/env not set for the panel service — do Section 5's supervisor `environment=` method. |
| Server slows to a crawl after a few runs | Zombie Chrome processes — make sure `driver.quit()` is in a `finally:`. Kill stragglers: `pkill -f chrome`. |
| `DevToolsActivePort file doesn't exist` | Add `--no-sandbox` and `--disable-dev-shm-usage` (already in the template). |
| Out of memory / `Killed` | Chrome is RAM-hungry; add swap (see `DEPLOYMENT.md` Step 1.5) or run one script at a time. |

Check a missing Python import:
```bash
sudo /srv/serverhub/venv/bin/pip install <package>
```

### The `is_displayed()` / Chrome 149+ workaround

Paste this once, right after you create the driver. It makes
`element_to_be_clickable` / `visibility_of` waits survive the broken Chrome JS
atom (it only changes behaviour when the check itself errors):

```python
from selenium.webdriver.remote.webelement import WebElement as _WebElement
_orig_is_displayed = _WebElement.is_displayed
def _safe_is_displayed(self):
    try:
        return _orig_is_displayed(self)
    except Exception:
        return True
_WebElement.is_displayed = _safe_is_displayed
```

All of the operations report scripts already include this block.

---

## 8. Checklist before you schedule any script

- [ ] Headless args set (`--headless=new --no-sandbox --disable-dev-shm-usage`).
- [ ] `binary_location` resolves to a real browser on the server.
- [ ] Download/output path is under `/srv/projects/<name>/data/` (writable).
- [ ] `Page.setDownloadBehavior` allow-download call present (for download scripts).
- [ ] `driver.quit()` in a `finally:` block.
- [ ] Credentials via env vars, not hard-coded.
- [ ] Tested once from the **Terminal**, then once via **Scripts → Run Now**.
- [ ] Output verified in the **Data Files** tab.

`P2P Custom.py` already satisfies items 1–6 — copy its structure for new scripts.
