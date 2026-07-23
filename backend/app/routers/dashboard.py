"""
Streamlit dashboard control routes — thin wrappers over supervisor_service,
plus the live tail of a dashboard's supervisor log (Project → Dashboard tab).
"""
from fastapi import (APIRouter, Depends, HTTPException, WebSocket,
                     WebSocketDisconnect)
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import authenticate_websocket, get_current_user
from ..schemas import DashboardStatusOut, DetailResponse
from ..services import supervisor_service
from ..services.activity import log_activity
from ..services.streaming import tail_file
from ..services.supervisor_service import dashboard_log_path
from .projects import get_project_or_404, project_root

router = APIRouter(
    prefix="/api/projects/{project_id}/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user)],
)
# WebSockets authenticate via ?token=, so they can't use the HTTP dependency.
ws_router = APIRouter(tags=["dashboard"])


def _set_status(project, db: Session):
    """Refresh the cached status column after an action."""
    state, raw = supervisor_service.status(project.name)
    project.dashboard_status = state
    db.commit()
    return state, raw


@router.post("/start", response_model=DetailResponse)
def start_dashboard(project_id: int, db: Session = Depends(get_db)):
    project = get_project_or_404(project_id, db)
    # Helpful error instead of a supervisor FATAL loop
    if not (project_root(project) / "dashboard" / "app.py").is_file():
        raise HTTPException(
            status_code=400,
            detail="dashboard/app.py not found — upload your Streamlit app first",
        )
    # Regenerate the supervisor config so it picks up a per-project venv created
    # after the project was made (deploy/dashboard-venv.sh). Self-healing: no
    # manual config edit / reread needed.
    supervisor_service.write_config(project.name, project.dashboard_port)
    output = supervisor_service.start(project.name)
    _set_status(project, db)
    log_activity(f"▶ dashboard {project.name} start")
    return DetailResponse(detail=output)


@router.post("/stop", response_model=DetailResponse)
def stop_dashboard(project_id: int, db: Session = Depends(get_db)):
    project = get_project_or_404(project_id, db)
    output = supervisor_service.stop(project.name)
    _set_status(project, db)
    log_activity(f"⏹ dashboard {project.name} stop")
    return DetailResponse(detail=output)


@router.post("/restart", response_model=DetailResponse)
def restart_dashboard(project_id: int, db: Session = Depends(get_db)):
    project = get_project_or_404(project_id, db)
    output = supervisor_service.restart(project.name)
    log_activity(f"🔄 dashboard {project.name} restart")
    _set_status(project, db)
    return DetailResponse(detail=output)


@router.get("/status", response_model=DashboardStatusOut)
def dashboard_status(project_id: int, db: Session = Depends(get_db)):
    project = get_project_or_404(project_id, db)
    state, raw = _set_status(project, db)
    return DashboardStatusOut(status=state, port=project.dashboard_port, raw=raw)


@ws_router.websocket("/ws/projects/{name}/dashboard-log")
async def dashboard_log_ws(websocket: WebSocket, name: str, stream: str = "out"):
    """Live-tail a project dashboard's supervisor stdout/stderr log."""
    user = await authenticate_websocket(websocket, require="projects")
    if user is None:
        return
    if "/" in name or "\\" in name or ".." in name or stream not in ("out", "err"):
        await websocket.close(code=1008, reason="Invalid log request")
        return
    await websocket.accept()

    async def send(line: str):
        await websocket.send_text(line)

    try:
        await tail_file(dashboard_log_path(name, stream), send)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        pass
