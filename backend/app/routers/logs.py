"""
Log routes (Phase 1 subset):
  - GET /api/logs/supervisor/{name}   tail of a dashboard's supervisor log
  - WS  /ws/logs/supervisor/{name}    live tail -f style streaming

The full log viewer (nginx, syslog, search) lands in Phase 2 on top of
the same tail/stream helpers.
"""
import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from ..deps import authenticate_websocket, get_current_user
from ..services.supervisor_service import dashboard_log_path

router = APIRouter(tags=["logs"])

TAIL_DEFAULT_LINES = 200


def _tail(path: Path, lines: int) -> str:
    """Return the last `lines` lines of a text file (read-safe)."""
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Log file not found: {path}")
    content = path.read_text(encoding="utf-8", errors="replace")
    return "\n".join(content.splitlines()[-lines:])


@router.get("/api/logs/supervisor/{name}", dependencies=[Depends(get_current_user)])
def supervisor_log(
    name: str,
    stream: str = Query("out", pattern="^(out|err)$"),
    lines: int = Query(TAIL_DEFAULT_LINES, ge=1, le=5000),
):
    """Last N lines of a dashboard's supervisor stdout/stderr log."""
    # `name` is a project name; dashboard_log_path builds a fixed pattern
    # inside SUPERVISOR_LOG_DIR so traversal isn't possible, but reject
    # separators anyway for defense in depth.
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid name")
    return {"name": name, "content": _tail(dashboard_log_path(name, stream), lines)}


@router.websocket("/ws/logs/supervisor/{name}")
async def supervisor_log_ws(websocket: WebSocket, name: str):
    """
    Live-stream a dashboard's supervisor log (like `tail -f`).

    Sends the last 50 lines on connect, then new content as it is written.
    """
    user = await authenticate_websocket(websocket)
    if user is None:
        return
    if "/" in name or "\\" in name or ".." in name:
        await websocket.close(code=1008, reason="Invalid name")
        return

    await websocket.accept()
    stream = websocket.query_params.get("stream", "out")
    if stream not in ("out", "err"):
        stream = "out"
    path = dashboard_log_path(name, stream)
    try:
        # Wait for the file to appear if the process hasn't logged yet
        while not path.is_file():
            await websocket.send_text("[serverhub] waiting for log file...")
            await asyncio.sleep(2)

        with path.open("r", encoding="utf-8", errors="replace") as fh:
            # Send a small backlog first
            backlog = fh.readlines()[-50:]
            for line in backlog:
                await websocket.send_text(line.rstrip("\n"))
            # Then poll for appended lines (simple + portable tail -f)
            while True:
                line = fh.readline()
                if line:
                    await websocket.send_text(line.rstrip("\n"))
                else:
                    await asyncio.sleep(0.5)
    except (WebSocketDisconnect, RuntimeError):
        pass  # client closed the connection
