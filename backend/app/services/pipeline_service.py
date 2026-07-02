"""
Project pipeline: run every script in a project's code/ folder one-by-one,
record each script's pass/fail, then restart the project's Streamlit dashboard
so it loads fresh data.

Scripts run in filename order — prefix names with 01_, 02_, ... to control the
sequence. A failing script does not stop the pipeline; it's recorded as FAILED
(shown red in the UI) and the run continues, then the dashboard is restarted.
"""
import json
from datetime import datetime

from ..config import settings
from ..database import SessionLocal
from ..models import PipelineRun, Project, Script
from . import supervisor_service
from .activity import log_activity
from .script_runner import run_script, stop_script

# Stop requests + the script currently running, keyed by project id, so a
# running pipeline can be cancelled from the UI.
_stop_requested: set[int] = set()
_current_script: dict[int, int] = {}
# Projects whose pipeline task is alive right now (for the whole run, not just
# while a script executes) — used so Stop works between scripts too.
_running_pipelines: set[int] = set()


def request_stop(project_id: int) -> bool:
    """Ask a running pipeline to stop and kill its in-progress script."""
    _stop_requested.add(project_id)
    sid = _current_script.get(project_id)
    if sid is not None:
        stop_script(sid)
    return True


def is_pipeline_running(project_id: int) -> bool:
    return project_id in _running_pipelines


def mark_interrupted() -> None:
    """
    On panel startup, any pipeline run or script left in RUNNING state must be
    stale — the process that was running them is gone (a restart kills child
    scripts). Mark them FAILED so the UI isn't stuck showing "RUNNING".
    """
    from datetime import datetime as _dt
    db = SessionLocal()
    try:
        db.query(PipelineRun).filter(PipelineRun.status == "RUNNING").update(
            {PipelineRun.status: "FAILED", PipelineRun.finished_at: _dt.utcnow()},
            synchronize_session=False,
        )
        db.query(Script).filter(Script.last_status == "RUNNING").update(
            {Script.last_status: "FAILED"}, synchronize_session=False,
        )
        db.commit()
    finally:
        db.close()


def pipeline_log_path(project_name: str):
    """Path of a project's pipeline log file (shown in the Logs page)."""
    return settings.PROJECTS_ROOT / project_name / "logs" / "pipeline.log"


def list_pipeline_scripts(project_id: int, db) -> list[Script]:
    """All registered code/ scripts for a project, in run order (by filename)."""
    return (
        db.query(Script)
        .filter(Script.project_id == project_id, Script.folder == "code")
        .order_by(Script.filename)
        .all()
    )


def _update_run(run_id: int, *, status: str, results: list, finished: bool = False,
                restarted: bool | None = None) -> None:
    """Persist pipeline-run progress with a short-lived session."""
    db = SessionLocal()
    try:
        run = db.get(PipelineRun, run_id)
        if run is None:
            return
        run.status = status
        run.results = json.dumps(results)
        if restarted is not None:
            run.dashboard_restarted = restarted
        if finished:
            run.finished_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


