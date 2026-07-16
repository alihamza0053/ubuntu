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
import re

from fastapi import (APIRouter, Depends, HTTPException, WebSocket,
                     WebSocketDisconnect)
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import SessionLocal, get_db
from ..deps import authenticate_websocket, get_current_user, require_admin
from ..models import App, NginxConfig, User
from ..permissions import hidden_for
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
        "id": app.id, "slug": app.slug, "instance": app.instance,
        "name": app.name, "kind": app.kind, "multi": entry.get("multi", False),
        "port": app.port, "domain": app.domain, "status": app.status,
        "secret": app.secret, "icon": entry.get("icon", "📦"),
        "image": app.image, "hidden": app.hidden,
        "websocket": entry.get("websocket", False),
        "username": entry.get("username"),
        "web_ui": entry.get("web_ui", True),
        "has_credentials": bool(entry.get("credentials")
                                and (entry.get("env_file") or entry.get("env_file_name"))),
        # Label "Token" for token-based apps (Jupyter), else "Password"
        "secret_label": "Token" if entry.get("use_token") else "Password",
        # Can the panel set this app's password/token?
        "can_set_password": bool(entry.get("use_password") or entry.get("use_token")
                                 or entry.get("set_password_cmd") or entry.get("pw_change")),
    }
    if entry.get("secret_label"):
        out["secret_label"] = entry["secret_label"]
    if live_status and app.kind in ("service", "docker", "compose"):
        try:
            out["status"] = app_service.live_status(app)
        except Exception:
            pass
    return out


@router.get("/catalog")
def catalog(db: Session = Depends(get_db)):
    """All catalog apps, each flagged with whether it's already installed."""
    installed = {a.slug for a in db.query(App).all()}
    return {
        "installer_ready": app_service.installer_ready(),
        "docker_ready": app_service.docker_ready(),
        "apps": [
            {"slug": slug, "name": e["name"], "description": e["description"],
             "icon": e["icon"], "kind": e["kind"],
             # multi apps can always be installed again (another instance)
             "installed": slug in installed and not e.get("multi"),
             "multi": e.get("multi", False),
             "category": app_service.category_of(slug),
             "web_ui": e.get("web_ui", True)}
            for slug, e in app_service.CATALOG.items()
            if slug != "custom"   # driven by the "run any image" form, not a card
        ],
    }


@router.get("/generate-password")
def generate_password():
    """Return a freshly generated strong password (for the autogenerate button)."""
    return {"password": app_service.strong_password()}


