"""
Async script runner.

Runs a project script with the configured Python interpreter, streams
combined stdout/stderr line-by-line to an optional callback (used by the
WebSocket endpoint), writes the full output to the project's logs/ folder
and records the result on the Script row.

Subprocesses are spawned with an argument list — never a shell string.
"""
import asyncio
import os
import signal
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..database import SessionLocal
from ..models import Script
from .activity import log_activity

# Currently-running script processes, keyed by script id, so they can be
# stopped. Scripts run in their own process group (start_new_session=True) so
# stopping also kills any child processes they spawned (e.g. headless Chrome).
_running: dict[int, asyncio.subprocess.Process] = {}
_stopped: set[int] = set()


def is_running(script_id: int) -> bool:
    proc = _running.get(script_id)
    return proc is not None and proc.returncode is None


def stop_script(script_id: int) -> bool:
    """Kill a running script (and its child processes). Returns True if it was running."""
    proc = _running.get(script_id)
    if proc is None or proc.returncode is not None:
        return False
    _stopped.add(script_id)
    try:
        # Kill the whole process group (script + Chrome/chromedriver children)
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, AttributeError, OSError):
        try:
            proc.kill()
        except Exception:
            pass
    return True


def log_path_for(project_name: str, filename: str) -> Path:
    """logs/{script}.log inside the project folder."""
    return settings.PROJECTS_ROOT / project_name / "logs" / f"{filename}.log"


async def run_script(
    script_id: int,
    project_name: str,
    folder: str,
    filename: str,
    on_line=None,
) -> tuple[str, int]:
    """
    Execute one script and return (status, exit_code).

    on_line: optional async callable invoked with each output line —
    exceptions from it (e.g. the WebSocket client disconnected) do not
    kill the script; the run continues and the log is still written.
    """
    script_dir = settings.PROJECTS_ROOT / project_name / folder
    script_path = script_dir / filename
    log_path = log_path_for(project_name, filename)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    _update_script(script_id, status="RUNNING", log=str(log_path))
    log_activity(f"▶ script {project_name}/{folder}/{filename} started")

    started = datetime.utcnow()

    try:
        process = await asyncio.create_subprocess_exec(
            settings.PYTHON_BIN, "-u", str(script_path),
            cwd=str(script_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout
            start_new_session=True,            # own process group (kill children on stop)
        )
    except FileNotFoundError as exc:
        # Interpreter or working directory missing
        error_line = f"[serverhub] failed to start: {exc}"
        log_path.write_text(error_line + "\n", encoding="utf-8")
        _update_script(script_id, status="FAILED", log=str(log_path), ran_at=started)
        log_activity(f"✗ script {project_name}/{folder}/{filename} FAILED to start")
        if on_line:
            try:
                await on_line(error_line)
            except Exception:
                pass
        return "FAILED", -1

    _running[script_id] = process
    assert process.stdout is not None
    # Stream output to the log file line-by-line (flushed) so "View Log" can
    # tail it live while the script runs — not only after it finishes.
    log_file = log_path.open("w", encoding="utf-8")
    try:
        while True:
            raw = await process.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            log_file.write(line + "\n")
            log_file.flush()
            if on_line:
                try:
                    await on_line(line)
                except Exception:
                    # Client went away — keep running, keep logging
                    on_line = None

        exit_code = await process.wait()
        # Reap any children the script leaked — headless Chrome/chromedriver that
        # outlived the script (e.g. it errored before driver.quit()). The script
        # ran in its own process group (start_new_session), so its pgid == its
        # pid; signalling that group cleans up stragglers instead of letting them
        # accumulate and eat RAM over many runs.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        _running.pop(script_id, None)
        if script_id in _stopped:
            _stopped.discard(script_id)
            status = "STOPPED"
        else:
            status = "SUCCESS" if exit_code == 0 else "FAILED"

        log_file.write(
            f"\n[serverhub] started {started.isoformat()}Z"
            f"\n[serverhub] finished {datetime.utcnow().isoformat()}Z"
            f"\n[serverhub] exit code {exit_code} ({status})\n"
        )
        log_file.flush()
    finally:
        log_file.close()

    _update_script(script_id, status=status, log=str(log_path), ran_at=started)
    mark = {"SUCCESS": "✓", "STOPPED": "⏹"}.get(status, "✗")
    log_activity(f"{mark} script {project_name}/{folder}/{filename} {status} (exit {exit_code})")
    return status, exit_code


def _update_script(script_id: int, status: str, log: str, ran_at: datetime | None = None):
    """Persist run state with a short-lived session (safe from any task)."""
    db = SessionLocal()
    try:
        script = db.get(Script, script_id)
        if script:
            script.last_status = status
            script.last_log = log
            if ran_at:
                script.last_run = ran_at
            db.commit()
    finally:
        db.close()
