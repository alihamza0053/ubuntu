"""
Connection details of a linked PostgreSQL database, handed to a project's or
website's code as environment variables.

    DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:<port>/<db>   (port 5432 unless taken)
    PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD   (libpq's standard
    names: psql, psycopg, SQLAlchemy and pandas pick them up with no config)

They live in /srv/serverhub/dbenv/<kind>-<name>.env (mode 600, panel-owned) —
never inside a project or website folder, so nothing can serve them over HTTP
and no other project's code can read them. Supervisor programs (dashboard,
api.py, Python websites) and script runs get them in their environment.
"""
import os
import re
from pathlib import Path

from ..config import settings

ENV_DIR = settings.PANEL_ROOT / "dbenv"
KEYS = ("DATABASE_URL", "PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")


def env_path(kind: str, name: str) -> Path:
    if kind not in ("project", "website") or not re.fullmatch(r"[A-Za-z0-9_.-]+", name or ""):
        raise ValueError("bad link target")
    return ENV_DIR / f"{kind}-{name}.env"


def write(kind: str, name: str, database: str, user: str, password: str, port: int = 5432) -> None:
    values = {
        "DATABASE_URL": f"postgresql://{user}:{password}@127.0.0.1:{port}/{database}",
        "PGHOST": "127.0.0.1", "PGPORT": str(port),
        "PGDATABASE": database, "PGUSER": user, "PGPASSWORD": password,
    }
    ENV_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(ENV_DIR, 0o700)
    path = env_path(kind, name)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("".join(f"{k}={v}\n" for k, v in values.items()))
    os.replace(tmp, path)


def remove(kind: str, name: str) -> None:
    try:
        env_path(kind, name).unlink()
    except (OSError, ValueError):
        pass


def read(kind: str, name: str) -> dict[str, str]:
    """The variables for a project/website ({} when nothing is linked)."""
    try:
        text = env_path(kind, name).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in KEYS:
            out[key] = value
    return out


def supervisor_env(kind: str, name: str) -> str:
    """Extra `,KEY="value"` pairs for a supervisor `environment=` line ('' when unlinked).

    Passwords are generated from [A-Za-z0-9] only, so nothing here needs
    escaping; '%' would be doubled for supervisor's interpolation anyway.
    """
    return "".join(f',{k}="{v.replace("%", "%%")}"' for k, v in read(kind, name).items())
