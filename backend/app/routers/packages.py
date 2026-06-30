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
from ..database import get_db
from ..deps import authenticate_websocket, get_current_user
from ..services.streaming import run_command, stream_command
from .projects import get_project_or_404

router = APIRouter(prefix="/api/projects", tags=["packages"],
                   dependencies=[Depends(get_current_user)])
ws_router = APIRouter(tags=["packages"])   # pip-install WS authenticates via ?token=

# A pip requirement spec: name, version pins, extras — no shell metacharacters.
_SPEC = re.compile(r"^[A-Za-z0-9_.\-\[\]=<>!~,+*]+$")


@router.get("/{project_id}/packages")
async def list_packages(project_id: int, db: Session = Depends(get_db)):
    """List packages installed in the scripts' Python environment."""
    get_project_or_404(project_id, db)
    code, out = await run_command(
        [settings.PYTHON_BIN, "-m", "pip", "list", "--format=json"], timeout=60)
    if code != 0:
        raise HTTPException(status_code=500, detail=f"pip list failed: {out[:300]}")
    try:
        packages = json.loads(out)
    except ValueError:
        packages = []
    return {"python": settings.PYTHON_BIN, "packages": packages}


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

    await send(f"[serverhub] pip install {' '.join(parts)} …")
    try:
        code = await stream_command(
            [settings.PYTHON_BIN, "-m", "pip", "install", "--upgrade", *parts], send)
        await send("[serverhub] ✓ done" if code == 0
                   else f"[serverhub] pip install failed (exit {code})")
    except WebSocketDisconnect:
        return
    await websocket.close()
