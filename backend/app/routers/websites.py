"""
Website routes: CRUD, zip upload (auto-extract + optional React build),
domain assignment, SSL, and file listing.
"""
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import NginxConfig, Website
from ..schemas import DetailResponse, FileInfo
from ..services import nginx_service, website_service

router = APIRouter(
    prefix="/api/websites",
    tags=["websites"],
    dependencies=[Depends(get_current_user)],
)

VALID_TYPES = {"react", "php", "html"}


class WebsiteCreate(BaseModel):
    name: str
    type: str
    db_name: str | None = None

    @field_validator("name")
    @classmethod
    def slug(cls, v: str) -> str:
        v = v.strip().lower().replace(" ", "-")
        if not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError("Name may only contain letters, numbers, '-' and '_'")
        return v

    @field_validator("type")
    @classmethod
    def type_ok(cls, v: str) -> str:
        if v not in VALID_TYPES:
            raise ValueError(f"type must be one of {VALID_TYPES}")
        return v


class DomainRequest(BaseModel):
    domain: str


class LinkDatabaseRequest(BaseModel):
    # Empty / null unlinks the database
    db_name: str | None = None


def get_website_or_404(website_id: int, db: Session) -> Website:
    site = db.get(Website, website_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Website not found")
    return site


def _to_out(site: Website) -> dict:
    return {
        "id": site.id, "name": site.name, "type": site.type,
        "folder_path": site.folder_path, "domain": site.domain,
        "db_name": site.db_name, "created_at": site.created_at,
    }


@router.get("")
def list_websites(db: Session = Depends(get_db)):
    return [_to_out(s) for s in db.query(Website).all()]


@router.post("", status_code=201)
def create_website(body: WebsiteCreate, db: Session = Depends(get_db)):
    if db.query(Website).filter(Website.name == body.name).first():
        raise HTTPException(status_code=409, detail="A website with this name already exists")
    root = website_service.website_root(body.name)
    root.mkdir(parents=True, exist_ok=True)
    site = Website(name=body.name, type=body.type, folder_path=str(root), db_name=body.db_name)
    db.add(site)
    db.commit()
    db.refresh(site)
    return _to_out(site)


@router.get("/{website_id}")
def get_website(website_id: int, db: Session = Depends(get_db)):
    return _to_out(get_website_or_404(website_id, db))


@router.delete("/{website_id}", response_model=DetailResponse)
def delete_website(website_id: int, delete_files: bool = Query(False),
                   db: Session = Depends(get_db)):
    site = get_website_or_404(website_id, db)
    nginx_service.remove_site(f"website-{site.name}")
    db.query(NginxConfig).filter(
        NginxConfig.entity_type == "website", NginxConfig.entity_id == site.id
    ).delete()
    if delete_files:
        import shutil
        shutil.rmtree(website_service.website_root(site.name), ignore_errors=True)
    db.delete(site)
    db.commit()
    return DetailResponse(detail=f"Website '{site.name}' deleted")


@router.post("/{website_id}/upload")
async def upload_website(website_id: int, file: UploadFile,
                         build: bool = Query(False, description="Run npm build (React)"),
                         replace: bool = Query(True, description="Clear folder first"),
                         db: Session = Depends(get_db)):
    """Upload a .zip of the site; auto-extract, optionally build React."""
    site = get_website_or_404(website_id, db)
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload a .zip archive")

    root = website_service.reset_folder(site.name) if replace else website_service.website_root(site.name)

    # Stream the upload to a temp file, then extract
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        while chunk := await file.read(1024 * 1024):
            tmp.write(chunk)
        tmp_path = Path(tmp.name)
    try:
        website_service.extract_zip(tmp_path, root)
    finally:
        tmp_path.unlink(missing_ok=True)

    result = {"detail": "Uploaded and extracted"}
    if build and site.type == "react":
        code, output = await website_service.build_react(site.name)
        result = {"detail": "Built" if code == 0 else "Build failed",
                  "build_exit_code": code, "build_output": output[-4000:]}
    return result


@router.get("/{website_id}/files", response_model=list[FileInfo])
def list_website_files(website_id: int, subpath: str = Query(""),
                       db: Session = Depends(get_db)):
    """List files at the top level (or a subpath) of the website folder."""
    site = get_website_or_404(website_id, db)
    from ..services.paths import ensure_within
    base = website_service.website_root(site.name)
    target = ensure_within(base, base / subpath) if subpath else base
    if not target.is_dir():
        return []
    out = []
    for entry in sorted(target.iterdir()):
        stat = entry.stat()
        out.append(FileInfo(
            name=entry.name + ("/" if entry.is_dir() else ""),
            size=stat.st_size,
            modified=datetime.utcfromtimestamp(stat.st_mtime),
        ))
    return out


@router.post("/{website_id}/link-database", response_model=DetailResponse)
def link_database(website_id: int, body: LinkDatabaseRequest, db: Session = Depends(get_db)):
    """Link (or unlink, with an empty value) a MySQL database to a website."""
    site = get_website_or_404(website_id, db)
    site.db_name = (body.db_name or "").strip() or None
    db.commit()
    if site.db_name:
        return DetailResponse(detail=f"Linked database '{site.db_name}'")
    return DetailResponse(detail="Database unlinked")


@router.post("/{website_id}/assign-domain", response_model=DetailResponse)
def assign_domain(website_id: int, body: DomainRequest, db: Session = Depends(get_db)):
    """Generate the nginx block matching the website type and reload."""
    site = get_website_or_404(website_id, db)
    slug = f"website-{site.name}"
    content = nginx_service.build_block(site.type, domain=body.domain, folder=site.name)
    config_path = nginx_service.write_site(slug, content)
    site.domain = body.domain

    row = (db.query(NginxConfig)
           .filter(NginxConfig.entity_type == "website", NginxConfig.entity_id == site.id)
           .first())
    if row:
        row.config_path, row.domain = str(config_path), body.domain
    else:
        db.add(NginxConfig(entity_type="website", entity_id=site.id,
                           config_path=str(config_path), domain=body.domain))
    db.commit()
    return DetailResponse(detail=f"Domain {body.domain} assigned and nginx reloaded")


@router.post("/{website_id}/ssl", response_model=DetailResponse)
def website_ssl(website_id: int, db: Session = Depends(get_db)):
    site = get_website_or_404(website_id, db)
    if not site.domain:
        raise HTTPException(status_code=400, detail="Assign a domain first")
    nginx_service.request_ssl(site.domain)
    return DetailResponse(detail=f"SSL issued for {site.domain}")
