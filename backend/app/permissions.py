"""
Per-tab access control for non-admin users.

Each panel tab has a key. A non-admin user may only reach the tabs whose keys
are in their `permissions` string. Admins bypass everything. Enforcement is
centralised: the HTTP middleware (main.py) maps a request path to its tab and
checks it; WebSocket handlers call `user_can_tab` via authenticate_websocket.
"""
from __future__ import annotations

import re

# Canonical tabs (key, label) — must match the frontend nav order.
TABS: list[tuple[str, str]] = [
    ("dashboard", "Dashboard"),
    ("projects", "Projects"),
    ("websites", "Websites"),
    ("proxies", "Proxies"),
    ("apps", "Apps"),
    ("shopify", "Shopify Apps"),
    ("docker", "Docker"),
    ("terminal", "Terminal"),
    ("logs", "Logs"),
    ("files", "Files"),
    ("databases", "Databases"),
    ("nginx", "Nginx"),
    ("server", "Server"),
    ("settings", "Settings"),
]
TAB_KEYS = [k for k, _ in TABS]

# Request path prefix → required tab (checked longest-prefix-first).
_PREFIX_TAB: list[tuple[str, str]] = [
    ("/api/scripts", "projects"),
    ("/api/schedules", "projects"),
    ("/api/projects", "projects"),
    ("/ws/script", "projects"),
    ("/ws/pipeline", "projects"),
    ("/api/websites", "websites"),
    ("/api/proxies", "proxies"),
    ("/api/apps", "apps"),
    ("/ws/apps", "apps"),
    ("/api/shopify-apps", "shopify"),
    ("/api/onedrive", "apps"),
    ("/api/docker", "docker"),
    ("/ws/docker", "docker"),
    ("/api/terminal", "terminal"),
    ("/ws/terminal", "terminal"),
    ("/api/logs", "logs"),
    ("/ws/logs", "logs"),
    ("/api/files", "files"),
    ("/api/databases", "databases"),
    ("/api/nginx", "nginx"),
    ("/api/server", "server"),
    ("/ws/apt", "server"),
    ("/api/settings", "settings"),
    ("/ws/settings", "settings"),
]
# Longest prefix first so e.g. /api/scripts wins before any shorter match.
_PREFIX_TAB.sort(key=lambda x: len(x[0]), reverse=True)

# Read-only GET endpoints any authenticated user may hit (the Dashboard landing
# page needs server stats). Exact path match. Project/website lists are NOT
# here: the Dashboard only shows them to users who hold those tabs.
_ALLOW_ANY_GET = {"/api/server/stats"}


def parse_permissions(raw: str | None) -> list[str]:
    """Comma string -> ordered list of valid tab keys."""
    if not raw:
        return []
    have = {x.strip() for x in raw.split(",")}
    return [k for k in TAB_KEYS if k in have]


def serialize_permissions(perms) -> str:
    """List -> canonical comma string (valid keys only, in display order)."""
    have = set(perms or [])
    return ",".join(k for k in TAB_KEYS if k in have)


def required_tab(path: str) -> str | None:
    """The tab a path belongs to, or None when no specific tab is required."""
    for prefix, tab in _PREFIX_TAB:
        if path == prefix or path.startswith(prefix + "/"):
            return tab
    return None


def user_can_tab(user, tab: str) -> bool:
    if getattr(user, "is_admin", False):
        return True
    return tab in parse_permissions(getattr(user, "permissions", ""))


def user_can(user, path: str, method: str) -> bool:
    """Whether `user` may make `method path`."""
    if getattr(user, "is_admin", False):
        return True
    if method == "GET" and path in _ALLOW_ANY_GET:
        return True
    tab = required_tab(path)
    if tab is None:
        return True
    return user_can_tab(user, tab)


# ---------------------------------------------------------------------------
# Admin-hidden entities: a project/website/app flagged `hidden` is invisible
# to non-admins. List endpoints filter them out; this maps a request path to
# the entity it addresses so the middleware can block direct access by id
# (including via a hidden project's scripts and schedules).
# ---------------------------------------------------------------------------
_HIDDEN_PATHS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^/api/projects/(\d+)(?:/|$)"), "project"),
    (re.compile(r"^/api/websites/(\d+)(?:/|$)"), "website"),
    (re.compile(r"^/api/apps/(\d+)(?:/|$)"), "app"),
    (re.compile(r"^/api/scripts/(\d+)(?:/|$)"), "script"),
    (re.compile(r"^/api/schedules/(\d+)(?:/|$)"), "schedule"),
]


def targets_hidden_entity(db, path: str) -> bool:
    """True when `path` addresses an admin-hidden project/website/app
    (directly, or through one of a hidden project's scripts/schedules)."""
    from .models import App, Project, Schedule, Script, Website

    for pattern, kind in _HIDDEN_PATHS:
        match = pattern.match(path)
        if not match:
            continue
        entity_id = int(match.group(1))
        if kind == "project":
            row = db.get(Project, entity_id)
        elif kind == "website":
            row = db.get(Website, entity_id)
        elif kind == "app":
            row = db.get(App, entity_id)
        elif kind == "script":
            script = db.get(Script, entity_id)
            row = script.project if script else None
        else:  # schedule → script → project
            schedule = db.get(Schedule, entity_id)
            script = db.get(Script, schedule.script_id) if schedule else None
            row = script.project if script else None
        return bool(row is not None and getattr(row, "hidden", False))
    return False


def hidden_for(user, entity) -> bool:
    """True when `entity` is admin-hidden and `user` isn't an admin.
    (WebSocket handlers use this after fetching their entity.)"""
    return bool(entity is not None and getattr(entity, "hidden", False)
                and not getattr(user, "is_admin", False))
