"""
Public per-project upload portal, served at <project-domain>/onedrivefiles/.

This is NOT behind the panel login — outside people use it to upload files for a
project. It is protected by a per-project username/password (HTTP Basic) that the
project owner sets in the panel. Files land in
/srv/projects/<project>/onedrivefiles/ where the project's scripts can read them;
uploading a file with an existing name replaces it.

The project's nginx block proxies /onedrivefiles/ → /portal/<project>/ on the
panel (see nginx_service.project_block). These routes live outside /api/ so the
permission middleware lets them through; auth is enforced here instead.
"""
import html
import logging
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Project
from ..security import verify_password

router = APIRouter(tags=["portal"])
_basic = HTTPBasic(auto_error=False)
log = logging.getLogger("uvicorn.error")

UNAUTHORIZED = HTTPException(
    status_code=401, detail="Authentication required",
    headers={"WWW-Authenticate": 'Basic realm="Upload portal"'},
)


def _portal_dir(project: Project) -> Path:
    return settings.PROJECTS_ROOT / project.name / "onedrivefiles"


def _safe_name(filename: str) -> str:
    name = Path(filename or "").name
    if not name or name in (".", ".."):
        raise HTTPException(status_code=400, detail=f"Invalid filename: {filename!r}")
    return name


def _authed_project(project_name: str, credentials: HTTPBasicCredentials | None,
                    db: Session) -> Project:
    """Load the project and verify the portal credentials, else 401/404."""
    project = db.query(Project).filter(Project.name == project_name).first()
    if project is None or not (project.portal_username and project.portal_password_hash):
        # Don't reveal whether the project exists; portal simply isn't available.
        raise HTTPException(status_code=404, detail="Upload portal not available")
    if credentials is None:
        raise UNAUTHORIZED
    user_ok = secrets.compare_digest(credentials.username, project.portal_username)
    pass_ok = verify_password(credentials.password, project.portal_password_hash)
    if not (user_ok and pass_ok):
        log.warning("portal: auth rejected for project=%r", project_name)
        raise UNAUTHORIZED
    return project


def _render_page(project: Project) -> str:
    folder = _portal_dir(project)
    folder.mkdir(parents=True, exist_ok=True)
    rows = ""
    files = sorted((e for e in folder.iterdir() if e.is_file()),
                   key=lambda e: e.name.lower())
    if files:
        for f in files:
            st = f.stat()
            size = st.st_size
            size_str = (f"{size} B" if size < 1024 else
                        f"{size/1024:.1f} KB" if size < 1024*1024 else
                        f"{size/1024/1024:.1f} MB")
            modified = datetime.utcfromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
            name = html.escape(f.name)
            rows += (f"<tr><td><a href='download/{name}'>{name}</a></td>"
                     f"<td>{size_str}</td><td>{modified} UTC</td></tr>")
    else:
        rows = "<tr><td colspan='3' class='empty'>No files yet.</td></tr>"

    title = html.escape(project.name)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — file upload</title>
<style>
 :root {{ color-scheme: light dark; }}
 body {{ font-family: system-ui, sans-serif; max-width: 820px; margin: 2rem auto;
        padding: 0 1rem; line-height: 1.5; }}
 h1 {{ font-size: 1.4rem; }}
 .card {{ border: 1px solid #8884; border-radius: 10px; padding: 1rem 1.25rem;
         margin: 1rem 0; }}
 table {{ width: 100%; border-collapse: collapse; font-size: .95rem; }}
 th, td {{ text-align: left; padding: .5rem .4rem; border-bottom: 1px solid #8883; }}
 th {{ font-size: .75rem; text-transform: uppercase; opacity: .6; }}
 .empty {{ text-align: center; opacity: .6; padding: 1.5rem 0; }}
 input[type=file] {{ margin: .5rem 0; }}
 button {{ background:#2563eb; color:#fff; border:0; border-radius:8px;
          padding:.6rem 1.1rem; font-size:1rem; cursor:pointer; }}
 .hint {{ opacity:.65; font-size:.85rem; }}
</style></head>
<body>
 <h1>📁 {title} — upload files</h1>
 <div class="card">
   <form method="post" action="upload" enctype="multipart/form-data">
     <p>Select one or more files. Uploading a file with the same name replaces it.</p>
     <input type="file" name="files" multiple required>
     <div><button type="submit">⬆ Upload</button></div>
   </form>
 </div>
 <div class="card">
   <h2 style="font-size:1rem;">Current files</h2>
   <table>
     <thead><tr><th>File</th><th>Size</th><th>Modified</th></tr></thead>
     <tbody>{rows}</tbody>
   </table>
 </div>
 <p class="hint">Files you upload here are used by the project automatically.</p>
</body></html>"""


@router.get("/portal/{project_name}/", response_class=HTMLResponse)
def portal_page(project_name: str,
                credentials: HTTPBasicCredentials | None = Depends(_basic),
                db: Session = Depends(get_db)):
    project = _authed_project(project_name, credentials, db)
    return HTMLResponse(_render_page(project))


@router.post("/portal/{project_name}/upload")
async def portal_upload(project_name: str,
                        files: list[UploadFile] = File(...),
                        credentials: HTTPBasicCredentials | None = Depends(_basic),
                        db: Session = Depends(get_db)):
    project = _authed_project(project_name, credentials, db)
    folder = _portal_dir(project)
    folder.mkdir(parents=True, exist_ok=True)
    for f in files:
        dest = folder / _safe_name(f.filename or "")
        with dest.open("wb") as out:               # overwrite same-named files
            while chunk := await f.read(1024 * 1024):
                out.write(chunk)
    # Relative redirect keeps the browser under /onedrivefiles/.
    return RedirectResponse(url="./", status_code=303)


@router.get("/portal/{project_name}/download/{filename}")
def portal_download(project_name: str, filename: str,
                    credentials: HTTPBasicCredentials | None = Depends(_basic),
                    db: Session = Depends(get_db)):
    project = _authed_project(project_name, credentials, db)
    path = _portal_dir(project) / _safe_name(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=path.name)
