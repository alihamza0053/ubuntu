"""
Path-safety helpers.

Every file operation that involves a user-supplied path MUST go through
safe_join / ensure_within so a crafted path like "../../etc/passwd" can
never escape the intended root directory.
"""
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
        settings.SHOPIFY_APPS_ROOT.resolve(),
    ]


def ensure_in_allowed_roots(candidate: Path) -> Path:
    """Verify an absolute path is inside one of the panel-managed roots."""
    resolved = candidate.resolve()
    for root in allowed_roots():
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
