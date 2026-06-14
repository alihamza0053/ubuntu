"""
Self-hosted app catalog + lifecycle.

Apps are one-click-installable tools. Two kinds:
  - "service": runs on a localhost port under Supervisor (e.g. code-server,
    File Browser). Can be given a domain + SSL like a project dashboard.
  - "tool": just an install (e.g. Google Chrome) — no port/process.

The actual package install is performed by a vetted root helper script
(deploy/serverhub-app-install.sh) invoked through a single restricted sudo
rule, so the panel never runs arbitrary commands as root.
"""
import secrets
import subprocess
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import App
from . import supervisor_service

APP_PORT_START = 9001
INSTALLER = "/srv/serverhub/bin/serverhub-app-install"

# Catalog of installable apps. `run` is the supervisor command for service
# apps; {port} and {bin} are substituted. The install steps themselves live in
# the root helper script keyed by the same slug.
CATALOG: dict[str, dict] = {
    "code-server": {
        "name": "VS Code (code-server)",
        "description": "Full VS Code in your browser — edit code on the server.",
        "icon": "🧩",
        "kind": "service",
        "bin": "/usr/bin/code-server",
        "run": "{bin} --bind-addr 127.0.0.1:{port} --auth password --disable-telemetry",
        "use_password": True,
        "websocket": True,
    },
    "filebrowser": {
        "name": "File Browser",
        "description": "Web-based file manager for the whole server.",
        "icon": "📂",
        "kind": "service",
        "bin": "/usr/local/bin/filebrowser",
        "run": "{bin} --address 127.0.0.1 --port {port} --root /srv --database /srv/serverhub/db/filebrowser.db",
        "use_password": False,
        "websocket": False,
        # Built-in login; password changeable via its CLI (against its own DB).
        "username": "admin",
        "set_password_cmd": ["{bin}", "users", "update", "admin",
                             "--password", "{password}",
                             "--database", "/srv/serverhub/db/filebrowser.db"],
    },
    "uptime-kuma": {
        "name": "Uptime Kuma",
        "description": "Self-hosted uptime monitoring dashboard.",
        "icon": "📈",
        "kind": "service",
        "bin": "/usr/bin/npx",
        "run": "/usr/bin/npx --yes uptime-kuma-server --port {port} --host 127.0.0.1",
        "use_password": False,
        "websocket": True,
    },
    "syncthing": {
        "name": "Syncthing",
        "description": "Continuous file synchronization with a web UI.",
        "icon": "🔄",
        "kind": "service",
        "bin": "/usr/bin/syncthing",
        "run": "{bin} serve --no-browser --gui-address=127.0.0.1:{port} --home=/srv/serverhub/apps/syncthing",
        "use_password": False,
        "websocket": True,
    },
    "glances": {
        "name": "Glances",
        "description": "Live CPU / RAM / disk / network monitor in the browser.",
        "icon": "📊",
        "kind": "service",
        "bin": "/srv/serverhub/apps/glances/venv/bin/glances",
        "run": "{bin} -w --bind 127.0.0.1 --port {port}",
        "use_password": False,
        "websocket": True,
    },
    "jupyterlab": {
        "name": "JupyterLab",
        "description": "Notebooks & data science IDE in the browser.",
        "icon": "📓",
        "kind": "service",
        "bin": "/srv/serverhub/apps/jupyterlab/venv/bin/jupyter",
        "run": ("{bin} lab --ip 127.0.0.1 --port {port} --no-browser "
                "--ServerApp.token={secret} --ServerApp.root_dir=/srv"),
        "use_token": True,
        "websocket": True,
    },
    "webtop": {
        "name": "Web Browser (Firefox)",
        "description": "A real Firefox desktop streamed to your browser via noVNC. "
                       "Heavy (runs a virtual display) — best on 2 GB+ RAM.",
        "icon": "🦊",
        "kind": "service",
        "bin": "/srv/serverhub/bin/serverhub-webtop",
        "run": "{bin} {port}",
        "use_password": False,
        "websocket": True,
    },
    "google-chrome": {
        "name": "Google Chrome",
        "description": "Headless Chrome for Selenium scripts (no web UI).",
        "icon": "🌐",
        "kind": "tool",
    },
}


