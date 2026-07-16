"""
Per-project Python package management (the "Packages" tab).

Installs/lists pip packages into the SAME interpreter that runs project scripts
(settings.PYTHON_BIN), so fixing a `ModuleNotFoundError: No module named 'X'`
is just typing `X` and clicking Install. Packages are shared across projects'
scripts (they share that interpreter).
"""
import json
import re

from fastapi import (APIRouter, Depends, HTTPException, Query, WebSocket,
                     WebSocketDisconnect)
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, get_db
from ..deps import authenticate_websocket, get_current_user
from ..models import Project
from ..services.streaming import run_command, stream_command
from .projects import get_project_or_404

router = APIRouter(prefix="/api/projects", tags=["packages"],
                   dependencies=[Depends(get_current_user)])
ws_router = APIRouter(tags=["packages"])   # pip-install WS authenticates via ?token=

# A pip requirement spec: name, version pins, extras — no shell metacharacters.
_SPEC = re.compile(r"^[A-Za-z0-9_.\-\[\]=<>!~,+*]+$")


def _project_pip(project_name: str) -> list[str]:
    """
    Pip command targeting the PROJECT's own venv (where its Streamlit dashboard
    runs), so installed packages actually reach the dashboard. Falls back to the
    shared scripts interpreter only when the project has no venv yet.
    """
    venv_pip = settings.PROJECTS_ROOT / project_name / "venv" / "bin" / "pip"
    if venv_pip.exists():
        return [str(venv_pip)]
    return [settings.PYTHON_BIN, "-m", "pip"]


def _project_python(project_name: str) -> str:
    """The project venv's python if present, else the shared interpreter."""
    venv_py = settings.PROJECTS_ROOT / project_name / "venv" / "bin" / "python"
    return str(venv_py) if venv_py.exists() else settings.PYTHON_BIN


def _project_name(project_id: int, user=None) -> str | None:
    """Look up a project's name from a WebSocket handler (no request-scoped db).
    Admin-hidden projects resolve to None for non-admin users."""
    from ..permissions import hidden_for
    db = SessionLocal()
    try:
        project = db.get(Project, project_id)
        if project is None or (user is not None and hidden_for(user, project)):
            return None
        return project.name
    finally:
        db.close()


@router.get("/{project_id}/packages")
async def list_packages(project_id: int, db: Session = Depends(get_db)):
    """List packages installed in the project's Python environment."""
    project = get_project_or_404(project_id, db)
    pip = _project_pip(project.name)
    code, out = await run_command([*pip, "list", "--format=json"], timeout=60)
    if code != 0:
        raise HTTPException(status_code=500, detail=f"pip list failed: {out[:300]}")
    try:
        packages = json.loads(out)
    except ValueError:
        packages = []
    return {"python": pip[0], "packages": packages}


@ws_router.websocket("/ws/projects/{project_id}/pip-install")
async def pip_install_ws(websocket: WebSocket, project_id: int, spec: str = Query("")):
    """Run `pip install <spec>` (live output). spec may be several packages."""
    user = await authenticate_websocket(websocket, require="projects")
    if user is None:
        return
    await websocket.accept()

    parts = [p for p in spec.split() if p]
    if not parts or not all(_SPEC.match(p) for p in parts):
        await websocket.send_text("[serverhub] Invalid package name(s).")
        await websocket.close()
        return

    async def send(line: str):
        await websocket.send_text(line)

    name = _project_name(project_id, user)
    if name is None:
        await send("[serverhub] project not found")
        await websocket.close()
        return
    pip = _project_pip(name)

    await send(f"[serverhub] pip install {' '.join(parts)}  (into {pip[0]}) …")
    try:
        code = await stream_command([*pip, "install", "--upgrade", *parts], send)
        await send("[serverhub] ✓ done — restart the dashboard to use it" if code == 0
                   else f"[serverhub] pip install failed (exit {code})")
    except WebSocketDisconnect:
        return
    await websocket.close()


@ws_router.websocket("/ws/projects/{project_id}/playwright-install")
async def playwright_install_ws(websocket: WebSocket, project_id: int):
    """Download Playwright's Chromium browser (the step after `pip install playwright`)."""
    user = await authenticate_websocket(websocket, require="projects")
    if user is None:
        return
    await websocket.accept()

    async def send(line: str):
        await websocket.send_text(line)

    name = _project_name(project_id, user)
    python = _project_python(name) if name else settings.PYTHON_BIN

    await send("[serverhub] playwright install chromium …")
    try:
        code = await stream_command(
            [python, "-m", "playwright", "install", "chromium"], send)
        if code == 0:
            await send("[serverhub] ✓ browsers installed — re-run your script")
        else:
            await send(f"[serverhub] failed (exit {code}). If it's a missing system "
                       f"library, run in Terminal:  sudo {python} -m playwright install-deps")
    except WebSocketDisconnect:
        return
    await websocket.close()
