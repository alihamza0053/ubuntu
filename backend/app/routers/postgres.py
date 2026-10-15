"""
PostgreSQL routes (Databases → PostgreSQL tab). Same `databases` permission
as the MySQL tab.
"""
import asyncio
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import PgDatabase, Project, Website
from ..schemas import DetailResponse
from ..services import db_env, postgres_service as pg
from ..services.activity import log_activity

router = APIRouter(prefix="/api/postgres", tags=["postgres"], dependencies=[Depends(get_current_user)])


class CreateRequest(BaseModel):
    name: str
    conn_limit: int = 20
    link_kind: str | None = None        # project / website
    link_name: str | None = None


class LinkRequest(BaseModel):
    kind: str | None = None             # None / "" = unlink
    name: str | None = None


class LimitRequest(BaseModel):
    conn_limit: int


class QueryRequest(BaseModel):
    database: str
    sql: str


def _row(db: Session, name: str) -> PgDatabase:
    row = db.query(PgDatabase).filter(PgDatabase.name == name).first()
    if row is None:                     # made outside the panel: start tracking it
        row = PgDatabase(name=name)
        db.add(row)
        db.flush()
    return row


def _connection(name: str, password: str) -> dict:
    return {"database": name, "user": name, "password": password, "host": "127.0.0.1", "port": 5432,
            "url": f"postgresql://{name}:{password}@127.0.0.1:5432/{name}"}


def _link(db: Session, row: PgDatabase, kind: str | None, target: str | None) -> dict | None:
    """Point the database at a project/website (new password, env file written) or unlink it."""
    if row.linked_kind and row.linked_name:
        db_env.remove(row.linked_kind, row.linked_name)
    row.linked_kind = row.linked_name = None
    if not kind:
        db.commit()
        return None
    if kind not in ("project", "website"):
        raise HTTPException(400, "kind must be project or website")
    model = Project if kind == "project" else Website
    if not db.query(model).filter(model.name == target).first():
        raise HTTPException(404, f"No {kind} named “{target}”.")
    # one database per project/website: whatever was linked there is unlinked
    for other in db.query(PgDatabase).filter(PgDatabase.linked_kind == kind, PgDatabase.linked_name == target):
        other.linked_kind = other.linked_name = None
    password = pg.set_password(row.name)            # only the linked code knows it
    db_env.write(kind, target, row.name, row.name, password)
    row.linked_kind, row.linked_name = kind, target
    db.commit()
    return _connection(row.name, password)


@router.get("/status")
def status():
    return pg.status()


@router.post("/install", response_model=DetailResponse)
async def install():
    out = await asyncio.to_thread(pg.install)
    log_activity("🐘 PostgreSQL installed")
    return DetailResponse(detail=out or "PostgreSQL installed")


@router.post("/configure", response_model=DetailResponse)
async def configure():
    return DetailResponse(detail=await asyncio.to_thread(pg.reconfigure))


@router.get("")
def list_databases(db: Session = Depends(get_db)):
    rows = {r.name: r for r in db.query(PgDatabase).all()}
    out = []
    for d in pg.list_databases():
        r = rows.get(d["name"])
        out.append({**d, "linked_kind": r.linked_kind if r else None, "linked_name": r.linked_name if r else None})
    return out


@router.get("/link-targets")
def link_targets(db: Session = Depends(get_db)):
    """Projects and websites a database can be linked to."""
    return {"projects": [p.name for p in db.query(Project).order_by(Project.name)],
            "websites": [w.name for w in db.query(Website).order_by(Website.name)]}


@router.post("", status_code=201)
def create(body: CreateRequest, db: Session = Depends(get_db)):
    name = pg.check_name(body.name)
    password = pg.create_database(name, body.conn_limit)
    row = _row(db, name)
    row.conn_limit = body.conn_limit
    db.commit()
    conn = _connection(name, password)
    if body.link_kind:
        conn = _link(db, row, body.link_kind, body.link_name) or conn
    log_activity(f"🐘 PostgreSQL database {name} created")
    return {"detail": f"Database “{name}” created", "connection": conn,
            "linked": f"{row.linked_kind} {row.linked_name}" if row.linked_kind else None}


