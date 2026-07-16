"""
Project pipeline routes:
  - GET  /api/projects/{id}/pipeline        config + scripts + last run
  - PUT  /api/projects/{id}/pipeline         set cron + active
  - POST /api/projects/{id}/run-pipeline      run now (background)
  - WS   /ws/pipeline/{id}/run                run now with live streaming

A pipeline runs all of a project's code/ scripts in order, records each
script's pass/fail, then restarts the dashboard.
"""
import asyncio
import json

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..deps import authenticate_websocket, get_current_user
from ..models import PipelineRun, PipelineSchedule, Project
from ..schemas import DetailResponse
from ..services import pipeline_service, scheduler_service

router = APIRouter(tags=["pipeline"])
ws_router = APIRouter(tags=["pipeline"])  # WS auth via ?token=, no HTTP bearer dep


class PipelineConfig(BaseModel):
    cron_expression: str | None = None
    is_active: bool = False


def _get_project(project_id: int, db: Session) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _last_run(project_id: int, db: Session) -> dict | None:
    run = (
        db.query(PipelineRun)
        .filter(PipelineRun.project_id == project_id)
        .order_by(PipelineRun.started_at.desc())
        .first()
    )
    if run is None:
        return None
    return {
        "id": run.id,
        "status": run.status,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "dashboard_restarted": run.dashboard_restarted,
        "results": json.loads(run.results or "[]"),
    }


@router.get("/api/projects/{project_id}/pipeline", dependencies=[Depends(get_current_user)])
def get_pipeline(project_id: int, db: Session = Depends(get_db)):
    """Pipeline config, the ordered script list, and the most recent run."""
    project = _get_project(project_id, db)
    # Keep the scripts table in sync with code/ on disk
    from .projects import sync_scripts
    sync_scripts(project, db)

    pipe = db.query(PipelineSchedule).filter(PipelineSchedule.project_id == project_id).first()
    scripts = pipeline_service.list_pipeline_scripts(project_id, db)
    return {
        "cron_expression": pipe.cron_expression if pipe else None,
        "is_active": pipe.is_active if pipe else False,
        "next_run": scheduler_service.pipeline_next_run(project_id) if (pipe and pipe.is_active) else None,
        "scripts": [s.filename for s in scripts],
        "last_run": _last_run(project_id, db),
    }


@router.put("/api/projects/{project_id}/pipeline", dependencies=[Depends(get_current_user)])
def set_pipeline(project_id: int, body: PipelineConfig, db: Session = Depends(get_db)):
    """Create/update the pipeline cron schedule for a project."""
    _get_project(project_id, db)

    if body.cron_expression:
        try:
            CronTrigger.from_crontab(body.cron_expression)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid cron: {body.cron_expression!r}")

    pipe = db.query(PipelineSchedule).filter(PipelineSchedule.project_id == project_id).first()
    if pipe is None:
        pipe = PipelineSchedule(project_id=project_id,
                                cron_expression=body.cron_expression or "0 6 * * *",
                                is_active=body.is_active)
        db.add(pipe)
    else:
        if body.cron_expression:
            pipe.cron_expression = body.cron_expression
        pipe.is_active = body.is_active
    db.commit()
    db.refresh(pipe)

    if pipe.is_active and pipe.cron_expression:
        scheduler_service.add_or_update_pipeline_job(pipe)
    else:
        scheduler_service.remove_pipeline_job(project_id)

    return {
        "cron_expression": pipe.cron_expression,
        "is_active": pipe.is_active,
        "next_run": scheduler_service.pipeline_next_run(project_id) if pipe.is_active else None,
    }


@router.delete("/api/projects/{project_id}/pipeline", response_model=DetailResponse,
               dependencies=[Depends(get_current_user)])
def delete_pipeline(project_id: int, db: Session = Depends(get_db)):
    """Remove a project's pipeline schedule entirely (stops + deletes it)."""
    scheduler_service.remove_pipeline_job(project_id)
    pipe = db.query(PipelineSchedule).filter(PipelineSchedule.project_id == project_id).first()
    if pipe:
        db.delete(pipe)
        db.commit()
    return DetailResponse(detail="Pipeline schedule removed")


@router.post("/api/projects/{project_id}/run-pipeline", response_model=DetailResponse,
             dependencies=[Depends(get_current_user)])
async def run_pipeline_now(project_id: int, db: Session = Depends(get_db)):
    """Trigger the pipeline immediately in the background."""
    project = _get_project(project_id, db)
    from .projects import sync_scripts
    sync_scripts(project, db)
    asyncio.create_task(pipeline_service.run_pipeline(project_id))
    return DetailResponse(detail=f"Pipeline started for '{project.name}'")


@router.post("/api/projects/{project_id}/stop-pipeline", response_model=DetailResponse,
             dependencies=[Depends(get_current_user)])
def stop_pipeline_now(project_id: int, db: Session = Depends(get_db)):
    """Stop a running pipeline; also clears a stale RUNNING run left by a restart."""
    _get_project(project_id, db)
    if pipeline_service.is_pipeline_running(project_id):
        pipeline_service.request_stop(project_id)
        return DetailResponse(detail="Stopping pipeline…")

    # Nothing is actually running — finalize a stale RUNNING row if present
    # (e.g. the panel restarted mid-run, leaving the record stuck).
    from datetime import datetime

    stale = (
        db.query(PipelineRun)
        .filter(PipelineRun.project_id == project_id, PipelineRun.status == "RUNNING")
        .order_by(PipelineRun.started_at.desc())
        .first()
    )
    if stale:
        stale.status = "FAILED"
        stale.finished_at = datetime.utcnow()
        db.commit()
        return DetailResponse(detail="Cleared a stale running pipeline")
    raise HTTPException(status_code=409, detail="No pipeline is currently running")


@ws_router.websocket("/ws/pipeline/{project_id}/run")
async def run_pipeline_ws(websocket: WebSocket, project_id: int):
    """Run the pipeline and stream progress live (✓/✗ markers per script)."""
    user = await authenticate_websocket(websocket, require="projects")
    if user is None:
        return
    await websocket.accept()

    # Sync scripts before running
    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        from ..permissions import hidden_for
        if project is None or hidden_for(user, project):
            await websocket.send_text("[pipeline] error: project not found")
            await websocket.close()
            return
        from .projects import sync_scripts
        sync_scripts(project, db)
    finally:
        db.close()

    async def send(line: str):
        await websocket.send_text(line)

    try:
        await pipeline_service.run_pipeline(project_id, on_line=send)
        await websocket.close()
    except WebSocketDisconnect:
        pass  # pipeline keeps running server-side
