"""
Server tools: live stats, supervisor + system process lists, supervisor
program control, and the APT package manager (search + live install/remove
via WebSocket).
"""
import time

import psutil
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..config import settings
from ..deps import authenticate_websocket, get_current_user
from ..schemas import DetailResponse
from ..services.streaming import run_command, stream_command

router = APIRouter(
    prefix="/api/server",
    tags=["server"],
    dependencies=[Depends(get_current_user)],
)

# WebSocket routes can't use the HTTP bearer dependency (no Authorization
# header on a WS handshake) — they authenticate via ?token= instead, so they
# live on a separate dependency-free router.
ws_router = APIRouter(tags=["server"])


class AptRequest(BaseModel):
    package: str


def _supervisorctl_cmd(*args: str) -> list[str]:
    cmd = ["supervisorctl", *args]
    return ["sudo", "-n", *cmd] if settings.SUPERVISORCTL_USE_SUDO else cmd


@router.get("/stats")
def server_stats():
    """Point-in-time CPU / RAM / disk / uptime snapshot."""
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    uptime_seconds = int(time.time() - psutil.boot_time())
    days, rem = divmod(uptime_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "memory": {"percent": memory.percent,
                   "used_gb": round(memory.used / 1024**3, 2),
                   "total_gb": round(memory.total / 1024**3, 2)},
        "disk": {"percent": disk.percent,
                 "used_gb": round(disk.used / 1024**3, 2),
                 "total_gb": round(disk.total / 1024**3, 2)},
        "uptime": {"seconds": uptime_seconds, "human": f"{days}d {hours}h {minutes}m"},
    }


@router.get("/processes")
async def processes():
    """Supervisor programs + top system processes by memory."""
    # Supervisor programs
    code, out = await run_command(_supervisorctl_cmd("status"), timeout=20)
    supervisor = []
    if code == 0 or out:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                supervisor.append({"name": parts[0], "state": parts[1],
                                   "detail": " ".join(parts[2:])})

    # Top system processes
    procs = []
    for p in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent"]):
        try:
            info = p.info
            procs.append({
                "pid": info["pid"], "name": info["name"], "user": info["username"],
                "cpu": round(info["cpu_percent"] or 0, 1),
                "memory": round(info["memory_percent"] or 0, 1),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda x: x["memory"], reverse=True)
    return {"supervisor": supervisor, "system": procs[:25]}


@router.post("/supervisor/{name}/{action}", response_model=DetailResponse)
async def supervisor_control(name: str, action: str):
    """start / stop / restart a supervisor program."""
    if action not in ("start", "stop", "restart"):
        raise HTTPException(status_code=400, detail="action must be start/stop/restart")
    if "/" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid program name")
    code, out = await run_command(_supervisorctl_cmd(action, name), timeout=30)
    return DetailResponse(detail=out.strip() or f"{action} {name}")


@router.get("/apt/search")
async def apt_search(q: str = Query(..., min_length=2)):
    """Search apt packages (apt-cache search)."""
    code, out = await run_command(["apt-cache", "search", q], timeout=30)
    results = []
    for line in out.splitlines()[:100]:
        if " - " in line:
            name, _, desc = line.partition(" - ")
            results.append({"name": name.strip(), "description": desc.strip()})
    return results


# --- HTTP apt actions (non-streaming convenience) ---

@router.post("/apt/update", response_model=DetailResponse)
async def apt_update():
    code, out = await run_command(["sudo", "-n", "apt-get", "update"], timeout=300)
    return DetailResponse(detail=out[-2000:])


@router.post("/apt/upgrade")
async def apt_upgrade_preview():
    """Preview what an upgrade would change (does not apply it — use the WS to apply)."""
    code, out = await run_command(
        ["sudo", "-n", "apt-get", "--simulate", "upgrade"], timeout=120)
    return {"preview": out[-4000:]}


# --- Live-streaming apt actions over WebSocket ---

@ws_router.websocket("/ws/apt/{action}")
async def apt_ws(websocket: WebSocket, action: str):
    """
    Stream an apt operation live. Connect with ?token=JWT and, for
    install/remove, ?package=NAME.
      action ∈ update | upgrade | install | remove
    """
    user = await authenticate_websocket(websocket, require="server")
    if user is None:
        return
    await websocket.accept()

    package = websocket.query_params.get("package", "")
    base = ["sudo", "-n", "apt-get", "-y"]
    if action == "update":
        cmd = ["sudo", "-n", "apt-get", "update"]
    elif action == "upgrade":
        cmd = base + ["upgrade"]
    elif action in ("install", "remove"):
        # Validate package name (letters/numbers/.+-_ only)
        import re
        if not re.match(r"^[A-Za-z0-9.+_-]+$", package):
            await websocket.send_text("[serverhub] invalid package name")
            await websocket.close()
            return
        cmd = base + [action, package]
    else:
        await websocket.send_text("[serverhub] unknown action")
        await websocket.close()
        return

    async def send(line: str):
        await websocket.send_text(line)

    try:
        code = await stream_command(cmd, send)
        await websocket.send_text(f"[serverhub] finished exit_code={code}")
        await websocket.close()
    except WebSocketDisconnect:
        pass
