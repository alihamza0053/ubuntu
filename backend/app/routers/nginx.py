"""
Nginx config manager routes: list/view/edit/delete managed config blocks and
reload nginx.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import NginxConfig
from ..schemas import DetailResponse
from ..services import nginx_service

router = APIRouter(
    prefix="/api/nginx",
    tags=["nginx"],
    dependencies=[Depends(get_current_user)],
)


class ConfigUpdate(BaseModel):
    content: str


@router.get("/configs")
def list_configs(db: Session = Depends(get_db)):
    """All panel-managed nginx blocks, with their on-disk content."""
    out = []
    for cfg in db.query(NginxConfig).all():
        path = Path(cfg.config_path)
        out.append({
            "id": cfg.id,
            "entity_type": cfg.entity_type,
            "entity_id": cfg.entity_id,
            "domain": cfg.domain,
            "config_path": cfg.config_path,
            "exists": path.is_file(),
        })
    return out


@router.get("/configs/{config_id}")
def get_config(config_id: int, db: Session = Depends(get_db)):
    cfg = db.get(NginxConfig, config_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Config not found")
    path = Path(cfg.config_path)
    return {
        "id": cfg.id,
        "domain": cfg.domain,
        "config_path": cfg.config_path,
        "content": path.read_text(encoding="utf-8", errors="replace") if path.is_file() else "",
    }


@router.put("/configs/{config_id}", response_model=DetailResponse)
def update_config(config_id: int, body: ConfigUpdate, db: Session = Depends(get_db)):
    """Overwrite a config block's content and reload nginx."""
    cfg = db.get(NginxConfig, config_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Config not found")
    Path(cfg.config_path).write_text(body.content, encoding="utf-8")
    nginx_service.test_and_reload()
    return DetailResponse(detail="Config saved and nginx reloaded")


@router.delete("/configs/{config_id}", response_model=DetailResponse)
def delete_config(config_id: int, db: Session = Depends(get_db)):
    cfg = db.get(NginxConfig, config_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Config not found")
    slug = Path(cfg.config_path).stem
    nginx_service.remove_site(slug)
    db.delete(cfg)
    db.commit()
    return DetailResponse(detail="Config deleted and nginx reloaded")


@router.post("/reload", response_model=DetailResponse)
def reload_nginx():
    return DetailResponse(detail=nginx_service.test_and_reload())
