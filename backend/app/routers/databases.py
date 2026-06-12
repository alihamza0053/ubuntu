"""
MySQL database manager routes.
"""
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Website
from ..schemas import DetailResponse
from ..services import mysql_service

router = APIRouter(
    prefix="/api/databases",
    tags=["databases"],
    dependencies=[Depends(get_current_user)],
)


class DatabaseCreate(BaseModel):
    name: str
    user: str | None = None
    password: str | None = None


class QueryRequest(BaseModel):
    database: str
    sql: str


@router.get("")
def list_databases(db: Session = Depends(get_db)):
    """All user databases, annotated with any website that links to them."""
    names = mysql_service.list_databases()
    linked = {w.db_name: w.name for w in db.query(Website).filter(Website.db_name.isnot(None)).all()}
    return [{"name": n, "linked_website": linked.get(n)} for n in names]


@router.post("", status_code=201, response_model=DetailResponse)
def create_database(body: DatabaseCreate):
    mysql_service.create_database(body.name, body.user, body.password)
    return DetailResponse(detail=f"Database '{body.name}' created")


@router.delete("/{name}", response_model=DetailResponse)
def drop_database(name: str):
    mysql_service.drop_database(name)
    return DetailResponse(detail=f"Database '{name}' dropped")


@router.post("/query")
def run_query(body: QueryRequest):
    return mysql_service.run_query(body.database, body.sql)


@router.get("/{name}/export")
def export_database(name: str):
    """Download a .sql dump of the database."""
    tmp = Path(tempfile.gettempdir()) / f"{name}.sql"
    mysql_service.export_database(name, tmp)
    return FileResponse(tmp, filename=f"{name}.sql", media_type="application/sql")


@router.post("/{name}/import", response_model=DetailResponse)
async def import_database(name: str, file: UploadFile):
    """Import an uploaded .sql file into the database."""
    if not (file.filename or "").lower().endswith(".sql"):
        raise HTTPException(status_code=400, detail="Upload a .sql file")
    content = (await file.read()).decode("utf-8", errors="replace")
    mysql_service.import_sql(name, content)
    return DetailResponse(detail=f"Imported into '{name}'")
