"""
Supervisor integration: one supervisor [program] per Streamlit dashboard.

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

SUPERVISOR_TEMPLATE = """[program:{name}_dashboard]
command={streamlit_bin} run {app_path} --server.port {port} --server.headless true
directory={dashboard_dir}
autostart=false
autorestart=true
stderr_logfile={log_dir}/{name}.err.log
stdout_logfile={log_dir}/{name}.out.log
"""


def program_name(project_name: str) -> str:
    return f"{project_name}_dashboard"


def config_path(project_name: str) -> Path:
    return settings.SUPERVISOR_CONF_DIR / f"{program_name(project_name)}.conf"


def project_streamlit_bin(project_name: str) -> str:
    """
    Streamlit executable to run a project's dashboard with.

    Prefer a per-project virtualenv at /srv/projects/<name>/venv — dashboards
    need their own dependencies (Streamlit pulls a Starlette version that
    conflicts with the panel's FastAPI in the shared venv). Fall back to the
    global STREAMLIT_BIN when the project has no venv yet.

    Create a project venv with: deploy/dashboard-venv.sh <name>
    """
    venv_streamlit = settings.PROJECTS_ROOT / project_name / "venv" / "bin" / "streamlit"
    if venv_streamlit.exists():
        return str(venv_streamlit)
    return settings.STREAMLIT_BIN


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


def write_config(project_name: str, port: int) -> Path:
    """Render and write the supervisor program config for a project."""
    settings.SUPERVISOR_CONF_DIR.mkdir(parents=True, exist_ok=True)
    dashboard_dir = settings.PROJECTS_ROOT / project_name / "dashboard"
    content = SUPERVISOR_TEMPLATE.format(
        name=project_name,
        streamlit_bin=project_streamlit_bin(project_name),
        app_path=dashboard_dir / "app.py",
        port=port,
        dashboard_dir=dashboard_dir,
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
    survives a reboot / supervisord restart (like a Docker `restart: always`),
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
