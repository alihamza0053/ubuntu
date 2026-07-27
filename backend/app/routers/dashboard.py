"""
Project dashboard control routes — thin wrappers over supervisor_service,
plus the live tail of a dashboard's supervisor log (Project → Dashboard tab).

The dashboard entrypoint is always `dashboard/app.py`, but it may be a
Streamlit script, a Flask app or a FastAPI app: the framework is read from the
code at start time unless the user pinned one in the UI.
"""
from fastapi import (APIRouter, Depends, HTTPException, WebSocket,
                     WebSocketDisconnect)
from pydantic import BaseModel, field_validator
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


class FrameworkRequest(BaseModel):
    """null/empty framework = go back to auto-detecting from the code."""
    framework: str | None = None
    target: str | None = None

    @field_validator("framework")
    @classmethod
    def framework_ok(cls, v: str | None) -> str | None:
        if not v or v.strip().lower() in ("", "auto"):
            return None
        v = v.strip().lower()
        if v not in supervisor_service.FRAMEWORK_COMMANDS:
            raise ValueError("framework must be streamlit, flask, fastapi or auto")
        return v


def _set_status(project, db: Session):
    """Refresh the cached status column after an action."""
    state, raw = supervisor_service.status(project.name)
    project.dashboard_status = state
    db.commit()
    return state, raw


def _resolve_framework(project) -> tuple[str, str | None, dict | None]:
    """
    How to run this dashboard: (framework, import target, raw detection).

    A framework pinned in the UI wins; otherwise the code in dashboard/ decides,
    falling back to Streamlit so behaviour is unchanged for anything the
    detector doesn't recognise.
    """
    detected = supervisor_service.detect_framework(project.name)
    framework = (project.dashboard_framework
                 or (detected["framework"] if detected else
                     supervisor_service.DEFAULT_FRAMEWORK))
    target = project.dashboard_target
    if not target and detected and detected["framework"] == framework:
        target = detected["target"]
    return framework, target, detected


@router.get("/detect")
def detect_dashboard(project_id: int, db: Session = Depends(get_db)):
    """What's in dashboard/ and how the panel would run it right now."""
    project = get_project_or_404(project_id, db)
    framework, target, detected = _resolve_framework(project)
    return {
        "detected": detected,                       # None if nothing recognised
        "pinned": project.dashboard_framework,      # None = auto-detect
        "framework": framework,
        "target": target,
        "command": supervisor_service.build_command(
            project.name, project.dashboard_port, framework, target),
    }


@router.put("/framework", response_model=DetailResponse)
def set_dashboard_framework(project_id: int, body: FrameworkRequest,
                            db: Session = Depends(get_db)):
    """Pin the framework (or pass null to go back to auto-detection)."""
    project = get_project_or_404(project_id, db)
    project.dashboard_framework = body.framework
    project.dashboard_target = (body.target or "").strip() or None
    db.commit()
    if body.framework:
        return DetailResponse(detail=f"Dashboard will run as {body.framework}. "
                                     f"Restart it to apply.")
    return DetailResponse(detail="Dashboard framework will be detected from the code.")


@router.post("/start", response_model=DetailResponse)
def start_dashboard(project_id: int, db: Session = Depends(get_db)):
    project = get_project_or_404(project_id, db)
    # Helpful error instead of a supervisor FATAL loop
    if not (project_root(project) / "dashboard" / "app.py").is_file():
        raise HTTPException(
            status_code=400,
            detail="dashboard/app.py not found — upload your Streamlit, Flask or "
                   "FastAPI app first",
        )
    framework, target, _ = _resolve_framework(project)
    # Regenerate the supervisor config so it picks up a per-project venv created
    # after the project was made (deploy/dashboard-venv.sh) and whatever code is
    # in dashboard/ right now. Self-healing: no manual config edit / reread needed.
    supervisor_service.write_config(project.name, project.dashboard_port,
                                    framework, target)
    output = supervisor_service.start(project.name)
    _set_status(project, db)
    log_activity(f"▶ dashboard {project.name} start ({framework})")
    return DetailResponse(detail=output or f"started as {framework}")


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
    # Re-read the code first: restarting is how you pick up an app.py that
    # changed from Streamlit to Flask (or vice versa).
    framework, target, _ = _resolve_framework(project)
    supervisor_service.write_config(project.name, project.dashboard_port,
                                    framework, target)
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
