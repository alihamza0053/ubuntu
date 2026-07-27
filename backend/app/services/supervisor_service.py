"""
Supervisor integration: one supervisor [program] per project dashboard.

A dashboard is whatever the project put in `dashboard/` — the panel reads the
code and serves it the way it wants to be served:

    streamlit  →  streamlit run app.py --server.port N
    flask      →  gunicorn app:app --bind 0.0.0.0:N
    fastapi    →  uvicorn app:app --host 0.0.0.0 --port N

Config files are written to SUPERVISOR_CONF_DIR (a directory owned by the
panel user and included from /etc/supervisor/supervisord.conf — see the
deploy README). supervisorctl itself is executed through sudo using the
restricted NOPASSWD rule installed by deploy/sudoers-serverhub.

All subprocess calls use argument lists — never shell=True.
"""
import re
import subprocess
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Project
from . import app_detect

DEFAULT_FRAMEWORK = "streamlit"          # what every dashboard was before

# Dashboards bind 0.0.0.0, not 127.0.0.1: the UI offers a direct
# http://<host>:<port> link alongside the nginx domain, and that has always
# worked for Streamlit. Flask/FastAPI keep the same deal.
FRAMEWORK_COMMANDS = {
    "streamlit": "{bin} run {app_path} --server.port {port} --server.headless true",
    "flask":     "{bin} {target} --bind 0.0.0.0:{port} --workers 2 --timeout 120",
    "fastapi":   "{bin} {target} --host 0.0.0.0 --port {port}",
}
FRAMEWORK_BINS = {"streamlit": "streamlit", "flask": "gunicorn", "fastapi": "uvicorn"}

# redirect_stderr is deliberately NOT used here: the dashboard UI has separate
# stdout/stderr log buttons, and both files are configured below.
SUPERVISOR_TEMPLATE = """[program:{name}_dashboard]
command={command}
directory={dashboard_dir}
environment=PATH="{venv_bin}:/usr/local/bin:/usr/bin:/bin",PYTHONUNBUFFERED="1"
autostart=false
autorestart=true
stderr_logfile={log_dir}/{name}.err.log
stdout_logfile={log_dir}/{name}.out.log
"""


def program_name(project_name: str) -> str:
    return f"{project_name}_dashboard"


def config_path(project_name: str) -> Path:
    return settings.SUPERVISOR_CONF_DIR / f"{program_name(project_name)}.conf"


def dashboard_dir(project_name: str) -> Path:
    return settings.PROJECTS_ROOT / project_name / "dashboard"


def venv_bin_dir(project_name: str) -> Path:
    return settings.PROJECTS_ROOT / project_name / "venv" / "bin"


def normalise_framework(framework: str | None) -> str:
    key = (framework or "").strip().lower()
    return key if key in FRAMEWORK_COMMANDS else DEFAULT_FRAMEWORK


def detect_framework(project_name: str) -> dict | None:
    """What kind of app is in the project's dashboard/ folder (or None)."""
    return app_detect.detect(dashboard_dir(project_name))


def project_bin(project_name: str, framework: str) -> str:
    """
    Server executable for a dashboard.

    Prefer the per-project virtualenv at /srv/projects/<name>/venv — dashboards
    need their own dependencies (Streamlit pulls a Starlette version that
    conflicts with the panel's FastAPI in the shared venv). Fall back to the
    global STREAMLIT_BIN / a bare name resolved via PATH.

    Create a project venv with: deploy/dashboard-venv.sh <name>
    """
    name = FRAMEWORK_BINS[normalise_framework(framework)]
    in_venv = venv_bin_dir(project_name) / name
    if in_venv.exists():
        return str(in_venv)
    if name == "streamlit":
        return settings.STREAMLIT_BIN
    return name          # resolved through the PATH set in the program config


def project_streamlit_bin(project_name: str) -> str:
    """Back-compat alias — the Streamlit executable for a project."""
    return project_bin(project_name, "streamlit")


def build_command(project_name: str, port: int, framework: str,
                  target: str | None = None) -> str:
    """The full supervisor `command=` line for a dashboard."""
    key = normalise_framework(framework)
    return FRAMEWORK_COMMANDS[key].format(
        bin=project_bin(project_name, key),
        app_path=dashboard_dir(project_name) / "app.py",
        target=target or "app:app",
        port=port,
    )


