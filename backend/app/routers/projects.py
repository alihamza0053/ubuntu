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
from ..deps import get_current_user, require_admin
from ..models import Project, Script, User
from pydantic import BaseModel

from ..schemas import (DetailResponse, FileInfo, ProjectCreate, ProjectFilesOut,
                       ProjectOut, ScriptOut)


class DomainRequest(BaseModel):
    domain: str
from ..models import NginxConfig
from ..security import hash_password
from ..services import nginx_service, supervisor_service, trash_service, venv_service
from ..services.paths import (ensure_within, safe_join, validate_extension,
                              validate_filename)

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
    user: User = Depends(get_current_user),
):
    query = db.query(Project)
    if not user.is_admin:   # admin-hidden projects are invisible to others
        query = query.filter(Project.hidden.is_(False))
    return [project_to_out(p, db, with_status) for p in query.all()]


class HiddenRequest(BaseModel):
    hidden: bool


@router.put("/{project_id}/hidden", response_model=DetailResponse,
            dependencies=[Depends(require_admin)])
def set_hidden(project_id: int, body: HiddenRequest, db: Session = Depends(get_db)):
    """Hide/unhide this project for non-admin users (admin only)."""
    project = get_project_or_404(project_id, db)
    project.hidden = body.hidden
    db.commit()
    return DetailResponse(detail=f"Project '{project.name}' is now "
                                 f"{'hidden from' if body.hidden else 'visible to'} non-admins")


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
        for folder in ("code", "allscripts", "data", "dashboard", "logs", "onedrivefiles")
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
    folder: str = Query(..., pattern="^(code|allscripts|data|dashboard|logs|onedrivefiles)$"),
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
    folder: str = Query(..., pattern="^(code|allscripts|data|dashboard|logs|onedrivefiles)$"),
    filename: str = Query(...),
    db: Session = Depends(get_db),
):
    project = get_project_or_404(project_id, db)
    path = safe_join(project_root(project), folder, validate_filename(filename))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    trash_service.move_to_trash(path)  # recoverable from the recycle bin for 24h
    sync_scripts(project, db)  # drop the script row if a .py was removed
    return DetailResponse(detail=f"Moved {folder}/{filename} to the recycle bin")


# ---------- OneDrive (read-only synced files) ----------

class OneDrivePathRequest(BaseModel):
    # Subfolder relative to ONEDRIVE_ROOT this project reads from ("" = root).
    path: str


def _onedrive_base(project: Project) -> Path:
    """Absolute path of this project's mapped OneDrive folder."""
    rel = (project.onedrive_path or "").strip("/")
    base = settings.ONEDRIVE_ROOT / rel if rel else settings.ONEDRIVE_ROOT
    return ensure_within(settings.ONEDRIVE_ROOT, base)


@router.put("/{project_id}/onedrive-path", response_model=DetailResponse)
def set_onedrive_path(project_id: int, body: OneDrivePathRequest,
                      db: Session = Depends(get_db)):
    """Map this project to a OneDrive subfolder (relative to ONEDRIVE_ROOT)."""
    project = get_project_or_404(project_id, db)
    rel = body.path.strip().strip("/")
    # Validate the target stays inside the OneDrive root (rejects ../ escapes).
    ensure_within(settings.ONEDRIVE_ROOT, settings.ONEDRIVE_ROOT / rel if rel
                  else settings.ONEDRIVE_ROOT)
    project.onedrive_path = rel or None
    db.commit()
    return DetailResponse(detail=f"OneDrive folder set to '{rel or '(root)'}'")


