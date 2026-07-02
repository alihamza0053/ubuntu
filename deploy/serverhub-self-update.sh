#!/usr/bin/env bash
# ============================================================
# ServerHub self-update launcher.
#
# Run as root via sudo from the panel ("Settings → Updates → Update now").
# It kicks off deploy/update.sh DETACHED (its own session) so that the panel
# restart update.sh performs at the end cannot kill the update half-way
# (the panel's supervisor program uses killasgroup=true).
#
#   serverhub-self-update <SRC_DIR> <LOG_FILE> [extra update.sh args...]
#
# Output of the real update goes to LOG_FILE, which the panel tails live.
# ============================================================
set -euo pipefail

SRC="${1:?source dir required}"; shift
LOG="${1:?log file required}"; shift

if [ "$(id -u)" -ne 0 ]; then
  echo "[self-update] must run as root" >&2
  exit 1
fi

if [ ! -f "$SRC/deploy/update.sh" ]; then
  echo "[self-update] No update.sh found under: $SRC/deploy" >&2
  echo "[self-update] This is the source-code checkout the panel updates from." >&2
  echo "[self-update] Clone/upload the project there, or set the correct path in" >&2
  echo "[self-update] Settings → Updates (UPDATE_SRC in backend/.env)." >&2
  exit 2
fi

mkdir -p "$(dirname "$LOG")"
: > "$LOG"

# Detach into a new session: survives the panel's own restart.
setsid bash "$SRC/deploy/update.sh" "$@" >>"$LOG" 2>&1 </dev/null &

echo "[self-update] launched update from $SRC"
echo "[self-update] log: $LOG"
