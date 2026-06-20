#!/usr/bin/env bash
# ============================================================
# ServerHub — "Linux Desktop (XFCE)" app.
#
# A full XFCE desktop streamed to the browser via the proven Xvfb + x11vnc +
# noVNC stack (the same pipeline the webtop app uses). No Docker, no KasmVNC —
# noVNC authenticates with a simple VNC password over the WebSocket, so it works
# over plain HTTP *and* HTTPS with no secure-cookie login loop.
#
# Supervisor runs websockify in the foreground; the display, XFCE session and
# VNC server run in the background under the unprivileged `kasm` user and are
# torn down on stop (stopasgroup/killasgroup + the trap below).
#
# The VNC password comes from the panel via the PASSWORD env var (use_password
# app) and is (re)applied on every start.
#
# Usage: serverhub-xfce-desktop <port>
# ============================================================
set -u

PORT="${1:-8700}"
U=kasm
H="/home/$U"
DISP=":1"
VNCPORT=5901
PW="${PASSWORD:-changeme}"

asuser() { runuser -u "$U" -- env HOME="$H" DISPLAY="$DISP" "$@"; }

cleanup() {
  pkill -u "$U" -f "Xvfb $DISP" 2>/dev/null || true
  pkill -u "$U" -f "x11vnc.*$VNCPORT" 2>/dev/null || true
  pkill -u "$U" -f "xfce4-session" 2>/dev/null || true
  pkill -u "$U" -f "websockify.*$PORT" 2>/dev/null || true
  exit 0
}
trap cleanup TERM INT

# 0. Clear any stragglers from a previous run.
pkill -u "$U" -f "Xvfb $DISP" 2>/dev/null || true
pkill -u "$U" -f "x11vnc.*$VNCPORT" 2>/dev/null || true
pkill -u "$U" -f "websockify.*$PORT" 2>/dev/null || true
rm -f /tmp/.X1-lock "/tmp/.X11-unix/X1" 2>/dev/null || true
sleep 1

# 1. VNC password file from the panel password.
install -d -o "$U" -g "$U" "$H/.vnc"
asuser x11vnc -storepasswd "$PW" "$H/.vnc/passwd" >/dev/null 2>&1 || true
chown "$U:$U" "$H/.vnc/passwd" 2>/dev/null || true

# 2. Virtual display.
asuser Xvfb "$DISP" -screen 0 1440x810x24 -nolisten tcp >/tmp/serverhub-desktop-x.log 2>&1 &
sleep 2

# 3. Full XFCE desktop session on that display.
asuser dbus-launch --exit-with-session startxfce4 >/tmp/serverhub-desktop-xfce.log 2>&1 &
sleep 2

# 4. Password-protected VNC server bound to localhost.
asuser x11vnc -display "$DISP" -rfbauth "$H/.vnc/passwd" -forever -shared \
  -rfbport "$VNCPORT" -localhost -noxdamage >/tmp/serverhub-desktop-vnc.log 2>&1 &
sleep 1

# 5. Make sure the VNC server actually came up — else fail loudly (FATAL).
up=""
for _ in $(seq 1 15); do
  if ss -ltn 2>/dev/null | grep -q ":${VNCPORT} "; then up=1; break; fi
  sleep 1
done
if [ -z "$up" ]; then
  echo "ERROR: the desktop (Xvfb/x11vnc) did not start. Recent logs:" >&2
  cat /tmp/serverhub-desktop-*.log >&2 2>/dev/null || true
  cleanup
fi

# 6. Foreground: serve the noVNC web client on PORT and proxy to the VNC server.
exec websockify --web=/usr/share/novnc 127.0.0.1:"$PORT" 127.0.0.1:"$VNCPORT"
