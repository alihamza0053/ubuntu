"""
Recycle bin API — list, restore, and purge deleted project/website files.

Items auto-expire after settings.TRASH_RETENTION_HOURS (also enforced by an
hourly scheduler job). All endpoints require an authenticated user.
"""
from fastapi import APIRouter, Depends

from ..config import settings
from ..deps import get_current_user
from ..schemas import DetailResponse
from ..services import trash_service

router = APIRouter(
    prefix="/api/trash",
    tags=["trash"],
    dependencies=[Depends(get_current_user)],
)


@router.get("")
def list_trash():
    """Deleted items still within the retention window (newest first)."""
    return {
        "retention_hours": settings.TRASH_RETENTION_HOURS,
        "items": trash_service.list_items(),
    }


@router.post("/{trash_id}/restore", response_model=DetailResponse)
def restore(trash_id: str):
    result = trash_service.restore(trash_id)
    return DetailResponse(detail=f"Restored to {result['restored_to']}")


@router.delete("/{trash_id}", response_model=DetailResponse)
def purge_one(trash_id: str):
    trash_service.purge(trash_id)
    return DetailResponse(detail="Permanently deleted")


@router.post("/empty", response_model=DetailResponse)
def empty():
    count = trash_service.empty()
    return DetailResponse(detail=f"Emptied the recycle bin ({count} item(s))")
