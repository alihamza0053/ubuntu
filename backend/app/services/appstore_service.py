"""
Apps section: install and run off-the-shelf software on the server.

Two kinds of app, one lifecycle:

  desktop (chromium, brave)
      A real browser window on a virtual X display. The generated run script
      starts Xvfb, a tiny window manager, x11vnc and the noVNC web bridge, then
      the browser — so you open the app's port in your own browser and drive it.

  web (n8n)
      Plain HTTP service; the run script just sets its environment and execs it.

  api (ollama)
      Like web, but with no login of its own: it listens on 127.0.0.1 only and
      its domain's nginx block lets through only requests carrying its API key.

Both end up as one supervisor program (`app_<key>`) running one generated
`run.sh`, which keeps start/stop/restart/logs/domain identical for every app —
exactly the plumbing Projects and Websites already use.

Installing needs root (apt/npm), so it goes through deploy/serverhub-apps.sh
under the restricted sudoers rule. That helper accepts three fixed app names
and hard-codes every package list; nothing here can widen it. Everything after
installation runs as the unprivileged panel user.

All subprocess calls use argument lists — never shell=True.
"""
from __future__ import annotations

import re
import secrets
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ManagedApp
from . import nginx_service, supervisor_service

# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
# `kind`  desktop = shown over noVNC, web = plain HTTP service
# `port`  preferred HTTP port (noVNC's web port for desktop apps)
CATALOG: dict[str, dict] = {
    "n8n": {
        "label": "n8n",
        "icon": "🔗",
        "kind": "web",
        "port": 5678,
        "summary": "Workflow automation — connect APIs, databases and scripts "
                   "with a visual editor.",
        "notes": "On first open n8n asks you to create an owner account; that "
                 "account is what protects it, so set it up straight away.",
        "install_hint": "Installs Node.js 20 LTS (if this server hasn't got it) "
                        "and n8n from npm. Takes a few minutes.",
    },
    "chromium": {
        "label": "Chromium",
        "icon": "🌐",
        "kind": "desktop",
        "port": 6080,
        "summary": "The open-source browser, on a virtual display you view in "
                   "your own browser over noVNC.",
        "notes": "Where Ubuntu only ships Chromium as a snap, the panel uses "
                 "that and keeps its profile under the panel user's home — a "
                 "confined snap cannot read /srv.",
        "install_hint": "Installs Chromium plus the headless-desktop stack "
                        "(Xvfb, x11vnc, noVNC, openbox).",
    },
    "brave": {
        "label": "Brave",
        "icon": "🦁",
        "kind": "desktop",
        "port": 6081,
        "summary": "Chromium-based browser with ad and tracker blocking built "
                   "in. Same noVNC view as Chromium.",
        "notes": "Installed from Brave's own APT repository — no snap, so its "
                 "profile lives with the rest of the app data under /srv/apps.",
        "install_hint": "Installs Brave plus the headless-desktop stack "
                        "(Xvfb, x11vnc, noVNC, openbox).",
    },
    "ollama": {
        "label": "Ollama",
        "icon": "🦙",
        "kind": "api",
        "port": 11434,
        "summary": "Run open AI models (Llama, Qwen, Mistral, Gemma…) on this "
                   "server and use them from anywhere through an API.",
        "notes": "API only — no web page. Ollama listens on 127.0.0.1, so it is "
                 "reachable from outside only through its domain, and only with "
                 "the API key (Authorization: Bearer <key>). Works with "
                 "OpenAI-compatible tools at <domain>/v1.",
        "install_hint": "Installs Ollama with its official installer (a few hundred "
                        "MB). Models are pulled separately on the Models tab.",
    },
}
DESKTOP_KINDS = {"desktop"}
# API-only apps: no page to open, reachable only through their key-protected domain.
API_KINDS = {"api"}

# Chromium/Brave flags. --no-sandbox is needed because the app runs as an
# unprivileged system user with no setuid sandbox helper available; the browser
# is already confined to this box and reachable only through noVNC's password.
BROWSER_FLAGS = [
    "--no-sandbox",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--password-store=basic",
    "--start-maximized",
]

_installing: set[str] = set()
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Paths / naming
# ---------------------------------------------------------------------------

def spec(key: str) -> dict:
    """Catalogue entry for `key`, or 404."""
    entry = CATALOG.get(key)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown app: {key}")
    return entry


def app_dir(key: str) -> Path:
    return settings.APPS_ROOT / key


def run_script_path(key: str) -> Path:
    return app_dir(key) / "run.sh"


