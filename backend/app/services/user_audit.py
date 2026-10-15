"""
Per-user activity log (Settings → Users → Activity).

Every change a user makes through the panel — HTTP POST/PUT/PATCH/DELETE,
script runs and installs over WebSocket, logins — is stored as one readable
row ("Started dashboard of mga-ops-dashboard"). The panel owner
(settings.OWNER_USERNAME) is never recorded and never shown.

Writing is best-effort: a failure here must never break the action itself.
"""
import re
from datetime import datetime, timedelta

from ..config import settings
from ..database import SessionLocal
from ..models import Project, Script, UserActivity, Website

_writes = 0


def is_owner(user_or_name) -> bool:
    name = getattr(user_or_name, "username", user_or_name) or ""
    return bool(settings.OWNER_USERNAME) and name == settings.OWNER_USERNAME


# (method, path regex, sentence). {p} = project name, {w} = website name,
# {s} = script file, {1}/{2} = captured groups.
_ROUTES = [
    ("POST", r"/api/projects/(\d+)/dashboard/start$", "Started dashboard of {p}"),
    ("POST", r"/api/projects/(\d+)/dashboard/stop$", "Stopped dashboard of {p}"),
    ("POST", r"/api/projects/(\d+)/dashboard/restart$", "Restarted dashboard of {p}"),
    ("PUT", r"/api/projects/(\d+)/dashboard/framework$", "Changed dashboard framework of {p}"),
    ("POST", r"/api/projects$", "Created a project"),
    ("DELETE", r"/api/projects/(\d+)$", "Deleted project {p}"),
    ("PUT", r"/api/projects/(\d+)/hidden$", "Changed visibility of project {p}"),
    ("POST", r"/api/projects/(\d+)/build-venv$", "Rebuilt the Python environment of {p}"),
    ("POST", r"/api/projects/(\d+)/upload-script$", "Uploaded a script to {p}"),
    ("POST", r"/api/projects/(\d+)/upload-dashboard$", "Uploaded dashboard files to {p}"),
    ("POST", r"/api/projects/(\d+)/upload-data$", "Uploaded data files to {p}"),
    ("DELETE", r"/api/projects/(\d+)/files$", "Deleted files in {p}"),
    ("PUT", r"/api/projects/(\d+)/onedrive-path$", "Changed the OneDrive folder of {p}"),
    ("POST", r"/api/projects/(\d+)/assign-domain$", "Assigned a domain to {p}"),
    ("PUT", r"/api/projects/(\d+)/portal-auth$", "Set the upload-portal password of {p}"),
    ("DELETE", r"/api/projects/(\d+)/portal-auth$", "Removed the upload-portal password of {p}"),
    ("POST", r"/api/projects/(\d+)/reapply-nginx$", "Re-applied nginx for {p}"),
    ("POST", r"/api/projects/(\d+)/ssl$", "Requested SSL for {p}"),
    ("PUT", r"/api/projects/(\d+)/pipeline$", "Changed the pipeline of {p}"),
    ("DELETE", r"/api/projects/(\d+)/pipeline$", "Deleted the pipeline of {p}"),
    ("POST", r"/api/projects/(\d+)/run-pipeline$", "Ran the pipeline of {p}"),
    ("POST", r"/api/projects/(\d+)/stop-pipeline$", "Stopped the pipeline of {p}"),
    ("POST", r"/api/scripts/(\d+)/stop$", "Stopped script {s}"),
    ("POST", r"/api/schedules$", "Created a schedule"),
    ("PUT", r"/api/schedules/(\d+)$", "Changed a schedule"),
    ("POST", r"/api/schedules/(\d+)/toggle$", "Turned a schedule on/off"),
    ("DELETE", r"/api/schedules/(\d+)$", "Deleted a schedule"),
    ("POST", r"/api/websites$", "Created a website"),
    ("DELETE", r"/api/websites/(\d+)$", "Deleted website {w}"),
    ("PUT", r"/api/websites/(\d+)/hidden$", "Changed visibility of website {w}"),
    ("POST", r"/api/websites/(\d+)/upload$", "Uploaded files to website {w}"),
    ("POST", r"/api/websites/(\d+)/link-database$", "Linked a database to website {w}"),
    ("POST", r"/api/websites/(\d+)/assign-domain$", "Assigned a domain to website {w}"),
    ("POST", r"/api/websites/(\d+)/ssl$", "Requested SSL for website {w}"),
    ("POST", r"/api/websites/(\d+)/install-deps$", "Installed dependencies of website {w}"),
    ("PUT", r"/api/websites/(\d+)/run-command$", "Changed the run command of website {w}"),
    ("POST", r"/api/websites/(\d+)/action/(\w+)$", "Website {w}: {2}"),
    ("POST", r"/api/databases$", "Created a database"),
    ("DELETE", r"/api/databases/([^/]+)$", "Deleted database {1}"),
    ("POST", r"/api/databases/query$", "Ran a database query"),
    ("POST", r"/api/databases/([^/]+)/tables/([^/]+)/update-row$", "Edited a row in {1}.{2}"),
    ("POST", r"/api/databases/([^/]+)/tables/([^/]+)/delete-row$", "Deleted a row in {1}.{2}"),
    ("POST", r"/api/databases/([^/]+)/import$", "Imported into database {1}"),
    ("POST", r"/api/postgres/install$", "Installed PostgreSQL"),
    ("POST", r"/api/postgres/configure$", "Re-applied the PostgreSQL configuration"),
    ("POST", r"/api/postgres$", "Created a PostgreSQL database"),
    ("DELETE", r"/api/postgres/([^/]+)$", "Deleted PostgreSQL database {1}"),
    ("POST", r"/api/postgres/([^/]+)/password$", "Reset the password of PostgreSQL database {1}"),
    ("POST", r"/api/postgres/([^/]+)/link$", "Linked/unlinked PostgreSQL database {1}"),
    ("PUT", r"/api/postgres/([^/]+)/limit$", "Changed the connection limit of PostgreSQL database {1}"),
    ("POST", r"/api/postgres/query$", "Ran a PostgreSQL query"),
    ("POST", r"/api/postgres/([^/]+)/import$", "Imported into PostgreSQL database {1}"),
    ("POST", r"/api/files/write$", "Edited a file"),
    ("POST", r"/api/files/upload$", "Uploaded files (File Manager)"),
    ("POST", r"/api/files/mkdir$", "Created a folder"),
    ("POST", r"/api/files/rename$", "Renamed a file"),
    ("POST", r"/api/files/move$", "Moved files"),
    ("DELETE", r"/api/files/delete$", "Deleted files (File Manager)"),
    ("POST", r"/api/apps/([^/]+)/install$", "Installed app {1}"),
    ("DELETE", r"/api/apps/([^/]+)$", "Removed app {1}"),
    ("POST", r"/api/apps/([^/]+)/action/(\w+)$", "App {1}: {2}"),
    ("POST", r"/api/apps/ollama/models/pull$", "Downloaded an Ollama model"),
    ("DELETE", r"/api/apps/ollama/models/(.+)$", "Deleted Ollama model {1}"),
    ("POST", r"/api/trash/(\d+)/restore$", "Restored an item from the recycle bin"),
    ("DELETE", r"/api/trash/(\d+)$", "Deleted an item from the recycle bin"),
    ("POST", r"/api/trash/empty$", "Emptied the recycle bin"),
    ("PUT", r"/api/settings$", "Changed panel settings"),
    ("POST", r"/api/settings/backups/([^/]+)/restore$", "Restored backup {1}"),
    ("POST", r"/api/settings/backup-db$", "Made a database backup"),
    ("POST", r"/api/settings/backups$", "Made a backup"),
    ("DELETE", r"/api/settings/backups/([^/]+)$", "Deleted backup {1}"),
    ("POST", r"/api/onedrive/resync$", "Started a OneDrive resync"),
    ("POST", r"/api/auth/users$", "Created a user"),
    ("PUT", r"/api/auth/users/(\d+)$", "Changed a user's access"),
    ("POST", r"/api/auth/users/(\d+)/password$", "Reset a user's password"),
    ("DELETE", r"/api/auth/users/(\d+)$", "Deleted a user"),
    ("POST", r"/api/auth/change-password$", "Changed own password"),
    # WebSocket actions (logged when the socket is accepted)
    ("WS", r"/ws/script/(\d+)/run$", "Ran script {s}"),
    ("WS", r"/ws/projects/(\d+)/pip-install$", "Installed Python packages in {p}"),
    ("WS", r"/ws/projects/(\d+)/playwright-install$", "Installed Playwright browsers in {p}"),
    ("WS", r"/ws/pipeline/(\d+)/run$", "Ran the pipeline of {p}"),
    ("WS", r"/ws/settings/cleanup$", "Ran a system cleanup"),
    ("WS", r"/ws/settings/update$", "Updated the panel"),
]
_COMPILED = [(m, re.compile(rx), text) for m, rx, text in _ROUTES]
LOGGED_WS = tuple(rx for m, rx, _ in _COMPILED if m == "WS")


