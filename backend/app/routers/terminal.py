"""
Terminal routes:
  - WS   /ws/terminal            full interactive PTY shell (xterm.js)
  - POST /api/terminal/run       run a single command, capture output
  - GET  /api/terminal/history   recent command history

The interactive shell is the one intentional place raw commands run — it is
single-admin and JWT-protected. It uses a real PTY so colors and interactive
programs (top, nano, etc.) work. PTY support is Linux-only; the import is done
lazily so the module still imports on Windows dev machines.
"""
import asyncio
import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import authenticate_websocket, get_current_user
from ..models import TerminalHistory
from ..services.streaming import run_command

router = APIRouter(tags=["terminal"])

# Shell launched for interactive sessions
SHELL = ["/bin/bash", "-i"]


class RunRequest(dict):
    pass


@router.post("/api/terminal/run", dependencies=[Depends(get_current_user)])
async def terminal_run(body: dict, db: Session = Depends(get_db)):
    """
    Run a single command and return its output. The command is split with
    shlex and executed as an argument list (no shell), then recorded in
    history.
    """
    import shlex

    command = (body.get("command") or "").strip()
    if not command:
        return {"command": command, "output": "", "exit_code": 0}

    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return {"command": command, "output": f"parse error: {exc}", "exit_code": 2}

    exit_code, output = await run_command(argv, timeout=120)

    db.add(TerminalHistory(command=command, output=output[:10000]))
    db.commit()
    return {"command": command, "output": output, "exit_code": exit_code}


@router.get("/api/terminal/history", dependencies=[Depends(get_current_user)])
def terminal_history(db: Session = Depends(get_db), limit: int = 100):
    """Most recent commands run through the single-command runner."""
    rows = (
        db.query(TerminalHistory)
        .order_by(TerminalHistory.executed_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {"id": r.id, "command": r.command, "executed_at": r.executed_at}
        for r in rows
    ]


@router.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket):
    """
    Interactive PTY shell. Client/server exchange JSON frames:
      client → {"type": "input", "data": "..."}    keystrokes
               {"type": "resize", "cols": N, "rows": N}
      server → {"type": "output", "data": "..."}    terminal output
    """
    user = await authenticate_websocket(websocket, require="terminal")
    if user is None:
        return
    await websocket.accept()

    # Lazy Unix-only imports
    try:
        import fcntl
        import os
        import pty
        import struct
        import termios
    except ImportError:
        await websocket.send_text(json.dumps({
            "type": "output",
            "data": "PTY terminal is only available on Linux (the VPS).\r\n",
        }))
        await websocket.close()
        return

    # Spawn a shell attached to a new PTY
    pid, fd = pty.fork()
    if pid == 0:
        # Child: become the shell
        os.execvp(SHELL[0], SHELL)
        return  # unreachable

    loop = asyncio.get_event_loop()

    def set_winsize(rows: int, cols: int):
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

    async def pty_to_ws():
        """Forward shell output to the browser."""
        try:
            while True:
                data = await loop.run_in_executor(None, os.read, fd, 1024)
                if not data:
                    break
                await websocket.send_text(json.dumps({
                    "type": "output",
                    "data": data.decode("utf-8", errors="replace"),
                }))
        except (OSError, WebSocketDisconnect):
            pass

    reader = asyncio.create_task(pty_to_ws())
    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            if msg.get("type") == "input":
                os.write(fd, msg["data"].encode("utf-8"))
            elif msg.get("type") == "resize":
                set_winsize(int(msg.get("rows", 24)), int(msg.get("cols", 80)))
    except (WebSocketDisconnect, json.JSONDecodeError, KeyError):
        pass
    finally:
        reader.cancel()
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.kill(pid, 9)
        except OSError:
            pass
