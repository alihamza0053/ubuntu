"""
OneDrive setup routes: status, authorization, and monitor control.

Setup lives under the Apps tab (see permissions._PREFIX_TAB). The per-project
file browsing/download endpoints live in routers/projects.py.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..deps import get_current_user
from ..schemas import DetailResponse
from ..services import onedrive_service
from ..services.activity import log_activity

router = APIRouter(
    prefix="/api/onedrive",
    tags=["onedrive"],
    dependencies=[Depends(get_current_user)],
)


class AuthCompleteRequest(BaseModel):
    response_url: str


@router.get("/status")
def status():
    """Installed / authorized / monitor state for the setup panel."""
    return onedrive_service.status()


@router.post("/auth/start")
def auth_start():
    """Begin authorization; returns the Microsoft login URL to open."""
    url = onedrive_service.auth_start()
    return {"auth_url": url}


@router.post("/auth/complete", response_model=DetailResponse)
def auth_complete(body: AuthCompleteRequest):
    """Finish authorization with the pasted redirect URL, then start syncing."""
    onedrive_service.auth_complete(body.response_url)
    onedrive_service.write_monitor_program()
    onedrive_service.control("start")
    log_activity("onedrive authorized + monitor started")
    return DetailResponse(detail="OneDrive authorized — syncing has started")


@router.post("/monitor/{action}", response_model=DetailResponse)
def monitor(action: str):
    """start | stop | restart the sync monitor (restart = sync now)."""
    out = onedrive_service.control(action)
    log_activity(f"onedrive monitor {action}")
    return DetailResponse(detail=out or f"monitor {action}")


@router.post("/resync", response_model=DetailResponse)
def resync():
    """Full resync (needed to pull Work/School 'Shared with me' items)."""
    out = onedrive_service.resync()
    log_activity("onedrive resync started")
    return DetailResponse(detail=out)
