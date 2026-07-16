"""
Script execution routes:
  - POST /api/projects/{id}/run-script/{filename}  fire-and-forget run
  - GET  /api/projects/{id}/logs/{filename}        last run's log content
  - WS   /ws/script/{script_id}/run                run with live streaming
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..deps import authenticate_websocket, get_current_user
from ..models import Script
from ..permissions import hidden_for
from ..schemas import DetailResponse
from ..services.script_runner import log_path_for, run_script, stop_script
from ..services.streaming import tail_file
from .projects import get_project_or_404, sync_scripts

router = APIRouter(tags=["scripts"])


@router.post("/api/scripts/{script_id}/stop", response_model=DetailResponse,
             dependencies=[Depends(get_current_user)])
def stop_script_endpoint(script_id: int):
    """Stop a running script (and its child processes, e.g. headless Chrome)."""
    if stop_script(script_id):
        return DetailResponse(detail="Stopping script…")
    raise HTTPException(status_code=409, detail="Script is not running")


def _find_script(db: Session, project_id: int, filename: str, folder: str) -> Script:
    script = (
        db.query(Script)
        .filter(Script.project_id == project_id,
                Script.filename == filename,
                Script.folder == folder)
        .first()
    )
    if script is None:
        raise HTTPException(status_code=404, detail=f"Script not found: {folder}/{filename}")
    return script


@router.post(
    "/api/projects/{project_id}/run-script/{filename}",
    response_model=DetailResponse,
    dependencies=[Depends(get_current_user)],
)
async def run_script_endpoint(
    project_id: int,
    filename: str,
    folder: str = Query("code", pattern="^(code|allscripts)$"),
    db: Session = Depends(get_db),
):
    """Start a script in the background; output goes to the project log."""
    project = get_project_or_404(project_id, db)
    sync_scripts(project, db)
    script = _find_script(db, project_id, filename, folder)
    if script.last_status == "RUNNING":
        raise HTTPException(status_code=409, detail="Script is already running")

    # Fire-and-forget: progress is visible via the logs endpoint / WS stream
    asyncio.create_task(run_script(script.id, project.name, folder, filename))
    return DetailResponse(detail=f"Started {folder}/{filename}")


@router.get(
    "/api/projects/{project_id}/logs/{filename}",
    dependencies=[Depends(get_current_user)],
)
def get_script_log(project_id: int, filename: str, db: Session = Depends(get_db)):
    """Return the captured output of the script's most recent run."""
    project = get_project_or_404(project_id, db)
    log_path = log_path_for(project.name, filename)
    if not log_path.is_file():
        raise HTTPException(status_code=404, detail="No log yet — script has not run")
    return {"filename": filename, "content": log_path.read_text(encoding="utf-8", errors="replace")}


@router.websocket("/ws/script/{script_id}/run")
async def run_script_ws(websocket: WebSocket, script_id: int):
    """
    Run a script and stream its output live.

    Protocol: client connects with ?token=JWT; server sends one text frame
    per output line, then a final frame "[serverhub] status=<SUCCESS|FAILED>".
    """
    user = await authenticate_websocket(websocket, require="projects")
    if user is None:
        return
    await websocket.accept()

    db = SessionLocal()
    try:
        script = db.get(Script, script_id)
        if script is None or hidden_for(user, script.project):
            await websocket.send_text("[serverhub] error: script not found")
            await websocket.close()
            return
        project_name = script.project.name
        folder, filename = script.folder, script.filename
        if script.last_status == "RUNNING":
            await websocket.send_text("[serverhub] error: script is already running")
            await websocket.close()
            return
    finally:
        db.close()

    async def send_line(line: str):
        await websocket.send_text(line)

    try:
        status, exit_code = await run_script(
            script_id, project_name, folder, filename, on_line=send_line
        )
        await websocket.send_text(f"[serverhub] status={status} exit_code={exit_code}")
        await websocket.close()
    except WebSocketDisconnect:
        # Client closed the tab — run_script keeps going and writes the log
        pass


@router.websocket("/ws/script/{script_id}/logs")
async def script_logs_ws(websocket: WebSocket, script_id: int):
    """
    Live-tail a script's log file: sends the recent lines, then streams new
    output as it's written. Works whether the script is running (live output)
    or idle (just shows the last run's log). Used by the "View Log" button.
    """
    user = await authenticate_websocket(websocket, require="projects")
    if user is None:
        return
    await websocket.accept()

    db = SessionLocal()
    try:
        script = db.get(Script, script_id)
        if script is None or hidden_for(user, script.project):
            await websocket.send_text("[serverhub] script not found")
            await websocket.close()
            return
        project_name, filename = script.project.name, script.filename
    finally:
        db.close()

    async def send_line(line: str):
        await websocket.send_text(line)

    try:
        await tail_file(log_path_for(project_name, filename), send_line, backlog=500)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        pass