def get_catalog_entry(slug: str) -> dict:
    entry = CATALOG.get(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown app: {slug}")
    return entry


def program_name(slug: str) -> str:
    return f"app_{slug}"


def config_path(slug: str) -> Path:
    return settings.SUPERVISOR_CONF_DIR / f"{program_name(slug)}.conf"


def log_path(slug: str, stream: str = "out") -> Path:
    return settings.SUPERVISOR_LOG_DIR / f"{program_name(slug)}.{stream}.log"


def allocate_port(db: Session) -> int:
    max_port = db.query(func.max(App.port)).scalar()
    return (max_port + 1) if max_port else APP_PORT_START


def installer_cmd(slug: str) -> list[str]:
    """The restricted sudo command that installs a catalog app (always root)."""
    return ["sudo", "-n", INSTALLER, slug]


def installer_ready() -> bool:
    """True if the installer helper exists and the panel can run it via sudo."""
    if not Path(INSTALLER).exists():
        return False
    try:
        result = subprocess.run(["sudo", "-n", INSTALLER, "--check"],
                                capture_output=True, text=True, timeout=15)
        # Our script exits 2 on unknown arg ("--check"), but reaching it means
        # sudo was allowed. A sudo-password failure exits 1 with that message.
        return "a password is required" not in (result.stderr + result.stdout)
    except Exception:
        return False


SUPERVISOR_TEMPLATE = """[program:{program}]
command={command}
directory=/srv/serverhub
autostart=false
autorestart=true
stopasgroup=true
killasgroup=true
{env_line}stderr_logfile={log_dir}/{program}.err.log
stdout_logfile={log_dir}/{program}.out.log
"""


def write_program(app: App) -> None:
    """Write/refresh the supervisor program for a service app."""
    entry = get_catalog_entry(app.slug)
    if entry["kind"] != "service":
        return
    settings.SUPERVISOR_CONF_DIR.mkdir(parents=True, exist_ok=True)
    command = entry["run"].format(
        bin=entry.get("bin", ""), port=app.port, secret=app.secret or "")

    # Build the environment= line from catalog env + an optional PASSWORD
    env_pairs = {
        k: str(v).format(port=app.port, secret=app.secret or "")
        for k, v in entry.get("env", {}).items()
    }
    if entry.get("use_password") and app.secret:
        env_pairs["PASSWORD"] = app.secret
    env_line = ""
    if env_pairs:
        joined = ",".join(f'{k}="{v}"' for k, v in env_pairs.items())
        env_line = f"environment={joined}\n"

    content = SUPERVISOR_TEMPLATE.format(
        program=program_name(app.slug),
        command=command,
        env_line=env_line,
        log_dir=settings.SUPERVISOR_LOG_DIR,
    )
    config_path(app.slug).write_text(content, encoding="utf-8")
    supervisor_service.run_supervisorctl("reread")
    supervisor_service.run_supervisorctl("update")


def remove_program(slug: str) -> None:
    supervisor_service.run_supervisorctl("stop", program_name(slug))
    path = config_path(slug)
    if path.exists():
        path.unlink()
    supervisor_service.run_supervisorctl("reread")
    supervisor_service.run_supervisorctl("update")


def control(slug: str, action: str) -> str:
    result = supervisor_service.run_supervisorctl(action, program_name(slug))
    out = (result.stdout + result.stderr).strip()
    if "ERROR" in out and "already started" not in out:
        raise HTTPException(status_code=500, detail=f"supervisorctl {action}: {out}")
    return out


def status(slug: str) -> str:
    result = supervisor_service.run_supervisorctl("status", program_name(slug))
    raw = (result.stdout + result.stderr).upper()
    if "RUNNING" in raw or "STARTING" in raw:
        return "RUNNING"
    if "FATAL" in raw or "BACKOFF" in raw:
        return "ERROR"
    return "STOPPED"


def new_password() -> str:
    return secrets.token_urlsafe(12)


def set_password(app, new_pw: str) -> None:
    """
    Change a service app's password. Two mechanisms:
      - env-based (code-server): store secret + rewrite the supervisor program
        (its env PASSWORD), which restarts it on `update`.
      - CLI-based (File Browser): stop, update the password in its own DB via
        its CLI, then start.
    Caller commits the App row afterwards.
    """
    entry = get_catalog_entry(app.slug)

    # code-server (env PASSWORD) or Jupyter (token in the run command): just
    # store the new secret and rewrite the program — `update` restarts it.
    if entry.get("use_password") or entry.get("use_token"):
        app.secret = new_pw
        write_program(app)
        return

    cmd_tpl = entry.get("set_password_cmd")
    if cmd_tpl:
        was_running = status(app.slug) == "RUNNING"
        if was_running:
            control(app.slug, "stop")
        cmd = [c.format(bin=entry.get("bin", ""), password=new_pw) for c in cmd_tpl]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        finally:
            if was_running:
                control(app.slug, "start")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown error").strip()
            raise HTTPException(status_code=500, detail=f"set password failed: {detail[:300]}")
        app.secret = new_pw
        return

    raise HTTPException(status_code=400, detail="This app's password can't be changed from the panel")
