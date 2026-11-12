"""
Run-it-yourself web services: Websites of type "python" and "node".

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

Node.js apps ("node" type) reuse all of it: `npm ci` instead of a venv, and
`node <entry file>` instead of gunicorn/uvicorn. The app gets its port in the
PORT environment variable, the way Node apps expect.

Runs as the panel's `serverhub` user, which owns /srv/websites — no sudo for the
venv/pip/npm work; supervisorctl uses the existing restricted sudo rule.
"""
import json
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Website
from . import app_detect, db_env, supervisor_service

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

SERVICE_TYPES = ("python", "node")      # website types the panel runs as a service
NODE_DEFAULT_COMMAND = "node server.js"
NODE_ENTRY_FILES = ("server.js", "app.js", "index.js", "main.js",
                    "src/server.js", "src/app.js", "src/index.js")
_SAFE_ENTRY = re.compile(r"[\w./-]+\.(?:c|m)?js")

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


def node_ready_marker(name: str) -> Path:
    """Written after a successful `npm ci`: an uploaded node_modules (often
    built on Windows) doesn't count as installed."""
    return site_dir(name) / "logs" / ".deps-ready"


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


def is_default_node_command(command: str | None) -> bool:
    """A `node <file>` command the panel wrote, as opposed to one typed by hand."""
    text = (command or "").strip()
    return not text or re.fullmatch(r"node " + _SAFE_ENTRY.pattern, text) is not None


def allocate_port(db: Session) -> int:
    max_port = db.query(func.max(Website.port)).scalar()
    return (max_port + 1) if max_port else WEBAPP_PORT_START


# ---------- app detection ----------

def detect_app(name: str) -> dict | None:
    """
    Work out how to start the uploaded app.

    Returns {framework, module, variable, target, run_command, file} for the
    first file that defines a Flask/FastAPI app (or an app factory), or None
    when nothing recognisable was uploaded. Streamlit is excluded: a website
    is served over a port by a WSGI/ASGI server, and a Streamlit script has
    no import target to hand one. (Streamlit belongs in Projects → dashboard/.)
    """
    found = app_detect.detect(site_dir(name), allowed=("flask", "fastapi"))
    if found is None:
        return None
    return {**found,
            "run_command": build_run_command(found["framework"], found["target"])}


