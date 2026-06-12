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
    """Single admin user (more could be added later)."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(128))


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
    type: Mapped[str] = mapped_column(String(16))  # react / php / html
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    db_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
