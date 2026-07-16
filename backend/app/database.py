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

    if "apps" not in insp.get_table_names():
        return

    cols = [c["name"] for c in insp.get_columns("apps")]
    indexes = insp.get_indexes("apps")
    with engine.begin() as conn:
        # apps.instance: per-instance id (added when multi-instance shipped)
        if "instance" not in cols:
            conn.execute(text("ALTER TABLE apps ADD COLUMN instance VARCHAR(96)"))
            conn.execute(text("UPDATE apps SET instance = slug WHERE instance IS NULL"))
        # custom-image apps: image + container port + extra env (added with the
        # "run any Docker image" feature).
        if "image" not in cols:
            conn.execute(text("ALTER TABLE apps ADD COLUMN image VARCHAR(255)"))
        if "container_port" not in cols:
            conn.execute(text("ALTER TABLE apps ADD COLUMN container_port INTEGER"))
        if "env_json" not in cols:
            conn.execute(text("ALTER TABLE apps ADD COLUMN env_json TEXT"))
        if "hidden" not in cols:
            conn.execute(text("ALTER TABLE apps ADD COLUMN hidden BOOLEAN DEFAULT 0"))
        # slug must no longer be UNIQUE (multiple instances share a slug)
        for idx in indexes:
            if idx.get("column_names") == ["slug"] and idx.get("unique"):
                conn.execute(text(f'DROP INDEX IF EXISTS "{idx["name"]}"'))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_apps_instance ON apps(instance)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_apps_slug_nonunique ON apps(slug)"))