def vnc_password_path(key: str) -> Path:
    return app_dir(key) / "vnc.pass"


def install_log_path(key: str) -> Path:
    return app_dir(key) / "logs" / "install.log"


def install_env_path(key: str) -> Path:
    return app_dir(key) / "install.env"


def program_name(key: str) -> str:
    return f"app_{key}"


def config_path(key: str) -> Path:
    return settings.SUPERVISOR_CONF_DIR / f"{program_name(key)}.conf"


def log_path(key: str) -> Path:
    return settings.SUPERVISOR_LOG_DIR / f"{program_name(key)}.out.log"


def nginx_slug(key: str) -> str:
    return f"app-{key}"


def url_path(key: str) -> str:
    """
    Path to open on the app's port or domain.

    The novnc package ships vnc.html rather than an index, so a desktop app's
    link has to name it; autoconnect+scale means one click gets you a fitted
    screen with only the password left to type.
    """
    if spec(key)["kind"] in DESKTOP_KINDS:
        return "/vnc.html?autoconnect=true&resize=scale"
    return "/"


def ensure_dirs(key: str) -> None:
    """Create the app's data/log directories (as the panel user).

    /srv/apps itself is created and handed over by the installer (see
    deploy/install.sh), so a failure here means the panel was deployed without
    that step and is worth saying out loud rather than crashing on a traceback.
    """
    try:
        (app_dir(key) / "logs").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Cannot write to {settings.APPS_ROOT} ({exc}). Re-run "
                   f"deploy/update.sh so it creates the Apps data directory.",
        ) from exc


# ---------------------------------------------------------------------------
# Installation state
# ---------------------------------------------------------------------------

def read_install_env(key: str) -> dict[str, str]:
    """Parse the key=value file the installer helper leaves behind."""
    path = install_env_path(key)
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            name, sep, value = line.partition("=")
            if sep:
                out[name.strip()] = value.strip()
    except OSError:
        return {}
    return out


def is_installed(key: str) -> bool:
    """True when the app's executable is actually on this server.

    The install.env file is the record of a panel-driven install, but the
    binary is the truth — someone may have removed it by hand.
    """
    env = read_install_env(key)
    binary = env.get("bin")
    if binary and Path(binary).exists():
        return True
    if binary and shutil.which(Path(binary).name):
        return True
    # Nothing recorded: fall back to looking for the usual executables.
    names = {"chromium": ("chromium", "chromium-browser"),
             "brave": ("brave-browser",),
             "n8n": ("n8n",),
             "ollama": ("ollama",)}.get(key, ())
    return any(shutil.which(n) for n in names)


def is_installing(key: str) -> bool:
    with _lock:
        return key in _installing


def install_state(key: str) -> str:
    """INSTALLED / INSTALLING / MISSING — what the card shows."""
    if is_installing(key):
        return "INSTALLING"
    return "INSTALLED" if is_installed(key) else "MISSING"


