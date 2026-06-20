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


def _file_icon(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {
        "xlsx": "📊", "xls": "📊", "csv": "📄", "pdf": "📕",
        "png": "🖼️", "jpg": "🖼️", "jpeg": "🖼️", "gif": "🖼️", "svg": "🖼️",
        "doc": "📝", "docx": "📝", "ppt": "📽️", "pptx": "📽️",
        "zip": "🗜️", "rar": "🗜️", "7z": "🗜️", "txt": "📄", "json": "🧾",
    }.get(ext, "📄")


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def _render_page(project: Project) -> str:
    folder = _portal_dir(project)
    folder.mkdir(parents=True, exist_ok=True)
    files = sorted((e for e in folder.iterdir() if e.is_file()),
                   key=lambda e: e.name.lower())
    if files:
        rows = ""
        for f in files:
            st = f.stat()
            modified = datetime.utcfromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
            name = html.escape(f.name)
            rows += (
                f"<tr><td class='fname'><span class='ico'>{_file_icon(f.name)}</span>"
                f"<a href='download/{name}'>{name}</a></td>"
                f"<td class='muted'>{_human_size(st.st_size)}</td>"
                f"<td class='muted'>{modified} UTC</td>"
                f"<td class='right'><a class='dl' href='download/{name}' title='Download'>⬇</a></td></tr>"
            )
        count = f"{len(files)} file{'s' if len(files) != 1 else ''}"
    else:
        rows = "<tr><td colspan='4' class='empty'>No files yet — upload some above.</td></tr>"
        count = "No files yet"

    return (_PAGE_TEMPLATE
            .replace("__TITLE__", html.escape(project.name))
            .replace("__COUNT__", count)
            .replace("__ROWS__", rows))


_PAGE_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ — upload files</title>
<style>
  :root{
    --bg:#0b1120; --card:#121a2b; --card2:#0f1626; --border:#26324a;
    --text:#e6edf6; --muted:#8a97ad; --accent:#3b82f6; --accent2:#2563eb;
    --green:#22c55e;
  }
  *{box-sizing:border-box}
  body{margin:0;background:linear-gradient(180deg,#0b1120,#0d1426);color:var(--text);
       font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.5;
       min-height:100vh;padding:2.5rem 1rem}
  .wrap{max-width:760px;margin:0 auto}
  header{display:flex;align-items:center;gap:.6rem;margin-bottom:1.4rem}
  header .logo{font-size:1.6rem}
  header h1{font-size:1.25rem;margin:0;font-weight:650}
  header .sub{color:var(--muted);font-size:.85rem;margin-top:.1rem}
  .card{background:var(--card);border:1px solid var(--border);border-radius:14px;
        padding:1.25rem;margin-bottom:1.25rem}
  .dz{border:2px dashed var(--border);border-radius:12px;background:var(--card2);
      padding:2rem 1rem;text-align:center;cursor:pointer;transition:.15s}
  .dz:hover,.dz.drag{border-color:var(--accent);background:rgba(59,130,246,.08)}
  .dz .big{font-size:2rem;display:block;margin-bottom:.4rem}
  .dz .t{font-weight:600}
  .dz .s{color:var(--muted);font-size:.85rem;margin-top:.25rem}
  .chips{margin-top:1rem;display:flex;flex-direction:column;gap:.4rem}
  .chip{display:flex;align-items:center;gap:.6rem;background:var(--card2);
        border:1px solid var(--border);border-radius:9px;padding:.5rem .7rem}
  .chip .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .chip .sz{color:var(--muted);font-size:.8rem;white-space:nowrap}
  .chip .x{background:none;border:0;color:var(--muted);cursor:pointer;font-size:1rem;
           padding:.1rem .3rem;border-radius:6px}
  .chip .x:hover{color:#f87171;background:rgba(248,113,113,.12)}
  .bar{margin-top:1rem;height:8px;background:var(--card2);border-radius:99px;overflow:hidden;display:none}
  .bar.show{display:block}
  .bar > i{display:block;height:100%;width:0;background:var(--accent);transition:width .15s}
  .actions{display:flex;align-items:center;gap:.8rem;margin-top:1rem}
  .btn{background:var(--accent2);color:#fff;border:0;border-radius:10px;
       padding:.7rem 1.3rem;font-size:.95rem;font-weight:600;cursor:pointer;transition:.15s}
  .btn:hover{background:var(--accent)}
  .btn:disabled{opacity:.45;cursor:not-allowed}
  .note{color:var(--muted);font-size:.85rem}
  .files h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.04em;
            color:var(--muted);margin:0 0 .6rem}
  table{width:100%;border-collapse:collapse;font-size:.92rem}
  th,td{text-align:left;padding:.6rem .4rem;border-bottom:1px solid var(--border)}
  th{font-size:.7rem;text-transform:uppercase;color:var(--muted);letter-spacing:.04em}
  tr:last-child td{border-bottom:0}
  td.fname{display:flex;align-items:center;gap:.5rem}
  td.fname a{color:var(--text);text-decoration:none}
  td.fname a:hover{color:var(--accent);text-decoration:underline}
  .ico{font-size:1.05rem}
  .muted{color:var(--muted);white-space:nowrap}
  .right{text-align:right}
  .dl{color:var(--muted);text-decoration:none;font-size:1.1rem}
  .dl:hover{color:var(--accent)}
  .empty{text-align:center;color:var(--muted);padding:2rem 0}
  .ok{color:var(--green);font-size:.85rem;margin-left:.2rem}
  @media(max-width:560px){ th.hide,td.hide{display:none} }
</style></head>
<body>
 <div class="wrap">
   <header>
     <span class="logo">📁</span>
     <div>
       <h1>__TITLE__</h1>
       <div class="sub">Upload files for this project</div>
     </div>
   </header>

   <div class="card">
     <form id="form" method="post" action="upload" enctype="multipart/form-data">
       <div class="dz" id="dz">
         <span class="big">⬆️</span>
         <span class="t">Drag &amp; drop files here</span>
         <div class="s">or click to choose — one or more. Same name replaces the existing file.</div>
       </div>
       <input id="input" type="file" name="files" multiple hidden>
       <div class="chips" id="chips"></div>
       <div class="bar" id="bar"><i id="barfill"></i></div>
       <div class="actions">
         <button class="btn" id="go" type="submit" disabled>⬆ Upload</button>
         <span class="note" id="status">__COUNT__</span>
       </div>
     </form>
   </div>

   <div class="card files">
     <h2>Current files</h2>
     <table>
       <thead><tr><th>File</th><th class="hide">Size</th><th class="hide">Modified</th><th></th></tr></thead>
       <tbody>__ROWS__</tbody>
     </table>
   </div>
 </div>

<script>
 const input=document.getElementById('input'), dz=document.getElementById('dz'),
       chips=document.getElementById('chips'), go=document.getElementById('go'),
       form=document.getElementById('form'), statusEl=document.getElementById('status'),
       bar=document.getElementById('bar'), barfill=document.getElementById('barfill');
 const dt=new DataTransfer();
 function human(n){ if(n<1024)return n+' B'; if(n<1048576)return (n/1024).toFixed(1)+' KB'; return (n/1048576).toFixed(1)+' MB'; }
 function esc(s){ const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }
 function sync(){ try{ input.files=dt.files; }catch(e){} render(); }
 function render(){
   const fs=Array.from(dt.files);
   chips.innerHTML=fs.map((f,i)=>`<div class="chip"><span class="nm">${esc(f.name)}</span><span class="sz">${human(f.size)}</span><button type="button" class="x" data-i="${i}" title="Remove">✕</button></div>`).join('');
   go.disabled=fs.length===0;
   statusEl.textContent=fs.length?`${fs.length} file${fs.length>1?'s':''} ready`:'__COUNT__';
 }
 function add(list){ for(const f of list) dt.items.add(f); sync(); }
 dz.addEventListener('click',()=>input.click());
 input.addEventListener('change',e=>{ add(e.target.files); input.value=''; sync(); });
 chips.addEventListener('click',e=>{ const b=e.target.closest('.x'); if(b){ dt.items.remove(+b.dataset.i); sync(); } });
 ['dragenter','dragover'].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.add('drag');}));
 ['dragleave','dragend'].forEach(ev=>dz.addEventListener(ev,e=>{dz.classList.remove('drag');}));
 dz.addEventListener('drop',e=>{ e.preventDefault(); dz.classList.remove('drag'); add(e.dataTransfer.files); });
 form.addEventListener('submit',e=>{
   e.preventDefault();
   if(!dt.files.length) return;
   const fd=new FormData(); for(const f of dt.files) fd.append('files',f);
   const xhr=new XMLHttpRequest(); xhr.open('POST','upload');
   go.disabled=true; go.textContent='Uploading…'; bar.classList.add('show');
   xhr.upload.onprogress=ev=>{ if(ev.lengthComputable){ barfill.style.width=Math.round(ev.loaded/ev.total*100)+'%'; } };
   xhr.onload=()=>{ if(xhr.status>=200&&xhr.status<400){ location.reload(); } else { alert('Upload failed ('+xhr.status+')'); go.disabled=false; go.textContent='⬆ Upload'; bar.classList.remove('show'); } };
   xhr.onerror=()=>{ alert('Upload failed — network error'); go.disabled=false; go.textContent='⬆ Upload'; bar.classList.remove('show'); };
   xhr.send(fd);
 });
</script>
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
