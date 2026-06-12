"""
File read/write routes used by the Monaco code editor.

Phase 1 scope: restricted to the panel-managed roots (PROJECTS_ROOT,
WEBSITES_ROOT, NGINX_CONFIGS_ROOT). The full server-wide file manager
arrives in Phase 3 and will extend these same endpoints.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import settings
from ..deps import get_current_user
from ..schemas import DetailResponse, FileReadResponse, FileWriteRequest
from ..services.paths import ensure_in_allowed_roots

router = APIRouter(
    prefix="/api/files",
    tags=["files"],
    dependencies=[Depends(get_current_user)],
)

MAX_EDITOR_FILE_BYTES = 2 * 1024 * 1024  # don't load huge files into Monaco


def _editable_path(raw_path: str) -> Path:
    """Validate an absolute path for editor access (root + extension)."""
    path = ensure_in_allowed_roots(Path(raw_path))
    if path.suffix.lower() not in settings.EDITABLE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"'{path.suffix}' files cannot be opened in the editor",
        )
    return path


@router.get("/read", response_model=FileReadResponse)
def read_file(path: str = Query(..., description="Absolute path on the server")):
    """Load a file's content for the Monaco editor."""
    file_path = _editable_path(path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if file_path.stat().st_size > MAX_EDITOR_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File too large for the editor (>2 MB)")
    return FileReadResponse(
        path=str(file_path),
        content=file_path.read_text(encoding="utf-8", errors="replace"),
    )


@router.post("/write", response_model=DetailResponse)
def write_file(body: FileWriteRequest):
    """Save edited content back to disk."""
    file_path = _editable_path(body.path)
    if not file_path.parent.is_dir():
        raise HTTPException(status_code=400, detail="Parent directory does not exist")
    file_path.write_text(body.content, encoding="utf-8")
    return DetailResponse(detail=f"Saved {file_path}")
