"""
Failed-login limiter (panel login + upload portal).

Counts FAILURES per client and per account. The client address comes from the
X-Real-IP header nginx sets (it overwrites anything the visitor sends, and the
panel listens on 127.0.0.1 only): request.client is always nginx, so limiting
on it would lock everybody out at once.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request

_failures: dict[str, list[float]] = defaultdict(list)
_lock = threading.Lock()
MAX_KEYS = 20000            # a flood of random names can't grow this forever


def client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def _recent(key: str, window: int, now: float) -> int:
    kept = [t for t in _failures.get(key, []) if now - t < window]
    if kept:
        _failures[key] = kept
    else:
        _failures.pop(key, None)
    return len(kept)


def check(keys: dict[str, int], window: int) -> None:
    """keys = {key: max failures}. 429 when any is over its limit."""
    now = time.monotonic()
    with _lock:
        if any(_recent(key, window, now) >= limit for key, limit in keys.items()):
            raise HTTPException(status_code=429, detail=f"Too many failed attempts. Try again in {window} seconds.")


def failed(keys) -> None:
    now = time.monotonic()
    with _lock:
        if len(_failures) >= MAX_KEYS:
            _failures.clear()
        for key in keys:
            _failures[key].append(now)
