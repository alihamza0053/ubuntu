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
from .script_runner import run_script


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
    try:
        log_activity(f"▶ pipeline {name} started ({len(scripts)} script(s))")
        await emit(f"===== pipeline run started: {name} — {len(scripts)} script(s) =====")

        if not scripts:
            await emit("[pipeline] no scripts found in code/ — nothing to run")

        for sid, folder, filename in scripts:
            await emit(f"[pipeline] ▶ running {folder}/{filename}")

            async def fwd(line: str):
                await emit(f"    {line}")

            status, code = await run_script(sid, name, folder, filename, on_line=fwd)
            results.append({
                "filename": filename,
                "folder": folder,
                "status": status,
                "exit_code": code,
                "finished": datetime.utcnow().isoformat(),
            })
            if status == "SUCCESS":
                await emit(f"[pipeline] ✓ {filename} OK")
            else:
                overall = "FAILED"
                await emit(f"[pipeline] ✗ {filename} FAILED (exit {code})")
            # Persist after each script so the UI updates live
            _update_run(run_id, status="RUNNING", results=results)

        # Restart the dashboard so it reloads fresh data (best effort)
        restarted = False
        dashboard_app = settings.PROJECTS_ROOT / name / "dashboard" / "app.py"
        if dashboard_app.is_file():
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
        log_activity(f"{'✓' if overall == 'SUCCESS' else '✗'} pipeline {name} finished — status={overall}")
        await emit(f"===== pipeline run finished: status={overall} =====")
        return overall, results
    finally:
        try:
            log_fh.close()
        except Exception:
            pass