def describe(db, method: str, path: str) -> str | None:
    """Readable sentence for a request, or None when it isn't worth logging."""
    for m, rx, text in _COMPILED:
        if m != method:
            continue
        match = rx.search(path)
        if not match:
            continue
        groups = match.groups()
        values = {str(i + 1): g for i, g in enumerate(groups)}
        first = groups[0] if groups else None
        if "{p}" in text:
            proj = db.get(Project, int(first)) if first and first.isdigit() else None
            values["p"] = proj.name if proj else f"project #{first}"
        if "{w}" in text:
            site = db.get(Website, int(first)) if first and first.isdigit() else None
            values["w"] = getattr(site, "name", None) or f"#{first}"
        if "{s}" in text:
            script = db.get(Script, int(first)) if first and first.isdigit() else None
            values["s"] = (f"{script.filename} ({script.project.name})"
                           if script and getattr(script, "project", None) else
                           (script.filename if script else f"#{first}"))
        return re.sub(r"\{(\w+)\}", lambda mm: values.get(mm.group(1), mm.group(0)), text)
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        return f"{method} {path}"              # anything new still shows up, just less pretty
    return None


def record(username: str, user_id: int | None, action: str, method: str = "", path: str = "",
           status: int = 0, ip: str = "") -> None:
    """Store one row (never for the owner). Never raises."""
    global _writes
    if not username or is_owner(username):
        return
    db = SessionLocal()
    try:
        db.add(UserActivity(at=datetime.now(), user_id=user_id, username=username[:64], action=action[:255],
                            method=method[:8], path=path[:512], status=status, ip=(ip or "")[:64]))
        _writes += 1
        if _writes % 500 == 1:                 # prune now and then
            cutoff = datetime.now() - timedelta(days=settings.USER_ACTIVITY_DAYS)
            db.query(UserActivity).filter(UserActivity.at < cutoff).delete()
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    finally:
        db.close()


def record_request(user, method: str, path: str, status: int, ip: str) -> None:
    """Called by the audit middleware after a request finished."""
    if user is None or is_owner(user):
        return
    db = SessionLocal()
    try:
        action = describe(db, method, path)
    except Exception:  # noqa: BLE001
        action = f"{method} {path}"
    finally:
        db.close()
    if action:
        if status >= 400:
            action = f"{action} — failed ({status})"
        record(user.username, user.id, action, method, path, status, ip)
