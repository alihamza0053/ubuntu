"""
Code editor (sidebar → Code): code-server — VS Code in the browser.

  * runs as the panel user (it edits /srv/projects, /srv/websites) on
    127.0.0.1:CODE_PORT, under Supervisor, started on demand;
  * reached at <panel>/ide/ — nginx asks /api/code/auth on every request, which
    checks a short-lived, HttpOnly editor cookie the panel sets when an allowed
    user clicks "Open". No separate editor password exists;
  * who may use it: users with the `code` tab (admins by default), unless the
    owner switched "Only me" on — then only the owner, admins included.

Its terminal is a shell as the panel user, so editor access is server access.
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from jose import JWTError, jwt

try:
    import pwd                       # Linux only (the server); absent on Windows dev machines
except ImportError:  # pragma: no cover
    pwd = None

from ..config import settings
from ..database import SessionLocal
from ..models import Setting
from ..permissions import user_can_tab
from . import supervisor_service, user_audit

PROGRAM = "code_server"
PORT = 8899
HELPER = str(settings.PANEL_ROOT / "bin" / "serverhub-code")
DATA_DIR = settings.PANEL_ROOT / "code"
OWNER_ONLY_KEY = "code_owner_only"
COOKIE = "serverhub_code"
COOKIE_HOURS = 12
BINARY = "/usr/bin/code-server"

TEMPLATE = """[program:{program}]
command={binary} --bind-addr 127.0.0.1:{port} --auth none --disable-telemetry --disable-update-check --disable-workspace-trust --user-data-dir {data}/user --extensions-dir {data}/extensions {folder}
directory={folder}
user={user}
environment=HOME="{home}",PATH="/usr/local/bin:/usr/bin:/bin"
autostart={autostart}
autorestart=true
stopasgroup=true
killasgroup=true
redirect_stderr=true
stdout_logfile={log_dir}/{program}.out.log
"""


# ---------------------------------------------------------------------------
# who may use it
# ---------------------------------------------------------------------------
def owner_only() -> bool:
    db = SessionLocal()
    try:
        row = db.query(Setting).filter(Setting.key == OWNER_ONLY_KEY).first()
        return bool(row and row.value == "1")
    finally:
        db.close()


def set_owner_only(enabled: bool) -> None:
    db = SessionLocal()
    try:
        row = db.query(Setting).filter(Setting.key == OWNER_ONLY_KEY).first()
        if row is None:
            db.add(Setting(key=OWNER_ONLY_KEY, value="1" if enabled else "0"))
        else:
            row.value = "1" if enabled else "0"
        db.commit()
    finally:
        db.close()


def can_use(user) -> bool:
    if user is None:
        return False
    if user_audit.is_owner(user):
        return True
    if owner_only():
        return False
    return user_can_tab(user, "code")


def require(user) -> None:
    if not can_use(user):
        raise HTTPException(404, "Not found")      # looks like it doesn't exist


# ---------------------------------------------------------------------------
# editor cookie (what nginx's auth_request checks)
# ---------------------------------------------------------------------------
def make_cookie_token(username: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=COOKIE_HOURS)
    return jwt.encode({"sub": username, "scope": "code", "exp": exp}, settings.SECRET_KEY,
                      algorithm=settings.ALGORITHM)


def cookie_username(token: str | None) -> str | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
    return payload.get("sub") if payload.get("scope") == "code" else None


# ---------------------------------------------------------------------------
# install / run
# ---------------------------------------------------------------------------
def _helper(*args: str, timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(["sudo", "-n", HELPER, *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "sudo not found"
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    return r.returncode, (r.stdout + r.stderr).strip()


def config_path() -> Path:
    return settings.SUPERVISOR_CONF_DIR / f"{PROGRAM}.conf"


def write_program() -> None:
    """(Re)write the Supervisor program; no-op when unchanged (keeps a running editor up)."""
    try:
        me = pwd.getpwuid(os.getuid())
        home, user = me.pw_dir, me.pw_name
    except (KeyError, AttributeError):
        home, user = "/home/serverhub", "serverhub"
    (DATA_DIR / "user").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "extensions").mkdir(parents=True, exist_ok=True)
    path = config_path()
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    current = re.search(r"(?m)^autostart=(.*)$", existing or "")
    content = TEMPLATE.format(program=PROGRAM, binary=BINARY, port=PORT, data=DATA_DIR,
                              folder=settings.PROJECTS_ROOT, user=user, home=home,
                              autostart=current.group(1) if current else "false",
                              log_dir=settings.SUPERVISOR_LOG_DIR)
    if content != existing:
        settings.SUPERVISOR_CONF_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        supervisor_service.run_supervisorctl("reread")
        supervisor_service.run_supervisorctl("update")


def _set_autostart(enabled: bool) -> None:
    path = config_path()
    if path.exists():
        text = path.read_text(encoding="utf-8")
        path.write_text(re.sub(r"(?m)^autostart=.*$", f"autostart={'true' if enabled else 'false'}", text),
                        encoding="utf-8")


def running() -> bool:
    if not config_path().exists():
        return False
    r = supervisor_service.run_supervisorctl("status", PROGRAM)
    return "RUNNING" in (r.stdout + r.stderr).upper()


def status() -> dict:
    code, out = _helper("status")
    info = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    st = {"installed": info.get("installed") == "yes", "version": info.get("version"),
          "nginx": info.get("nginx") == "yes", "running": False, "helper": code == 0,
          "owner_only": owner_only()}
    if code != 0:
        st["error"] = out[-300:] or "The editor helper isn't installed yet — run deploy/update.sh."
    if st["installed"]:
        st["running"] = running()
    return st


def install() -> str:
    code, out = _helper("install", timeout=900)
    if code != 0:
        raise HTTPException(500, f"Install failed: {out[-800:]}")
    code2, out2 = _helper("nginx", str(PORT), timeout=120)
    if code2 != 0:
        raise HTTPException(500, f"Installed, but the /ide/ web path couldn't be set up: {out2[-800:]}")
    write_program()
    start()
    return f"{out}\n{out2}"


def start() -> str:
    write_program()
    if not status_nginx_ok():
        code, out = _helper("nginx", str(PORT), timeout=120)
        if code != 0:
            raise HTTPException(500, f"The /ide/ web path couldn't be set up: {out[-800:]}")
    _set_autostart(True)
    r = supervisor_service.run_supervisorctl("start", PROGRAM)
    out = (r.stdout + r.stderr).strip()
    if "ERROR" in out and "already started" not in out:
        raise HTTPException(500, f"Couldn't start the editor: {out}")
    return out or "started"


def stop() -> str:
    _set_autostart(False)
    r = supervisor_service.run_supervisorctl("stop", PROGRAM)
    return (r.stdout + r.stderr).strip() or "stopped"


def status_nginx_ok() -> bool:
    code, out = _helper("status")
    return code == 0 and "nginx=yes" in out
