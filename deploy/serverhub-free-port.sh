#!/usr/bin/env bash
# ServerHub — free a dashboard port held by a leftover process (runs as root via
# a single sudoers rule). Installed to $PANEL_ROOT/bin/serverhub-free-port.
#
# Usage: serverhub-free-port <port>
#
# Why: when supervisord is restarted/reloaded, a dashboard it started can survive
# as an orphan. It keeps serving the site (the URL still works) but holds the
# port, so every Start from the panel dies with "spawn error / Exited too
# quickly". This stops ONLY such leftovers:
#   * something listening on <port> (a dashboard port, never the panel's / < 1024)
#   * that is a dashboard server: streamlit, gunicorn or uvicorn
#   * that supervisord is NOT managing right now (its parent isn't supervisord)
# Anything else on the port is reported and left alone.
set -u

PORT="${1:-}"
PANEL_PORT="${PANEL_PORT:-8765}"
case "$PORT" in ''|*[!0-9]*) echo "usage: serverhub-free-port <port>" >&2; exit 2 ;; esac
if [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ] || [ "$PORT" = "$PANEL_PORT" ]; then
  echo "refusing port $PORT" >&2; exit 2
fi

listeners() {   # PIDs listening on the port
  ss -Hltnp "sport = :$PORT" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u
}

PIDS=$(listeners)
if [ -z "$PIDS" ]; then
  echo "port $PORT is free"; exit 0
fi

TARGETS=""
for pid in $PIDS; do
  cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
  ppid=$(awk '{print $4}' "/proc/$pid/stat" 2>/dev/null)
  parent=$(cat "/proc/$ppid/comm" 2>/dev/null)
  # gunicorn/uvicorn workers' parent is their own master — judge by the master.
  if [ "$parent" != "supervisord" ] && echo "$parent" | grep -qE 'gunicorn|uvicorn|python'; then
    pparent=$(cat "/proc/$(awk '{print $4}' "/proc/$ppid/stat" 2>/dev/null)/comm" 2>/dev/null)
    [ "$pparent" = "supervisord" ] && parent="supervisord"
  fi
  if ! echo "$cmd" | grep -qE 'streamlit|gunicorn|uvicorn'; then
    echo "left alone: pid $pid is not a dashboard server ($cmd)"; continue
  fi
  if [ "$parent" = "supervisord" ]; then
    echo "left alone: pid $pid is managed by supervisor ($cmd)"; continue
  fi
  echo "stopping leftover pid $pid: $cmd"
  TARGETS="$TARGETS $pid"
done

[ -z "$TARGETS" ] && exit 1
kill -TERM $TARGETS 2>/dev/null
for _ in 1 2 3 4 5 6 7 8 9 10; do
  [ -z "$(listeners)" ] && { echo "port $PORT is free"; exit 0; }
  sleep 0.5
done
kill -KILL $TARGETS 2>/dev/null
sleep 1
[ -z "$(listeners)" ] && { echo "port $PORT is free (forced)"; exit 0; }
echo "port $PORT is still in use"; exit 1
