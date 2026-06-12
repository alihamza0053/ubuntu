"""
Website deployment helpers: safe zip extraction and optional React build.
"""
import shutil
import zipfile
from pathlib import Path

from fastapi import HTTPException

from ..config import settings
from .streaming import run_command


def website_root(name: str) -> Path:
    return settings.WEBSITES_ROOT / name


def extract_zip(zip_path: Path, dest: Path) -> None:
    """
    Extract an uploaded zip into dest, guarding against Zip-Slip (entries that
    escape the destination via .. or absolute paths).
    """
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            target = (dest / member).resolve()
            if dest.resolve() != target and dest.resolve() not in target.parents:
                raise HTTPException(status_code=400,
                                    detail=f"Unsafe path in zip: {member}")
        zf.extractall(dest)


async def build_react(name: str) -> tuple[int, str]:
    """Run `npm install && npm run build` for a React site (outputs dist/)."""
    root = website_root(name)
    if not (root / "package.json").is_file():
        raise HTTPException(status_code=400,
                            detail="No package.json found — upload the React source first")
    code, out = await run_command(["npm", "install"], cwd=str(root), timeout=600)
    if code != 0:
        return code, out
    code2, out2 = await run_command(["npm", "run", "build"], cwd=str(root), timeout=600)
    return code2, out + "\n" + out2


def reset_folder(name: str) -> Path:
    """Clear and recreate a website folder (used before a fresh upload)."""
    root = website_root(name)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return root
