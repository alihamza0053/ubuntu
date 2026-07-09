"""
Backup & restore for the panel.

Creates compressed archives (``serverhub-backup-<stamp>.tar.gz``) under
``PANEL_ROOT/backups`` containing any selection of:

  panel_db   the panel's SQLite database (projects, scripts, apps, settings…)
  projects   /srv/projects        (code, data, dashboards)
  websites   /srv/websites        (hosted sites)
  nginx      /srv/nginx-configs   (generated vhosts)
  apps       /srv/serverhub/apps  (docker-compose stacks)
  databases  all MySQL databases  (via mysqldump)

Most paths are owned by the panel user, so create/restore are plain file ops;
only MySQL needs the (already whitelisted) ``sudo mysqldump`` / ``sudo mysql``.

All operations are synchronous and meant to be called from sync FastAPI
endpoints (which run in a threadpool).
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from ..config import settings

BACKUP_DIR: Path = settings.PANEL_ROOT / "backups"
NAME_RE = re.compile(r"^[\w.-]+\.tar\.gz$")

# Directory names never worth backing up (regenerable / huge)
_SKIP_DIRS = {"venv", ".venv", "__pycache__", "node_modules", ".git", "backups"}


# Each component: key, label, description, and where it lives.
COMPONENTS: list[dict] = [
    {"key": "panel_db", "label": "Panel database",
     "desc": "Projects, scripts, apps, schedules, users, settings"},
    {"key": "projects", "label": "Projects",
     "desc": "/srv/projects — code, data, dashboards"},
    {"key": "websites", "label": "Websites",
     "desc": "/srv/websites — hosted sites & PHP apps"},
    {"key": "nginx", "label": "Nginx configs",
     "desc": "/srv/nginx-configs — generated vhosts"},
    {"key": "apps", "label": "App data",
     "desc": "/srv/serverhub/apps — docker-compose stacks"},
    {"key": "databases", "label": "MySQL databases",
     "desc": "All MySQL databases (mysqldump)"},
]
COMPONENT_KEYS = {c["key"] for c in COMPONENTS}


def _component_path(key: str) -> Path | None:
    """Filesystem source for a component, or None for special handlers."""
    return {
        "panel_db": settings.DB_PATH,
        "projects": settings.PROJECTS_ROOT,
        "websites": settings.WEBSITES_ROOT,
        "nginx": settings.NGINX_CONFIGS_ROOT,
        "apps": settings.PANEL_ROOT / "apps",
    }.get(key)


def _sqlite_snapshot(src: Path, dst: Path) -> None:
    """Make a consistent copy of a (possibly live) SQLite DB."""
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(str(dst))
        try:
            with target:
                source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _add_tree(tar: tarfile.TarFile, src: Path, arcname: str) -> None:
    """
    Recursively add a file/dir to the archive, but:
      - skip regenerable/huge dirs (venv, node_modules, …), and
      - skip anything the panel user can't read.

    That last part matters for the `apps` component: Docker apps like self-hosted
    Supabase keep a Postgres data dir there owned by the container's postgres user
    at mode 0700. The panel's `serverhub` user can't read it, so a naive tar walk
    dies with "[Errno 13] Permission denied". A live DB data dir can't be safely
    file-copied anyway (use a DB dump), so skipping it is the right behaviour.
    """
    if src.name in _SKIP_DIRS:
        return
    try:
        if src.is_symlink():
            tar.add(src, arcname=arcname, recursive=False)
            return
        if src.is_dir():
            tar.add(src, arcname=arcname, recursive=False)   # directory entry only
            for child in sorted(src.iterdir()):               # may raise PermissionError
                _add_tree(tar, child, f"{arcname}/{child.name}")
        else:
            tar.add(src, arcname=arcname, recursive=False)
    except (PermissionError, FileNotFoundError, OSError):
        # Unreadable (container-owned) or vanished entry — skip, keep the backup going.
        return


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
def create_backup(components: list[str]) -> dict:
    selected = [c for c in components if c in COMPONENT_KEYS]
    if not selected:
        raise ValueError("Select at least one thing to back up.")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"serverhub-backup-{stamp}.tar.gz"
    out = BACKUP_DIR / name

    included: list[str] = []
    try:
        with tempfile.TemporaryDirectory() as tmp, \
                tarfile.open(out, "w:gz") as tar:
            for c in selected:
                if c == "databases":
                    dump = Path(tmp) / "all-databases.sql"
                    with dump.open("wb") as fh:
                        proc = subprocess.run(
                            ["sudo", "-n", "mysqldump", "--all-databases",
                             "--single-transaction", "--routines", "--events"],
                            stdout=fh, stderr=subprocess.PIPE, timeout=600)
                    if proc.returncode != 0:
                        err = proc.stderr.decode("utf-8", "replace").strip()
                        raise RuntimeError(f"mysqldump failed: {err[:300]}")
                    tar.add(dump, arcname="databases/all-databases.sql")
                    included.append(c)
                elif c == "panel_db":
                    src = _component_path(c)
                    if not src or not src.exists():
                        continue
                    # Consistent snapshot via SQLite's online backup API
                    snap = Path(tmp) / "serverhub.db"
                    _sqlite_snapshot(src, snap)
                    tar.add(snap, arcname="panel_db/serverhub.db")
                    included.append(c)
                else:
                    src = _component_path(c)
                    if not src or not src.exists():
                        continue
                    _add_tree(tar, src, c)
                    included.append(c)

            manifest = {
                "version": 1,
                "created": datetime.now().isoformat(timespec="seconds"),
                "components": included,
            }
            mpath = Path(tmp) / "manifest.json"
            mpath.write_text(json.dumps(manifest, indent=2))
            tar.add(mpath, arcname="manifest.json")
    except Exception:
        out.unlink(missing_ok=True)
        raise

    if not included:
        out.unlink(missing_ok=True)
        raise ValueError("Nothing to back up — selected items were empty/missing.")
    return backup_info(out)


# ---------------------------------------------------------------------------
# List / inspect
# ---------------------------------------------------------------------------
def _read_manifest(path: Path) -> dict:
    try:
        with tarfile.open(path) as tar:
            m = tar.extractfile("manifest.json")
            if m is not None:
                return json.loads(m.read().decode("utf-8"))
    except (KeyError, tarfile.TarError, json.JSONDecodeError, OSError):
        pass
    return {}


def _human(size: int) -> str:
    val = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024 or unit == "TB":
            return f"{val:.0f} {unit}" if unit == "B" else f"{val:.1f} {unit}"
        val /= 1024
    return f"{size} B"


def backup_info(path: Path) -> dict:
    stat = path.stat()
    manifest = _read_manifest(path)
    created = manifest.get("created") or datetime.fromtimestamp(
        stat.st_mtime).isoformat(timespec="seconds")
    return {
        "name": path.name,
        "size": stat.st_size,
        "size_human": _human(stat.st_size),
        "created": created,
        "components": manifest.get("components", []),
    }


def list_backups() -> list[dict]:
    if not BACKUP_DIR.is_dir():
        return []
    items = [backup_info(p) for p in BACKUP_DIR.glob("*.tar.gz") if p.is_file()]
    items.sort(key=lambda b: b["created"], reverse=True)
    return items


def _safe_backup(name: str) -> Path:
    """Resolve a backup file name to a path inside BACKUP_DIR (no traversal)."""
    if not NAME_RE.match(name):
        raise ValueError("Invalid backup name.")
    path = (BACKUP_DIR / name).resolve()
    if BACKUP_DIR.resolve() not in path.parents or not path.is_file():
        raise FileNotFoundError("Backup not found.")
    return path


def delete_backup(name: str) -> None:
    _safe_backup(name).unlink()


def backup_file_path(name: str) -> Path:
    return _safe_backup(name)


# ---------------------------------------------------------------------------
# Import (upload)
# ---------------------------------------------------------------------------
def save_uploaded(filename: str, data: bytes) -> dict:
    if not (filename.endswith(".tar.gz") or filename.endswith(".tgz")):
        raise ValueError("Backup must be a .tar.gz archive.")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.-]+", "_", Path(filename).name)
    if not safe.startswith("serverhub-backup"):
        safe = f"serverhub-backup-imported-{safe}"
    dest = BACKUP_DIR / safe
    dest.write_bytes(data)
    # Validate it's a readable tar; drop it otherwise
    try:
        with tarfile.open(dest) as tar:
            tar.getmembers()
    except tarfile.TarError:
        dest.unlink(missing_ok=True)
        raise ValueError("File is not a valid tar.gz archive.")
    return backup_info(dest)


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
def _within(base: Path, target: Path) -> bool:
    base = base.resolve()
    target = target.resolve()
    return base == target or base in target.parents


def _safe_extractall(tar: tarfile.TarFile, dest: Path) -> None:
    for member in tar.getmembers():
        out = (dest / member.name).resolve()
        if not _within(dest, out):
            continue  # skip path-traversal entries
        tar.extract(member, dest)


def restore_backup(name: str, components: list[str]) -> dict:
    path = _safe_backup(name)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    rollback = BACKUP_DIR / f"pre-restore-{stamp}"

    restored: list[str] = []
    restart_panel = False

    with tarfile.open(path) as tar:
        manifest = _read_manifest(path)
        available = set(manifest.get("components", [])) or COMPONENT_KEYS
        selected = [c for c in components
                    if c in COMPONENT_KEYS and c in available]
        if not selected:
            raise ValueError("None of the selected items are in this backup.")

        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp)
            _safe_extractall(tar, staging)

            for c in selected:
                if c == "databases":
                    sql = staging / "databases" / "all-databases.sql"
                    if not sql.is_file():
                        continue
                    with sql.open("rb") as fh:
                        proc = subprocess.run(["sudo", "-n", "mysql"],
                                              stdin=fh,
                                              stderr=subprocess.PIPE,
                                              timeout=600)
                    if proc.returncode != 0:
                        err = proc.stderr.decode("utf-8", "replace").strip()
                        raise RuntimeError(f"mysql restore failed: {err[:300]}")
                    restored.append(c)

                elif c == "panel_db":
                    src = staging / "panel_db" / "serverhub.db"
                    if not src.is_file():
                        continue
                    dst = settings.DB_PATH
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    _stash(dst, rollback / "panel_db" / dst.name)
                    shutil.copy2(src, dst)
                    restored.append(c)
                    restart_panel = True

                else:
                    src = staging / c
                    if not src.is_dir():
                        continue
                    target = _component_path(c)
                    if target is None:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    _stash(target, rollback / c)
                    shutil.copytree(src, target)
                    restored.append(c)

    if not restored:
        raise ValueError("Nothing was restored.")

    if restart_panel:
        _restart_panel_detached()

    return {"restored": restored, "restart": restart_panel,
            "rollback": str(rollback) if rollback.exists() else None}


def _stash(path: Path, dest: Path) -> None:
    """Move an existing file/dir aside (for rollback) before overwriting."""
    if not path.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))


def _restart_panel_detached() -> None:
    """Restart the panel out-of-band so the restored DB takes effect."""
    try:
        subprocess.Popen(
            ["sudo", "-n", "supervisorctl", "restart", "serverhub"],
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
