"""
Docker manager routes: list & manage containers / images / volumes.

  GET    /api/docker                      ready + containers + images + volumes
  POST   /api/docker/containers/{id}/{action}   start|stop|restart|remove
  DELETE /api/docker/images/{id}
  DELETE /api/docker/volumes/{name}
  POST   /api/docker/prune
  WS     /ws/docker/containers/{id}/logs  live container logs
"""
from fastapi import (APIRouter, Depends, WebSocket, WebSocketDisconnect)
from fastapi import HTTPException

from ..deps import authenticate_websocket, get_current_user
from ..schemas import DetailResponse
from ..services import docker_service
from ..services.activity import log_activity
from ..services.streaming import stream_command

router = APIRouter(prefix="/api/docker", tags=["docker"],
                   dependencies=[Depends(get_current_user)])
ws_router = APIRouter(tags=["docker"])   # logs WS authenticates via ?token=


@router.get("")
def docker_overview():
    """Everything the Docker page shows. Returns ready=false if not installed."""
    if not docker_service.ready():
        return {"ready": False, "containers": [], "images": [], "volumes": []}
    return docker_service.stats()


@router.post("/containers/{cid}/{action}", response_model=DetailResponse)
def container_action(cid: str, action: str):
    detail = docker_service.container_action(cid, action)
    log_activity(f"docker container {action}: {cid[:12]}")
    return DetailResponse(detail=detail)


@router.delete("/images/{image_id}", response_model=DetailResponse)
def remove_image(image_id: str):
    return DetailResponse(detail=docker_service.remove_image(image_id))


@router.delete("/volumes/{name}", response_model=DetailResponse)
def remove_volume(name: str):
    return DetailResponse(detail=docker_service.remove_volume(name))


@router.post("/prune", response_model=DetailResponse)
def prune():
    return DetailResponse(detail=docker_service.prune() or "Nothing to prune")


@ws_router.websocket("/ws/docker/containers/{cid}/logs")
async def container_logs_ws(websocket: WebSocket, cid: str):
    user = await authenticate_websocket(websocket, require="docker")
    if user is None:
        return
    await websocket.accept()

    async def send(line: str):
        await websocket.send_text(line)

    try:
        await stream_command(docker_service.logs_cmd(cid), send)
    except (WebSocketDisconnect, RuntimeError):
        pass
