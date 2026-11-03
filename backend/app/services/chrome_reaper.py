"""
Leftover headless Chrome / chromedriver from project scripts.

Selenium starts chromedriver (and Chrome under it) in a session of its own, so
signalling a finished script's process group misses them; scripts that crash
before driver.quit() leave whole browsers running — dozens of processes, RAM,
swap and CPU (the October 2026 server had 115 of them).

Every script run gets a unique SERVERHUB_RUN_ID in its environment. Everything
the script starts inherits it — however it detaches — so:
  * finish_run(): when the script exits, stop everything still carrying its id;
  * sweep(): every few minutes, stop headless Chrome / chromedriver whose run is
    over. A run is "over" when no non-browser process (the script itself) with
    that id is alive, so this needs no memory and survives panel restarts.
Browsers without an id (started before this existed) are stopped once they're
older than LEGACY_MAX_AGE. The Apps section's Chromium/Brave aren't headless
and are never touched; neither is anything owned by another user.
"""
from __future__ import annotations

import os
import time
import uuid

import psutil

MARKER = "SERVERHUB_RUN_ID"
GRACE_SECONDS = 60                 # a finished run's browser gets this long to exit by itself
LEGACY_MAX_AGE = 3 * 3600          # un-tagged headless browsers older than this are leftovers


def new_run_id() -> str:
    return uuid.uuid4().hex


def _cmdline(p: psutil.Process) -> str:
    try:
        return " ".join(p.cmdline())
    except (psutil.Error, OSError):
        return ""


def _is_browser(p: psutil.Process, cmd: str) -> bool:
    """Headless Chrome (any of its helper processes) or chromedriver."""
    if "chromedriver" in cmd:
        return True
    if "chrome" not in cmd:
        return False
    # helpers (renderer, gpu, zygote, utility) don't all repeat --headless;
    # they carry --type=… and live under a headless browser process
    return "--headless" in cmd or "--type=" in cmd


def _under_headless(p: psutil.Process, cmd: str) -> bool:
    """chromedriver, a --headless browser, or a helper whose parent chain has one.
    (Strict on purpose for untagged processes: the Apps section's Brave/Chromium
    are real windowed browsers and their helpers also carry --type=.)"""
    if "chromedriver" in cmd or "--headless" in cmd:
        return True
    try:
        for parent in p.parents()[:6]:
            pcmd = _cmdline(parent)
            if "--headless" in pcmd or "chromedriver" in pcmd:
                return True
    except (psutil.Error, OSError):
        pass
    return False


def _mine():
    me = os.getuid()
    for p in psutil.process_iter(["pid", "uids", "create_time"]):
        try:
            if p.info["uids"] and p.info["uids"].real == me and p.pid != os.getpid():
                yield p
        except (psutil.Error, OSError):
            continue


def _run_id(p: psutil.Process) -> str | None:
    try:
        return p.environ().get(MARKER)
    except (psutil.Error, OSError):
        return None


def _stop(procs: list[psutil.Process]) -> int:
    """SIGTERM, wait up to 3 s, SIGKILL the rest. Returns how many were stopped."""
    procs = [p for p in procs if p.is_running()]
    for p in procs:
        try:
            p.terminate()
        except psutil.Error:
            pass
    gone, alive = psutil.wait_procs(procs, timeout=3)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
    return len(procs)


def finish_run(run_id: str) -> int:
    """The script has exited: stop whatever it left running (anything with its id)."""
    if not run_id:
        return 0
    leftovers = [p for p in _mine() if _run_id(p) == run_id]
    return _stop(leftovers) if leftovers else 0


def sweep() -> int:
    """Stop headless browsers whose script is gone. Returns how many processes were stopped."""
    now = time.time()
    by_run: dict[str, list[tuple[psutil.Process, bool]]] = {}
    untagged: list[psutil.Process] = []
    for p in _mine():
        cmd = _cmdline(p)
        browser = _is_browser(p, cmd)
        rid = _run_id(p)
        if rid:
            by_run.setdefault(rid, []).append((p, browser))
        elif (browser and now - (p.info.get("create_time") or now) > LEGACY_MAX_AGE
              and _under_headless(p, cmd)):
            untagged.append(p)
    victims: list[psutil.Process] = list(untagged)
    for rid, procs in by_run.items():
        script_alive = any(not browser for _, browser in procs)
        if script_alive:
            continue                                  # the run is still going: leave its browser alone
        for p, browser in procs:
            if browser and now - (p.info.get("create_time") or now) > GRACE_SECONDS:
                victims.append(p)
    return _stop(victims) if victims else 0
