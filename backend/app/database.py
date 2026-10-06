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


def run_migrations() -> None:
    """
    Lightweight SQLite migrations for columns added after a DB already exists
    (create_all only creates missing tables, never alters existing ones).
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)

    # users: per-tab permissions + admin flag (added with multi-user support).
    # Existing users predate this and must stay full admins so login keeps
    # working exactly as before.
    if "users" in insp.get_table_names():
        ucols = [c["name"] for c in insp.get_columns("users")]
        with engine.begin() as conn:
            if "is_admin" not in ucols:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
                conn.execute(text("UPDATE users SET is_admin = 1"))
            if "permissions" not in ucols:
                conn.execute(text("ALTER TABLE users ADD COLUMN permissions TEXT DEFAULT ''"))

    # projects: per-project OneDrive subfolder mapping (added with the OneDrive
    # integration). Existing projects get NULL (no folder mapped yet).
    if "projects" in insp.get_table_names():
        pcols = [c["name"] for c in insp.get_columns("projects")]
        with engine.begin() as conn:
            if "onedrive_path" not in pcols:
                conn.execute(text("ALTER TABLE projects ADD COLUMN onedrive_path VARCHAR(512)"))
            if "portal_username" not in pcols:
                conn.execute(text("ALTER TABLE projects ADD COLUMN portal_username VARCHAR(64)"))
            if "portal_password_hash" not in pcols:
                conn.execute(text("ALTER TABLE projects ADD COLUMN portal_password_hash VARCHAR(128)"))
            # admin-only visibility (added with the hide-from-non-admins feature)
            if "hidden" not in pcols:
                conn.execute(text("ALTER TABLE projects ADD COLUMN hidden BOOLEAN DEFAULT 0"))
            # Flask/FastAPI dashboards (added when dashboard/ stopped being
            # Streamlit-only). Left NULL on purpose: NULL means "detect from the
            # code", which resolves existing Streamlit dashboards to streamlit
            # anyway, and keeps working if their code is later replaced.
            if "dashboard_framework" not in pcols:
                conn.execute(text("ALTER TABLE projects ADD COLUMN "
                                  "dashboard_framework VARCHAR(16)"))
            if "dashboard_target" not in pcols:
                conn.execute(text("ALTER TABLE projects ADD COLUMN "
                                  "dashboard_target VARCHAR(255)"))

    # managed_apps: API key for API-only apps (added with Ollama).
    if "managed_apps" in insp.get_table_names():
        acols = [c["name"] for c in insp.get_columns("managed_apps")]
        with engine.begin() as conn:
            if "api_key" not in acols:
                conn.execute(text("ALTER TABLE managed_apps ADD COLUMN api_key VARCHAR(128)"))

    # websites: run-it-yourself Python web services (added with the "python" type).
    if "websites" in insp.get_table_names():
        wcols = [c["name"] for c in insp.get_columns("websites")]
        with engine.begin() as conn:
            if "run_command" not in wcols:
                conn.execute(text("ALTER TABLE websites ADD COLUMN run_command VARCHAR(512)"))
            if "port" not in wcols:
                conn.execute(text("ALTER TABLE websites ADD COLUMN port INTEGER"))
            if "status" not in wcols:
                conn.execute(text("ALTER TABLE websites ADD COLUMN status VARCHAR(16) DEFAULT 'STOPPED'"))
            if "hidden" not in wcols:
                conn.execute(text("ALTER TABLE websites ADD COLUMN hidden BOOLEAN DEFAULT 0"))
            # Flask/FastAPI selection (added with first-class Flask deploys).
            # Existing python websites predate it and ran the old uvicorn
            # default, so they are backfilled as fastapi.
            if "framework" not in wcols:
                conn.execute(text("ALTER TABLE websites ADD COLUMN framework VARCHAR(16)"))
                conn.execute(text("UPDATE websites SET framework = 'fastapi' "
                                  "WHERE type = 'python'"))

    # NOTE: the old `apps` / `proxies` tables belonged to the removed Apps and
    # Proxies sections. Their rows are deliberately left untouched in existing
    # databases (dropping them would be destructive and buys nothing) — the
    # panel simply no longer reads or writes them.
    #
    # The Apps section that exists now stores its state in `managed_apps`, a
    # different table on purpose: create_all() never alters a table that is
    # already there, so reusing the name `apps` would silently keep the old,
    # incompatible schema and break every query against it.
