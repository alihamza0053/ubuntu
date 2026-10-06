"""
Project dashboard control routes — thin wrappers over supervisor_service,
plus the live tail of a dashboard's supervisor log (Project → Dashboard tab).

The dashboard entrypoint is always `dashboard/app.py`, but it may be a
Streamlit script, a Flask app or a FastAPI app: the framework is read from the
code at start time unless the user pinned one in the UI.
"""
from pathlib import Path, PurePosixPath

from fastapi import (APIRouter, Depends, HTTPException, WebSocket,
                     WebSocketDisconnect)
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import authenticate_websocket, get_current_user
from ..schemas import DashboardStatusOut, DetailResponse
from ..services import app_detect, supervisor_service, venv_service
from ..services.activity import log_activity
from ..services.streaming import tail_file
from ..services.supervisor_service import dashboard_log_path
from .projects import _write_project_site, get_project_or_404, project_root

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


def _ensure_runnable(project, framework: str) -> None:
    """
    Make sure the server binary for `framework` exists before supervisor is
    asked to spawn it — otherwise all the user sees is "ERROR (spawn error)".

    A new project's venv is built in the background after creation, so Start
    can easily be pressed before it's ready (or after the build failed). And a
    venv built earlier may lack the binary for the framework app.py now uses.
    """
    name = project.name
    framework = supervisor_service.normalise_framework(framework)
    binary = supervisor_service.project_bin(name, framework)
    # A bare name ("gunicorn") means "not in the venv" — supervisord resolves it
    # against its own PATH, where it almost never is.
    if PurePosixPath(binary).is_absolute() and Path(binary).exists():
        return

    if venv_service.is_building(name):
        raise HTTPException(
            status_code=409,
            detail="The dashboard's Python environment is still being built "
                   "(streamlit + packages, takes a few minutes). Wait until "
                   "logs/venv-setup.log says \"✓ environment ready\", then Start.",
        )
    if not venv_service.has_python(name):
        venv_service.ensure_async(name)
        raise HTTPException(
            status_code=409,
            detail="This project has no dashboard environment yet (or its build "
                   "failed) — building it now. Watch logs/venv-setup.log and "
                   "press Start once it says \"✓ environment ready\".",
        )

    # venv exists but lacks this framework's server: install it right now.
    ok, out = venv_service.install_packages(name, venv_service.FRAMEWORK_PKGS[framework])
    installed = supervisor_service.venv_bin_dir(name) / supervisor_service.FRAMEWORK_BINS[framework]
    if not ok or not installed.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Couldn't install the {framework} server into the project "
                   f"venv — see logs/venv-setup.log.\n{out[-500:]}",
        )


def _prepare_api(project) -> str:
    """
    dashboard/api.py (optional) runs next to the dashboard as <name>_api and is
    served on the project's own domain at /api/… . Make sure its server is in
    the venv and the nginx block has (or drops) the /api/ location. Never
    blocks the dashboard itself: problems come back as a note.
    """
    name = project.name
    wants_api = supervisor_service.has_api(name)
    notes = []
    # uvicorn alone isn't enough (a venv can have it without fastapi): check both.
    has_fastapi = any(venv_service.venv_dir(name).glob("lib/python*/site-packages/fastapi"))
    if wants_api and not (has_fastapi and (supervisor_service.venv_bin_dir(name) / "uvicorn").exists()):
        ok, out = venv_service.install_packages(name, ["fastapi", "uvicorn[standard]"])
        if not ok:
            notes.append(f"API: couldn't install fastapi/uvicorn — {out[-300:]}")

    if project.domain:
        conf = settings.NGINX_CONFIGS_ROOT / f"project-{name}.conf"
        try:
            has_location = "location /api/" in conf.read_text(encoding="utf-8")
        except OSError:
            has_location = False
        if has_location != wants_api:
            try:
                _write_project_site(project, project.domain)
                notes.append(f"API: nginx {'now serves' if wants_api else 'no longer serves'} "
                             f"https://{project.domain}/api/")
            except HTTPException as exc:
                notes.append(f"API: nginx update failed — {exc.detail}")
    return "\n".join(notes)


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
        # Set when the dashboard will be started as the wrong kind of app, or
        # when dashboard/ calls app.run() at import time — between them, the two
        # commonest reasons a dashboard starts and then dies.
        "warning": (app_detect.mismatch_warning(detected, framework)
                    or app_detect.blocking_run_warning(detected)),
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
    _ensure_runnable(project, framework)
    api_note = _prepare_api(project)
    # Regenerate the supervisor config so it picks up a per-project venv created
    # after the project was made (deploy/dashboard-venv.sh) and whatever code is
    # in dashboard/ right now. Self-healing: no manual config edit / reread needed.
    supervisor_service.write_config(project.name, project.dashboard_port,
                                    framework, target)
    output = "\n".join(p for p in (supervisor_service.start(project.name), api_note) if p)
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
    _ensure_runnable(project, framework)
    api_note = _prepare_api(project)
    supervisor_service.write_config(project.name, project.dashboard_port,
                                    framework, target)
    output = "\n".join(p for p in (supervisor_service.restart(project.name), api_note) if p)
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
