"""
Path-safety helpers.

Every file operation that involves a user-supplied path MUST go through
safe_join / ensure_within so a crafted path like "../../etc/passwd" can
never escape the intended root directory.
"""
import re
from pathlib import Path

from fastapi import HTTPException

from ..config import settings


def ensure_within(root: Path, candidate: Path) -> Path:
    """Resolve `candidate` and verify it lives inside `root`. 400 otherwise."""
    root = root.resolve()
    resolved = candidate.resolve()
    if root != resolved and root not in resolved.parents:
        raise HTTPException(status_code=400, detail="Path escapes its allowed root")
    return resolved


def safe_join(root: Path, *parts: str) -> Path:
    """Join user-supplied path parts onto root, guarding against traversal."""
    candidate = root.joinpath(*parts)
    return ensure_within(root, candidate)


def allowed_roots() -> list[Path]:
    """Roots the editor/file APIs may touch (expanded in later phases)."""
    return [
        settings.PROJECTS_ROOT.resolve(),
        settings.WEBSITES_ROOT.resolve(),
        settings.NGINX_CONFIGS_ROOT.resolve(),
        settings.ONEDRIVE_ROOT.resolve(),
        settings.OPT_ROOT.resolve(),
    ]


def ensure_in_allowed_roots(candidate: Path, user=None) -> Path:
    """
    Verify an absolute path is inside one of the panel-managed roots. Non-admins
    don't get nginx-configs (loaded by root) or /opt (update.sh runs from it as
    root): writing there would be a way to run things as root.
    """
    resolved = candidate.resolve()
    roots = allowed_roots()
    if user is not None and not getattr(user, "is_admin", False):
        roots = [settings.PROJECTS_ROOT.resolve(), settings.WEBSITES_ROOT.resolve(),
                 settings.ONEDRIVE_ROOT.resolve()]
    for root in roots:
        if resolved == root or root in resolved.parents:
            return resolved
    raise HTTPException(
        status_code=400,
        detail="Path is outside panel-managed directories",
    )


def validate_filename(filename: str) -> str:
    """Reject path separators and hidden/odd names in uploaded filenames."""
    name = Path(filename).name  # strips any directory components
    if not name or name.startswith(".") or name != filename:
        raise HTTPException(status_code=400, detail=f"Invalid filename: {filename!r}")
    return name


def validate_extension(filename: str, allowed: set[str]) -> None:
    """Enforce the per-folder upload extension allow-list."""
    ext = Path(filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed here. Allowed: {sorted(allowed)}",
        )


DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")


def validate_domain(domain: str) -> str:
    """A real host name only: it is written into nginx configs that root loads."""
    value = (domain or "").strip().lower()
    if not DOMAIN_RE.match(value):
        raise ValueError("Enter a valid domain, like panel.example.com")
    return value


def validate_command_line(value: str) -> str:
    """One line, no control characters: it is written into a Supervisor config."""
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value or ""):
        raise ValueError("Must be a single line without control characters")
    return value
