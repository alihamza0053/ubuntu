"""
Python web-service (Websites "python" type) lifecycle.

Lets a user upload their own FastAPI/Flask app as a zip, build a virtualenv +
install requirements.txt, and run it under Supervisor on a localhost port (the
domain is then a reverse proxy to that port). Mirrors venv_service (background
env build) and app_service (per-program supervisor conf).

Runs as the panel's `serverhub` user, which owns /srv/websites — no sudo for the
venv/pip work; supervisorctl uses the existing restricted sudo rule.
"""
import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Website
from . import supervisor_service

WEBAPP_PORT_START = 8600
DEFAULT_RUN_COMMAND = "uvicorn app_server:app --host 127.0.0.1 --port {port}"

_building: set[str] = set()
_lock = threading.Lock()


# ---------- paths / naming ----------

def site_dir(name: str) -> Path:
    return settings.WEBSITES_ROOT / name


def venv_dir(name: str) -> Path:
    return site_dir(name) / "venv"


def program_name(name: str) -> str:
    return f"webapp_{name}"


def config_path(name: str) -> Path:
    return settings.SUPERVISOR_CONF_DIR / f"{program_name(name)}.conf"


def log_path(name: str, stream: str = "out") -> Path:
    return settings.SUPERVISOR_LOG_DIR / f"{program_name(name)}.{stream}.log"


def setup_log_path(name: str) -> Path:
    return site_dir(name) / "logs" / "setup.log"


def default_run_command() -> str:
    return DEFAULT_RUN_COMMAND


def allocate_port(db: Session) -> int:
    max_port = db.query(func.max(Website.port)).scalar()
    return (max_port + 1) if max_port else WEBAPP_PORT_START


# ---------- venv + dependency build (background) ----------

def env_status(name: str) -> str:
    """READY / BUILDING / MISSING for the UI."""
    if (venv_dir(name) / "bin" / "python").exists():
        return "READY"
    with _lock:
        return "BUILDING" if name in _building else "MISSING"


def is_building(name: str) -> bool:
    with _lock:
        return name in _building


def _setup_log(name: str, line: str) -> None:
    path = setup_log_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {line}\n")


def _build(name: str) -> None:
    vdir = venv_dir(name)
    try:
        _setup_log(name, f"creating virtualenv at {vdir}")
        r = subprocess.run(["python3", "-m", "venv", str(vdir)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            _setup_log(name, "venv creation FAILED:\n" + (r.stderr or r.stdout)[:1500])
            return

        pip = str(vdir / "bin" / "pip")
        subprocess.run([pip, "install", "--upgrade", "pip"],
                       capture_output=True, text=True, timeout=300)

        req = site_dir(name) / "requirements.txt"
        if req.is_file():
            _setup_log(name, f"installing from {req}")
            r = subprocess.run([pip, "install", "-r", str(req)],
                               capture_output=True, text=True, timeout=1800)
            _setup_log(name, (r.stdout or "")[-4000:])
            if r.returncode != 0:
                _setup_log(name, "pip install FAILED:\n" + (r.stderr or "")[-2000:])
            else:
                _setup_log(name, "✓ dependencies installed")
        else:
            _setup_log(name, "no requirements.txt found — venv created without deps")

        _setup_log(name, "✓ environment ready")
    except subprocess.TimeoutExpired:
        _setup_log(name, "TIMED OUT building the environment")
    except Exception as exc:  # noqa: BLE001
        _setup_log(name, f"error: {exc}")
    finally:
        with _lock:
            _building.discard(name)


def build_env_async(name: str) -> bool:
    """Start building the venv + installing deps in the background."""
    with _lock:
        if name in _building:
            return False
        _building.add(name)
    # Fresh setup log each run so the UI shows just this build.
    p = setup_log_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("", encoding="utf-8")
    threading.Thread(target=_build, args=(name,), daemon=True).start()
    return True


# ---------- supervisor program ----------

_TEMPLATE = """[program:{program}]
command={command}
directory={directory}
environment=PATH="{venv_bin}:/usr/local/bin:/usr/bin:/bin"
autostart=false
autorestart=true
stopasgroup=true
killasgroup=true
stdout_logfile={log_dir}/{program}.out.log
stderr_logfile={log_dir}/{program}.err.log
"""


def write_program(site: Website) -> None:
    """Write/refresh the supervisor program that runs the app."""
    if not site.run_command or not site.port:
        raise HTTPException(status_code=400, detail="Set a run command and port first")
    settings.SUPERVISOR_CONF_DIR.mkdir(parents=True, exist_ok=True)
    command = site.run_command.format(port=site.port)
    content = _TEMPLATE.format(
        program=program_name(site.name),
        command=command,
        directory=site_dir(site.name),
        venv_bin=venv_dir(site.name) / "bin",
        log_dir=settings.SUPERVISOR_LOG_DIR,
    )
    config_path(site.name).write_text(content, encoding="utf-8")
    supervisor_service.run_supervisorctl("reread")
    supervisor_service.run_supervisorctl("update")


def set_autostart(name: str, enabled: bool) -> None:
    """Persist desired run-state into the conf so a running app survives a reboot
    / supervisord restart. autostart is only read at supervisord boot, so we just
    rewrite the file — no reread/update needed."""
    path = config_path(name)
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    new = re.sub(r"(?m)^autostart=.*$", f"autostart={'true' if enabled else 'false'}", text)
    if new != text:
        path.write_text(new, encoding="utf-8")


def control(site: Website, action: str) -> str:
    """start / stop / restart the app; (re)writes the program if needed."""
    if action not in ("start", "stop", "restart"):
        raise HTTPException(status_code=400, detail="action must be start/stop/restart")
    if not config_path(site.name).exists():
        write_program(site)
    if action in ("start", "restart"):
        set_autostart(site.name, True)
    result = supervisor_service.run_supervisorctl(action, program_name(site.name))
    out = (result.stdout + result.stderr).strip()
    if "ERROR" in out and "already started" not in out:
        raise HTTPException(status_code=500, detail=f"supervisorctl {action}: {out}")
    if action == "stop":
        set_autostart(site.name, False)
    return out


def status(name: str) -> str:
    """RUNNING / STOPPED / ERROR for a python website program."""
    result = supervisor_service.run_supervisorctl("status", program_name(name))
    upper = (result.stdout + result.stderr).strip().upper()
    if "RUNNING" in upper or "STARTING" in upper:
        return "RUNNING"
    if "FATAL" in upper or "BACKOFF" in upper:
        return "ERROR"
    return "STOPPED"


def remove_program(name: str) -> None:
    """Stop + delete the supervisor program (on website delete)."""
    try:
        supervisor_service.run_supervisorctl("stop", program_name(name))
    except HTTPException:
        pass
    path = config_path(name)
    if path.exists():
        path.unlink()
    supervisor_service.run_supervisorctl("reread")
    supervisor_service.run_supervisorctl("update")