@router.get("/{project_id}/onedrive")
def list_onedrive(project_id: int, subpath: str = Query(""),
                  db: Session = Depends(get_db)):
    """List the project's mapped OneDrive folder (dirs + files), navigable."""
    project = get_project_or_404(project_id, db)
    base = _onedrive_base(project)
    sub = subpath.strip().strip("/")
    target = ensure_within(base, base / sub if sub else base)

    if not settings.ONEDRIVE_ROOT.exists():
        return {"mapped": project.onedrive_path, "subpath": sub, "parent": None,
                "available": False, "entries": []}
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="OneDrive folder not found yet")

    entries = []
    for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        st = entry.stat()
        entries.append({
            "name": entry.name,
            "is_dir": entry.is_dir(),
            "size": st.st_size,
            "modified": datetime.utcfromtimestamp(st.st_mtime),
            "rel": f"{sub}/{entry.name}" if sub else entry.name,
        })
    parent = sub.rsplit("/", 1)[0] if "/" in sub else ("" if sub else None)
    return {"mapped": project.onedrive_path, "subpath": sub, "parent": parent,
            "available": True, "entries": entries}


@router.get("/{project_id}/onedrive/download")
def download_onedrive(project_id: int, path: str = Query(...),
                      db: Session = Depends(get_db)):
    """Download one file from the project's mapped OneDrive folder."""
    project = get_project_or_404(project_id, db)
    base = _onedrive_base(project)
    rel = path.strip().strip("/")
    target = ensure_within(base, base / rel)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target, filename=target.name)


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


def _write_project_site(project: Project, domain: str) -> str:
    """(Re)write the project's nginx block (dashboard + /onedrivefiles/ portal)."""
    slug = f"project-{project.name}"
    content = nginx_service.project_block(
        domain=domain, port=project.dashboard_port,
        project=project.name, panel_port=settings.PANEL_PORT,
    )
    return str(nginx_service.write_site(slug, content))


@router.post("/{project_id}/assign-domain", response_model=DetailResponse)
def assign_domain(project_id: int, body: DomainRequest, db: Session = Depends(get_db)):
    """Generate the project's nginx block (dashboard + upload portal) and reload."""
    project = get_project_or_404(project_id, db)
    config_path = _write_project_site(project, body.domain)
    project.domain = body.domain
    _upsert_nginx_config(db, "project", project.id, config_path, body.domain)
    db.commit()
    return DetailResponse(detail=f"Domain {body.domain} assigned and nginx reloaded")


# ---------- Upload portal (per-project, password-protected) ----------

class PortalAuthRequest(BaseModel):
    username: str
    password: str


@router.put("/{project_id}/portal-auth", response_model=DetailResponse)
def set_portal_auth(project_id: int, body: PortalAuthRequest, db: Session = Depends(get_db)):
    """Enable/update the project's upload portal username + password."""
    project = get_project_or_404(project_id, db)
    username = body.username.strip()
    if not username or len(body.password) < 4:
        raise HTTPException(status_code=400,
                            detail="Username required and password must be at least 4 characters")
    project.portal_username = username
    project.portal_password_hash = hash_password(body.password)
    # Persist the credentials FIRST so a later nginx hiccup can't lose them.
    db.commit()
    # Make sure the upload folder exists.
    (project_root(project) / "onedrivefiles").mkdir(parents=True, exist_ok=True)
    # If a domain is already assigned, refresh its nginx block so the portal
    # location is present (older blocks predate this feature). Best-effort.
    if project.domain:
        try:
            _write_project_site(project, project.domain)
        except HTTPException:
            return DetailResponse(detail="Credentials saved, but updating nginx failed — "
                                         "re-assign the project's domain to apply.")
    return DetailResponse(detail="Upload portal enabled — share <domain>/onedrivefiles/")


@router.delete("/{project_id}/portal-auth", response_model=DetailResponse)
def disable_portal_auth(project_id: int, db: Session = Depends(get_db)):
    """Disable the upload portal (clears its credentials)."""
    project = get_project_or_404(project_id, db)
    project.portal_username = None
    project.portal_password_hash = None
    db.commit()
    return DetailResponse(detail="Upload portal disabled")


@router.post("/{project_id}/ssl", response_model=DetailResponse)
def project_ssl(project_id: int, db: Session = Depends(get_db)):
    """Request a Let's Encrypt certificate for the project's domain."""
    project = get_project_or_404(project_id, db)
    if not project.domain:
        raise HTTPException(status_code=400, detail="Assign a domain first")
    nginx_service.request_ssl(project.domain)
    return DetailResponse(detail=f"SSL issued for {project.domain}")
