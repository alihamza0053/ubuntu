"""
Settings routes: change admin password, panel key/value settings, a download
of the panel SQLite database for backup, panel self-update, and system cleanup.
"""
import asyncio
import re
from datetime import datetime
from pathlib import Path

import psutil
from fastapi import (APIRouter, Depends, File, HTTPException, UploadFile,
                     WebSocket, WebSocketDisconnect)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings as app_settings
from ..database import get_db
from ..deps import authenticate_websocket, get_current_user, require_admin
from ..models import Setting
from ..schemas import DetailResponse
from ..services import backup_service, trash_service
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
# Full backup & restore
# ---------------------------------------------------------------------------
class BackupCreate(BaseModel):
    components: list[str]


class RestoreRequest(BaseModel):
    components: list[str]


@router.get("/backups")
def list_backups():
    """Installable backup components + existing backup archives."""
    return {
        "components": backup_service.COMPONENTS,
        "backups": backup_service.list_backups(),
    }


@router.post("/backups")
def create_backup(body: BackupCreate):
    try:
        return backup_service.create_backup(body.components)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/backups/{name}/download")
def download_backup(name: str):
    try:
        path = backup_service.backup_file_path(name)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return FileResponse(path, filename=name, media_type="application/gzip")


@router.delete("/backups/{name}", response_model=DetailResponse)
def delete_backup(name: str):
    try:
        backup_service.delete_backup(name)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return DetailResponse(detail="Backup deleted")


