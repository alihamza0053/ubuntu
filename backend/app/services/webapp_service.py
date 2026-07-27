"""
Python web-service (Websites "python" type) lifecycle.

Lets a user upload their own Flask/FastAPI app as a zip, build a virtualenv +
install requirements.txt, and run it under Supervisor on a localhost port (the
domain is then a reverse proxy to that port). Mirrors venv_service (background
env build) for the environment work.

Two frameworks are first-class:
  * flask   — WSGI, served by gunicorn ("module:app")
  * fastapi — ASGI, served by uvicorn ("module:app")
Anything else is "other": the user writes the run command themselves.

`detect_app()` reads the uploaded code and works out the framework, the module
to import and the app variable, so a plain zip-upload usually needs no manual
configuration at all.

Runs as the panel's `serverhub` user, which owns /srv/websites — no sudo for the
venv/pip work; supervisorctl uses the existing restricted sudo rule.
"""
import os
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

# ---------- frameworks ----------
# server_package: pip-installed into the venv even if requirements.txt forgets
# it, because without it the app can never start.
FRAMEWORKS: dict[str, dict[str, str]] = {
    "flask": {
        "label": "Flask (gunicorn)",
        "server_package": "gunicorn",
        "server_bin": "gunicorn",
        "command": ("gunicorn {target} --bind 127.0.0.1:{{port}} "
                    "--workers 3 --timeout 120"),
        "default_target": "app:app",
    },
    "fastapi": {
        "label": "FastAPI (uvicorn)",
        "server_package": "uvicorn[standard]",
        "server_bin": "uvicorn",
        "command": "uvicorn {target} --host 127.0.0.1 --port {{port}}",
        "default_target": "app_server:app",
    },
}
DEFAULT_FRAMEWORK = "fastapi"          # what pre-framework rows were running
# Kept for callers/tests that still reference the old constant.
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


def normalise_framework(framework: str | None) -> str:
    """Map anything unknown/legacy onto a framework key we understand."""
    key = (framework or "").strip().lower()
    return key if key in FRAMEWORKS or key == "other" else DEFAULT_FRAMEWORK


def build_run_command(framework: str | None, target: str | None = None) -> str:
    """
    The start command for a framework, with `{port}` left in as a placeholder.

    `target` is the "module:variable" import path (e.g. "app:app"). Falls back
    to the framework's conventional default when not supplied.
    """
    key = normalise_framework(framework)
    if key == "other":
        return ""
    spec = FRAMEWORKS[key]
    return spec["command"].format(target=target or spec["default_target"])


def default_run_command(framework: str | None = None) -> str:
    return build_run_command(framework)


def is_default_run_command(command: str | None) -> bool:
    """
    True if `command` is one the panel generated rather than one the user typed.

    Used to decide whether a re-upload may overwrite the run command: we never
    clobber something the user wrote by hand.
    """
    text = (command or "").strip()
    if not text:
        return True
    if text == DEFAULT_RUN_COMMAND:
        return True
    # Any command whose shape matches a framework template with some target.
    # NUL stands in for the target while escaping, then becomes the one wildcard.
    for spec in FRAMEWORKS.values():
        pattern = re.escape(spec["command"].format(target="\x00"))
        pattern = pattern.replace("\x00", r"[\w./:()\[\]-]+")
        if re.fullmatch(pattern, text):
            return True
    return False


def allocate_port(db: Session) -> int:
    max_port = db.query(func.max(Website.port)).scalar()
    return (max_port + 1) if max_port else WEBAPP_PORT_START


# ---------- app detection ----------

# Directories that never contain the app entrypoint (and that we must not walk
# — venv/node_modules are huge).
_SKIP_DIRS = {"venv", ".venv", "env", "node_modules", "__pycache__", ".git",
              "static", "staticfiles", "dist", "build", "migrations", "tests",
              "logs", ".idea", ".vscode"}

# Filenames checked first — the conventional entrypoints, best guess on top.
_PREFERRED = ["app.py", "wsgi.py", "application.py", "main.py", "app_server.py",
              "server.py", "run.py", "asgi.py", "manage.py"]

