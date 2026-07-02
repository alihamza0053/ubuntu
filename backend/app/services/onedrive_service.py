"""
OneDrive (read-only) sync lifecycle.

One company OneDrive account is synced into ONEDRIVE_ROOT (/srv/onedrive) by the
abraunegg `onedrive` Linux client running in --monitor --download-only mode.
Projects map to a subfolder of that tree (see routers/projects.py).

The client runs as the panel's own user (serverhub):
  - Authorization is performed by this process directly (a subprocess), so the
    refresh token lands in ONEDRIVE_CONFDIR which the panel user owns.
  - The continuous monitor runs as a Supervisor program named "onedrive" (with
    user=serverhub), driven through the existing supervisorctl sudo rule — so no
    new privileges are needed.

Headless authorization uses the client's `--auth-files "<url>:<resp>"` flow:
the client writes the Microsoft login URL to <url> and waits for the browser
redirect URL to appear in <resp>. The panel surfaces the URL, the admin signs in
and pastes the redirect URL back, and the client finishes and exits.
"""
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from fastapi import HTTPException

from ..config import settings
from . import supervisor_service

PROGRAM = "onedrive"
MONITOR_INTERVAL = 300

# Module-level handle for an in-progress authorization (single-flight).
_auth: dict = {"proc": None, "resp": None, "tmp": None}

# Whether a background resync is currently running.
_resync: dict = {"running": False}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def binary() -> str | None:
    return shutil.which("onedrive")


def is_installed() -> bool:
    return binary() is not None


def is_authorized() -> bool:
    """The client stores a refresh token in its confdir once authorized."""
    return (settings.ONEDRIVE_CONFDIR / "refresh_token").exists()


def monitor_status() -> str:
    """RUNNING / STOPPED / ERROR / UNKNOWN for the onedrive supervisor program."""
    result = supervisor_service.run_supervisorctl("status", PROGRAM)
    upper = (result.stdout + result.stderr).strip().upper()
    if "RUNNING" in upper or "STARTING" in upper:
        return "RUNNING"
    if "FATAL" in upper or "BACKOFF" in upper:
        return "ERROR"
    return "STOPPED"


def status() -> dict:
    installed = is_installed()
    return {
        "installed": installed,
        "authorized": installed and is_authorized(),
        "monitor": "RESYNCING" if _resync["running"] else (
            monitor_status() if installed else "STOPPED"),
        "resyncing": _resync["running"],
        "sync_dir": str(settings.ONEDRIVE_ROOT),
    }


# ---------------------------------------------------------------------------
# Authorization (headless, two-step)
# ---------------------------------------------------------------------------

def _confdir_args() -> list[str]:
    return ["--confdir", str(settings.ONEDRIVE_CONFDIR)]


