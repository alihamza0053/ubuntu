"""
Central configuration for the ServerHub backend.

All values come from environment variables (loaded from backend/.env via
python-dotenv) with sensible defaults for an Ubuntu VPS deployment.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# backend/ directory (parent of the app/ package)
BASE_DIR = Path(__file__).resolve().parent.parent

# Load backend/.env if present (silently ignored when missing)
load_dotenv(BASE_DIR / ".env")


def _env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser()


class Settings:
    """Plain settings object — read once at import time."""

    # --- Security / JWT ---
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-insecure-secret-change-me")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "720"))

    # --- Login rate limiting (attempts per window, per client IP) ---
    LOGIN_RATE_LIMIT_ATTEMPTS: int = int(os.getenv("LOGIN_RATE_LIMIT_ATTEMPTS", "5"))
    # The panel owner: a full-access admin that is invisible to every other user
    # (other admins included) — not listed, not editable, its actions not logged.
    OWNER_USERNAME: str = os.getenv("OWNER_USERNAME", "hamza")
    # How long per-user activity entries are kept (Settings → Users → Activity).
    USER_ACTIVITY_DAYS: int = int(os.getenv("USER_ACTIVITY_DAYS", "90"))
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60"))

    # --- Internal database (SQLite) ---
    DB_PATH: Path = _env_path("DB_PATH", str(BASE_DIR.parent / "db" / "serverhub.db"))

    # --- Managed roots on the VPS ---
    PROJECTS_ROOT: Path = _env_path("PROJECTS_ROOT", "/srv/projects")
    WEBSITES_ROOT: Path = _env_path("WEBSITES_ROOT", "/srv/websites")
    NGINX_CONFIGS_ROOT: Path = _env_path("NGINX_CONFIGS_ROOT", "/srv/nginx-configs")
    # File Manager shortcut. It is not shown in the default roots listing.
    OPT_ROOT: Path = _env_path("OPT_ROOT", "/opt")

    # --- Apps section (Chromium / Brave / n8n) ---
    # Per-app data, generated run scripts and install logs live here; the
    # privileged installer helper creates each subfolder and hands it to the
    # panel user. Desktop apps start at APP_DISPLAY_START (X display number)
    # and are viewed over noVNC on the port stored with the app.
    APPS_ROOT: Path = _env_path("APPS_ROOT", "/srv/apps")
    APPS_BIN: Path = _env_path("APPS_BIN", "/srv/serverhub/bin/serverhub-apps")
    APP_DISPLAY_START: int = int(os.getenv("APP_DISPLAY_START", "90"))
    # Screen size of the virtual display a browser app is drawn on.
    APP_SCREEN: str = os.getenv("APP_SCREEN", "1440x900x24")

    # --- Recycle bin ---
    # Deleted project/website files are moved here (with metadata) instead of
    # being erased, and auto-purged after TRASH_RETENTION_HOURS.
    TRASH_ROOT: Path = _env_path("TRASH_ROOT", "/srv/serverhub/trash")
    TRASH_RETENTION_HOURS: int = int(os.getenv("TRASH_RETENTION_HOURS", "24"))

    # --- OneDrive sync (read-only into /srv/onedrive; one company account) ---
    # The onedrive client syncs here; projects map to a subfolder of it.
    ONEDRIVE_ROOT: Path = _env_path("ONEDRIVE_ROOT", "/srv/onedrive")
    # The onedrive client's config/token directory (owned by the panel user).
    ONEDRIVE_CONFDIR: Path = _env_path("ONEDRIVE_CONFDIR", "/srv/serverhub/onedrive")

    # --- Supervisor (Streamlit dashboard process manager) ---
    SUPERVISOR_CONF_DIR: Path = _env_path("SUPERVISOR_CONF_DIR", "/srv/serverhub/supervisor.d")
    SUPERVISOR_LOG_DIR: Path = _env_path("SUPERVISOR_LOG_DIR", "/var/log/supervisor")
    SUPERVISORCTL_USE_SUDO: bool = os.getenv("SUPERVISORCTL_USE_SUDO", "true").lower() == "true"

    # --- Streamlit dashboards ---
    DASHBOARD_PORT_START: int = int(os.getenv("DASHBOARD_PORT_START", "8501"))

    # --- Pipeline ---
    # After the first pass, re-run any scripts that FAILED, at the end of the
    # run. Number of extra passes over the still-failing scripts (0 disables).
    PIPELINE_MAX_RETRIES: int = int(os.getenv("PIPELINE_MAX_RETRIES", "1"))

    # --- Executables ---
    PYTHON_BIN: str = os.getenv("PYTHON_BIN", "python3")
    STREAMLIT_BIN: str = os.getenv("STREAMLIT_BIN", "streamlit")

    # --- Panel itself ---
    PANEL_PORT: int = int(os.getenv("PANEL_PORT", "8765"))
    PANEL_ROOT: Path = _env_path("PANEL_ROOT", "/srv/serverhub")

    # --- Self-update ("Settings → Updates → Update now") ---
    # Source-code checkout the panel redeploys from (a git clone or uploaded
    # bundle that contains deploy/update.sh). Set by the installer.
    UPDATE_SRC: Path = _env_path("UPDATE_SRC", "/opt/serverhub-src")

    # Frontend build output served by FastAPI in production
    STATIC_DIR: Path = BASE_DIR / "static"

    # Project sub-folders created for every workspace
    PROJECT_FOLDERS: tuple = ("code", "allscripts", "data", "dashboard", "logs")

    # Upload extension allow-lists per folder (security: reject executables)
    SCRIPT_EXTENSIONS: set = {".py", ".txt", ".json", ".yaml", ".yml", ".csv", ".md", ".cfg", ".ini", ".toml"}
    DATA_EXTENSIONS: set = {".xlsx", ".xls", ".csv", ".json", ".txt"}
    DASHBOARD_EXTENSIONS: set = {".py", ".txt", ".json", ".yaml", ".yml", ".csv", ".md",
                                 ".png", ".jpg", ".jpeg", ".svg", ".css", ".toml",
                                 ".html", ".js"}

    # Extensions the Monaco editor is allowed to open/save
    EDITABLE_EXTENSIONS: set = {".py", ".txt", ".json", ".yaml", ".yml", ".csv", ".md",
                                ".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx",
                                ".php", ".sql", ".conf", ".cfg", ".ini", ".toml", ".env",
                                ".sh", ".log", ".xml"}


settings = Settings()
