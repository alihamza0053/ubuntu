"""
Pydantic request/response schemas for the API.
"""
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ---------- Auth ----------

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    is_admin: bool = False
    permissions: list[str] = []


class UserCreate(BaseModel):
    username: str
    password: str
    is_admin: bool = False
    permissions: list[str] = []


class UserUpdate(BaseModel):
    is_admin: bool | None = None
    permissions: list[str] | None = None


class PasswordReset(BaseModel):
    new_password: str


# ---------- Projects ----------

class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64)

    @field_validator("name")
    @classmethod
    def slug_only(cls, v: str) -> str:
        """Project names become folder names and supervisor program names,
        so restrict them to a safe slug."""
        v = v.strip().lower().replace(" ", "-")
        if not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError("Name may only contain letters, numbers, '-' and '_'")
        return v


class ScriptOut(BaseModel):
    id: int
    folder: str
    filename: str
    schedule_cron: str | None
    last_run: datetime | None
    last_status: str | None

    model_config = {"from_attributes": True}


class FileInfo(BaseModel):
    name: str
    size: int
    modified: datetime


class ProjectOut(BaseModel):
    id: int
    name: str
    folder_path: str
    dashboard_port: int
    dashboard_status: str
    domain: str | None
    onedrive_path: str | None = None
    portal_username: str | None = None
    # Admin-hidden: only ever True in responses admins see (filtered otherwise)
    hidden: bool = False
    created_at: datetime
    # Extra computed fields for dashboard cards
    file_counts: dict[str, int] = {}
    last_script_run: datetime | None = None
    last_script_status: str | None = None
    next_scheduled_run: datetime | None = None
    # Dashboard venv state: READY / BUILDING / MISSING
    venv_status: str = "MISSING"

    model_config = {"from_attributes": True}


class ProjectFilesOut(BaseModel):
    """Files grouped by project sub-folder."""
    folders: dict[str, list[FileInfo]]


# ---------- Editor / files ----------

class FileWriteRequest(BaseModel):
    path: str
    content: str


class FileReadResponse(BaseModel):
    path: str
    content: str


# ---------- Generic ----------

class DetailResponse(BaseModel):
    detail: str


class DashboardStatusOut(BaseModel):
    status: str          # RUNNING / STOPPED / ERROR / UNKNOWN
    port: int
    raw: str             # raw supervisorctl status line for debugging
