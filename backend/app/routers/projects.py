"""
Project workspace routes: CRUD, per-folder file upload/list/download/delete.

A project is a folder under PROJECTS_ROOT with the fixed layout:
    code/  allscripts/  data/  dashboard/  logs/
plus a supervisor program for its Streamlit dashboard.
"""
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import (APIRouter, Depends, HTTPException, Query, UploadFile)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import Project, Script
from pydantic import BaseModel

from ..schemas import (DetailResponse, FileInfo, ProjectCreate, ProjectFilesOut,
                       ProjectOut, ScriptOut)


class DomainRequest(BaseModel):
    domain: str
from ..models import NginxConfig
from ..services import nginx_service, supervisor_service, venv_service
from ..services.paths import safe_join, validate_extension, validate_filename

router = APIRouter(
    prefix="/api/projects",
    tags=["projects"],
    dependencies=[Depends(get_current_user)],  # every route requires auth
)

# Which extensions each project sub-folder accepts on upload
FOLDER_EXTENSIONS = {
    "code": settings.SCRIPT_EXTENSIONS,
    "allscripts": settings.SCRIPT_EXTENSIONS,
    "data": settings.DATA_EXTENSIONS,
    "dashboard": settings.DASHBOARD_EXTENSIONS,
}


# ---------- helpers ----------

def get_project_or_404(project_id: int, db: Session) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def project_root(project: Project) -> Path:
    return settings.PROJECTS_ROOT / project.name


def list_folder(project: Project, folder: str) -> list[FileInfo]:
    """List regular files in one project sub-folder (non-recursive)."""
    folder_path = project_root(project) / folder
    if not folder_path.is_dir():
        return []
    files = []
    for entry in sorted(folder_path.iterdir()):
        if entry.is_file():
            stat = entry.stat()
            files.append(FileInfo(
                name=entry.name,
                size=stat.st_size,
                modified=datetime.utcfromtimestamp(stat.st_mtime),
            ))
    return files


def project_to_out(project: Project, db: Session, with_status: bool = False) -> ProjectOut:
    """Build the API shape including computed dashboard-card fields."""
    out = ProjectOut.model_validate(project)
    out.file_counts = {
        folder: len(list_folder(project, folder))
        for folder in ("code", "allscripts", "data", "dashboard")
    }
    # Most recent script run across the project
    last = (
        db.query(Script)
        .filter(Script.project_id == project.id, Script.last_run.isnot(None))
        .order_by(Script.last_run.desc())
        .first()
    )
    if last:
        out.last_script_run = last.last_run
        out.last_script_status = last.last_status
    out.venv_status = venv_service.status(project.name)
    if with_status:
        # Live supervisor status (one subprocess call per project)
        state, _ = supervisor_service.status(project.name)
        out.dashboard_status = state
        if state != project.dashboard_status:
            project.dashboard_status = state
            db.commit()
    return out


def sync_scripts(project: Project, db: Session) -> None:
    """
    Keep the scripts table in sync with .py files on disk in code/ and
    allscripts/ — adds new files, removes rows whose file disappeared.
    """
    on_disk = set()
    for folder in ("code", "allscripts"):
        folder_path = project_root(project) / folder
        if folder_path.is_dir():
            for entry in folder_path.glob("*.py"):
                on_disk.add((folder, entry.name))

    existing = {(s.folder, s.filename): s for s in project.scripts}
    for key in on_disk - existing.keys():
        db.add(Script(project_id=project.id, folder=key[0], filename=key[1]))
    for key in existing.keys() - on_disk:
        db.delete(existing[key])
    db.commit()


# ---------- CRUD ----------

@router.get("", response_model=list[ProjectOut])
def list_projects(
    with_status: bool = Query(False, description="Also query live supervisor status"),
    db: Session = Depends(get_db),
):
    return [project_to_out(p, db, with_status) for p in db.query(Project).all()]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    """Create the DB row, the folder structure and the supervisor config."""
    if db.query(Project).filter(Project.name == body.name).first():
        raise HTTPException(status_code=409, detail="A project with this name already exists")

    root = settings.PROJECTS_ROOT / body.name
    if root.exists():
        raise HTTPException(status_code=409, detail=f"Folder already exists: {root}")

    port = supervisor_service.allocate_port(db)

    # 1. Folder structure
    for folder in settings.PROJECT_FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)

    # 2. Supervisor program (autostart=false — user starts it from the UI)
    try:
        supervisor_service.write_config(body.name, port)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)  # roll back folders
        raise

    # 3. DB row
    project = Project(
        name=body.name,
        folder_path=str(root),
        dashboard_port=port,
        dashboard_status="STOPPED",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # 4. Build the dashboard's Python venv in the background (streamlit + deps),
    #    so "Start dashboard" works without a manual setup step.
    venv_service.ensure_async(body.name)

    return project_to_out(project, db)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    project = get_project_or_404(project_id, db)
    sync_scripts(project, db)
    return project_to_out(project, db, with_status=True)


@router.post("/{project_id}/build-venv", response_model=DetailResponse)
def build_venv(project_id: int, db: Session = Depends(get_db)):
    """(Re)build the dashboard's Python environment in the background."""
    project = get_project_or_404(project_id, db)
    if venv_service.is_building(project.name):
        return DetailResponse(detail="Environment is already being built…")
    started = venv_service.ensure_async(project.name)
    if not started and venv_service.is_ready(project.name):
        return DetailResponse(detail="Environment is already ready")
    return DetailResponse(detail="Building the dashboard environment "
                                 "(streamlit + packages)… watch logs/venv-setup.log")


@router.delete("/{project_id}", response_model=DetailResponse)
def delete_project(
    project_id: int,
    delete_files: bool = Query(False, description="Also delete the project folder on disk"),
    db: Session = Depends(get_db),
):
    project = get_project_or_404(project_id, db)
    # Stop dashboard + remove its supervisor program first
    try:
        supervisor_service.remove_config(project.name)
    except HTTPException:
        pass  # supervisor unreachable shouldn't block deletion of the record

    if delete_files:
        root = project_root(project)
        if root.is_dir():
            shutil.rmtree(root)

    db.delete(project)  # cascades to scripts
    db.commit()
    return DetailResponse(detail=f"Project '{project.name}' deleted")


# ---------- Files ----------

@router.get("/{project_id}/files", response_model=ProjectFilesOut)
def list_files(project_id: int, db: Session = Depends(get_db)):
    """All files grouped by sub-folder (for the Files tab and editor tree)."""
    project = get_project_or_404(project_id, db)
    return ProjectFilesOut(folders={
        folder: list_folder(project, folder)
        for folder in ("code", "allscripts", "data", "dashboard", "logs")
    })


@router.get("/{project_id}/scripts", response_model=list[ScriptOut])
def list_scripts(project_id: int, db: Session = Depends(get_db)):
    """Registered scripts with their last-run info (Scripts tab)."""
    project = get_project_or_404(project_id, db)
    sync_scripts(project, db)
    return project.scripts


async def _save_upload(project: Project, folder: str, file: UploadFile) -> FileInfo:
    """Validate name + extension, then stream the upload to disk."""
    filename = validate_filename(file.filename or "")
    validate_extension(filename, FOLDER_EXTENSIONS[folder])
    dest = safe_join(project_root(project), folder, filename)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)
    stat = dest.stat()
    return FileInfo(name=filename, size=stat.st_size,
                    modified=datetime.utcfromtimestamp(stat.st_mtime))