async def run_pipeline(project_id: int, on_line=None) -> tuple[str, list]:
    """
    Execute the whole project pipeline. Returns (overall_status, results).

    on_line: optional async callback for live streaming (the WebSocket endpoint
    passes one). Markers use ✓ / ✗ so the UI can colour them green / red.
    """
    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if project is None:
            return "FAILED", []
        name = project.name
        scripts = [(s.id, s.folder, s.filename)
                   for s in list_pipeline_scripts(project_id, db)]
        run = PipelineRun(project_id=project_id, status="RUNNING", results="[]")
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    _running_pipelines.add(project_id)   # Stop works for the whole run now

    # Every line is timestamped and appended to the project's pipeline.log so it
    # also shows in the Logs page (source "Pipeline: <project>").
    log_path = pipeline_log_path(name)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("a", encoding="utf-8")

    async def emit(line: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stamped = f"[{ts}] {line}"
        try:
            log_fh.write(stamped + "\n")
            log_fh.flush()
        except Exception:
            pass
        if on_line:
            try:
                await on_line(stamped)
            except Exception:
                pass

    results: list = []
    overall = "SUCCESS"
    stopped = False
    # Scripts that ended FAILED on the first pass — retried at the end.
    # Each item: (sid, folder, filename, index-in-results)
    failed: list[tuple] = []
    _stop_requested.discard(project_id)   # clear any stale stop flag

    async def fwd(line: str):
        await emit(f"    {line}")

    async def run_one(sid: str, folder: str, filename: str):
        _current_script[project_id] = sid
        try:
            return await run_script(sid, name, folder, filename, on_line=fwd)
        finally:
            _current_script.pop(project_id, None)

    try:
        log_activity(f"▶ pipeline {name} started ({len(scripts)} script(s))")
        await emit(f"===== pipeline run started: {name} — {len(scripts)} script(s) =====")

        if not scripts:
            await emit("[pipeline] no scripts found in code/ — nothing to run")

        for sid, folder, filename in scripts:
            if project_id in _stop_requested:
                stopped = True
                await emit("[pipeline] ⏹ stopped by user — remaining scripts skipped")
                break

            await emit(f"[pipeline] ▶ running {folder}/{filename}")
            status, code = await run_one(sid, folder, filename)

            results.append({
                "filename": filename,
                "folder": folder,
                "status": status,
                "exit_code": code,
                "attempts": 1,
                "retried": False,
                "finished": datetime.utcnow().isoformat(),
            })
            if status == "SUCCESS":
                await emit(f"[pipeline] ✓ {filename} OK")
            elif status == "STOPPED":
                stopped = True
                await emit(f"[pipeline] ⏹ {filename} stopped by user")
                break
            else:
                await emit(f"[pipeline] ✗ {filename} FAILED (exit {code}) — will retry at the end")
                failed.append((sid, folder, filename, len(results) - 1))
            # Persist after each script so the UI updates live
            _update_run(run_id, status="RUNNING", results=results)

        # --- Retry pass: re-run scripts that failed, at the end of the run ---
        max_retries = settings.PIPELINE_MAX_RETRIES
        if not stopped and failed and max_retries > 0:
            await emit(f"[pipeline] ↻ retrying {len(failed)} failed script(s) "
                       f"at the end (up to {max_retries} pass(es))")
            for attempt in range(1, max_retries + 1):
                if not failed or stopped:
                    break
                still_failed: list[tuple] = []
                for sid, folder, filename, idx in failed:
                    if project_id in _stop_requested:
                        stopped = True
                        await emit("[pipeline] ⏹ stopped by user during retry")
                        break

                    await emit(f"[pipeline] ↻ retry {attempt}/{max_retries}: {folder}/{filename}")
                    status, code = await run_one(sid, folder, filename)

                    entry = results[idx]
                    entry["status"] = status
                    entry["exit_code"] = code
                    entry["attempts"] = entry.get("attempts", 1) + 1
                    entry["retried"] = True
                    entry["finished"] = datetime.utcnow().isoformat()

                    if status == "SUCCESS":
                        await emit(f"[pipeline] ✓ {filename} OK on retry {attempt}")
                    elif status == "STOPPED":
                        stopped = True
                        await emit(f"[pipeline] ⏹ {filename} stopped by user")
                        still_failed.append((sid, folder, filename, idx))
                        break
                    else:
                        await emit(f"[pipeline] ✗ {filename} still FAILED (exit {code})")
                        still_failed.append((sid, folder, filename, idx))
                    _update_run(run_id, status="RUNNING", results=results)
                failed = still_failed

        # Final status: STOPPED wins; otherwise SUCCESS only if everything passed
        if stopped:
            overall = "STOPPED"
        elif all(r["status"] == "SUCCESS" for r in results):
            overall = "SUCCESS"
        else:
            overall = "FAILED"

        # Restart the dashboard so it reloads fresh data (skipped if stopped)
        restarted = False
        dashboard_app = settings.PROJECTS_ROOT / name / "dashboard" / "app.py"
        if overall == "STOPPED":
            await emit("[pipeline] (stopped — dashboard not restarted)")
        elif dashboard_app.is_file():
            await emit("[pipeline] ↻ restarting dashboard to load fresh data")
            try:
                supervisor_service.restart(name)
                restarted = True
                await emit("[pipeline] ✓ dashboard restarted")
            except Exception as exc:  # supervisor/HTTPException — don't fail the run
                await emit(f"[pipeline] ✗ dashboard restart failed: {exc}")
        else:
            await emit("[pipeline] (no dashboard/app.py — skipping restart)")

        _update_run(run_id, status=overall, results=results, finished=True, restarted=restarted)
        mark = {"SUCCESS": "✓", "STOPPED": "⏹"}.get(overall, "✗")
        log_activity(f"{mark} pipeline {name} finished — status={overall}")
        await emit(f"===== pipeline run finished: status={overall} =====")
        return overall, results
    except Exception as exc:
        # Never leave the run stuck at RUNNING on an unexpected error
        _update_run(run_id, status="FAILED", results=results, finished=True)
        log_activity(f"✗ pipeline {name} crashed: {exc}")
        return "FAILED", results
    finally:
        _running_pipelines.discard(project_id)
        _stop_requested.discard(project_id)
        _current_script.pop(project_id, None)
        try:
            log_fh.close()
        except Exception:
            pass
