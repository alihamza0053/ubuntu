"""
Recycle bin for deleted project/website files.

Instead of erasing a file, the file API moves it here with a small metadata
sidecar, so it can be restored. Items are auto-purged after
settings.TRASH_RETENTION_HOURS (24h by default) — enforced both on every list()
call and by an hourly scheduler job.

Layout on disk:
    TRASH_ROOT/<trash_id>/meta.json     # original path, name, size, deleted_at
    TRASH_ROOT/<trash_id>/<name>        # the moved file or directory

Everything is confined to the panel-managed roots via ensure_in_allowed_roots.
"""
import json
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException

from ..config import settings

RETENTION = timedelta(hours=settings.TRASH_RETENTION_HOURS)


def _root() -> Path:
    settings.TRASH_ROOT.mkdir(parents=True, exist_ok=True)
    return settings.TRASH_ROOT


def is_trashable(path: Path) -> bool:
    """Only project and website files go to the bin (not nginx configs etc.)."""
    resolved = path.resolve()
    for root in (settings.PROJECTS_ROOT, settings.WEBSITES_ROOT):
        r = root.resolve()
        if resolved == r or r in resolved.parents:
            return True
    return False


def _origin_label(original_path: str) -> str:
    """Human 'Projects / <name> / …' style location for the UI."""
    p = Path(original_path)
    for root, label in ((settings.PROJECTS_ROOT, "Projects"),
                        (settings.WEBSITES_ROOT, "Websites")):
        try:
            rel = p.relative_to(root.resolve())
            return f"{label} / {rel.as_posix()}"
        except ValueError:
            continue
    return original_path


def _dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            pass
    return total


def move_to_trash(path: Path) -> dict:
    """Move a file/dir into the bin and record where it came from."""
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")

    trash_id = f"{datetime.utcnow():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
    item_dir = _root() / trash_id
    item_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "id": trash_id,
        "name": path.name,
        "original_path": str(path),
        "origin": _origin_label(str(path)),
        "is_dir": path.is_dir(),
        "size": _dir_size(path),
        "deleted_at": datetime.utcnow().isoformat(),
    }
    # Move the payload in, then write metadata (so a half-move never looks valid).
    shutil.move(str(path), str(item_dir / path.name))
    (item_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def _read_meta(item_dir: Path) -> dict | None:
    meta_file = item_dir / "meta.json"
    if not meta_file.is_file():
        return None
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _expiry(meta: dict) -> datetime:
    try:
        return datetime.fromisoformat(meta["deleted_at"]) + RETENTION
    except (KeyError, ValueError):
        return datetime.utcnow() + RETENTION


def purge_all() -> tuple[int, int]:
    """Empty the recycle bin completely. Returns (items removed, bytes freed)."""
    removed = 0
    freed = 0
    if not settings.TRASH_ROOT.exists():
        return 0, 0
    for item_dir in settings.TRASH_ROOT.iterdir():
        if not item_dir.is_dir():
            continue
        freed += _dir_size(item_dir)
        shutil.rmtree(item_dir, ignore_errors=True)
        removed += 1
    return removed, freed


def purge_expired() -> int:
    """Delete bin items older than the retention window. Returns count removed."""
    now = datetime.utcnow()
    removed = 0
    if not settings.TRASH_ROOT.exists():
        return 0
    for item_dir in settings.TRASH_ROOT.iterdir():
        if not item_dir.is_dir():
            continue
        meta = _read_meta(item_dir)
        # Corrupt/incomplete items and expired items both get swept.
        if meta is None or _expiry(meta) <= now:
            shutil.rmtree(item_dir, ignore_errors=True)
            removed += 1
    return removed


def list_items() -> list[dict]:
    """Purge expired items, then return the rest (newest first)."""
    purge_expired()
    items = []
    if settings.TRASH_ROOT.exists():
        for item_dir in settings.TRASH_ROOT.iterdir():
            meta = _read_meta(item_dir) if item_dir.is_dir() else None
            if meta:
                meta["expires_at"] = _expiry(meta).isoformat()
                items.append(meta)
    items.sort(key=lambda m: m.get("deleted_at", ""), reverse=True)
    return items


def _find(trash_id: str) -> tuple[Path, dict]:
    item_dir = _root() / trash_id
    meta = _read_meta(item_dir) if item_dir.is_dir() else None
    if meta is None:
        raise HTTPException(status_code=404, detail="Item not found in recycle bin")
    return item_dir, meta


def restore(trash_id: str) -> dict:
    """Move an item back to its original location."""
    item_dir, meta = _find(trash_id)
    payload = item_dir / meta["name"]
    if not payload.exists():
        raise HTTPException(status_code=410, detail="Item payload is gone")

    dest = Path(meta["original_path"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        # Don't clobber a file that was recreated since deletion.
        stem, suffix = dest.stem, dest.suffix
        dest = dest.with_name(f"{stem} (restored){suffix}")

    shutil.move(str(payload), str(dest))
    shutil.rmtree(item_dir, ignore_errors=True)
    return {"restored_to": str(dest)}


def purge(trash_id: str) -> None:
    """Permanently delete one bin item."""
    item_dir, _ = _find(trash_id)
    shutil.rmtree(item_dir, ignore_errors=True)


def empty() -> int:
    """Permanently delete everything in the bin. Returns count removed."""
    removed = 0
    if settings.TRASH_ROOT.exists():
        for item_dir in settings.TRASH_ROOT.iterdir():
            if item_dir.is_dir():
                shutil.rmtree(item_dir, ignore_errors=True)
                removed += 1
    return removed