def _log_install(key: str, line: str) -> None:
    path = install_log_path(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {line}\n")
    except OSError:
        pass


def _run_helper(key: str, action: str) -> None:
    """Stream `serverhub-apps <action> <key>` into the app's install log."""
    cmd = ["sudo", "-n", str(settings.APPS_BIN), action, key]
    _log_install(key, f"$ {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
    except FileNotFoundError:
        _log_install(key, f"✗ {settings.APPS_BIN} not found — re-run "
                          f"deploy/update.sh to install the Apps helper.")
        return
    with proc.stdout:                       # type: ignore[union-attr]
        for line in proc.stdout:            # type: ignore[union-attr]
            _log_install(key, line.rstrip())
    code = proc.wait()
    _log_install(key, f"✓ finished" if code == 0 else f"✗ exited with code {code}")


def _install_worker(key: str, action: str, purge_after: bool) -> None:
    try:
        _run_helper(key, action)
    finally:
        # Only now is it safe to delete the data directory: the helper logs
        # into it, and wiping it while that is running just recreates it.
        if purge_after:
            shutil.rmtree(app_dir(key), ignore_errors=True)
        with _lock:
            _installing.discard(key)


def start_install(key: str, action: str = "install",
                  purge_after: bool = False) -> bool:
    """
    Kick off install/remove in the background. False if one is already running.

    `purge_after` deletes the app's data directory once the helper has finished
    (uninstall with "delete data too").
    """
    spec(key)
    ensure_dirs(key)
    with _lock:
        if key in _installing:
            return False
        _installing.add(key)
    # Fresh log per run so the live view shows only this attempt.
    try:
        install_log_path(key).write_text("", encoding="utf-8")
    except OSError:
        pass
    threading.Thread(target=_install_worker, args=(key, action, purge_after),
                     daemon=True).start()
    return True


# ---------------------------------------------------------------------------
# Registration (the DB row that holds port / display / domain)
# ---------------------------------------------------------------------------

def allocate_port(db: Session, key: str) -> int:
    """The catalogue's preferred port, nudged up past anything already taken."""
    taken = {row.port for row in db.query(ManagedApp).all()}
    port = spec(key)["port"]
    while port in taken:
        port += 1
    return port


def allocate_display(db: Session) -> int:
    """Next free X display number for a desktop app."""
    used = {row.display for row in db.query(ManagedApp).all() if row.display}
    display = settings.APP_DISPLAY_START
    while display in used:
        display += 1
    return display


def vnc_port(app: ManagedApp) -> int:
    """x11vnc's own port — localhost only; noVNC is what's exposed."""
    return 5900 + (app.display or 0)


def new_api_key() -> str:
    """A fresh API key: "sk-" (what AI tools expect a key to look like) + 40
    URL-safe characters."""
    return "sk-" + secrets.token_urlsafe(30)


def get_or_create(db: Session, key: str) -> ManagedApp:
    """The row for `key`, created with fresh port/display/password if new."""
    entry = spec(key)
    app = db.query(ManagedApp).filter(ManagedApp.key == key).first()
    if app:
        return app
    app = ManagedApp(key=key, port=allocate_port(db, key), status="STOPPED")
    if entry["kind"] in DESKTOP_KINDS:
        app.display = allocate_display(db)
        # 8 characters exactly: x11vnc silently truncates a VNC password there,
        # so a longer one would only look stronger than it is.
        app.vnc_password = secrets.token_urlsafe(6)
        app.start_url = "https://duckduckgo.com"
    if entry["kind"] in API_KINDS:
        app.api_key = new_api_key()
    db.add(app)
    db.commit()
    db.refresh(app)
    return app


# ---------------------------------------------------------------------------
# Run script generation
# ---------------------------------------------------------------------------

_DESKTOP_RUN = """#!/usr/bin/env bash
# Generated by ServerHub — regenerated on every Start/Restart, do not edit.
#
# Brings up a one-window desktop and publishes it over noVNC:
#   Xvfb        the virtual display the browser draws on
#   openbox     a window manager, so dialogs and resizing behave
#   x11vnc      serves that display on 127.0.0.1 only
#   websockify  bridges noVNC's web port to it
# The browser is last and runs in the foreground: when it exits, the trap tears
# the rest down so supervisor's restart gets a clean display to start on.
set -u

export HOME="{home}"
export DISPLAY=":{display}"
export XDG_RUNTIME_DIR="{home}/.xdg"
mkdir -p "$HOME" "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"

PIDS=""
cleanup() {{
  for pid in $PIDS; do kill "$pid" 2>/dev/null; done
  rm -f "/tmp/.X{display}-lock"
}}
trap cleanup EXIT INT TERM

# A previous crash can leave the display locked; Xvfb refuses to start on it.
rm -f "/tmp/.X{display}-lock"

Xvfb ":{display}" -screen 0 {screen} -nolisten tcp &
PIDS="$PIDS $!"
for _ in $(seq 1 60); do
  xdpyinfo -display ":{display}" >/dev/null 2>&1 && break
  sleep 0.25
done
xdpyinfo -display ":{display}" >/dev/null 2>&1 || {{ echo "Xvfb failed to start"; exit 1; }}

if command -v openbox >/dev/null 2>&1; then
  openbox &
  PIDS="$PIDS $!"
fi

x11vnc -display ":{display}" -rfbport {vnc_port} -passwdfile "{passwd_file}" \\
       -localhost -forever -shared -noxdamage -quiet &
PIDS="$PIDS $!"

websockify --web="{novnc_root}" {port} "127.0.0.1:{vnc_port}" &
PIDS="$PIDS $!"

echo "[serverhub] {label} ready — noVNC on port {port}, display :{display}"
"{bin}" {flags} "{start_url}"
"""

_WEB_RUN = """#!/usr/bin/env bash
# Generated by ServerHub — regenerated on every Start/Restart, do not edit.
set -u

export HOME="{home}"
mkdir -p "$HOME"

{env_lines}

echo "[serverhub] starting {label} on port {port}"
exec "{bin}" {args}
"""


def _write_vnc_password(app: ManagedApp) -> Path:
    """(Re)write the x11vnc password file, readable only by the panel user."""
    path = vnc_password_path(app.key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((app.vnc_password or "") + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _n8n_env(app: ManagedApp) -> list[str]:
    """Environment for n8n, including the public URL it builds webhooks from."""
    home = read_install_env(app.key).get("home") or str(app_dir(app.key) / "home")
    https = bool(app.domain) and nginx_service.has_cert(app.domain)
    host = app.domain or "0.0.0.0"
    lines = [
        f'export N8N_USER_FOLDER="{home}"',
        f'export N8N_PORT={app.port}',
        'export N8N_LISTEN_ADDRESS=0.0.0.0',
        f'export N8N_HOST="{host}"',
        f'export N8N_PROTOCOL="{"https" if https else "http"}"',
        'export N8N_DIAGNOSTICS_ENABLED=false',
        'export N8N_RUNNERS_ENABLED=true',
        'export N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true',
    ]
    if app.domain:
        scheme = "https" if https else "http"
        lines.append(f'export WEBHOOK_URL="{scheme}://{app.domain}/"')
    if not https:
        # n8n 1.x refuses to hand out its auth cookie over plain HTTP unless
        # this is off, which locks you out of a not-yet-SSL'd install.
        lines.append('export N8N_SECURE_COOKIE=false')
    return lines


def models_dir(key: str = "ollama") -> Path:
    """Where Ollama keeps downloaded models (they are large — GBs each)."""
    return app_dir(key) / "models"


def _ollama_env(app: ManagedApp) -> list[str]:
    """
    Environment for `ollama serve`.

    127.0.0.1 only: Ollama has no authentication, so it must never listen on
    a public address — the key-checking nginx block is the only way in.
    """
    return [
        f'export OLLAMA_HOST="127.0.0.1:{app.port}"',
        f'export OLLAMA_MODELS="{models_dir(app.key)}"',
        f'mkdir -p "{models_dir(app.key)}"',
        # Browser clients on other sites send an Origin header; allow them (the
        # API key at nginx is what actually guards access).
        'export OLLAMA_ORIGINS="*"',
        # Keep a model in memory for 10 minutes after the last request, so a
        # conversation doesn't reload it from disk every message.
        'export OLLAMA_KEEP_ALIVE="10m"',
    ]


def write_run_script(app: ManagedApp) -> Path:
    """Generate the app's run.sh from its current settings."""
    entry = spec(app.key)
    env = read_install_env(app.key)
    binary = env.get("bin")
    if not binary:
        raise HTTPException(
            status_code=400,
            detail=f"{entry['label']} isn't installed yet — install it first.")

    ensure_dirs(app.key)
    home = env.get("home") or str(app_dir(app.key) / "home")
    path = run_script_path(app.key)

    if entry["kind"] in DESKTOP_KINDS:
        novnc_root = env.get("novnc") or "/usr/share/novnc"
        flags = list(BROWSER_FLAGS)
        # A confined snap can only read the panel user's home, so its profile
        # has to live there; install.env already points `home` at it.
        flags.append(f"--user-data-dir={home}/profile")
        content = _DESKTOP_RUN.format(
            home=home,
            display=app.display,
            screen=settings.APP_SCREEN,
            vnc_port=vnc_port(app),
            passwd_file=_write_vnc_password(app),
            novnc_root=novnc_root,
            port=app.port,
            bin=binary,
            flags=" ".join(f'"{f}"' for f in flags),
            start_url=app.start_url or "about:blank",
            label=entry["label"],
        )
    else:
        env_lines = {"n8n": _n8n_env, "ollama": _ollama_env}.get(app.key)
        content = _WEB_RUN.format(
            home=home,
            env_lines="\n".join(env_lines(app)) if env_lines else "",
            bin=binary,
            args={"n8n": "start", "ollama": "serve"}.get(app.key, ""),
            port=app.port,
            label=entry["label"],
        )

    path.write_text(content, encoding="utf-8")
    path.chmod(0o750)
    return path


# ---------------------------------------------------------------------------
# Supervisor program
# ---------------------------------------------------------------------------
# stopasgroup/killasgroup matter more here than anywhere else in the panel: a
# desktop app is five processes in one group, and a stop that only reached the
# script would leave Xvfb holding the display.
_PROGRAM = """[program:{program}]
command=/bin/bash {run_script}
directory={directory}
environment=PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin",HOME="{home}"
autostart=false
autorestart=true
startsecs=5
stopasgroup=true
killasgroup=true
stopwaitsecs=20
redirect_stderr=true
stdout_logfile={log_dir}/{program}.out.log
"""


def write_program(app: ManagedApp) -> None:
    """
    Write/refresh the supervisor program for an app.

    Same no-op discipline as supervisor_service.write_config: `update` stops
    and re-adds any program whose config changed, so preserve the on-disk
    autostart and skip identical writes rather than killing a running app.
    """
    run_script = write_run_script(app)
    env = read_install_env(app.key)
    settings.SUPERVISOR_CONF_DIR.mkdir(parents=True, exist_ok=True)
    content = _PROGRAM.format(
        program=program_name(app.key),
        run_script=run_script,
        directory=app_dir(app.key),
        home=env.get("home") or str(app_dir(app.key) / "home"),
        log_dir=settings.SUPERVISOR_LOG_DIR,
    )
    path = config_path(app.key)
    existing = path.read_text(encoding="utf-8") if path.exists() else None

    if existing is not None:
        current = re.search(r"(?m)^autostart=(.*)$", existing)
        if current:
            content = re.sub(r"(?m)^autostart=.*$",
                             f"autostart={current.group(1)}", content)
        if content == existing:
            return                      # unchanged — leave a running app alone

    path.write_text(content, encoding="utf-8")
    supervisor_service.run_supervisorctl("reread")
    supervisor_service.run_supervisorctl("update")


def set_autostart(key: str, enabled: bool) -> None:
    """Persist the desired run-state so the app survives a reboot. autostart is
    only read when supervisord boots, so rewriting the file is enough — no
    reread/update, which would restart the app right now."""
    path = config_path(key)
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    new = re.sub(r"(?m)^autostart=.*$",
                 f"autostart={'true' if enabled else 'false'}", text)
    if new != text:
        path.write_text(new, encoding="utf-8")


def control(app: ManagedApp, action: str) -> str:
    """start / stop / restart, writing the program first if it's missing."""
    if action not in ("start", "stop", "restart"):
        raise HTTPException(status_code=400, detail="action must be start/stop/restart")
    if not is_installed(app.key):
        raise HTTPException(status_code=400,
                            detail=f"{spec(app.key)['label']} isn't installed yet")
    # Always refresh before starting: the run script embeds the domain, port
    # and start URL, any of which may have been edited since the last start.
    if action in ("start", "restart"):
        write_program(app)
        set_autostart(app.key, True)
    elif not config_path(app.key).exists():
        return "not configured"

    result = supervisor_service.run_supervisorctl(action, program_name(app.key))
    out = (result.stdout + result.stderr).strip()
    if "ERROR" in out and not supervisor_service.is_benign_output(out):
        raise HTTPException(status_code=500, detail=f"supervisorctl {action}: {out}")
    if action == "stop":
        set_autostart(app.key, False)
    return out


def status(key: str) -> str:
    """RUNNING / STOPPED / ERROR for an app's supervisor program."""
    if not config_path(key).exists():
        return "STOPPED"
    result = supervisor_service.run_supervisorctl("status", program_name(key))
    upper = (result.stdout + result.stderr).strip().upper()
    if "RUNNING" in upper or "STARTING" in upper:
        return "RUNNING"
    if "FATAL" in upper or "BACKOFF" in upper:
        return "ERROR"
    return "STOPPED"


def remove_program(key: str) -> None:
    """Stop the app and delete its supervisor program (on uninstall)."""
    try:
        supervisor_service.run_supervisorctl("stop", program_name(key))
    except HTTPException:
        pass
    path = config_path(key)
    if path.exists():
        path.unlink()
    supervisor_service.run_supervisorctl("reread")
    supervisor_service.run_supervisorctl("update")


# ---------------------------------------------------------------------------
# Domains
# ---------------------------------------------------------------------------

def nginx_block(app: ManagedApp, domain: str) -> str:
    """
    The proxy block for an app.

    Both kinds need the websocket upgrade passed through — noVNC *is* a
    websocket, and n8n pushes execution updates over one — so the ASGI-style
    block is right for the browser apps and n8n. An API app (Ollama) has no
    login of its own, so its block only lets requests carrying its key through.
    """
    if spec(app.key)["kind"] in API_KINDS:
        if not app.api_key:
            raise HTTPException(status_code=400, detail="This app has no API key yet")
        return nginx_service.api_key_block(domain, app.port, app.api_key, app.key)
    return nginx_service.asgi_block(domain, app.port)
