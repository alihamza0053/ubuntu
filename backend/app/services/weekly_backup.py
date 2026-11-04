"""
The automatic weekly backup of the whole panel.

Runs as its own low-priority process (see scheduler_service._weekly_backup):

    python -m app.services.weekly_backup

Replacing the previous backup is done in the only safe order: make the new one,
read it back end to end, and only then delete the old. If anything fails the
previous backup stays, and the reason shows in Settings → Backup & Restore.
Only automatic backups (serverhub-auto-*) are ever deleted — never manual ones.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime

from ..database import SessionLocal
from ..models import Setting
from . import backup_service as bs

LAST_KEY = "auto_backup_last"
SPACE_MARGIN = 1.3          # want this many times the last backup's size free


def _save_last(result: dict) -> None:
    db = SessionLocal()
    try:
        row = db.query(Setting).filter(Setting.key == LAST_KEY).first()
        text = json.dumps(result)
        if row is None:
            db.add(Setting(key=LAST_KEY, value=text))
        else:
            row.value = text
        db.commit()
    finally:
        db.close()


def last_result() -> dict | None:
    db = SessionLocal()
    try:
        row = db.query(Setting).filter(Setting.key == LAST_KEY).first()
        return json.loads(row.value) if row and row.value else None
    except ValueError:
        return None
    finally:
        db.close()


def _auto_backups():
    return sorted(bs.BACKUP_DIR.glob(f"{bs.AUTO_PREFIX}-*.tar.gz"))


def run() -> dict:
    """Make the new backup, verify it, then remove the previous automatic one(s)."""
    bs.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    # leftovers of an interrupted run (never a finished backup)
    for stale in bs.BACKUP_DIR.glob(f"{bs.AUTO_PREFIX}-*.tar.gz.partial"):
        stale.unlink(missing_ok=True)

    previous = _auto_backups()
    if previous:
        need = int(previous[-1].stat().st_size * SPACE_MARGIN)
        free = shutil.disk_usage(bs.BACKUP_DIR).free
        if free < need:
            raise RuntimeError(f"Not enough disk space: {bs._human(free)} free, about {bs._human(need)} needed "
                               "(the previous backup is kept until the new one is finished).")

    info = bs.create_backup(bs.ALL_COMPONENTS, prefix=bs.AUTO_PREFIX)

    # Reading the manifest decompresses the archive to its very end (it's the last
    # entry), so a truncated or corrupt file fails here — before anything is deleted.
    new_path = bs.BACKUP_DIR / info["name"]
    manifest = bs._read_manifest(new_path)
    if not manifest.get("components") or set(manifest["components"]) != set(info["components"]):
        new_path.unlink(missing_ok=True)      # the bad new file, not the previous good one
        raise RuntimeError("The new backup failed verification; the previous one was kept.")

    deleted = []
    for old in previous:
        old.unlink(missing_ok=True)
        deleted.append(old.name)
    return {**info, "deleted": deleted}


def main() -> int:
    started = time.time()
    try:
        info = run()
        _save_last({"ok": True, "at": datetime.now().isoformat(timespec="seconds"), "name": info["name"],
                    "size_human": info["size_human"], "components": info["components"],
                    "deleted": info["deleted"], "minutes": round((time.time() - started) / 60, 1)})
        print(f"OK {info['name']} {info['size_human']}")
        return 0
    except Exception as exc:  # noqa: BLE001 — record the reason for Settings
        _save_last({"ok": False, "at": datetime.now().isoformat(timespec="seconds"),
                    "error": str(exc)[:500], "minutes": round((time.time() - started) / 60, 1)})
        print(f"FAILED {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
