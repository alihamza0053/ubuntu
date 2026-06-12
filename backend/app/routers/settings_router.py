"""
Settings routes: change admin password, panel key/value settings, and a
download of the panel SQLite database for backup.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings as app_settings
from ..database import get_db
from ..deps import get_current_user
from ..models import Setting
from ..schemas import DetailResponse

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(get_current_user)],
)


class SettingsUpdate(BaseModel):
    # Arbitrary key/value pairs (panel port, subdomain, etc.)
    values: dict[str, str]


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    """All stored panel settings as a flat dict."""
    rows = db.query(Setting).all()
    return {r.key: r.value for r in rows}


@router.put("", response_model=DetailResponse)
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    for key, value in body.values.items():
        row = db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = value
        else:
            db.add(Setting(key=key, value=value))
    db.commit()
    return DetailResponse(detail="Settings saved")


@router.post("/backup-db")
def backup_db():
    """Download the panel's SQLite database file."""
    db_path = app_settings.DB_PATH
    if not db_path.is_file():
        raise HTTPException(status_code=404, detail="Database file not found")
    return FileResponse(db_path, filename="serverhub-backup.db",
                        media_type="application/octet-stream")
