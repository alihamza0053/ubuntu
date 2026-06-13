"""
Central activity log: a single timestamped feed of everything the panel is
doing right now (scripts starting/finishing, pipelines, dashboard actions).

The Logs page tails this file live in its "Live Activity" section. Writing is
best-effort and thread-safe so it never breaks the action it's reporting.
"""
import threading
from datetime import datetime

from ..config import settings

# /srv/serverhub/logs/activity.log (next to the panel root)
ACTIVITY_LOG = settings.DB_PATH.parent.parent / "logs" / "activity.log"

_lock = threading.Lock()


def _ensure() -> None:
    ACTIVITY_LOG.parent.mkdir(parents=True, exist_ok=True)
    if not ACTIVITY_LOG.exists():
        ACTIVITY_LOG.touch()


# Make sure the file exists at import so the live tail has something to follow
_ensure()


def log_activity(message: str) -> None:
    """Append one timestamped line to the activity feed."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with _lock:
            with ACTIVITY_LOG.open("a", encoding="utf-8") as fh:
                fh.write(f"[{ts}] {message}\n")
    except Exception:
        pass  # never let logging break the real work