@router.get("")
def list_apps(db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    query = db.query(App)
    if not user.is_admin:   # admin-hidden apps are invisible to others
        query = query.filter(App.hidden.is_(False))
    apps = query.all()
    # Backfill compose-app credentials read from their .env (for apps installed
    # before this was added).
    for a in apps:
        entry = app_service.CATALOG.get(a.slug, {})
        env_file = app_service.app_env_file(a)
        if not a.secret and entry.get("secret_env_key") and env_file:
            a.secret = app_service.read_env_value(env_file, entry["secret_env_key"])
    db.commit()
    return [_to_out(a, live_status=True) for a in apps]


class HiddenRequest(BaseModel):
    hidden: bool


@router.put("/{app_id}/hidden", response_model=DetailResponse,
            dependencies=[Depends(require_admin)])
def set_hidden(app_id: int, body: HiddenRequest, db: Session = Depends(get_db)):
    """Hide/unhide this app for non-admin users (admin only)."""
    app = _get_app(app_id, db)
    app.hidden = body.hidden
    db.commit()
    return DetailResponse(detail=f"App '{app.name}' is now "
                                 f"{'hidden from' if body.hidden else 'visible to'} non-admins")


@router.post("/{app_id}/action/{action}", response_model=DetailResponse)
def control_app(app_id: int, action: str, db: Session = Depends(get_db)):
    if action not in ("start", "stop", "restart"):
        raise HTTPException(status_code=400, detail="action must be start/stop/restart")
    app = _get_app(app_id, db)
    output = app_service.control_app(app, action)   # dispatches by kind
    db.commit()
    log_activity(f"app {app.slug} {action}")
    return DetailResponse(detail=output or f"{action} {app.slug}")


@router.get("/{app_id}/credentials")
def app_credentials(app_id: int, db: Session = Depends(get_db)):
    """Full credential set for an app, read live from its config (.env)."""
    app = _get_app(app_id, db)
    entry = app_service.CATALOG.get(app.slug, {})
    creds = entry.get("credentials")
    env_file = app_service.app_env_file(app)
    if not creds or not env_file:
        raise HTTPException(status_code=404, detail="This app has no managed credentials")

    # Static fallbacks for fields not stored in the env file
    static = {"Postgres user": "postgres"}
    items = []
    for label, key in creds:
        value = static.get(label, "") if key is None else (app_service.read_env_value(env_file, key) or "")
        items.append({"label": label, "value": value})
    return {"items": items, "source": env_file}


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
    if app.kind == "tool" or not app.port:
        raise HTTPException(status_code=400, detail="Only running apps can have a domain")
    site = f"app-{app.instance}"
    # The streamlit proxy block forwards WebSockets too (needed by code-server)
    content = nginx_service.build_block("streamlit", domain=body.domain, port=app.port)
    config = nginx_service.write_site(site, content)
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
    if app.kind != "tool":
        try:
            app_service.remove_app(app)   # supervisor / docker / compose
        except HTTPException:
            pass
    nginx_service.remove_site(f"app-{app.instance}")
    db.query(NginxConfig).filter(
        NginxConfig.entity_type == "app", NginxConfig.entity_id == app.id).delete()
    db.delete(app)
    db.commit()
    return DetailResponse(detail=f"App '{app.instance}' removed")


@ws_router.websocket("/ws/apps/{app_id}/logs")
async def app_logs_ws(websocket: WebSocket, app_id: int):
    """Live logs for any app kind (file tail for services, docker logs for containers)."""
    user = await authenticate_websocket(websocket, require="apps")
    if user is None:
        return
    await websocket.accept()

    db = SessionLocal()
    try:
        app = db.get(App, app_id)
    finally:
        db.close()
    if app is None or hidden_for(user, app):
        await websocket.send_text("[serverhub] app not found")
        await websocket.close()
        return

    async def send(line: str):
        await websocket.send_text(line)

    try:
        cmd = app_service.logs_stream_cmd(app)
        if cmd is None:   # service → tail the supervisor stdout log
            from ..services.streaming import tail_file
            await tail_file(app_service.log_path(app.instance, "out"), send)
        else:             # docker / compose → stream the container logs
            await stream_command(cmd, send)
    except (WebSocketDisconnect, RuntimeError):
        pass


@ws_router.websocket("/ws/apps/{slug}/install")
async def install_app_ws(websocket: WebSocket, slug: str):
    """Stream the install of a catalog app; register + start it on success."""
    user = await authenticate_websocket(websocket, require="apps")
    if user is None:
        return
    await websocket.accept()

    entry = app_service.CATALOG.get(slug)
    if entry is None:
        await websocket.send_text(f"[serverhub] unknown app: {slug}")
        await websocket.close()
        return

    kind = entry["kind"]
    sudo_blocked = {"hit": False}

    async def send(line: str):
        if "a password is required" in line or "sudo:" in line:
            sudo_blocked["hit"] = True
        await websocket.send_text(line)

    # Custom image: image + container port (+ optional env) come from the form.
    custom: dict = {}
    if slug == "custom":
        img = (websocket.query_params.get("image", "") or "").strip()
        cport = (websocket.query_params.get("container_port", "") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][\w./:@-]*", img) or not cport.isdigit():
            await send("[serverhub] Provide a valid image name and a numeric container port.")
            await websocket.close()
            return
        env_map = {}
        for line in (websocket.query_params.get("env", "") or "").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                if k.strip():
                    env_map[k.strip()] = v.strip()
        custom = {"image": img, "container_port": int(cport), "env": env_map}

    # Docker / compose apps need the Docker engine first
    if kind in ("docker", "compose") and not app_service.docker_ready():
        await send("[serverhub] Docker isn't installed/running yet.")
        await send("[serverhub] Install the 'Docker Engine' app first, then retry.")
        await send("[serverhub] install failed (exit 1)")
        await websocket.close()
        return

    # --- Work out the instance id + port BEFORE installing ---
    multi = entry.get("multi")
    db = SessionLocal()
    try:
        if multi:
            raw = re.sub(r"[^a-z0-9-]+", "-",
                         (websocket.query_params.get("name", "") or "").lower()).strip("-")
            base = raw if raw.startswith(slug) else (f"{slug}-{raw}" if raw else slug)
            instance, n = base, 2
            while db.query(App).filter(App.instance == instance).first():
                instance = f"{base}-{n}"; n += 1
        else:
            instance = slug
            if db.query(App).filter(App.instance == instance).first():
                await send(f"[serverhub] {entry['name']} is already installed")
                await websocket.close()
                return
        # Port: single compose uses its fixed port; everyone else gets allocated
        port = None
        if kind in ("service", "docker", "compose"):
            port = (entry["container_port"] if (kind == "compose" and not multi)
                    else app_service.allocate_port(db))
    finally:
        db.close()

    await send(f"[serverhub] installing {entry['name']} (instance: {instance}) …")
    try:
        if kind in ("docker",):  # single-container: pull the image
            pull_image = custom.get("image") or entry["image"]
            code = await stream_command(["sudo", "-n", "docker", "pull", pull_image], send)
        elif kind == "compose" and multi:
            # Multi compose: the installer writes a per-instance stack on this port
            code = await stream_command(app_service.installer_cmd(slug, instance, port), send)
        else:  # tool / service / single-compose → the vetted root installer
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
        await send(f"[serverhub] install failed (exit {code})")
        await websocket.close()
        return

    # Register the app instance and bring it up
    db = SessionLocal()
    try:
        display = entry["name"] if instance == slug else f"{entry['name']} — {instance}"
        app = App(slug=slug, instance=instance, name=display, kind=kind,
                  port=port, status="STOPPED")
        if entry.get("use_password") or entry.get("use_token") or entry.get("secret_env"):
            app.secret = app_service.new_password()
        if custom:   # custom-image app: persist its image/port/env
            app.image = custom["image"]
            app.container_port = custom["container_port"]
            app.name = f"{custom['image']} — {instance}"
            if custom["env"]:
                import json as _json
                app.env_json = _json.dumps(custom["env"])
        db.add(app)
        db.commit()
        db.refresh(app)

        # Compose creds (e.g. EspoCRM/Supabase) live in the stack's env file
        if entry.get("secret_env_key"):
            ef = app_service.app_env_file(app)
            if ef:
                app.secret = app_service.read_env_value(ef, entry["secret_env_key"])

        try:
            if kind == "service":
                app_service.write_program(app)
                app_service.control(app.instance, "start")
            elif kind == "docker":
                app_service.docker_run(app)
            elif kind == "compose":
                app_service.compose_control(app, "start")
            if kind != "tool":
                app.status = app_service.live_status(app)
                db.commit()
                await send(f"[serverhub] started on port {app.port}")
                if app.secret:
                    await send(f"[serverhub] {('username: ' + entry['username'] + '  ') if entry.get('username') else ''}"
                               f"{entry.get('secret_label', 'password').lower()}: {app.secret}")
        except HTTPException as exc:
            db.commit()
            await send(f"[serverhub] installed but failed to start: {exc.detail}")

        log_activity(f"app {instance} installed")
        await send("[serverhub] ✓ done")
    finally:
        db.close()
    await websocket.close()