@router.post("/backups/import")
async def import_backup(file: UploadFile = File(...)):
    data = await file.read()
    try:
        return backup_service.save_uploaded(file.filename or "backup.tar.gz", data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/backups/{name}/restore")
def restore_backup(name: str, body: RestoreRequest):
    try:
        return backup_service.restore_backup(name, body.components)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except (RuntimeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# System cleanup (Settings → System Cleanup, admin only)
# ---------------------------------------------------------------------------
CLEANUP_BIN = str(app_settings.PANEL_ROOT / "bin" / "serverhub-cleanup")

# Tasks the root helper script understands, in display order. `trash` is
# handled inside the panel (no root needed) — it empties the recycle bin.
CLEANUP_TASKS: list[tuple[str, str, str]] = [
    ("tmp", "Temp files", "Files in /tmp and /var/tmp untouched for over a day"),
    ("apt", "APT cache", "Downloaded .deb packages + packages nothing needs anymore"),
    ("journal", "System journal", "systemd journal logs older than 3 days"),
    ("logs", "Rotated logs", "Old compressed/rotated log files under /var/log"),
    ("pip", "Pip cache", "Python package download caches"),
    ("docker", "Docker leftovers", "Dangling images + build cache (never containers)"),
    ("trash", "Recycle bin", "Everything in the panel's recycle bin, immediately"),
    ("ram", "RAM caches", "Flush filesystem caches from memory (drop_caches)"),
]
CLEANUP_TASK_KEYS = {k for k, _, _ in CLEANUP_TASKS}


def _dir_size(path: Path) -> int | None:
    """Best-effort recursive size; None when the path can't be read at all."""
    if not path.exists():
        return None
    total = 0
    try:
        stack = [path]
        while stack:
            current = stack.pop()
            try:
                for entry in current.iterdir():
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir():
                            stack.append(entry)
                        elif entry.is_file():
                            total += entry.stat().st_size
                    except OSError:
                        continue
            except OSError:
                continue
    except OSError:
        return None
    return total


def _rotated_logs_size() -> int | None:
    root = Path("/var/log")
    if not root.exists():
        return None
    total = 0
    try:
        for entry in root.rglob("*"):
            try:
                name = entry.name
                if entry.is_file() and (
                        name.endswith((".gz", ".xz", ".old"))
                        or name.rsplit(".", 1)[-1].isdigit()):
                    total += entry.stat().st_size
            except OSError:
                continue
    except OSError:
        return None
    return total


# Disk locations reported in the "where is my disk going" breakdown.
DISK_BREAKDOWN: list[tuple[str, str]] = [
    ("/srv/projects", "Project workspaces"),
    ("/srv/websites", "Websites"),
    ("/srv/serverhub/apps", "Installed apps (data)"),
    ("/srv/serverhub/backups", "Panel backups"),
    ("/srv/serverhub/trash", "Recycle bin"),
    ("/srv/onedrive", "OneDrive sync"),
    ("/var/lib/mysql", "MySQL databases"),
    ("/var/log", "System logs"),
    ("/var/cache/apt/archives", "APT package cache"),
    ("/tmp", "Temp (/tmp)"),
    ("/var/tmp", "Temp (/var/tmp)"),
    ("/home", "Home directories"),
]


async def _du(path: str) -> int | None:
    """Best-effort recursive size of a directory via `du` (bytes)."""
    if not Path(path).exists():
        return None
    try:
        code, out = await run_command(["du", "-sb", path], timeout=25)
    except OSError:
        return None
    # stderr is merged in (permission warnings) — find the total line, which
    # du prints even when parts of the tree weren't readable.
    for line in reversed(out.splitlines()):
        m = re.match(r"^(\d+)\s", line)
        if m:
            return int(m.group(1))
    return None


async def _docker_df() -> list[dict] | None:
    """Docker disk usage rows (images/containers/volumes/build cache)."""
    try:
        code, out = await run_command(["sudo", "-n", "docker", "system", "df"],
                                      timeout=20)
    except OSError:
        return None
    if code != 0:
        return None
    rows = []
    for line in out.splitlines()[1:]:
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 5:
            rows.append({"type": parts[0], "count": parts[1],
                         "size": parts[3], "reclaimable": parts[4]})
    return rows or None


def _top_processes() -> tuple[float, list[dict], list[dict]]:
    """(total CPU %, top by CPU, top by memory) over a short sampling window."""
    psutil.cpu_percent(None)      # prime the system-wide counter
    procs = []
    for p in psutil.process_iter(["pid", "name", "username"]):
        try:
            p.cpu_percent(None)   # prime the per-process counter
            procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    import time
    time.sleep(0.4)               # sampling window for cpu_percent
    total_cpu = psutil.cpu_percent(None)

    snapshot = []
    for p in procs:
        if p.pid == 0:   # kernel idle pseudo-process
            continue
        try:
            with p.oneshot():
                snapshot.append({
                    "pid": p.pid,
                    "name": p.info.get("name") or "?",
                    "user": p.info.get("username") or "?",
                    "cpu": round(p.cpu_percent(None), 1),
                    "memory_percent": round(p.memory_percent(), 1),
                    "memory_mb": round(p.memory_info().rss / 1024**2, 1),
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    by_cpu = sorted(snapshot, key=lambda x: x["cpu"], reverse=True)[:8]
    by_mem = sorted(snapshot, key=lambda x: x["memory_mb"], reverse=True)[:8]
    return total_cpu, by_cpu, by_mem


@router.get("/cleanup/preview", dependencies=[Depends(require_admin)])
async def cleanup_preview():
    """
    Full CPU / RAM / Disk picture for the System Cleanup section:
    load + top processes, memory breakdown, and where disk space is going —
    plus a best-effort size for each cleanable item.
    """
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    # Top processes sample in a thread (it sleeps 0.4s to measure CPU)
    cpu_total, top_cpu, top_mem = await asyncio.to_thread(_top_processes)

    try:
        load_avg = [round(x, 2) for x in psutil.getloadavg()]
    except (AttributeError, OSError):
        load_avg = None

    # Disk breakdown: all `du`s + docker df run concurrently
    du_sizes, docker_rows = await asyncio.gather(
        asyncio.gather(*(_du(path) for path, _ in DISK_BREAKDOWN)),
        _docker_df(),
    )
    breakdown = [
        {"path": path, "label": label, "size": size}
        for (path, label), size in zip(DISK_BREAKDOWN, du_sizes)
        if size is not None
    ]
    breakdown.sort(key=lambda x: x["size"], reverse=True)

    trash_count = 0
    trash_size = 0
    if app_settings.TRASH_ROOT.exists():
        for item in app_settings.TRASH_ROOT.iterdir():
            if item.is_dir():
                trash_count += 1
                trash_size += _dir_size(item) or 0

    sizes: dict[str, int | None] = {
        "tmp": (_dir_size(Path("/tmp")) or 0) + (_dir_size(Path("/var/tmp")) or 0)
               if Path("/tmp").exists() else None,
        "apt": _dir_size(Path("/var/cache/apt/archives")),
        "journal": _dir_size(Path("/var/log/journal")),
        "logs": _rotated_logs_size(),
        "pip": _dir_size(Path.home() / ".cache" / "pip"),
        "docker": None,   # shown via the docker df table instead
        "trash": trash_size,
        "ram": getattr(memory, "cached", 0) or None,
    }

    return {
        "cpu": {
            "percent": cpu_total,
            "cores": psutil.cpu_count() or 1,
            "load_avg": load_avg,
            "top": top_cpu,
        },
        "memory": {
            "percent": memory.percent,
            "used_gb": round(memory.used / 1024**3, 2),
            "available_gb": round(memory.available / 1024**3, 2),
            "total_gb": round(memory.total / 1024**3, 2),
            "cached_gb": round(getattr(memory, "cached", 0) / 1024**3, 2),
            "top": top_mem,
        },
        "disk": {
            "percent": disk.percent,
            "used_gb": round(disk.used / 1024**3, 2),
            "free_gb": round(disk.free / 1024**3, 2),
            "total_gb": round(disk.total / 1024**3, 2),
            "breakdown": breakdown,
            "docker": docker_rows,
        },
        "tasks": [
            {"key": key, "label": label, "description": desc,
             "size": sizes.get(key),
             **({"count": trash_count} if key == "trash" else {})}
            for key, label, desc in CLEANUP_TASKS
        ],
        "ready": Path(CLEANUP_BIN).is_file(),
    }


@ws_router.websocket("/ws/settings/cleanup")
async def cleanup_ws(websocket: WebSocket):
    """
    Run the selected cleanup tasks with live output. Admin only.
    Connect with ?token=JWT&tasks=tmp,apt,ram — task keys from CLEANUP_TASKS.
    """
    user = await authenticate_websocket(websocket, require="settings")
    if user is None:
        return
    if not user.is_admin:
        await websocket.close(code=1008, reason="Admin access required")
        return
    await websocket.accept()

    async def send(line: str):
        await websocket.send_text(line)

    raw = websocket.query_params.get("tasks", "")
    tasks = [t for t in (x.strip() for x in raw.split(",")) if t in CLEANUP_TASK_KEYS]
    if not tasks:
        await send("[serverhub] no valid cleanup tasks selected")
        await websocket.close()
        return

    # Recycle bin: handled by the panel itself (its own files, no root needed).
    if "trash" in tasks:
        await send("── recycle bin: delete everything now ──")
        removed, freed = trash_service.purge_all()
        await send(f"removed {removed} item(s), freed {freed / 1024**2:.1f} MB")
        await send("")
        tasks = [t for t in tasks if t != "trash"]

    if not tasks:
        await send("[serverhub] ✓ cleanup finished")
        await websocket.close()
        return

    sudo_blocked = {"hit": False}

    async def watch(line: str):
        if "a password is required" in line or line.lower().startswith("sudo:"):
            sudo_blocked["hit"] = True
        await send(line)

    try:
        code = await stream_command(["sudo", "-n", CLEANUP_BIN, *tasks], watch)
    except WebSocketDisconnect:
        return

    if sudo_blocked["hit"] or code == 127:
        await send("[serverhub] The panel isn't allowed to run the cleanup "
                   "helper via sudo yet. Re-run deploy/update.sh once on the "
                   "server to install it:")
        await send("[serverhub]   cd /opt/serverhub-src && sudo bash deploy/update.sh")
    elif code != 0:
        await send(f"[serverhub] cleanup exited with code {code}")
    else:
        await send("[serverhub] ✓ cleanup finished")
    await websocket.close()


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

    # The repo is usually cloned by root (get.sh/update.sh) while the panel runs
    # as `serverhub`; without safe.directory, git aborts with "dubious ownership"
    # and the panel could never see updates. Credential helper off so a private
    # remote can't block on a password prompt (the timeout is the backstop).
    git = ["git", "-c", f"safe.directory={src}", "-c", "credential.helper=",
           "-C", str(src)]

    # Current commit
    code, out = await run_command([*git, "log", "-1", "--format=%h %s"], timeout=15)
    info["current"] = out.strip() if code == 0 else "unknown"

    behind = None
    available = False
    fcode, ferr = await run_command([*git, "fetch", "--quiet"], timeout=40)
    if fcode == 0:
        lc, local = await run_command([*git, "rev-parse", "HEAD"], timeout=15)
        rc, remote = await run_command([*git, "rev-parse", "@{u}"], timeout=15)
        if lc == 0 and rc == 0:
            available = local.strip() != remote.strip()
            bc, bout = await run_command(
                [*git, "rev-list", "--count", "HEAD..@{u}"], timeout=15)
            if bc == 0 and bout.strip().isdigit():
                behind = int(bout.strip())
        if available and not behind:
            behind = 1   # shallow clone: exact count may be unavailable
    info["behind"] = behind

    if fcode != 0:
        info["message"] = ("Couldn't reach the remote (check the panel's network "
                           "or repo access).")
    elif available:
        info["message"] = (f"{behind} update(s) available." if behind
                           else "Update available.")
    else:
        info["message"] = "Panel is up to date."
    return info


@ws_router.websocket("/ws/settings/update")
async def update_ws(websocket: WebSocket):
    """
    Run the panel self-update, streaming output live. The update detaches
    itself before restarting the panel, so this WebSocket will drop near the
    end (the panel restarts) — that is expected; the update still completes.
    Optional ?backend_only=1 / ?frontend_only=1 / ?no_pull=1 query flags.
    """
    user = await authenticate_websocket(websocket, require="settings")
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
