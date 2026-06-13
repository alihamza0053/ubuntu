"""
Async script runner.

Runs a project script with the configured Python interpreter, streams
combined stdout/stderr line-by-line to an optional callback (used by the
WebSocket endpoint), writes the full output to the project's logs/ folder
and records the result on the Script row.

Subprocesses are spawned with an argument list — never a shell string.
"""
import asyncio
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..database import SessionLocal
from ..models import Script
from .activity import log_activity


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
    lines: list[str] = []

    try:
        process = await asyncio.create_subprocess_exec(
            settings.PYTHON_BIN, "-u", str(script_path),
            cwd=str(script_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout
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

    assert process.stdout is not None
    while True:
        raw = await process.stdout.readline()
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").rstrip("\n")
        lines.append(line)
        if on_line:
            try:
                await on_line(line)
            except Exception:
                # Client went away — keep running, keep logging
                on_line = None

    exit_code = await process.wait()
    status = "SUCCESS" if exit_code == 0 else "FAILED"

    footer = (
        f"\n[serverhub] started {started.isoformat()}Z"
        f"\n[serverhub] finished {datetime.utcnow().isoformat()}Z"
        f"\n[serverhub] exit code {exit_code} ({status})\n"
    )
    log_path.write_text("\n".join(lines) + footer, encoding="utf-8")
    _update_script(script_id, status=status, log=str(log_path), ran_at=started)
    mark = "✓" if status == "SUCCESS" else "✗"
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