def _supervisorctl(*args: str) -> subprocess.CompletedProcess:
    """Run supervisorctl (optionally via sudo) and return the result."""
    cmd = ["supervisorctl", *args]
    if settings.SUPERVISORCTL_USE_SUDO:
        cmd = ["sudo", "-n", *cmd]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="supervisorctl not found on this host")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="supervisorctl timed out")


def run_supervisorctl(*args: str) -> subprocess.CompletedProcess:
    """Public wrapper so other services (apps) can drive supervisorctl too."""
    return _supervisorctl(*args)


def allocate_port(db: Session) -> int:
    """Pick the next free dashboard port (max existing + 1)."""
    max_port = db.query(func.max(Project.dashboard_port)).scalar()
    return (max_port + 1) if max_port else settings.DASHBOARD_PORT_START


def write_config(project_name: str, port: int, framework: str | None = None,
                 target: str | None = None) -> Path:
    """Render and write the supervisor program config for a project."""
    settings.SUPERVISOR_CONF_DIR.mkdir(parents=True, exist_ok=True)
    content = SUPERVISOR_TEMPLATE.format(
        name=project_name,
        command=build_command(project_name, port, framework, target),
        dashboard_dir=dashboard_dir(project_name),
        venv_bin=venv_bin_dir(project_name),
        log_dir=settings.SUPERVISOR_LOG_DIR,
    )
    path = config_path(project_name)
    path.write_text(content, encoding="utf-8")
    # Tell supervisor about the new/changed program definition
    _supervisorctl("reread")
    _supervisorctl("update")
    return path


def remove_config(project_name: str) -> None:
    """Stop the program and delete its config (used on project delete)."""
    _supervisorctl("stop", program_name(project_name))
    path = config_path(project_name)
    if path.exists():
        path.unlink()
    _supervisorctl("reread")
    _supervisorctl("update")


def set_autostart(project_name: str, enabled: bool) -> None:
    """
    Persist the desired run-state into the program's conf so a running dashboard
    survives a reboot / supervisord restart,
    while a stopped one stays down.

    `autostart` is only evaluated when supervisord itself boots, so we just
    rewrite the file on disk — no reread/update (which would disruptively
    restart the running program right now).
    """
    path = config_path(project_name)
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    new = re.sub(r"(?m)^autostart=.*$", f"autostart={'true' if enabled else 'false'}", text)
    if new != text:
        path.write_text(new, encoding="utf-8")


def start(project_name: str) -> str:
    set_autostart(project_name, True)
    return _action("start", project_name)


def stop(project_name: str) -> str:
    out = _action("stop", project_name)
    set_autostart(project_name, False)
    return out


def restart(project_name: str) -> str:
    set_autostart(project_name, True)
    return _action("restart", project_name)


def _action(action: str, project_name: str) -> str:
    result = _supervisorctl(action, program_name(project_name))
    output = (result.stdout + result.stderr).strip()
    # supervisorctl exits 0 even on some failures, so inspect the text too
    if "ERROR" in output and "already started" not in output:
        raise HTTPException(status_code=500, detail=f"supervisorctl {action}: {output}")
    return output


def status(project_name: str) -> tuple[str, str]:
    """
    Return (STATE, raw_line) for a dashboard program.
    STATE is one of RUNNING / STOPPED / ERROR / UNKNOWN.
    """
    result = _supervisorctl("status", program_name(project_name))
    raw = (result.stdout + result.stderr).strip()
    upper = raw.upper()
    if "RUNNING" in upper or "STARTING" in upper:
        return "RUNNING", raw
    if "STOPPED" in upper or "EXITED" in upper or "NOT STARTED" in upper:
        return "STOPPED", raw
    if "FATAL" in upper or "BACKOFF" in upper or "ERROR" in upper:
        return "ERROR", raw
    return "UNKNOWN", raw


def dashboard_log_path(project_name: str, stream: str = "out") -> Path:
    """Path of the supervisor stdout/stderr log for a dashboard."""
    return settings.SUPERVISOR_LOG_DIR / f"{project_name}.{stream}.log"
