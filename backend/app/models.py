"""
ORM models for the panel's internal SQLite database.

All tables from the ServerHub spec are defined up-front so the schema is
stable across phases; Phase 1 actively uses: users, projects, scripts.
"""
from datetime import datetime

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    """A panel user. Admins have full access; others are limited to the tabs
    listed in `permissions` (comma-separated keys, see app/permissions.py)."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(128))
    # Admins bypass all permission checks and can manage users.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Comma-separated allowed tab keys for non-admins (e.g. "projects,logs").
    permissions: Mapped[str] = mapped_column(Text, default="")


class Project(Base):
    """A Python workspace under /srv/projects/{name}/."""
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    folder_path: Mapped[str] = mapped_column(String(255))
    dashboard_port: Mapped[int] = mapped_column(Integer, unique=True)
    # Cached status string: RUNNING / STOPPED / ERROR / UNKNOWN
    dashboard_status: Mapped[str] = mapped_column(String(16), default="STOPPED")
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # OneDrive subfolder (relative to ONEDRIVE_ROOT) this project reads from.
    onedrive_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Public upload portal credentials (served at <domain>/onedrivefiles/).
    # Both set = portal enabled. Password is bcrypt-hashed.
    portal_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    portal_password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Admin-hidden: invisible and unreachable for non-admin users.
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    scripts: Mapped[list["Script"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Script(Base):
    """A runnable .py file inside a project's code/ or allscripts/ folder."""
    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    # Which sub-folder the script lives in: "code" or "allscripts"
    folder: Mapped[str] = mapped_column(String(32), default="code")
    filename: Mapped[str] = mapped_column(String(255))
    schedule_cron: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_run: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # SUCCESS / FAILED / RUNNING / None (never run)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Path to the log file of the most recent run
    last_log: Mapped[str | None] = mapped_column(String(255), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="scripts")


class Website(Base):
    """A deployed website under /srv/websites/{name}/ (Phase 3)."""
    __tablename__ = "websites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    folder_path: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(16))  # react / php / html / python
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    db_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # --- "python" type only: a run-it-yourself web service ---
    # Start command (with a {port} placeholder), the localhost port it runs on,
    # and the cached supervisor status.
    run_command: Mapped[str | None] = mapped_column(String(512), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="STOPPED")
    # Admin-hidden: invisible and unreachable for non-admin users.
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Schedule(Base):
    """A cron schedule attached to a script (Phase 2)."""
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    script_id: Mapped[int] = mapped_column(ForeignKey("scripts.id"))
    cron_expression: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class NginxConfig(Base):
    """A panel-managed nginx config block (Phase 3)."""
    __tablename__ = "nginx_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(16))  # project / website / panel
    entity_id: Mapped[int] = mapped_column(Integer)
    config_path: Mapped[str] = mapped_column(String(255))
    domain: Mapped[str] = mapped_column(String(255))


class TerminalHistory(Base):
    """History of commands run through the panel terminal (Phase 2)."""
    __tablename__ = "terminal_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    command: Mapped[str] = mapped_column(Text)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Setting(Base):
    """Key/value panel settings (Phase 5): panel port, subdomain, etc."""
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text)


class PipelineSchedule(Base):
    """
    Project-level pipeline schedule: run ALL of a project's code/ scripts in
    sequence on a cron, then restart its dashboard. One row per project.
    """
    __tablename__ = "pipeline_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), unique=True)
    cron_expression: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class App(Base):
    """
    A self-hosted app installed from the catalog (e.g. code-server / VS Code).
    `kind`: 'service' (runs on a port under Supervisor) or 'tool' (install only).
    """
    __tablename__ = "apps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Catalog key (NOT unique — an app can have multiple instances)
    slug: Mapped[str] = mapped_column(String(64), index=True)
    # Unique per-instance id used for container/program/nginx naming
    instance: Mapped[str] = mapped_column(String(96), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16), default="service")
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="STOPPED")
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Optional access secret (e.g. code-server password) shown to the admin
    secret: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Custom-image apps (slug == "custom"): the Docker image + container port to
    # run, plus extra env vars (JSON {KEY: VALUE}). NULL for catalog apps.
    image: Mapped[str | None] = mapped_column(String(255), nullable=True)
    container_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    env_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Admin-hidden: invisible and unreachable for non-admin users.
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Proxy(Base):
    """
    A reverse proxy: route a domain to a local service (127.0.0.1:port) — e.g.
    a Docker container or a uvicorn/Flask/Node app you run yourself. The panel
    generates the nginx proxy block and (optionally) issues SSL.
    """
    __tablename__ = "proxies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    upstream_port: Mapped[int] = mapped_column(Integer)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PipelineRun(Base):
    """One execution of a project's pipeline (manual or scheduled)."""
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # RUNNING / SUCCESS / FAILED
    status: Mapped[str] = mapped_column(String(16), default="RUNNING")
    # JSON list of per-script results: [{filename, folder, status, exit_code, finished}]
    results: Mapped[str] = mapped_column(Text, default="[]")
    dashboard_restarted: Mapped[bool] = mapped_column(Boolean, default=False)