@router.post("/{project_id}/upload-script", response_model=list[FileInfo])
async def upload_script(
    project_id: int,
    files: list[UploadFile],
    folder: str = Query("code", pattern="^(code|allscripts)$"),
    db: Session = Depends(get_db),
):
    """Upload one or more scripts into code/ or allscripts/."""
    project = get_project_or_404(project_id, db)
    saved = [await _save_upload(project, folder, f) for f in files]
    sync_scripts(project, db)  # register new .py files as runnable scripts
    return saved


@router.post("/{project_id}/upload-dashboard", response_model=list[FileInfo])
async def upload_dashboard(project_id: int, files: list[UploadFile],
                           db: Session = Depends(get_db)):
    """Upload Streamlit dashboard files (entrypoint must be app.py)."""
    project = get_project_or_404(project_id, db)
    return [await _save_upload(project, "dashboard", f) for f in files]


@router.post("/{project_id}/upload-data", response_model=list[FileInfo])
async def upload_data(project_id: int, files: list[UploadFile],
                      db: Session = Depends(get_db)):
    """Upload Excel/CSV data files into data/."""
    project = get_project_or_404(project_id, db)
    return [await _save_upload(project, "data", f) for f in files]


@router.get("/{project_id}/download")
def download_file(
    project_id: int,
    folder: str = Query(..., pattern="^(code|allscripts|data|dashboard|logs)$"),
    filename: str = Query(...),
    db: Session = Depends(get_db),
):
    project = get_project_or_404(project_id, db)
    path = safe_join(project_root(project), folder, validate_filename(filename))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=path.name)


@router.delete("/{project_id}/files", response_model=DetailResponse)
def delete_file(
    project_id: int,
    folder: str = Query(..., pattern="^(code|allscripts|data|dashboard|logs)$"),
    filename: str = Query(...),
    db: Session = Depends(get_db),
):
    project = get_project_or_404(project_id, db)
    path = safe_join(project_root(project), folder, validate_filename(filename))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    path.unlink()
    sync_scripts(project, db)  # drop the script row if a .py was removed
    return DetailResponse(detail=f"Deleted {folder}/{filename}")


# ---------- Domain & SSL ----------

def _upsert_nginx_config(db: Session, entity_type: str, entity_id: int,
                         config_path: str, domain: str) -> None:
    """Record (or update) the NginxConfig row for an entity."""
    row = (
        db.query(NginxConfig)
        .filter(NginxConfig.entity_type == entity_type, NginxConfig.entity_id == entity_id)
        .first()
    )
    if row:
        row.config_path, row.domain = config_path, domain
    else:
        db.add(NginxConfig(entity_type=entity_type, entity_id=entity_id,
                           config_path=config_path, domain=domain))
    db.commit()


@router.post("/{project_id}/assign-domain", response_model=DetailResponse)
def assign_domain(project_id: int, body: DomainRequest, db: Session = Depends(get_db)):
    """Generate the Streamlit nginx proxy block for this project's dashboard."""
    project = get_project_or_404(project_id, db)
    slug = f"project-{project.name}"
    content = nginx_service.build_block(
        "streamlit", domain=body.domain, port=project.dashboard_port
    )
    config_path = nginx_service.write_site(slug, content)
    project.domain = body.domain
    _upsert_nginx_config(db, "project", project.id, str(config_path), body.domain)
    db.commit()
    return DetailResponse(detail=f"Domain {body.domain} assigned and nginx reloaded")


@router.post("/{project_id}/ssl", response_model=DetailResponse)
def project_ssl(project_id: int, db: Session = Depends(get_db)):
    """Request a Let's Encrypt certificate for the project's domain."""
    project = get_project_or_404(project_id, db)
    if not project.domain:
        raise HTTPException(status_code=400, detail="Assign a domain first")
    nginx_service.request_ssl(project.domain)
    return DetailResponse(detail=f"SSL issued for {project.domain}")
