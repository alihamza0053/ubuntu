"""
Apps section: one-click install of self-hosted apps (VS Code/code-server,
File Browser, etc.), run them on a port under Supervisor, assign a domain
and SSL, and manage them.

  GET  /api/apps                  installed apps (+ live status)
  GET  /api/apps/catalog          installable apps
  WS   /ws/apps/{slug}/install    install with live output; registers on success
  POST /api/apps/{id}/start|stop|restart
  POST /api/apps/{id}/assign-domain
  POST /api/apps/{id}/ssl
  DELETE /api/apps/{id}
"""
from pathlib import Path

from fastapi import (APIRouter, Depends, HTTPException, WebSocket,
                     WebSocketDisconnect)
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..deps import authenticate_websocket, get_current_user
from ..models import App, NginxConfig
from ..schemas import DetailResponse
from ..services import app_service, nginx_service
from ..services.activity import log_activity
from ..services.streaming import stream_command

router = APIRouter(prefix="/api/apps", tags=["apps"], dependencies=[Depends(get_current_user)])
ws_router = APIRouter(tags=["apps"])   # install WS authenticates via ?token=


class DomainRequest(BaseModel):
    domain: str


class PasswordRequest(BaseModel):
    password: str


def _get_app(app_id: int, db: Session) -> App:
    app = db.get(App, app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="App not found")
    return app


def _to_out(app: App, live_status: bool = False) -> dict:
    entry = app_service.CATALOG.get(app.slug, {})
    out = {
        "id": app.id, "slug": app.slug, "name": app.name, "kind": app.kind,
        "port": app.port, "domain": app.domain, "status": app.status,
        "secret": app.secret, "icon": entry.get("icon", "📦"),
        "websocket": entry.get("websocket", False),
        "username": entry.get("username"),
        # Label "Token" for token-based apps (Jupyter), else "Password"
        "secret_label": "Token" if entry.get("use_token") else "Password",
        # Can the panel set this app's password/token?
        "can_set_password": bool(entry.get("use_password") or entry.get("use_token")
                                 or entry.get("set_password_cmd")),
    }
    if live_status and app.kind == "service":
        out["status"] = app_service.status(app.slug)
    return out


@router.get("/catalog")
def catalog(db: Session = Depends(get_db)):
    """All catalog apps, each flagged with whether it's already installed."""
    installed = {a.slug for a in db.query(App).all()}
    return {
        "installer_ready": app_service.installer_ready(),
        "apps": [
            {"slug": slug, "name": e["name"], "description": e["description"],
             "icon": e["icon"], "kind": e["kind"], "installed": slug in installed}
            for slug, e in app_service.CATALOG.items()
        ],
    }


@router.get("")
def list_apps(db: Session = Depends(get_db)):
    return [_to_out(a, live_status=True) for a in db.query(App).all()]


@router.post("/{app_id}/action/{action}", response_model=DetailResponse)
def control_app(app_id: int, action: str, db: Session = Depends(get_db)):
    if action not in ("start", "stop", "restart"):
        raise HTTPException(status_code=400, detail="action must be start/stop/restart")
    app = _get_app(app_id, db)
    if app.kind != "service":
        raise HTTPException(status_code=400, detail="This app is a tool (nothing to run)")
    output = app_service.control(app.slug, action)
    app.status = app_service.status(app.slug)
    db.commit()
    log_activity(f"app {app.slug} {action}")
    return DetailResponse(detail=output or f"{action} {app.slug}")


