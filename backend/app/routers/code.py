"""
Code editor routes (sidebar → Code). Everything here needs the `code` tab —
and when the owner switched "Only me" on, being the owner.

/api/code/auth is different: nginx calls it (auth_request) for every request
to /ide/ with the browser's editor cookie, not a bearer token.
"""
import asyncio
from urllib.parse import quote

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Project, User, Website
from ..config import settings
from ..schemas import DetailResponse
from ..services import bg_tasks, code_editor as ce, user_audit
from ..services.activity import log_activity

router = APIRouter(prefix="/api/code", tags=["code"])


TASK = "code-install"


def _install() -> str:
    out = ce.install()
    log_activity("💻 code editor installed")
    return out.strip()[-400:] or "Installed"


class OwnerOnlyRequest(BaseModel):
    enabled: bool


def allowed_user(user: User = Depends(get_current_user)) -> User:
    ce.require(user)
    return user


@router.get("/auth", include_in_schema=False)
def auth(serverhub_code: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    """nginx auth_request: 204 when the editor cookie belongs to someone allowed in."""
    username = ce.cookie_username(serverhub_code)
    user = db.query(User).filter(User.username == username).first() if username else None
    if not ce.can_use(user):
        raise HTTPException(401)
    return Response(status_code=204)


@router.get("/status")
def status(user: User = Depends(allowed_user)):
    st = ce.status()
    st["can_set_owner_only"] = user_audit.is_owner(user)
    st["task"] = bg_tasks.state(TASK)
    return st


@router.post("/install", response_model=DetailResponse)
def install(user: User = Depends(allowed_user)):
    """Starts in the background; the page polls /status for the result."""
    if not bg_tasks.start(TASK, _install):
        raise HTTPException(409, "The editor is already being installed.")
    return DetailResponse(detail="Installing in the background…")


@router.post("/start", response_model=DetailResponse)
async def start(user: User = Depends(allowed_user)):
    return DetailResponse(detail=await asyncio.to_thread(ce.start))


@router.post("/stop", response_model=DetailResponse)
async def stop(user: User = Depends(allowed_user)):
    return DetailResponse(detail=await asyncio.to_thread(ce.stop))


SUBFOLDERS = {"", "code", "allscripts", "dashboard", "data"}


def _folder(db: Session, user: User, kind: str | None, name: str | None, sub: str) -> str:
    """Absolute folder to open, after checking it exists and this user may see it."""
    if not kind:
        return str(settings.PROJECTS_ROOT)
    if sub not in SUBFOLDERS:
        raise HTTPException(400, "Unknown folder")
    if kind == "project":
        row, root = db.query(Project).filter(Project.name == name).first(), settings.PROJECTS_ROOT
    elif kind == "website":
        row, root = db.query(Website).filter(Website.name == name).first(), settings.WEBSITES_ROOT
    else:
        raise HTTPException(400, "kind must be project or website")
    if row is None or (getattr(row, "hidden", False) and not user.is_admin):
        raise HTTPException(404, "Not found")
    path = root / row.name / sub if sub else root / row.name
    return str(path)


@router.post("/session")
async def session(request: Request, response: Response, kind: str | None = None, name: str | None = None,
                  sub: str = "", user: User = Depends(allowed_user), db: Session = Depends(get_db)):
    """Set the editor cookie (and make sure the editor runs); returns the /ide/ link to open."""
    folder = _folder(db, user, kind, name, sub)
    if not ce.installed():
        raise HTTPException(409, "The code editor isn't installed — install it from the Code page first.")
    if not await asyncio.to_thread(ce.running):
        await asyncio.to_thread(ce.start)
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(ce.COOKIE, ce.make_cookie_token(user.username), max_age=ce.COOKIE_HOURS * 3600,
                        path="/", httponly=True, secure=secure, samesite="lax")
    return {"url": f"/ide/?folder={quote(folder)}"}


@router.post("/uninstall", response_model=DetailResponse)
async def uninstall(delete_data: bool = False, user: User = Depends(allowed_user)):
    """Administrators only. Projects and websites are not touched."""
    if not user.is_admin:
        raise HTTPException(403, "Only administrators can uninstall the editor.")
    detail = await asyncio.to_thread(ce.uninstall, delete_data)
    log_activity(f"💻 code editor uninstalled{' (data deleted)' if delete_data else ''}")
    return DetailResponse(detail=detail)


@router.get("/folders")
def folders(user: User = Depends(allowed_user), db: Session = Depends(get_db)):
    """Projects and websites to open (hidden ones only for admins, like everywhere else)."""
    projects = db.query(Project)
    websites = db.query(Website)
    if not user.is_admin:
        projects = projects.filter(Project.hidden.is_(False))
        websites = websites.filter(Website.hidden.is_(False))
    return {
        "projects": [{"name": p.name, "path": str(settings.PROJECTS_ROOT / p.name)}
                     for p in projects.order_by(Project.name)],
        "websites": [{"name": w.name, "path": str(settings.WEBSITES_ROOT / w.name)}
                     for w in websites.order_by(Website.name)],
    }


@router.put("/owner-only", response_model=DetailResponse)
def owner_only(body: OwnerOnlyRequest, user: User = Depends(allowed_user)):
    """Only the owner can flip this — and only the owner sees the switch."""
    if not user_audit.is_owner(user):
        raise HTTPException(404, "Not found")
    ce.set_owner_only(body.enabled)
    return DetailResponse(detail="Only you can use the editor now." if body.enabled
                          else "Users with the Code permission can use the editor.")
