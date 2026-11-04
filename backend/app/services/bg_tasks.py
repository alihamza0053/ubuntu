"""
Long actions (installs, bulk start/stop) run in the background.

The button's request returns at once and the page polls for the result. A
request held open for minutes gets cut by whatever proxy sits in front of the
panel (e.g. Cloudflare's 100–120 s limit) — the work carries on unseen, the
user sees an error, and a second click collides with the first.

One task per key at a time. State lives in memory: the panel is one process,
and a restart ends the tasks with it.
"""
from __future__ import annotations

import threading
from datetime import datetime

_tasks: dict[str, dict] = {}
_lock = threading.Lock()


def start(key: str, fn, *args) -> bool:
    """Run fn(*args) in a thread. False when that key is already running."""
    with _lock:
        if _tasks.get(key, {}).get("running"):
            return False
        _tasks[key] = {"running": True, "ok": None, "result": None, "error": None,
                       "started": datetime.now().isoformat(timespec="seconds")}

    def work():
        try:
            result = fn(*args)
            update = {"ok": True, "result": result}
        except Exception as exc:  # noqa: BLE001 — shown to the user by the page
            update = {"ok": False, "error": str(getattr(exc, "detail", exc))[:1500]}
        with _lock:
            _tasks[key].update(running=False, **update)

    threading.Thread(target=work, daemon=True, name=f"bg-{key}").start()
    return True


def state(key: str) -> dict | None:
    with _lock:
        task = _tasks.get(key)
        return dict(task) if task else None