@router.post("/{app_id}/set-password", response_model=DetailResponse)
def set_password(app_id: int, body: PasswordRequest, db: Session = Depends(get_db)):
    """Change a service app's login password."""
    app = _get_app(app_id, db)
    if len(body.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")
    app_service.set_password(app, body.password)
    db.commit()
    log_activity(f"app {app.slug} password changed")
    return DetailResponse(detail="Password updated")


@router.post("/{app_id}/assign-domain", response_model=DetailResponse)
def assign_domain(app_id: int, body: DomainRequest, db: Session = Depends(get_db)):
    app = _get_app(app_id, db)
    if app.kind != "service" or not app.port:
        raise HTTPException(status_code=400, detail="Only running apps can have a domain")
    slug = f"app-{app.slug}"
    # The streamlit proxy block forwards WebSockets too (needed by code-server)
    content = nginx_service.build_block("streamlit", domain=body.domain, port=app.port)
    config = nginx_service.write_site(slug, content)
    app.domain = body.domain
    row = (db.query(NginxConfig)
           .filter(NginxConfig.entity_type == "app", NginxConfig.entity_id == app.id).first())
    if row:
        row.config_path, row.domain = str(config), body.domain
    else:
        db.add(NginxConfig(entity_type="app", entity_id=app.id,
                           config_path=str(config), domain=body.domain))
    db.commit()
    return DetailResponse(detail=f"Domain {body.domain} assigned and nginx reloaded")


@router.post("/{app_id}/ssl", response_model=DetailResponse)
def app_ssl(app_id: int, db: Session = Depends(get_db)):
    app = _get_app(app_id, db)
    if not app.domain:
        raise HTTPException(status_code=400, detail="Assign a domain first")
    nginx_service.request_ssl(app.domain)
    return DetailResponse(detail=f"SSL issued for {app.domain}")


@router.delete("/{app_id}", response_model=DetailResponse)
def uninstall_app(app_id: int, db: Session = Depends(get_db)):
    """Remove the app from the panel (stops it; leaves the installed binary)."""
    app = _get_app(app_id, db)
    if app.kind == "service":
        try:
            app_service.remove_program(app.slug)
        except HTTPException:
            pass
    nginx_service.remove_site(f"app-{app.slug}")
    db.query(NginxConfig).filter(
        NginxConfig.entity_type == "app", NginxConfig.entity_id == app.id).delete()
    db.delete(app)
    db.commit()
    return DetailResponse(detail=f"App '{app.slug}' removed")


@ws_router.websocket("/ws/apps/{slug}/install")
async def install_app_ws(websocket: WebSocket, slug: str):
    """Stream the install of a catalog app; register + start it on success."""
    user = await authenticate_websocket(websocket)
    if user is None:
        return
    await websocket.accept()

    entry = app_service.CATALOG.get(slug)
    if entry is None:
        await websocket.send_text(f"[serverhub] unknown app: {slug}")
        await websocket.close()
        return

    sudo_blocked = {"hit": False}

    async def send(line: str):
        if "a password is required" in line or "sudo:" in line:
            sudo_blocked["hit"] = True
        await websocket.send_text(line)

    await send(f"[serverhub] installing {entry['name']} …")
    try:
        code = await stream_command(app_service.installer_cmd(slug), send)
    except WebSocketDisconnect:
        return

    if code != 0:
        if sudo_blocked["hit"]:
            await send("")
            await send("[serverhub] ── why this failed ──")
            await send("[serverhub] The panel installs apps through ONE whitelisted root")
            await send("[serverhub] script (it can't run arbitrary commands as root, by design).")
            await send("[serverhub] That rule isn't deployed on this server yet.")
            await send("[serverhub] Fix it once, then retry Install:")
            await send("[serverhub]   cd /opt/serverhub-src && sudo bash deploy/update.sh")
            await send("[serverhub] (installs /srv/serverhub/bin/serverhub-app-install + the sudoers rule)")
        await send(f"[serverhub] install failed (exit {code})")
        await websocket.close()
        return

    # Register the app (idempotent) and, for services, write supervisor + start
    db = SessionLocal()
    try:
        app = db.query(App).filter(App.slug == slug).first()
        if app is None:
            app = App(slug=slug, name=entry["name"], kind=entry["kind"], status="STOPPED")
            if entry["kind"] == "service":
                app.port = app_service.allocate_port(db)
                if entry.get("use_password") or entry.get("use_token"):
                    app.secret = app_service.new_password()
            db.add(app)
            db.commit()
            db.refresh(app)
        if entry["kind"] == "service":
            app_service.write_program(app)
            try:
                app_service.control(slug, "start")
                app.status = "RUNNING"
                db.commit()
                await send(f"[serverhub] started on port {app.port}")
                if app.secret:
                    await send(f"[serverhub] password: {app.secret}")
            except HTTPException as exc:
                await send(f"[serverhub] installed but failed to start: {exc.detail}")
        log_activity(f"app {slug} installed")
        await send("[serverhub] ✓ done")
    finally:
        db.close()
    await websocket.close()