def auth_start() -> str:
    """Begin authorization; return the Microsoft login URL for the admin."""
    if not is_installed():
        raise HTTPException(status_code=400, detail="OneDrive client is not installed yet")

    _cleanup_auth()
    tmp = Path(tempfile.mkdtemp(prefix="onedrive-auth-"))
    url_file, resp_file = tmp / "url", tmp / "resp"
    settings.ONEDRIVE_CONFDIR.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        [binary(), *_confdir_args(), "--auth-files", f"{url_file}:{resp_file}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    _auth.update(proc=proc, resp=resp_file, tmp=tmp)

    # The client writes the login URL to url_file, then polls for resp_file.
    for _ in range(60):  # up to ~15s
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            _cleanup_auth()
            raise HTTPException(status_code=500,
                                detail=f"OneDrive auth failed to start: {out[:300]}")
        if url_file.exists() and url_file.read_text(encoding="utf-8").strip():
            return url_file.read_text(encoding="utf-8").strip()
        time.sleep(0.25)

    _cleanup_auth()
    raise HTTPException(status_code=504, detail="Timed out getting the OneDrive login URL")


def auth_complete(response_url: str) -> None:
    """Finish authorization with the redirect URL the admin pasted back."""
    proc, resp = _auth.get("proc"), _auth.get("resp")
    if proc is None or resp is None:
        raise HTTPException(status_code=400, detail="Start authorization first")
    if "nativeclient?code=" not in response_url and "code=" not in response_url:
        raise HTTPException(status_code=400, detail="That doesn't look like the redirect URL")

    Path(resp).write_text(response_url.strip(), encoding="utf-8")
    try:
        proc.wait(timeout=45)
    except subprocess.TimeoutExpired:
        proc.kill()
        _cleanup_auth()
        raise HTTPException(status_code=504, detail="OneDrive authorization timed out")

    out = proc.stdout.read() if proc.stdout else ""
    code = proc.returncode
    _cleanup_auth()
    if code != 0 or not is_authorized():
        raise HTTPException(status_code=500,
                            detail=f"OneDrive authorization failed: {out[:300]}")


def _cleanup_auth() -> None:
    proc = _auth.get("proc")
    if proc is not None and proc.poll() is None:
        proc.kill()
    tmp = _auth.get("tmp")
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
    _auth.update(proc=None, resp=None, tmp=None)


# ---------------------------------------------------------------------------
# Monitor (continuous download-only sync via Supervisor)
# ---------------------------------------------------------------------------

SUPERVISOR_TEMPLATE = """[program:{program}]
command={bin} --monitor --confdir {confdir} --download-only --monitor-interval {interval}
directory=/srv/serverhub
user=serverhub
autostart=true
autorestart=true
environment=HOME="/srv/serverhub"
stderr_logfile={log_dir}/{program}.err.log
stdout_logfile={log_dir}/{program}.out.log
"""


def write_monitor_program() -> None:
    """Write/refresh the Supervisor program that runs the monitor."""
    if not is_installed():
        raise HTTPException(status_code=400, detail="OneDrive client is not installed yet")
    settings.SUPERVISOR_CONF_DIR.mkdir(parents=True, exist_ok=True)
    content = SUPERVISOR_TEMPLATE.format(
        program=PROGRAM,
        bin=binary(),
        confdir=settings.ONEDRIVE_CONFDIR,
        interval=MONITOR_INTERVAL,
        log_dir=settings.SUPERVISOR_LOG_DIR,
    )
    (settings.SUPERVISOR_CONF_DIR / f"{PROGRAM}.conf").write_text(content, encoding="utf-8")
    supervisor_service.run_supervisorctl("reread")
    supervisor_service.run_supervisorctl("update")


def control(action: str) -> str:
    """start / stop / restart the monitor. 'restart' doubles as 'sync now'
    (the client does an immediate pull on (re)start)."""
    if action not in ("start", "stop", "restart"):
        raise HTTPException(status_code=400, detail="action must be start/stop/restart")
    if not is_authorized():
        raise HTTPException(status_code=400, detail="Authorize OneDrive first")
    # Make sure the program exists before controlling it.
    if not (settings.SUPERVISOR_CONF_DIR / f"{PROGRAM}.conf").exists():
        write_monitor_program()
    result = supervisor_service.run_supervisorctl(action, PROGRAM)
    out = (result.stdout + result.stderr).strip()
    if "ERROR" in out and "already started" not in out:
        raise HTTPException(status_code=500, detail=f"supervisorctl {action}: {out}")
    return out


def resync() -> str:
    """
    Run a one-time full resync, then resume the monitor. Needed after enabling
    shared-item syncing (the client refuses scope changes without --resync).
    Runs in the background; the monitor is stopped during the resync and
    restarted afterward.
    """
    if not is_installed():
        raise HTTPException(status_code=400, detail="OneDrive client is not installed yet")
    if not is_authorized():
        raise HTTPException(status_code=400, detail="Authorize OneDrive first")
    if _resync["running"]:
        return "A resync is already running…"

    log_path = settings.SUPERVISOR_LOG_DIR / "onedrive-resync.log"

    def _run() -> None:
        try:
            supervisor_service.run_supervisorctl("stop", PROGRAM)
            with open(log_path, "w", encoding="utf-8") as log:
                subprocess.run(
                    [binary(), *_confdir_args(), "--download-only",
                     "--synchronize", "--resync", "--resync-auth"],
                    stdout=log, stderr=subprocess.STDOUT, timeout=3600,
                )
        except Exception:
            pass
        finally:
            _resync["running"] = False
            # Always bring the live monitor back up.
            try:
                write_monitor_program()
                supervisor_service.run_supervisorctl("restart", PROGRAM)
            except Exception:
                pass

    _resync["running"] = True
    threading.Thread(target=_run, daemon=True).start()
    return "Resync started — pulling all files incl. shared items (watch the monitor status)"