def detect_node(name: str) -> dict | None:
    """
    The entry file of an uploaded Node.js app: `scripts.start` when it is a plain
    `node <file>`, else package.json `main`, else a conventional file name.
    """
    root = site_dir(name)
    if not (root / "package.json").is_file():
        return None
    try:
        data = json.loads((root / "package.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    candidates = []
    scripts = data.get("scripts")
    start = scripts.get("start") if isinstance(scripts, dict) else None
    match = re.fullmatch(r"node\s+(\S+)", start.strip()) if isinstance(start, str) else None
    if match:
        candidates.append(match.group(1))
    if isinstance(data.get("main"), str):
        candidates.append(data["main"])
    candidates.extend(NODE_ENTRY_FILES)
    base = root.resolve()
    for candidate in candidates:
        rel = candidate.strip().replace("\\", "/")
        rel = rel[2:] if rel.startswith("./") else rel
        if not _SAFE_ENTRY.fullmatch(rel) or ".." in rel.split("/"):
            continue
        path = (base / rel).resolve()
        if base in path.parents and path.is_file():
            return {"framework": "node", "file": rel, "target": rel,
                    "run_command": f"node {rel}"}
    return None


def flatten_single_folder(name: str) -> str | None:
    """
    A zip made by right-clicking the app folder holds everything inside one
    folder. Move that folder's contents up so package.json sits at the top.
    Returns the folder name when it did so.
    """
    root = site_dir(name)
    if (root / "package.json").is_file():
        return None
    entries = [e for e in root.iterdir() if e.name != "__MACOSX"]
    if len(entries) != 1 or not entries[0].is_dir() or not (entries[0] / "package.json").is_file():
        return None
    inner = entries[0]
    children = list(inner.iterdir())
    if any((root / child.name).exists() for child in children):
        return None
    for child in children:
        shutil.move(str(child), str(root / child.name))
    inner.rmdir()
    return inner.name


# ---------- venv + dependency build (background) ----------

def env_status(name: str, kind: str = "python") -> str:
    """READY / BUILDING / MISSING for the UI."""
    ready = (node_ready_marker(name).exists() and (site_dir(name) / "node_modules").is_dir()
             if kind == "node" else (venv_dir(name) / "bin" / "python").exists())
    if ready:
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


def _build_node(name: str) -> None:
    root = site_dir(name)
    try:
        node_ready_marker(name).unlink(missing_ok=True)
        if not (root / "package.json").is_file():
            _setup_log(name, "no package.json found — upload the app first")
            return
        node, npm = shutil.which("node"), shutil.which("npm")
        if not node or not npm:
            _setup_log(name, "Node.js isn't installed on this server — run the panel update, "
                             "which installs it")
            return
        version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30)
        _setup_log(name, f"Node.js {version.stdout.strip()}")
        env = {**os.environ,
               "npm_config_cache": str(settings.PANEL_ROOT / "cache" / "npm"),
               "npm_config_update_notifier": "false",
               "npm_config_fund": "false",
               "npm_config_audit": "false"}
        # `npm ci` rebuilds node_modules from scratch, which replaces packages
        # compiled for another system (an upload made on Windows).
        steps = []
        if (root / "package-lock.json").is_file():
            steps.append(["ci", "--omit=dev"])
        steps.append(["install", "--omit=dev"])
        for step in steps:
            _setup_log(name, "npm " + " ".join(step))
            r = subprocess.run([npm, *step], cwd=root, env=env,
                               capture_output=True, text=True, timeout=1800)
            _setup_log(name, ((r.stdout or "") + (r.stderr or ""))[-4000:])
            if r.returncode == 0:
                node_ready_marker(name).write_text("", encoding="utf-8")
                _setup_log(name, "✓ dependencies installed")
                _setup_log(name, "✓ environment ready")
                return
            _setup_log(name, f"npm {step[0]} FAILED")
    except subprocess.TimeoutExpired:
        _setup_log(name, "TIMED OUT installing dependencies")
    except Exception as exc:  # noqa: BLE001
        _setup_log(name, f"error: {exc}")
    finally:
        with _lock:
            _building.discard(name)


def build_env_async(name: str, framework: str | None = None, kind: str = "python") -> bool:
    """Start installing the app's dependencies in the background."""
    with _lock:
        if name in _building:
            return False
        _building.add(name)
    # Fresh setup log each run so the UI shows just this build.
    p = setup_log_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("", encoding="utf-8")
    if kind == "node":
        threading.Thread(target=_build_node, args=(name,), daemon=True).start()
    else:
        threading.Thread(target=_build, args=(name, framework), daemon=True).start()
    return True


# ---------- supervisor program ----------

# redirect_stderr: gunicorn and uvicorn both log to stderr, so without this the
# "App logs" view (which tails the .out.log) stays empty while the app is
# clearly running. One merged stream is what the user actually wants to read.
_TEMPLATE = """[program:{program}]
command={command}
directory={directory}
{run_as}environment=PATH="{venv_bin}:/usr/local/bin:/usr/bin:/bin",PYTHONUNBUFFERED="1"{run_env}{db_env}
autostart=false
autorestart=true
stopasgroup=true
killasgroup=true
redirect_stderr=true
stdout_logfile={log_dir}/{program}.out.log
"""

# Node apps take their port from PORT. A PORT in the app's own .env doesn't
# override it: dotenv never replaces a variable that is already set.
_NODE_TEMPLATE = _TEMPLATE.replace(
    'environment=PATH="{venv_bin}:/usr/local/bin:/usr/bin:/bin",PYTHONUNBUFFERED="1"',
    'environment=PATH="/usr/local/bin:/usr/bin:/bin",NODE_ENV="production",PORT="{port}"')


def write_program(site: Website) -> None:
    """
    Write/refresh the supervisor program that runs the app.

    Preserves the on-disk `autostart` and skips identical writes, for the same
    reason as supervisor_service.write_config: `update` stops and re-adds any
    program whose config changed, so a pointless rewrite would kill a running
    app and make the next restart report "ERROR (not running)".
    """
    if not site.run_command or not site.port:
        raise HTTPException(status_code=400, detail="Set a run command and port first")
    settings.SUPERVISOR_CONF_DIR.mkdir(parents=True, exist_ok=True)
    # Plain replace, not .format(): a run command may legitimately contain other
    # braces (gunicorn --access-logformat, shell expansions) that str.format
    # would choke on or eat.
    command = site.run_command.replace("{port}", str(site.port))
    template = _NODE_TEMPLATE if site.type == "node" else _TEMPLATE
    content = template.format(
        program=program_name(site.name),
        command=command,
        directory=site_dir(site.name),
        venv_bin=venv_dir(site.name) / "bin",
        port=site.port,
        log_dir=settings.SUPERVISOR_LOG_DIR,
        db_env=db_env.supervisor_env("website", site.name),   # linked PostgreSQL, if any
        run_as=supervisor_service.run_as_line(), run_env=supervisor_service.run_as_env(),
    )
    path = config_path(site.name)
    existing = path.read_text(encoding="utf-8") if path.exists() else None

    if existing is not None:
        current = re.search(r"(?m)^autostart=(.*)$", existing)
        if current:
            content = re.sub(r"(?m)^autostart=.*$",
                             f"autostart={current.group(1)}", content)
        if content == existing:
            return                  # unchanged — leave a running app alone

    path.write_text(content, encoding="utf-8")
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
        if supervisor_service.switch_program_user(config_path(site.name), "website", site.name,
                                                  program_name(site.name)):
            action = "start"                       # `update` already restarted it
    result = supervisor_service.run_supervisorctl(action, program_name(site.name))
    out = (result.stdout + result.stderr).strip()
    if "ERROR" in out and not supervisor_service.is_benign_output(out):
        raise HTTPException(status_code=500, detail=f"supervisorctl {action}: {out}")
    if action == "stop":
        set_autostart(site.name, False)
    return out


def status(name: str) -> str:
    """RUNNING / STOPPED / ERROR for a python/node website program."""
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