@router.delete("/{name}", response_model=DetailResponse)
def drop(name: str, db: Session = Depends(get_db)):
    name = pg.check_name(name)
    backup = pg.drop_database(name)
    row = db.query(PgDatabase).filter(PgDatabase.name == name).first()
    if row:
        if row.linked_kind:
            db_env.remove(row.linked_kind, row.linked_name)
        db.delete(row)
        db.commit()
    log_activity(f"🐘 PostgreSQL database {name} deleted (backup {backup.name})")
    return DetailResponse(detail=f"Deleted “{name}”. A backup was saved first: {backup}")


@router.post("/{name}/password")
def reset_password(name: str, db: Session = Depends(get_db)):
    """New password. A linked project/website gets it automatically (restart it to apply)."""
    name = pg.check_name(name)
    row = _row(db, name)
    if row.linked_kind:
        conn = _link(db, row, row.linked_kind, row.linked_name)
        return {"detail": f"New password set and given to {row.linked_kind} {row.linked_name} — "
                          "restart its dashboard/app to use it.", "connection": conn}
    password = pg.set_password(name)
    db.commit()
    return {"detail": "New password set.", "connection": _connection(name, password)}


@router.post("/{name}/link")
def link(name: str, body: LinkRequest, db: Session = Depends(get_db)):
    name = pg.check_name(name)
    row = _row(db, name)
    conn = _link(db, row, (body.kind or "").strip() or None, (body.name or "").strip() or None)
    if conn is None:
        return {"detail": f"“{name}” unlinked.", "connection": None}
    return {"detail": f"Linked to {row.linked_kind} {row.linked_name}. Restart its dashboard/app (scripts pick it "
                      "up on their next run).", "connection": conn}


@router.get("/{name}/connection")
def connection(name: str, db: Session = Depends(get_db)):
    """Connection details of a linked database (unlinked ones: reset the password to see one)."""
    name = pg.check_name(name)
    row = db.query(PgDatabase).filter(PgDatabase.name == name).first()
    env = db_env.read(row.linked_kind, row.linked_name) if row and row.linked_kind else {}
    if not env:
        return {"connection": None}
    return {"connection": _connection(name, env.get("PGPASSWORD", ""))}


@router.put("/{name}/limit", response_model=DetailResponse)
def set_limit(name: str, body: LimitRequest, db: Session = Depends(get_db)):
    pg.set_conn_limit(name, body.conn_limit)
    row = _row(db, pg.check_name(name))
    row.conn_limit = body.conn_limit
    db.commit()
    return DetailResponse(detail=f"Connection limit set to {body.conn_limit}")


@router.get("/{name}/tables")
def tables(name: str):
    return pg.list_tables(name)


@router.get("/{name}/tables/{table}")
def table(name: str, table: str, limit: int = 50):
    return pg.describe_table(name, table, limit)


@router.post("/query")
def query(body: QueryRequest):
    return pg.run_query(body.database, body.sql)


@router.get("/{name}/export")
def export(name: str):
    name = pg.check_name(name)
    dest = Path(tempfile.gettempdir()) / f"pg-{name}-{datetime.now():%Y%m%d-%H%M%S}.sql"
    pg.export_database(name, dest)
    return FileResponse(dest, filename=dest.name.removeprefix("pg-"), media_type="application/sql",
                        background=BackgroundTask(dest.unlink, missing_ok=True))   # don't fill /tmp


@router.post("/{name}/import", response_model=DetailResponse)
async def import_dump(name: str, file: UploadFile):
    name = pg.check_name(name)
    if not (file.filename or "").lower().endswith(".sql"):
        raise HTTPException(400, "Upload a plain .sql file (from pg_dump or this page's Export).")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".sql") as tmp:
        while chunk := await file.read(1024 * 1024):
            tmp.write(chunk)
    try:
        await asyncio.to_thread(pg.import_sql, name, Path(tmp.name))
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    return DetailResponse(detail=f"Imported into “{name}”")
