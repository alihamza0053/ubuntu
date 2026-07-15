"""Local source workspaces for Docker-based Shopify apps."""
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, field_validator

from ..config import settings
from ..deps import get_current_user
from ..schemas import DetailResponse
from ..services.paths import ensure_within

router = APIRouter(prefix="/api/shopify-apps", tags=["shopify-apps"],
                   dependencies=[Depends(get_current_user)])

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_EXTRACTED_BYTES = 300 * 1024 * 1024


class WorkspaceCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        name = value.strip().lower().replace(" ", "-")
        if not name or len(name) > 64 or not all(c.isalnum() or c in "-_" for c in name):
            raise ValueError("Use 1-64 letters, numbers, hyphens, or underscores")
        return name


def root() -> Path:
    settings.SHOPIFY_APPS_ROOT.mkdir(parents=True, exist_ok=True)
    return settings.SHOPIFY_APPS_ROOT.resolve()


def workspace(name: str) -> Path:
    return ensure_within(root(), root() / WorkspaceCreate(name=name).name)


@router.get("")
def list_workspaces():
    base = root()
    entries = []
    for entry in sorted(base.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_dir():
            entries.append({
                "name": entry.name,
                "path": str(entry),
                "has_dockerfile": (entry / "Dockerfile").is_file(),
                "modified": datetime.utcfromtimestamp(entry.stat().st_mtime),
            })
    return entries


@router.post("", response_model=DetailResponse, status_code=201)
def create_workspace(body: WorkspaceCreate):
    target = workspace(body.name)
    if target.exists():
        raise HTTPException(status_code=409, detail="A Shopify app workspace already exists with this name")
    target.mkdir(parents=True)
    return DetailResponse(detail=f"Created {target}")


@router.post("/{name}/archive", response_model=DetailResponse)
async def upload_source_archive(name: str, file: UploadFile = File(...)):
    """Replace a workspace with a safely-extracted ZIP source archive."""
    target = workspace(name)
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload a .zip source archive")

    data = await file.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="Archive is larger than 100 MB")

    import io
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP archive")

    infos = archive.infolist()
    if sum(info.file_size for info in infos) > MAX_EXTRACTED_BYTES:
        raise HTTPException(status_code=413, detail="Uncompressed archive is larger than 300 MB")
    for info in infos:
        member = Path(info.filename)
        if member.is_absolute() or ".." in member.parts:
            raise HTTPException(status_code=400, detail="Archive contains an unsafe path")
        # ZIP symlinks can point outside the workspace; reject them.
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise HTTPException(status_code=400, detail="Archive may not contain symbolic links")

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    archive.extractall(target)

    # Archive tools often wrap source in one top-level directory. Flatten it so
    # Dockerfile and package files land directly in the selected workspace.
    children = list(target.iterdir())
    if len(children) == 1 and children[0].is_dir() and not (target / "Dockerfile").exists():
        wrapped = children[0]
        for child in wrapped.iterdir():
            child.rename(target / child.name)
        wrapped.rmdir()

    return DetailResponse(detail=f"Uploaded source to {target}")
