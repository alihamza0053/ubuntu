#!/usr/bin/env bash
# ============================================================
# ServerHub — "Linux Desktop (XFCE + KasmVNC)" app.
#
# A full, fast XFCE desktop streamed to the browser via KasmVNC (no Docker,
# no extra UDP ports — plain HTTP/WebSocket that nginx fronts with SSL).
#
# Supervisor runs this as one foreground process; the KasmVNC X server + the
# XFCE session run under the unprivileged `kasm` user and are torn down on stop
# (the app program uses stopasgroup/killasgroup, plus the trap below).
#
# The web login password comes from the panel via the PASSWORD env var
# (use_password app) and is (re)applied on every start.
#
# Usage: serverhub-xfce-desktop <port>
# ============================================================
set -u

PORT="${1:-8700}"
U=kasm
H="/home/$U"
DISPLAY_NUM=":1"
PW="${PASSWORD:-changeme}"

asuser() { runuser -u "$U" -- env HOME="$H" "$@"; }

cleanup() {
  asuser vncserver -kill "$DISPLAY_NUM" >/dev/null 2>&1 || true
  pkill -u "$U" -f "Xvnc $DISPLAY_NUM" 2>/dev/null || true
  pkill -u "$U" xfce4-session 2>/dev/null || true
  exit 0
}
trap cleanup TERM INT

# 0. KasmVNC must be installed (the `vncserver` wrapper). Fail loudly if not —
#    otherwise the desktop never binds and nginx returns 502.
if ! command -v vncserver >/dev/null 2>&1; then
  echo "ERROR: KasmVNC ('vncserver') is not installed. Re-install the app, or run:" >&2
  echo "  sudo bash /opt/serverhub-src/deploy/serverhub-app-install.sh xfce-desktop" >&2
  exit 1
fi

# 1. Apply the web password the panel set (KasmVNC reads ~/.kasmpasswd).
printf '%s\n%s\n' "$PW" "$PW" | asuser kasmvncpasswd -u "$U" -w >/dev/null 2>&1 || true

# 2. Clear any stale session/lock from a previous run.
asuser vncserver -kill "$DISPLAY_NUM" >/dev/null 2>&1 || true
pkill -u "$U" -f "Xvnc $DISPLAY_NUM" 2>/dev/null || true
rm -f /tmp/.X1-lock "/tmp/.X11-unix/X1" 2>/dev/null || true
sleep 1

# 3. Start KasmVNC (the X server + web server) bound to localhost on PORT.
#    SSL is disabled in ~/.vnc/kasmvnc.yaml (the installer) — nginx adds HTTPS.
asuser vncserver "$DISPLAY_NUM" \
  -websocketPort "$PORT" -interface 127.0.0.1 \
  -depth 24 -geometry 1440x810 >/tmp/serverhub-kasm.log 2>&1 || true

sleep 2

# 4. Verify KasmVNC actually bound the port — if not, surface the logs and exit
#    non-zero so Supervisor shows FATAL (instead of a fake "RUNNING").
bound=""
for _ in $(seq 1 15); do
  if ss -ltn 2>/dev/null | grep -q ":${PORT} "; then bound=1; break; fi
  sleep 1
done
if [ -z "$bound" ]; then
  echo "ERROR: KasmVNC did not start listening on 127.0.0.1:${PORT}." >&2
  echo "----- /tmp/serverhub-kasm.log -----" >&2
  cat /tmp/serverhub-kasm.log >&2 2>/dev/null || true
  echo "----- KasmVNC session log -----" >&2
  cat "$H/.vnc/"*"${DISPLAY_NUM}.log" >&2 2>/dev/null || true
  asuser vncserver -kill "$DISPLAY_NUM" >/dev/null 2>&1 || true
  exit 1
fi

# 5. Foreground: follow the session log so Supervisor tracks a live process and
#    forwards signals; the trap above cleans up the desktop on stop.
LOG="$(ls -1 "$H/.vnc/"*"${DISPLAY_NUM}.log" 2>/dev/null | head -1)"
exec tail -F "${LOG:-/tmp/serverhub-kasm.log}"
