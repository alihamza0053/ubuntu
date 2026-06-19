"""
Reverse-proxy routes: expose any local service (a Docker container, a uvicorn /
Flask / Node app on 127.0.0.1:PORT) on a domain with SSL.

The panel generates an nginx proxy block (the same websocket-capable block used
for Streamlit dashboards) and issues a Let's Encrypt certificate. This is the
"bring your own app" path that Websites (static) and Apps (catalog) don't cover.
"""
import socket
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import NginxConfig, Proxy
from ..schemas import DetailResponse
from ..services import nginx_service

router = APIRouter(
    prefix="/api/proxies",
    tags=["proxies"],
    dependencies=[Depends(get_current_user)],
)


class ProxyCreate(BaseModel):
    name: str
    upstream_port: int

    @field_validator("name")
    @classmethod
    def slug(cls, v: str) -> str:
        v = v.strip().lower().replace(" ", "-")
        if not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError("Name may only contain letters, numbers, '-' and '_'")
        return v

    @field_validator("upstream_port")
    @classmethod
    def port_ok(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError("Port must be between 1 and 65535")
        return v


class DomainRequest(BaseModel):
    domain: str


def _port_is_up(port: int) -> bool:
    """True if something is listening on 127.0.0.1:port (liveness badge)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _to_out(p: Proxy) -> dict:
    return {
        "id": p.id, "name": p.name, "upstream_port": p.upstream_port,
        "domain": p.domain, "created_at": p.created_at,
        "live": _port_is_up(p.upstream_port),
    }


def _get_or_404(proxy_id: int, db: Session) -> Proxy:
    p = db.get(Proxy, proxy_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Proxy not found")
    return p


@router.get("")
def list_proxies(db: Session = Depends(get_db)):
    return [_to_out(p) for p in db.query(Proxy).all()]


@router.post("", status_code=201)
def create_proxy(body: ProxyCreate, db: Session = Depends(get_db)):
    if db.query(Proxy).filter(Proxy.name == body.name).first():
        raise HTTPException(status_code=409, detail="A proxy with this name already exists")
    p = Proxy(name=body.name, upstream_port=body.upstream_port)
    db.add(p)
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.post("/{proxy_id}/assign-domain", response_model=DetailResponse)
def assign_domain(proxy_id: int, body: DomainRequest, db: Session = Depends(get_db)):
    """Generate the nginx reverse-proxy block for this domain and reload."""
    p = _get_or_404(proxy_id, db)
    slug = f"proxy-{p.name}"
    # The "streamlit" block is a websocket-capable reverse proxy to a localhost
    # port — exactly what a generic proxy needs.
    content = nginx_service.build_block("streamlit", domain=body.domain, port=p.upstream_port)
    config_path = nginx_service.write_site(slug, content)
    p.domain = body.domain

    row = (db.query(NginxConfig)
           .filter(NginxConfig.entity_type == "proxy", NginxConfig.entity_id == p.id)
           .first())
    if row:
        row.config_path, row.domain = str(config_path), body.domain
    else:
        db.add(NginxConfig(entity_type="proxy", entity_id=p.id,
                           config_path=str(config_path), domain=body.domain))
    db.commit()
    return DetailResponse(detail=f"Domain {body.domain} → 127.0.0.1:{p.upstream_port} (nginx reloaded)")


@router.post("/{proxy_id}/ssl", response_model=DetailResponse)
def proxy_ssl(proxy_id: int, db: Session = Depends(get_db)):
    p = _get_or_404(proxy_id, db)
    if not p.domain:
        raise HTTPException(status_code=400, detail="Assign a domain first")
    nginx_service.request_ssl(p.domain)
    return DetailResponse(detail=f"SSL issued for {p.domain}")


@router.delete("/{proxy_id}", response_model=DetailResponse)
def delete_proxy(proxy_id: int, db: Session = Depends(get_db)):
    p = _get_or_404(proxy_id, db)
    nginx_service.remove_site(f"proxy-{p.name}")
    db.query(NginxConfig).filter(
        NginxConfig.entity_type == "proxy", NginxConfig.entity_id == p.id).delete()
    db.delete(p)
    db.commit()
    return DetailResponse(detail=f"Proxy '{p.name}' removed (your service keeps running)")
