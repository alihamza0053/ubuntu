"""
Streamlit dashboard control routes — thin wrappers over supervisor_service.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..schemas import DashboardStatusOut, DetailResponse
from ..services import supervisor_service
from .projects import get_project_or_404, project_root

router = APIRouter(
    prefix="/api/projects/{project_id}/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user)],
)


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
    output = supervisor_service.start(project.name)
    _set_status(project, db)
    return DetailResponse(detail=output)


@router.post("/stop", response_model=DetailResponse)
def stop_dashboard(project_id: int, db: Session = Depends(get_db)):
    project = get_project_or_404(project_id, db)
    output = supervisor_service.stop(project.name)
    _set_status(project, db)
    return DetailResponse(detail=output)


@router.post("/restart", response_model=DetailResponse)
def restart_dashboard(project_id: int, db: Session = Depends(get_db)):
    project = get_project_or_404(project_id, db)
    output = supervisor_service.restart(project.name)
    _set_status(project, db)
    return DetailResponse(detail=output)


@router.get("/status", response_model=DashboardStatusOut)
def dashboard_status(project_id: int, db: Session = Depends(get_db)):
    project = get_project_or_404(project_id, db)
    state, raw = _set_status(project, db)
    return DashboardStatusOut(status=state, port=project.dashboard_port, raw=raw)
