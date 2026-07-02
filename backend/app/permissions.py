"""
Per-tab access control for non-admin users.

Each panel tab has a key. A non-admin user may only reach the tabs whose keys
are in their `permissions` string. Admins bypass everything. Enforcement is
centralised: the HTTP middleware (main.py) maps a request path to its tab and
checks it; WebSocket handlers call `user_can_tab` via authenticate_websocket.
"""
from __future__ import annotations

# Canonical tabs (key, label) — must match the frontend nav order.
TABS: list[tuple[str, str]] = [
    ("dashboard", "Dashboard"),
    ("projects", "Projects"),
    ("websites", "Websites"),
    ("proxies", "Proxies"),
    ("apps", "Apps"),
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
# page aggregates these). Exact path match.
_ALLOW_ANY_GET = {"/api/server/stats", "/api/projects", "/api/websites"}


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
