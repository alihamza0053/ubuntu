"""
Full log viewer:
  - GET /api/logs/sources                list of available log sources
  - GET /api/logs/nginx/access|error     nginx logs
  - GET /api/logs/supervisor/{name}      dashboard supervisor log
  - GET /api/logs/script/{id}            a script's last-run log
  - GET /api/logs/system                 /var/log/syslog
  - GET /api/logs/download               download any source as .txt
  - WS  /ws/logs/{log_type}/{name}       live tail of any of the above
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..deps import authenticate_websocket, get_current_user
from ..models import Project, Script
from ..services.activity import ACTIVITY_LOG
from ..services.pipeline_service import pipeline_log_path
from ..services.streaming import tail_file
from ..services.supervisor_service import dashboard_log_path

router = APIRouter(tags=["logs"])

TAIL_DEFAULT = 200

# Fixed system log locations
NGINX_ACCESS = Path("/var/log/nginx/access.log")
NGINX_ERROR = Path("/var/log/nginx/error.log")
SYSLOG = Path("/var/log/syslog")


def _safe_name(name: str) -> str:
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid name")
    return name


def _resolve(log_type: str, name: str | None, db: Session) -> Path:
    """Map a (log_type, name) pair to a concrete file path."""
    if log_type == "activity":
        return ACTIVITY_LOG
    if log_type == "nginx":
        return NGINX_ACCESS if name == "access" else NGINX_ERROR
    if log_type == "system":
        return SYSLOG
    if log_type == "supervisor":
        return dashboard_log_path(_safe_name(name or ""), "out")
    if log_type == "app":
        from ..services.app_service import log_path as app_log_path
        return app_log_path(_safe_name(name or ""), "out")
    if log_type == "pipeline":
        return pipeline_log_path(_safe_name(name or ""))
    if log_type == "script":
        script = db.get(Script, int(name)) if name else None
        if not script or not script.last_log:
            raise HTTPException(status_code=404, detail="No log for this script yet")
        return Path(script.last_log)
    raise HTTPException(status_code=400, detail=f"Unknown log type: {log_type}")


def _tail(path: Path, lines: int) -> str:
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Log not found: {path}")
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


@router.get("/api/logs/sources", dependencies=[Depends(get_current_user)])
def log_sources(db: Session = Depends(get_db)):
    """Everything the log viewer can show, for the sidebar."""
    sources = [
        {"type": "nginx", "name": "access", "label": "Nginx access"},
        {"type": "nginx", "name": "error", "label": "Nginx error"},
        {"type": "system", "name": "syslog", "label": "System (syslog)"},
    ]
    for p in db.query(Project).all():
        sources.append({"type": "supervisor", "name": p.name,
                        "label": f"Dashboard: {p.name}"})
        # Pipeline log (only list it once the project has run a pipeline)
        if pipeline_log_path(p.name).is_file():
            sources.append({"type": "pipeline", "name": p.name,
                            "label": f"Pipeline: {p.name}"})
    for s in db.query(Script).filter(Script.last_log.isnot(None)).all():
        sources.append({"type": "script", "name": str(s.id),
                        "label": f"Script: {s.project.name}/{s.filename}"})
    return sources


@router.get("/api/logs/nginx/{stream}", dependencies=[Depends(get_current_user)])
def nginx_log(stream: str, lines: int = Query(TAIL_DEFAULT, ge=1, le=5000)):
    if stream not in ("access", "error"):
        raise HTTPException(status_code=400, detail="stream must be access or error")
    return {"content": _tail(NGINX_ACCESS if stream == "access" else NGINX_ERROR, lines)}


@router.get("/api/logs/system", dependencies=[Depends(get_current_user)])
def system_log(lines: int = Query(TAIL_DEFAULT, ge=1, le=5000)):
    return {"content": _tail(SYSLOG, lines)}


@router.get("/api/logs/activity", dependencies=[Depends(get_current_user)])
def activity_log(lines: int = Query(300, ge=1, le=5000)):
    """The global activity feed (scripts, pipelines, dashboard actions)."""
    if not ACTIVITY_LOG.is_file():
        return {"content": ""}
    return {"content": _tail(ACTIVITY_LOG, lines)}


@router.get("/api/logs/supervisor/{name}", dependencies=[Depends(get_current_user)])
def supervisor_log(name: str, stream: str = Query("out", pattern="^(out|err)$"),
                   lines: int = Query(TAIL_DEFAULT, ge=1, le=5000)):
    return {"content": _tail(dashboard_log_path(_safe_name(name), stream), lines)}


@router.get("/api/logs/script/{script_id}", dependencies=[Depends(get_current_user)])
def script_log(script_id: int, lines: int = Query(2000, ge=1, le=20000),
               db: Session = Depends(get_db)):
    return {"content": _tail(_resolve("script", str(script_id), db), lines)}


@router.get("/api/logs/pipeline/{name}", dependencies=[Depends(get_current_user)])
def pipeline_log(name: str, lines: int = Query(5000, ge=1, le=50000),
                 db: Session = Depends(get_db)):
    return {"content": _tail(_resolve("pipeline", name, db), lines)}


@router.get("/api/logs/app/{name}", dependencies=[Depends(get_current_user)])
def app_log(name: str, lines: int = Query(500, ge=1, le=5000),
            db: Session = Depends(get_db)):
    return {"content": _tail(_resolve("app", name, db), lines)}


@router.get("/api/logs/download", dependencies=[Depends(get_current_user)])
def download_log(log_type: str, name: str = "", db: Session = Depends(get_db)):
    """Download a log source as a .txt attachment."""
    path = _resolve(log_type, name, db)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Log not found")
    content = path.read_text(encoding="utf-8", errors="replace")
    filename = f"{log_type}-{name or 'log'}.txt".replace("/", "-")
    return PlainTextResponse(
        content,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.websocket("/ws/logs/{log_type}/{name}")
async def logs_ws(websocket: WebSocket, log_type: str, name: str):
    """Live-tail any log source (nginx/system/supervisor/script)."""
    user = await authenticate_websocket(websocket, require="logs")
    if user is None:
        return
    await websocket.accept()

    db = SessionLocal()
    try:
        try:
            path = _resolve(log_type, name, db)
        except HTTPException as exc:
            await websocket.send_text(f"[serverhub] {exc.detail}")
            await websocket.close()
            return
    finally:
        db.close()

    async def send(line: str):
        await websocket.send_text(line)

    try:
        await tail_file(path, send)
    except (WebSocketDisconnect, RuntimeError):
        pass
