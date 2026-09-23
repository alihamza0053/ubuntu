"""
Per-project Streamlit virtualenv.

Each project's dashboard runs from its OWN venv at /srv/projects/<name>/venv
(Streamlit pulls a Starlette version that clashes with the panel's FastAPI in
the shared venv). This used to be a manual step (deploy/dashboard-venv.sh);
now the panel builds it automatically in the background when a project is
created, so "Start dashboard" just works.

The panel runs as the `serverhub` user which owns /srv/projects, so no sudo is
needed. Progress is written to the project's logs/venv-setup.log.
"""
import subprocess
import threading
from datetime import datetime

from ..config import settings

# Packages every dashboard typically needs (mirrors deploy/dashboard-venv.sh —
# keep both lists in sync). flask+gunicorn are included so a Flask dashboard can
# be started without a separate install step, the same way streamlit is there
# for a Streamlit one; gunicorn alone only gets as far as ModuleNotFoundError.
# fastapi+uvicorn likewise for a FastAPI dashboard — without them supervisor
# falls back to a bare `uvicorn` that isn't on its PATH: "ERROR (spawn error)".
BASE_PKGS = ["streamlit", "streamlit-autorefresh", "plotly", "pandas",
             "openpyxl", "xlrd", "flask", "gunicorn", "fastapi", "uvicorn"]

# What each dashboard framework needs in the venv to be spawnable at all.
FRAMEWORK_PKGS = {
    "streamlit": ["streamlit"],
    "flask": ["flask", "gunicorn"],
    "fastapi": ["fastapi", "uvicorn"],
}

_building: set[str] = set()
_lock = threading.Lock()


def venv_dir(name: str):
    return settings.PROJECTS_ROOT / name / "venv"


def streamlit_bin(name: str):
    return venv_dir(name) / "bin" / "streamlit"


def is_ready(name: str) -> bool:
    return streamlit_bin(name).exists()


def is_building(name: str) -> bool:
    with _lock:
        return name in _building


def _log(name: str, line: str) -> None:
    path = settings.PROJECTS_ROOT / name / "logs" / "venv-setup.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {line}\n")


def _run(cmd, timeout=1800):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _build(name: str, extra) -> None:
    vdir = venv_dir(name)
    try:
        _log(name, f"creating virtualenv at {vdir}")
        r = _run(["python3", "-m", "venv", str(vdir)], timeout=300)
        if r.returncode != 0:
            _log(name, "venv creation FAILED: " + (r.stderr or r.stdout)[:1000])
            return

        pip = str(vdir / "bin" / "pip")
        _run([pip, "install", "--upgrade", "pip"], timeout=300)

        pkgs = BASE_PKGS + list(extra or [])
        _log(name, "installing: " + " ".join(pkgs))
        r = _run([pip, "install", *pkgs])
        if r.returncode != 0:
            _log(name, "package install FAILED:\n" + (r.stderr or r.stdout)[:2000])
        else:
            _log(name, "base packages installed")

        # Honour a project requirements.txt if present
        for req in requirement_files(name):
            if req.is_file():
                _log(name, f"installing from {req}")
                _run([pip, "install", "-r", str(req)])

        _log(name, "✓ environment ready" if is_ready(name)
                   else "finished but streamlit not found — check the log above")
    except subprocess.TimeoutExpired:
        _log(name, "TIMED OUT building the environment")
    except Exception as exc:  # noqa: BLE001
        _log(name, f"error: {exc}")
    finally:
        with _lock:
            _building.discard(name)


def requirement_files(name: str) -> list:
    """requirements.txt files the project ships (root, code/, dashboard/)."""
    root = settings.PROJECTS_ROOT / name
    return [root / "requirements.txt", root / "code" / "requirements.txt",
            root / "dashboard" / "requirements.txt"]


def has_python(name: str) -> bool:
    """True once `python -m venv` has produced a usable interpreter + pip."""
    return (venv_dir(name) / "bin" / "pip").exists()


def install_packages(name: str, pkgs) -> tuple[bool, str]:
    """
    Synchronously pip-install `pkgs` into an existing project venv.

    Used when a dashboard is started with a framework whose server binary the
    venv lacks (e.g. a venv built before uvicorn was in BASE_PKGS).
    Returns (ok, pip output tail).
    """
    pip = str(venv_dir(name) / "bin" / "pip")
    _log(name, "installing for dashboard start: " + " ".join(pkgs))
    try:
        r = _run([pip, "install", *pkgs], timeout=600)
    except subprocess.TimeoutExpired:
        _log(name, "TIMED OUT installing " + " ".join(pkgs))
        return False, "pip install timed out"
    out = (r.stderr or r.stdout)[-2000:]
    _log(name, "installed" if r.returncode == 0 else "install FAILED:\n" + out)
    return r.returncode == 0, out


def ensure_async(name: str, extra=None) -> bool:
    """
    Start building the project's venv in the background if it isn't ready and
    isn't already building. Returns True if a build was started.
    """
    if is_ready(name):
        return False
    with _lock:
        if name in _building:
            return False
        _building.add(name)
    threading.Thread(target=_build, args=(name, extra), daemon=True).start()
    return True


def status(name: str) -> str:
    """READY / BUILDING / MISSING — for the UI."""
    if is_ready(name):
        return "READY"
    if is_building(name):
        return "BUILDING"
    return "MISSING"
