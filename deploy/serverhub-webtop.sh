#!/usr/bin/env bash
# ============================================================
# ServerHub — "Web Browser" app: a real Firefox desktop streamed over noVNC.
# Supervisor runs this as one foreground process (websockify); the virtual
# display, window manager, browser and VNC server run in the background and
# are torn down together (the app program uses stopasgroup/killasgroup).
#
# Usage: serverhub-webtop <port>
# ============================================================
set -u

PORT="${1:-8999}"
export DISPLAY=:99
export HOME="${HOME:-/root}"

# Clean any stragglers from a previous run
pkill -f "Xvfb :99" 2>/dev/null || true
pkill -f "x11vnc.*5901" 2>/dev/null || true
pkill -f "chrome" 2>/dev/null || true
sleep 1

# Virtual display
Xvfb :99 -screen 0 1360x768x24 -nolisten tcp &
sleep 2

# Lightweight window manager + the browser (Chrome needs --no-sandbox as root)
fluxbox >/dev/null 2>&1 &
sleep 1
google-chrome --no-sandbox --disable-gpu --no-first-run --no-default-browser-check \
  --user-data-dir=/tmp/webtop-chrome --start-maximized about:blank >/dev/null 2>&1 &

# VNC server bound to localhost, exposed to the browser via noVNC/websockify
x11vnc -display :99 -forever -shared -nopw -rfbport 5901 -localhost >/dev/null 2>&1 &
sleep 1

# Foreground: serves the noVNC web client on PORT and proxies to the VNC server
exec websockify --web=/usr/share/novnc 127.0.0.1:"$PORT" 127.0.0.1:5901
