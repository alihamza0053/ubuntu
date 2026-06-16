"""
Settings routes: change admin password, panel key/value settings, a download
of the panel SQLite database for backup, and panel self-update.
"""
from datetime import datetime

from fastapi import (APIRouter, Depends, HTTPException, WebSocket,
                     WebSocketDisconnect)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings as app_settings
from ..database import get_db
from ..deps import authenticate_websocket, get_current_user
from ..models import Setting
from ..schemas import DetailResponse
from ..services.streaming import run_command, stream_command, tail_file

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(get_current_user)],
)
ws_router = APIRouter(tags=["settings"])   # update WS authenticates via ?token=


class SettingsUpdate(BaseModel):
    # Arbitrary key/value pairs (panel port, subdomain, etc.)
    values: dict[str, str]


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    """All stored panel settings as a flat dict."""
    rows = db.query(Setting).all()
    return {r.key: r.value for r in rows}


@router.put("", response_model=DetailResponse)
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    for key, value in body.values.items():
        row = db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = value
        else:
            db.add(Setting(key=key, value=value))
    db.commit()
    return DetailResponse(detail="Settings saved")


@router.post("/backup-db")
def backup_db():
    """Download the panel's SQLite database file."""
    db_path = app_settings.DB_PATH
    if not db_path.is_file():
        raise HTTPException(status_code=404, detail="Database file not found")
    return FileResponse(db_path, filename="serverhub-backup.db",
                        media_type="application/octet-stream")


# ---------------------------------------------------------------------------
# Self-update
# ---------------------------------------------------------------------------
SELF_UPDATE_BIN = str(app_settings.PANEL_ROOT / "bin" / "serverhub-self-update")


@router.get("/update/info")
async def update_info():
    """
    Report whether a panel update is available, by inspecting the source
    checkout the panel redeploys from (``UPDATE_SRC``). Best-effort: a missing
    checkout or no network just returns a friendly message.
    """
    src = app_settings.UPDATE_SRC
    info: dict = {"src": str(src)}

    if not (src / "deploy" / "update.sh").is_file():
        info.update(ready=False, git=False,
                    message=f"No source checkout at {src}. Set UPDATE_SRC in "
                            "backend/.env to a git clone / uploaded bundle.")
        return info
    info["ready"] = True

    if not (src / ".git").exists():
        info.update(git=False,
                    message="Source is present but not a git checkout — "
                            "'Update now' will redeploy the current files.")
        return info
    info["git"] = True

    # Current commit
    code, out = await run_command(
        ["git", "-C", str(src), "log", "-1", "--format=%h %s"], timeout=15)
    info["current"] = out.strip() if code == 0 else "unknown"

    # Fetch + how many commits behind the upstream branch
    behind = None
    # -c credential helpers off so a private remote can't block on a prompt;
    # the timeout is the backstop.
    fcode, _ = await run_command(
        ["git", "-c", "credential.helper=", "-C", str(src), "fetch", "--quiet"],
        timeout=20)
    if fcode == 0:
        bcode, bout = await run_command(
            ["git", "-C", str(src), "rev-list", "--count", "HEAD..@{u}"],
            timeout=15)
        if bcode == 0 and bout.strip().isdigit():
            behind = int(bout.strip())
    info["behind"] = behind
    if behind is None:
        info["message"] = "Couldn't check the remote (no upstream or no network)."
    elif behind == 0:
        info["message"] = "Panel is up to date."
    else:
        info["message"] = f"{behind} update(s) available."
    return info


@ws_router.websocket("/ws/settings/update")
async def update_ws(websocket: WebSocket):
    """
    Run the panel self-update, streaming output live. The update detaches
    itself before restarting the panel, so this WebSocket will drop near the
    end (the panel restarts) — that is expected; the update still completes.
    Optional ?backend_only=1 / ?frontend_only=1 / ?no_pull=1 query flags.
    """
    user = await authenticate_websocket(websocket)
    if user is None:
        return
    await websocket.accept()

    async def send(line: str):
        await websocket.send_text(line)

    src = app_settings.UPDATE_SRC
    if not (src / "deploy" / "update.sh").is_file():
        await send(f"[serverhub] No update.sh under {src}/deploy.")
        await send("[serverhub] Set UPDATE_SRC in backend/.env to your source "
                   "checkout (a git clone or uploaded bundle).")
        await send("[serverhub] update failed")
        await websocket.close()
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = app_settings.PANEL_ROOT / "backups" / f"self-update-{stamp}.log"

    extra: list[str] = []
    q = websocket.query_params
    if q.get("backend_only"):
        extra.append("--backend-only")
    if q.get("frontend_only"):
        extra.append("--frontend-only")
    if q.get("no_pull"):
        extra.append("--no-pull")

    sudo_blocked = {"hit": False}

    async def watch(line: str):
        if "a password is required" in line or "sudo:" in line.lower():
            sudo_blocked["hit"] = True
        await send(line)

    await send("[serverhub] starting update…")
    cmd = ["sudo", "-n", SELF_UPDATE_BIN, str(src), str(log_path), *extra]
    code = await stream_command(cmd, watch)

    if sudo_blocked["hit"] or code == 127:
        await send("[serverhub] The panel isn't allowed to run the updater via "
                   "sudo. Re-run deploy/update.sh once on the server to install "
                   "the sudoers rule.")
        await websocket.close()
        return
    if code != 0:
        await send(f"[serverhub] launcher exited with code {code}")
        await websocket.close()
        return

    # Launcher returned immediately; the real update now runs detached and
    # writes to log_path. Tail it live until the panel is restarted under us.
    await send("[serverhub] ── live update log ──")
    try:
        await tail_file(log_path, send, backlog=200)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        # Most likely the panel itself is being restarted by the update.
        try:
            await send("[serverhub] panel is restarting to finish the update…")
        except Exception:
            pass
