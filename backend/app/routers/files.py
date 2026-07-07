"""
Global file manager + Monaco editor file access.

Every path is confined to the panel-managed roots (PROJECTS_ROOT,
WEBSITES_ROOT, NGINX_CONFIGS_ROOT) via ensure_in_allowed_roots — requests for
anything outside are rejected. Browsing starts at /srv.
"""
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import settings
from ..deps import get_current_user
from ..schemas import DetailResponse, FileReadResponse, FileWriteRequest
from ..services import trash_service
from ..services.paths import ensure_in_allowed_roots, validate_filename

router = APIRouter(
    prefix="/api/files",
    tags=["files"],
    dependencies=[Depends(get_current_user)],
)

MAX_EDITOR_FILE_BYTES = 2 * 1024 * 1024


class RenameRequest(BaseModel):
    path: str
    new_name: str


class MoveRequest(BaseModel):
    source: str
    dest_dir: str


class MkdirRequest(BaseModel):
    path: str


class DeleteRequest(BaseModel):
    path: str


def _entry_info(entry: Path) -> dict:
    stat = entry.stat()
    return {
        "name": entry.name,
        "is_dir": entry.is_dir(),
        "size": stat.st_size,
        "modified": datetime.utcfromtimestamp(stat.st_mtime),
        "path": str(entry),
    }


@router.get("/browse")
def browse(path: str = Query("", description="Directory to list; defaults to /srv roots")):
    """
    List a directory. With no path, returns the managed roots as the starting
    points so the user can drill into projects/websites/nginx-configs.
    """
    if not path:
        roots = []
        for root in (settings.PROJECTS_ROOT, settings.WEBSITES_ROOT,
                     settings.NGINX_CONFIGS_ROOT, settings.ONEDRIVE_ROOT):
            roots.append({
                "name": root.name, "is_dir": True, "size": 0,
                "modified": datetime.utcnow(), "path": str(root),
            })
        return {"path": "", "parent": None, "entries": roots}

    target = ensure_in_allowed_roots(Path(path))
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    entries = sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    # parent is null when at a managed root (don't allow climbing above)
    parent = str(target.parent)
    try:
        ensure_in_allowed_roots(target.parent)
    except HTTPException:
        parent = None
    return {"path": str(target), "parent": parent,
            "entries": [_entry_info(e) for e in entries]}


@router.get("/read", response_model=FileReadResponse)
def read_file(path: str = Query(...)):
    """Load a file for the Monaco editor."""
    file_path = ensure_in_allowed_roots(Path(path))
    if file_path.suffix.lower() not in settings.EDITABLE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"'{file_path.suffix}' is not an editable type")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if file_path.stat().st_size > MAX_EDITOR_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File too large for the editor (>2 MB)")
    return FileReadResponse(path=str(file_path),
                            content=file_path.read_text(encoding="utf-8", errors="replace"))


@router.post("/write", response_model=DetailResponse)
def write_file(body: FileWriteRequest):
    """Save edited content back to disk."""
    file_path = ensure_in_allowed_roots(Path(body.path))
    if file_path.suffix.lower() not in settings.EDITABLE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"'{file_path.suffix}' is not an editable type")
    if not file_path.parent.is_dir():
        raise HTTPException(status_code=400, detail="Parent directory does not exist")
    file_path.write_text(body.content, encoding="utf-8")
    return DetailResponse(detail=f"Saved {file_path}")


@router.post("/upload", response_model=DetailResponse)
async def upload(path: str = Query(..., description="Destination directory"),
                 files: list[UploadFile] = None):
    """Upload one or more files into a directory."""
    dest_dir = ensure_in_allowed_roots(Path(path))
    if not dest_dir.is_dir():
        raise HTTPException(status_code=400, detail="Destination is not a directory")
    count = 0
    for file in files or []:
        name = validate_filename(file.filename or "")
        dest = dest_dir / name
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
        count += 1
    return DetailResponse(detail=f"Uploaded {count} file(s)")


@router.post("/mkdir", response_model=DetailResponse)
def mkdir(body: MkdirRequest):
    target = ensure_in_allowed_roots(Path(body.path))
    target.mkdir(parents=True, exist_ok=True)
    return DetailResponse(detail=f"Created {target}")


@router.post("/rename", response_model=DetailResponse)
def rename(body: RenameRequest):
    source = ensure_in_allowed_roots(Path(body.path))
    new_name = validate_filename(body.new_name)
    if not source.exists():
        raise HTTPException(status_code=404, detail="Source not found")
    target = source.parent / new_name
    source.rename(target)
    return DetailResponse(detail=f"Renamed to {new_name}")


@router.post("/move", response_model=DetailResponse)
def move(body: MoveRequest):
    source = ensure_in_allowed_roots(Path(body.source))
    dest_dir = ensure_in_allowed_roots(Path(body.dest_dir))
    if not source.exists():
        raise HTTPException(status_code=404, detail="Source not found")
    if not dest_dir.is_dir():
        raise HTTPException(status_code=400, detail="Destination is not a directory")
    shutil.move(str(source), str(dest_dir / source.name))
    return DetailResponse(detail=f"Moved {source.name} → {dest_dir}")


@router.delete("/delete", response_model=DetailResponse)
def delete(body: DeleteRequest):
    target = ensure_in_allowed_roots(Path(body.path))
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    # Project/website files go to the recycle bin (restorable for 24h); other
    # managed paths (e.g. nginx configs) are still deleted outright.
    if trash_service.is_trashable(target):
        trash_service.move_to_trash(target)
        return DetailResponse(detail=f"Moved {target.name} to the recycle bin")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return DetailResponse(detail=f"Deleted {target}")


@router.get("/download")
def download(path: str = Query(...)):
    file_path = ensure_in_allowed_roots(Path(path))
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, filename=file_path.name)