_FLASK_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*Flask\s*\(", re.M)
_FASTAPI_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*FastAPI\s*\(", re.M)
_FACTORY_RE = re.compile(r"^\s*def\s+(create_app|make_app)\s*\(", re.M)

_MAX_SCAN_BYTES = 2 * 1024 * 1024      # don't read giant data files
_MAX_SCAN_DEPTH = 2                    # root + two levels is plenty


def _module_path(root: Path, file: Path) -> str:
    """`/srv/websites/x/pkg/app.py` → `pkg.app` (a gunicorn/uvicorn import path)."""
    rel = file.relative_to(root).with_suffix("")
    return ".".join(rel.parts)


def _candidate_files(root: Path) -> list[Path]:
    """
    Python files worth scanning, conventional entrypoints first.

    Walks manually rather than with rglob so that venv/ and node_modules/ are
    pruned instead of merely filtered out after being descended into — the
    site's own virtualenv holds tens of thousands of .py files.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        depth = len(here.relative_to(root).parts)
        if depth >= _MAX_SCAN_DEPTH:
            dirnames[:] = []            # deep enough — don't go further
        else:
            dirnames[:] = [d for d in dirnames
                           if d not in _SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = here / filename
            try:
                if path.stat().st_size > _MAX_SCAN_BYTES:
                    continue
            except OSError:
                continue
            found.append(path)

    def rank(p: Path) -> tuple[int, int, str]:
        name_rank = _PREFERRED.index(p.name) if p.name in _PREFERRED else len(_PREFERRED)
        depth = len(p.relative_to(root).parts) - 1
        return (depth, name_rank, p.name)

    return sorted(found, key=rank)


def detect_app(name: str) -> dict | None:
    """
    Work out how to start the uploaded app.

    Returns {framework, module, variable, target, run_command, file} for the
    first file that defines a Flask/FastAPI app (or an app factory), or None
    when nothing recognisable was uploaded.
    """
    root = site_dir(name)
    if not root.is_dir():
        return None

    factory_hit: dict | None = None

    for path in _candidate_files(root):
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for framework, regex in (("flask", _FLASK_RE), ("fastapi", _FASTAPI_RE)):
            match = regex.search(source)
            if not match:
                continue
            module, variable = _module_path(root, path), match.group(1)
            target = f"{module}:{variable}"
            return {
                "framework": framework,
                "module": module,
                "variable": variable,
                "target": target,
                "run_command": build_run_command(framework, target),
                "file": str(path.relative_to(root)),
            }

        # An app factory only counts if nothing exports a module-level app.
        if factory_hit is None and "Flask" in source:
            match = _FACTORY_RE.search(source)
            if match:
                module, variable = _module_path(root, path), f"{match.group(1)}()"
                target = f"{module}:{variable}"
                factory_hit = {
                    "framework": "flask",
                    "module": module,
                    "variable": variable,
                    "target": target,
                    "run_command": build_run_command("flask", target),
                    "file": str(path.relative_to(root)),
                }

    return factory_hit


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


def _build(name: str, framework: str | None = None) -> None:
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

        # The WSGI/ASGI server itself: without it the app can never start, and
        # requirements.txt very often lists only the framework.
        spec = FRAMEWORKS.get(normalise_framework(framework))
        if spec and not (vdir / "bin" / spec["server_bin"]).exists():
            _setup_log(name, f"installing {spec['server_package']} (needed to serve the app)")
            r = subprocess.run([pip, "install", spec["server_package"]],
                               capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                _setup_log(name, f"{spec['server_package']} install FAILED:\n"
                                 + (r.stderr or "")[-1500:])
            else:
                _setup_log(name, f"✓ {spec['server_bin']} installed")

        _setup_log(name, "✓ environment ready")
    except subprocess.TimeoutExpired:
        _setup_log(name, "TIMED OUT building the environment")
    except Exception as exc:  # noqa: BLE001
        _setup_log(name, f"error: {exc}")
    finally:
        with _lock:
            _building.discard(name)


def build_env_async(name: str, framework: str | None = None) -> bool:
    """Start building the venv + installing deps in the background."""
    with _lock:
        if name in _building:
            return False
        _building.add(name)
    # Fresh setup log each run so the UI shows just this build.
    p = setup_log_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("", encoding="utf-8")
    threading.Thread(target=_build, args=(name, framework), daemon=True).start()
    return True


# ---------- supervisor program ----------

# redirect_stderr: gunicorn and uvicorn both log to stderr, so without this the
# "App logs" view (which tails the .out.log) stays empty while the app is
# clearly running. One merged stream is what the user actually wants to read.
_TEMPLATE = """[program:{program}]
command={command}
directory={directory}
environment=PATH="{venv_bin}:/usr/local/bin:/usr/bin:/bin",PYTHONUNBUFFERED="1"
autostart=false
autorestart=true
stopasgroup=true
killasgroup=true
redirect_stderr=true
stdout_logfile={log_dir}/{program}.out.log
"""


def write_program(site: Website) -> None:
    """Write/refresh the supervisor program that runs the app."""
    if not site.run_command or not site.port:
        raise HTTPException(status_code=400, detail="Set a run command and port first")
    settings.SUPERVISOR_CONF_DIR.mkdir(parents=True, exist_ok=True)
    # Plain replace, not .format(): a run command may legitimately contain other
    # braces (gunicorn --access-logformat, shell expansions) that str.format
    # would choke on or eat.
    command = site.run_command.replace("{port}", str(site.port))
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
