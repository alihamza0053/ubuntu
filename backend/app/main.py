"""
ServerHub — FastAPI application entry point.

Run in development:
    uvicorn app.main:app --reload --port 8765
In production this runs under Supervisor (see deploy/serverhub.conf) and
serves the built React frontend from backend/static/.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .database import Base, SessionLocal, engine, run_migrations
from .models import User
from .permissions import targets_hidden_entity, user_can
from .security import decode_access_token
from .routers import (apps, auth, dashboard, databases, docker, files, logs,
                      nginx, onedrive, packages, pipeline, portal, projects,
                      proxies, schedules, scripts, server, settings_router,
                      shopify_apps, terminal, trash, websites)
from .services import pipeline_service, scheduler_service

# Create any missing tables on startup (idempotent), then run column migrations
Base.metadata.create_all(bind=engine)
run_migrations()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A restart kills any in-flight scripts/pipelines — clear stale RUNNING rows
    pipeline_service.mark_interrupted()
    # Start APScheduler and load active schedules from the DB
    scheduler_service.start()
    yield
    if scheduler_service.scheduler.running:
        scheduler_service.scheduler.shutdown(wait=False)


app = FastAPI(
    title="ServerHub",
    description="Self-hosted Ubuntu VPS management panel",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS is only needed for the Vite dev server; in production the frontend is
# served from this same origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PermissionMiddleware(BaseHTTPMiddleware):
    """
    Enforce per-tab permissions on HTTP API calls so a non-admin can't reach a
    section they weren't granted by calling the API directly (the UI hides it,
    this makes it real). Auth/health and non-API paths pass through; unknown or
    missing tokens fall through to the route's own 401. WebSockets are checked
    in authenticate_websocket instead.
    """
    async def dispatch(self, request, call_next):
        path = request.url.path
        if (path.startswith("/api/")
                and not path.startswith("/api/auth")
                and path != "/api/health"):
            auth = request.headers.get("authorization", "")
            token = auth[7:] if auth[:7].lower() == "bearer " else None
            username = decode_access_token(token) if token else None
            if username:
                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.username == username).first()
                    if user and not user_can(user, path, request.method):
                        return JSONResponse(
                            {"detail": "You don't have access to this section."},
                            status_code=403)
                    # Admin-hidden projects/websites/apps look like they don't
                    # exist to non-admins, even when addressed by id.
                    if (user and not user.is_admin
                            and targets_hidden_entity(db, path)):
                        return JSONResponse({"detail": "Not found"},
                                            status_code=404)
                finally:
                    db.close()
        return await call_next(request)


app.add_middleware(PermissionMiddleware)

# --- API + WebSocket routers ---
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(scripts.router)
app.include_router(packages.router)           # per-project pip packages
app.include_router(packages.ws_router)        # pip-install live WebSocket
app.include_router(dashboard.router)
app.include_router(schedules.router)
app.include_router(pipeline.router)
app.include_router(pipeline.ws_router)        # pipeline live-stream WebSocket
app.include_router(websites.router)
app.include_router(websites.ws_router)        # python web-service logs WebSocket
app.include_router(proxies.router)
app.include_router(databases.router)
app.include_router(nginx.router)
app.include_router(files.router)
app.include_router(trash.router)               # recycle bin (deleted project/website files)
app.include_router(logs.router)
app.include_router(terminal.router)
app.include_router(server.router)
app.include_router(server.ws_router)          # apt live-stream WebSocket
app.include_router(apps.router)
app.include_router(apps.ws_router)            # app install WebSocket
app.include_router(shopify_apps.router)
app.include_router(onedrive.router)           # OneDrive setup (under the Apps tab)
app.include_router(docker.router)
app.include_router(docker.ws_router)          # container logs WebSocket
app.include_router(settings_router.router)
app.include_router(settings_router.ws_router)  # self-update live-stream WebSocket
app.include_router(portal.router)              # public per-project upload portal


@app.get("/api/health", tags=["meta"])
def health():
    return {"status": "ok"}


# ---------- Frontend (production build) ----------
# `npm run build` outputs to backend/static/. Serve it with an SPA fallback so
# React Router deep links (e.g. /projects/3) work on refresh.
if settings.STATIC_DIR.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=settings.STATIC_DIR / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        candidate = settings.STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(settings.STATIC_DIR / "index.html")
