#!/usr/bin/env bash
# ============================================================
# ServerHub — create a per-project virtualenv for a Streamlit dashboard.
#
# Why: dashboards need their OWN dependencies. The newest Streamlit pulls a
# Starlette version that conflicts with the panel's FastAPI in the shared venv,
# so running a dashboard from /srv/serverhub/venv fails to start. A dedicated
# venv per project avoids this completely.
#
# Usage (run as root / with sudo):
#   sudo bash deploy/dashboard-venv.sh <project-name> [extra pip packages...]
#
# Examples:
#   sudo bash deploy/dashboard-venv.sh operations
#   sudo bash deploy/dashboard-venv.sh finance plotly-express seaborn
#
# After this, just click "Start" on the dashboard in the panel — the panel
# regenerates the supervisor config to use this venv automatically.
# ============================================================
set -euo pipefail

PANEL_USER="serverhub"
PROJECTS_ROOT="/srv/projects"

if [ $# -lt 1 ]; then
  echo "Usage: sudo bash deploy/dashboard-venv.sh <project-name> [extra pip packages...]" >&2
  exit 1
fi

PROJECT="$1"; shift
EXTRA_PKGS="$*"
PROJ_DIR="$PROJECTS_ROOT/$PROJECT"
VENV="$PROJ_DIR/venv"

if [ ! -d "$PROJ_DIR" ]; then
  echo "ERROR: project '$PROJECT' not found at $PROJ_DIR" >&2
  echo "       Create the project in the panel first." >&2
  exit 1
fi

# Standard libraries a typical dashboard needs. xlrd is required to read old
# .xls files (openpyxl only handles .xlsx). Add anything else as extra args.
BASE_PKGS="streamlit streamlit-autorefresh plotly pandas openpyxl xlrd"

echo "==> Creating venv at $VENV"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip

echo "==> Installing dashboard dependencies"
echo "    base : $BASE_PKGS"
[ -n "$EXTRA_PKGS" ] && echo "    extra: $EXTRA_PKGS"
# shellcheck disable=SC2086
"$VENV/bin/pip" install $BASE_PKGS $EXTRA_PKGS

# If the project has a requirements.txt (in code/ or its root), install it too
for req in "$PROJ_DIR/requirements.txt" "$PROJ_DIR/code/requirements.txt"; do
  if [ -f "$req" ]; then
    echo "==> Installing from $req"
    "$VENV/bin/pip" install -r "$req"
  fi
done

echo "==> Fixing ownership"
chown -R "$PANEL_USER:$PANEL_USER" "$VENV"

echo
echo "============================================================"
echo " Dashboard venv ready: $VENV"
echo " Streamlit: $("$VENV/bin/streamlit" --version 2>/dev/null || echo '?')"
echo
echo " Next: in the panel, open the project's Dashboard tab and click Start."
echo " (The panel auto-points supervisor at this venv on Start.)"
echo "============================================================"
