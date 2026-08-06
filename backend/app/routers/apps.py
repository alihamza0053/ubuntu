"""
Apps routes: install/remove Chromium, Brave and n8n, run them under supervisor,
point a domain at them and watch their logs.

The app list is a fixed catalogue (services/appstore_service.CATALOG), so every
route addresses an app by its catalogue key rather than a database id — there
is nothing to create, only to install.
"""
from fastapi import (APIRouter, Depends, HTTPException, Query, WebSocket,
                     WebSocketDisconnect)
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..deps import authenticate_websocket, get_current_user, require_admin
from ..models import ManagedApp, NginxConfig, User
from ..schemas import DetailResponse
from ..services import appstore_service, nginx_service
from ..services.streaming import tail_file

router = APIRouter(
    prefix="/api/apps",
    tags=["apps"],
    dependencies=[Depends(get_current_user)],
)
ws_router = APIRouter(tags=["apps"])   # logs WS authenticates via ?token=


class DomainRequest(BaseModel):
    domain: str


class SettingsRequest(BaseModel):
    """Editable per-app settings (browser apps only, for now)."""
    start_url: str | None = None
    vnc_password: str | None = None

    @field_validator("start_url")
    @classmethod
    def url_ok(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not v.startswith(("http://", "https://", "about:")):
            raise ValueError("Start URL must begin with http:// or https://")
        return v

    @field_validator("vnc_password")
    @classmethod
    def password_ok(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        # x11vnc truncates at 8 characters, so anything longer is a false sense
        # of security — say so instead of silently ignoring the rest.
        if not 6 <= len(v) <= 8:
            raise ValueError("VNC password must be 6–8 characters (x11vnc "
                             "ignores anything past the 8th)")
        return v


class HiddenRequest(BaseModel):
    hidden: bool


def _to_out(key: str, app: ManagedApp | None) -> dict:
    """One catalogue entry plus whatever state this server has for it."""
    entry = appstore_service.spec(key)
    state = appstore_service.install_state(key)
    out = {
        "key": key,
        "label": entry["label"],
        "icon": entry["icon"],
        "kind": entry["kind"],
        "summary": entry["summary"],
        "notes": entry["notes"],
        "install_hint": entry["install_hint"],
        "install_state": state,
        "url_path": appstore_service.url_path(key),
        # Not registered yet — everything below only exists once installed.
        "port": None, "display": None, "domain": None, "status": "STOPPED",
        "vnc_password": None, "start_url": None, "hidden": False, "ssl": False,
    }
    if app is not None:
        out.update({
            "port": app.port,
            "display": app.display,
            "domain": app.domain,
            "vnc_password": app.vnc_password,
            "start_url": app.start_url,
            "hidden": app.hidden,
            "status": appstore_service.status(key) if state == "INSTALLED" else "STOPPED",
            # Whether the domain already has a certificate — the UI has to know
            # to build an https link, or embedding the app in the (https) panel
            # trips the browser's mixed-content block.
            "ssl": bool(app.domain) and nginx_service.has_cert(app.domain),
        })
    return out


def _get_app_or_404(key: str, db: Session) -> ManagedApp:
    appstore_service.spec(key)          # 404s on an unknown key
    app = db.query(ManagedApp).filter(ManagedApp.key == key).first()
    if app is None:
        raise HTTPException(status_code=404,
                            detail="This app isn't installed on this server yet")
    return app


@router.get("")
def list_apps(db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """The whole catalogue, each entry annotated with its state here."""
    rows = {a.key: a for a in db.query(ManagedApp).all()}
    out = []
    for key in appstore_service.CATALOG:
        app = rows.get(key)
        if app is not None and app.hidden and not user.is_admin:
            continue                    # admin-hidden apps don't exist to others
        out.append(_to_out(key, app))
    return out


@router.get("/{key}")
def get_app(key: str, db: Session = Depends(get_db)):
    app = db.query(ManagedApp).filter(ManagedApp.key == key).first()
    return _to_out(key, app)


@router.post("/{key}/install", response_model=DetailResponse,
             dependencies=[Depends(require_admin)])
def install_app(key: str, db: Session = Depends(get_db)):
    """
    Install the app in the background (admin only — it installs packages).

    Registering the row up front is deliberate: the port, display number and
    noVNC password are what the UI shows while the install runs.
    """
    entry = appstore_service.spec(key)
    if appstore_service.is_installed(key):
        raise HTTPException(status_code=409,
                            detail=f"{entry['label']} is already installed")
    appstore_service.get_or_create(db, key)
    if not appstore_service.start_install(key):
        return DetailResponse(detail="Already installing — watch the install log")
    return DetailResponse(
        detail=f"Installing {entry['label']}… watch the install log. "
               f"{entry['install_hint']}")


@router.delete("/{key}", response_model=DetailResponse,
               dependencies=[Depends(require_admin)])
def uninstall_app(key: str, delete_data: bool = Query(False),
                  db: Session = Depends(get_db)):
    """Stop the app, remove its packages, and optionally its data directory."""
    entry = appstore_service.spec(key)
    app = db.query(ManagedApp).filter(ManagedApp.key == key).first()

    appstore_service.remove_program(key)
    nginx_service.remove_site(appstore_service.nginx_slug(key))
    if app is not None:
        db.query(NginxConfig).filter(
            NginxConfig.entity_type == "app", NginxConfig.entity_id == app.id
        ).delete()
        db.delete(app)
        db.commit()

    appstore_service.start_install(key, action="remove", purge_after=delete_data)
    return DetailResponse(
        detail=f"Removing {entry['label']}"
               + (" and its data" if delete_data else " (its data was kept)"))


@router.put("/{key}/hidden", response_model=DetailResponse,
            dependencies=[Depends(require_admin)])
def set_hidden(key: str, body: HiddenRequest, db: Session = Depends(get_db)):
    """Hide/unhide this app for non-admin users (admin only)."""
    app = _get_app_or_404(key, db)
    app.hidden = body.hidden
    db.commit()
    return DetailResponse(
        detail=f"{appstore_service.spec(key)['label']} is now "
               f"{'hidden from' if body.hidden else 'visible to'} non-admins")


@router.put("/{key}/settings", response_model=DetailResponse)
def update_settings(key: str, body: SettingsRequest, db: Session = Depends(get_db)):
    """Change the start page / noVNC password of a browser app."""
    app = _get_app_or_404(key, db)
    if appstore_service.spec(key)["kind"] not in appstore_service.DESKTOP_KINDS:
        raise HTTPException(status_code=400,
                            detail="This app has no browser settings")
    if body.start_url is not None:
        app.start_url = body.start_url
    if body.vnc_password is not None:
        app.vnc_password = body.vnc_password
    db.commit()
    return DetailResponse(detail="Saved — restart the app to apply")


@router.post("/{key}/action/{action}", response_model=DetailResponse)
def control_app(key: str, action: str, db: Session = Depends(get_db)):
    app = _get_app_or_404(key, db)
    out = appstore_service.control(app, action)
    app.status = appstore_service.status(key)
    db.commit()
    return DetailResponse(detail=out or f"{action} {key}")


@router.post("/{key}/assign-domain", response_model=DetailResponse)
def assign_domain(key: str, body: DomainRequest, db: Session = Depends(get_db)):
    """Reverse-proxy `domain` to the app's port, then reload nginx."""
    app = _get_app_or_404(key, db)
    content = appstore_service.nginx_block(app, body.domain)
    config_path = nginx_service.write_site(appstore_service.nginx_slug(key), content)
    app.domain = body.domain

    row = (db.query(NginxConfig)
           .filter(NginxConfig.entity_type == "app", NginxConfig.entity_id == app.id)
           .first())
    if row:
        row.config_path, row.domain = str(config_path), body.domain
    else:
        db.add(NginxConfig(entity_type="app", entity_id=app.id,
                           config_path=str(config_path), domain=body.domain))
    db.commit()

    # n8n bakes its public URL into the webhook addresses it hands out, so the
    # domain has to reach its environment — that means a restart.
    extra = ""
    if key == "n8n" and appstore_service.status(key) == "RUNNING":
        appstore_service.control(app, "restart")
        extra = " n8n was restarted so its webhook URLs use the new domain."
    return DetailResponse(
        detail=f"Domain {body.domain} assigned and nginx reloaded.{extra}")


@router.post("/{key}/ssl", response_model=DetailResponse)
def app_ssl(key: str, db: Session = Depends(get_db)):
    app = _get_app_or_404(key, db)
    if not app.domain:
        raise HTTPException(status_code=400, detail="Assign a domain first")
    nginx_service.request_ssl(app.domain)
    extra = ""
    if key == "n8n":
        # Now https — N8N_PROTOCOL, WEBHOOK_URL and the secure-cookie setting
        # all change, and only a restart picks them up.
        appstore_service.control(app, "restart")
        extra = " n8n was restarted to switch its public URL to https."
    return DetailResponse(detail=f"SSL issued for {app.domain}.{extra}")


@ws_router.websocket("/ws/apps/{key}/logs")
async def app_logs_ws(websocket: WebSocket, key: str, source: str = "app"):
    """Live logs: source=app (the running app) or source=install."""
    user = await authenticate_websocket(websocket, require="apps")
    if user is None:
        return
    await websocket.accept()

    if key not in appstore_service.CATALOG:
        await websocket.send_text("[serverhub] unknown app")
        await websocket.close()
        return

    db = SessionLocal()
    try:
        app = db.query(ManagedApp).filter(ManagedApp.key == key).first()
    finally:
        db.close()
    if app is not None and app.hidden and not user.is_admin:
        await websocket.send_text("[serverhub] app not found")
        await websocket.close()
        return

    path = (appstore_service.install_log_path(key) if source == "install"
            else appstore_service.log_path(key))

    async def send(line: str):
        await websocket.send_text(line)

    try:
        await tail_file(path, send, backlog=200)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        pass
