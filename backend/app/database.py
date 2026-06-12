"""
SQLAlchemy engine / session setup for the panel's internal SQLite database.
"""
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

# Make sure the db/ directory exists before SQLite tries to open the file
Path(settings.DB_PATH).parent.mkdir(parents=True, exist_ok=True)

# check_same_thread=False: FastAPI may touch the session from multiple
# threads (sync endpoints run in a threadpool). Sessions themselves are
# still used one-request-at-a-time.
engine = create_engine(
    f"sqlite:///{settings.DB_PATH}",
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


def get_db():
    """FastAPI dependency: yield a session, always close it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
