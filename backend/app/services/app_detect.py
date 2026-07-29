"""
Work out how a folder of Python code wants to be served.

One implementation shared by both places the panel runs user code:
  * Websites → "python" type  (webapp_service)
  * Projects → dashboard/     (supervisor_service)

It reads the source rather than importing it — importing untrusted code to
inspect it would execute it, and a broken file would take the panel down.

Recognised frameworks:
  streamlit — `import streamlit` (run by the streamlit CLI: no import target)
  flask     — `x = Flask(...)`, or a `create_app()`/`make_app()` factory
  dash      — `x = Dash(...)`; served as flask via its `.server` attribute
  fastapi   — `x = FastAPI(...)`

It also reports `blocking_run`: a module-level `app.run(...)` outside an
`if __name__ == "__main__":` guard. That line starts Flask's development
server the moment anything imports the file, which breaks every way the panel
runs it — gunicorn hangs on the import, and `streamlit run` raises
"signal only works in main thread of the main interpreter" because Streamlit
executes scripts on a worker thread.
"""
import os
import re
from pathlib import Path

# Directories that never hold the entrypoint, and that we must not walk into:
# a project's own venv holds tens of thousands of .py files.
SKIP_DIRS = {"venv", ".venv", "env", "node_modules", "__pycache__", ".git",
             "static", "staticfiles", "dist", "build", "migrations", "tests",
             "logs", ".idea", ".vscode"}

# Conventional entrypoint names, best guess first.
PREFERRED = ["app.py", "wsgi.py", "application.py", "main.py", "app_server.py",
             "server.py", "run.py", "dashboard.py", "asgi.py", "streamlit_app.py"]

_FLASK_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*Flask\s*\(", re.M)
_FASTAPI_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*FastAPI\s*\(", re.M)
_DASH_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(?:dash\.)?Dash\s*\(", re.M)
_FACTORY_RE = re.compile(r"^\s*def\s+(create_app|make_app)\s*\(", re.M)
_STREAMLIT_RE = re.compile(r"^\s*(?:import\s+streamlit|from\s+streamlit\b)", re.M)

# A `.run(...)` / `.run_server(...)` at column 0 — i.e. NOT indented inside an
# `if __name__ == "__main__":` guard, so it fires on import.
_BLOCKING_RUN_RE = re.compile(r"^([A-Za-z_]\w*)\.run(?:_server)?\s*\(.*$", re.M)

MAX_SCAN_BYTES = 2 * 1024 * 1024      # don't read giant data files
MAX_SCAN_DEPTH = 2                    # root + two levels is plenty


def module_path(root: Path, file: Path) -> str:
    """`/srv/websites/x/pkg/app.py` → `pkg.app` (a gunicorn/uvicorn import path)."""
    return ".".join(file.relative_to(root).with_suffix("").parts)


def candidate_files(root: Path) -> list[Path]:
    """
    Python files worth scanning, conventional entrypoints first.

    Walks manually rather than with rglob so SKIP_DIRS are pruned instead of
    merely filtered out after being descended into.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        depth = len(here.relative_to(root).parts)
        if depth >= MAX_SCAN_DEPTH:
            dirnames[:] = []            # deep enough — don't go further
        else:
            dirnames[:] = [d for d in dirnames
                           if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = here / filename
            try:
                if path.stat().st_size > MAX_SCAN_BYTES:
                    continue
            except OSError:
                continue
            found.append(path)

    def rank(p: Path) -> tuple[int, int, str]:
        name_rank = PREFERRED.index(p.name) if p.name in PREFERRED else len(PREFERRED)
        return (len(p.relative_to(root).parts) - 1, name_rank, p.name)

    return sorted(found, key=rank)


def detect(root: Path, allowed: tuple[str, ...] = ("streamlit", "flask", "fastapi")
           ) -> dict | None:
    """
    Identify the app in `root`.

    Returns {framework, module, variable, target, file, blocking_run} —
    `target` is the "module:variable" import path servers want, and is None for
    Streamlit, which is handed a file path instead. `blocking_run` is the
    offending source line when the file calls `.run()` at import time, else
    None. Returns None when nothing matches.

    `allowed` restricts which frameworks count: the Websites section passes
    ("flask", "fastapi") because a Streamlit app there has no way to run.
    """
    if not root.is_dir():
        return None

    factory_hit: dict | None = None

    for path in candidate_files(root):
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        rel = str(path.relative_to(root))
        module = module_path(root, path)
        blocking = _blocking_run(source)

        def hit(framework: str, variable: str | None, target: str | None) -> dict:
            return {"framework": framework, "module": module, "variable": variable,
                    "target": target, "file": rel, "blocking_run": blocking}

        # Streamlit first: a Streamlit script may also build a Flask app for a
        # side endpoint, but `streamlit run` is what the author meant.
        if "streamlit" in allowed and _STREAMLIT_RE.search(source):
            return hit("streamlit", None, None)

        # Dash before Flask: a Dash app owns a Flask server internally and is
        # served through `app.server`, which gunicorn resolves as an attribute.
        if "flask" in allowed:
            match = _DASH_RE.search(source)
            if match:
                variable = f"{match.group(1)}.server"
                return hit("flask", variable, f"{module}:{variable}")

        for framework, regex in (("flask", _FLASK_RE), ("fastapi", _FASTAPI_RE)):
            if framework not in allowed:
                continue
            match = regex.search(source)
            if match:
                return hit(framework, match.group(1), f"{module}:{match.group(1)}")

        # An app factory only counts if nothing exports a module-level app.
        if "flask" in allowed and factory_hit is None and "Flask" in source:
            match = _FACTORY_RE.search(source)
            if match:
                variable = f"{match.group(1)}()"
                factory_hit = hit("flask", variable, f"{module}:{variable}")

    return factory_hit


def _blocking_run(source: str) -> str | None:
    """The un-indented `app.run(...)` line that would fire on import, if any."""
    match = _BLOCKING_RUN_RE.search(source)
    return match.group(0).strip() if match else None


def blocking_run_warning(found: dict | None) -> str | None:
    """A ready-to-show explanation of a `blocking_run`, or None if all is well."""
    if not found or not found.get("blocking_run"):
        return None
    return (
        f"⚠ {found['file']} calls {found['blocking_run']} at the top level, so it "
        f"starts Flask's development server as soon as the file is imported. "
        f"That breaks the app here: under gunicorn the worker hangs on the import, "
        f"and under Streamlit it raises \"signal only works in main thread\". "
        f"Indent that line under `if __name__ == \"__main__\":` so only "
        f"`python {found['file']}` runs the dev server."
    )
