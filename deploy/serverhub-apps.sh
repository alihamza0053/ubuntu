#!/usr/bin/env bash
# ServerHub — Apps installer helper (runs as root via a single sudoers rule).
# Installed to $PANEL_ROOT/bin/serverhub-apps by deploy/install.sh|update.sh.
#
# Usage: serverhub-apps <install|remove|probe> <chromium|brave|n8n>
#
# Only those three app names are accepted and every package list is hard-coded
# below, so nothing the panel passes in can turn into an arbitrary apt/npm
# command — the sudoers rule stays as narrow as the cleanup helper's.
#
# `install` finishes by writing $APPS_ROOT/<app>/install.env, which the panel
# reads to build the run script:
#     bin=…          absolute path of the executable
#     snap=true|false  snap builds are confined to the real $HOME
#     home=…         data/profile directory to run the app with
#     novnc=…        noVNC web root (desktop apps only)
set -u

APPS_ROOT="${APPS_ROOT:-/srv/apps}"
PANEL_USER="${PANEL_USER:-serverhub}"
PANEL_HOME="$(getent passwd "$PANEL_USER" | cut -d: -f6)"
PANEL_HOME="${PANEL_HOME:-/home/$PANEL_USER}"
export DEBIAN_FRONTEND=noninteractive

# Packages a browser needs to run on a headless box and be viewed in a browser:
# a virtual X display, a tiny window manager, a VNC server and the noVNC bridge.
DESKTOP_PKGS="xvfb x11vnc novnc websockify openbox x11-utils xdg-utils dbus-x11
              fonts-liberation procps"

die() { echo "ERROR: $*" >&2; exit 1; }

app_dir() { echo "$APPS_ROOT/$1"; }

# Create the app's directories and hand them to the panel user, which is what
# actually runs the app afterwards.
prepare_dirs() {
  local dir home
  dir="$(app_dir "$1")"
  home="${2:-$dir/home}"
  mkdir -p "$dir/logs" "$home"
  chown -R "$PANEL_USER:$PANEL_USER" "$dir" 2>/dev/null || true
  chown -R "$PANEL_USER:$PANEL_USER" "$home" 2>/dev/null || true
}

write_env() {  # write_env <app> <key=value>…
  local dir file
  dir="$(app_dir "$1")"; shift
  file="$dir/install.env"
  : > "$file"
  for pair in "$@"; do echo "$pair" >> "$file"; done
  chown "$PANEL_USER:$PANEL_USER" "$file"
}

apt_update_once() {
  if [ -z "${_APT_UPDATED:-}" ]; then
    echo "── apt-get update ──"
    apt-get update -qq || die "apt-get update failed"
    _APT_UPDATED=1
  fi
}

install_desktop_stack() {
  echo "── installing the headless-desktop stack ──"
  apt_update_once
  # shellcheck disable=SC2086
  apt-get install -y $DESKTOP_PKGS || die "could not install the desktop stack"
  echo "✓ Xvfb + x11vnc + noVNC ready"
}

novnc_root() {
  for d in /usr/share/novnc /usr/share/webapps/novnc; do
    [ -d "$d" ] && { echo "$d"; return; }
  done
  echo ""
}

# ---------------------------------------------------------------------------
# Brave — official APT repository. No snap involved, so it runs happily with a
# data directory under /srv.
# ---------------------------------------------------------------------------
install_brave() {
  install_desktop_stack
  if ! command -v brave-browser >/dev/null 2>&1; then
    echo "── adding the Brave APT repository ──"
    apt_update_once
    apt-get install -y curl ca-certificates gnupg || die "could not install curl/gnupg"
    curl -fsSL https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg \
      -o /usr/share/keyrings/brave-browser-archive-keyring.gpg \
      || die "could not download the Brave signing key"
    chmod 0644 /usr/share/keyrings/brave-browser-archive-keyring.gpg
    echo "deb [signed-by=/usr/share/keyrings/brave-browser-archive-keyring.gpg] https://brave-browser-apt-release.s3.brave.com/ stable main" \
      > /etc/apt/sources.list.d/brave-browser-release.list
    apt-get update -qq || die "apt-get update failed after adding the Brave repo"
    echo "── installing brave-browser ──"
    apt-get install -y brave-browser || die "could not install brave-browser"
  else
    echo "brave-browser is already installed"
  fi

  local bin home
  bin="$(command -v brave-browser)"
  home="$(app_dir brave)/home"
  prepare_dirs brave "$home"
  write_env brave "bin=$bin" "snap=false" "home=$home" "novnc=$(novnc_root)"
  echo "✓ Brave installed: $bin"
}

# ---------------------------------------------------------------------------
# Chromium — apt where a real .deb exists, otherwise the Ubuntu snap.
#
# The snap is strictly confined: it can only read $HOME of a real user, so a
# snap install is recorded with home=$PANEL_HOME/.serverhub-apps/chromium and
# snap=true, and the panel points --user-data-dir there instead of /srv.
# ---------------------------------------------------------------------------
install_chromium() {
  install_desktop_stack
  local bin="" snap=false home
  bin="$(command -v chromium || command -v chromium-browser || true)"

  if [ -z "$bin" ]; then
    echo "── installing chromium (apt) ──"
    apt_update_once
    if apt-get install -y chromium 2>/dev/null || apt-get install -y chromium-browser 2>/dev/null; then
      bin="$(command -v chromium || command -v chromium-browser || true)"
    fi
  fi

  if [ -z "$bin" ]; then
    echo "── no chromium .deb available — falling back to the snap ──"
    command -v snap >/dev/null 2>&1 || die \
      "chromium is not available as a .deb on this release and snapd is not installed. Install Brave instead, or run: apt-get install -y snapd"
    snap install chromium || die "snap install chromium failed"
    bin="/snap/bin/chromium"
  fi

  # An apt "chromium-browser" on Ubuntu is often just a wrapper that launches
  # the snap — that is confined too, so detect it and treat it as a snap.
  if [ "${bin#/snap/}" != "$bin" ] || grep -qs 'snap' "$bin" 2>/dev/null; then
    snap=true
  fi

  if [ "$snap" = true ]; then
    home="$PANEL_HOME/.serverhub-apps/chromium"
    echo "note: this is a confined snap build — its profile lives in $home"
  else
    home="$(app_dir chromium)/home"
  fi

  prepare_dirs chromium "$home"
  write_env chromium "bin=$bin" "snap=$snap" "home=$home" "novnc=$(novnc_root)"
  echo "✓ Chromium installed: $bin"
}

# ---------------------------------------------------------------------------
# n8n — Node LTS (NodeSource when the distro's node is too old) + npm global.
# ---------------------------------------------------------------------------
install_n8n() {
  local major=0
  if command -v node >/dev/null 2>&1; then
    major="$(node -v 2>/dev/null | sed 's/^v//; s/\..*//')"
    major="${major:-0}"
  fi

  if [ "$major" -lt 18 ]; then
    echo "── installing Node.js 20 LTS (found: ${major:-none}) ──"
    apt_update_once
    apt-get install -y curl ca-certificates || die "could not install curl"
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - || die "NodeSource setup failed"
    apt-get install -y nodejs || die "could not install nodejs"
  else
    echo "Node.js $(node -v) is recent enough"
  fi

  # n8n builds native modules (sqlite3), which needs a toolchain.
  apt_update_once
  apt-get install -y build-essential python3 >/dev/null 2>&1 || true

  echo "── npm install -g n8n (this takes a few minutes) ──"
  npm install -g n8n --unsafe-perm || die "npm install -g n8n failed"

  local bin home
  bin="$(command -v n8n)" || die "n8n installed but is not on PATH"
  home="$(app_dir n8n)/home"
  prepare_dirs n8n "$home"
  write_env n8n "bin=$bin" "snap=false" "home=$home" "novnc="
  echo "✓ n8n installed: $bin ($(n8n --version 2>/dev/null || echo 'version unknown'))"
}

# ---------------------------------------------------------------------------
# Removal — drops the software, never the app's data directory (the panel
# deletes that itself, and only when the user asks for it).
# ---------------------------------------------------------------------------
remove_app() {
  case "$1" in
    brave)
      apt-get purge -y brave-browser >/dev/null 2>&1 || true
      rm -f /etc/apt/sources.list.d/brave-browser-release.list
      ;;
    chromium)
      snap remove chromium >/dev/null 2>&1 || true
      apt-get purge -y chromium chromium-browser >/dev/null 2>&1 || true
      ;;
    n8n)
      npm uninstall -g n8n >/dev/null 2>&1 || true
      ;;
  esac
  rm -f "$(app_dir "$1")/install.env"
  echo "✓ $1 removed (its data directory was left in place)"
}

# ---------------------------------------------------------------------------
# Probe — report whether each app's executable is present, for the UI.
# ---------------------------------------------------------------------------
probe_app() {
  case "$1" in
    brave)    command -v brave-browser >/dev/null 2>&1 && echo "installed=true" || echo "installed=false" ;;
    chromium) { command -v chromium || command -v chromium-browser; } >/dev/null 2>&1 \
                && echo "installed=true" || echo "installed=false" ;;
    n8n)      command -v n8n >/dev/null 2>&1 && echo "installed=true" || echo "installed=false" ;;
  esac
}

# ---------------------------------------------------------------------------

[ "$#" -ge 2 ] || { echo "usage: serverhub-apps <install|remove|probe> <chromium|brave|n8n>" >&2; exit 1; }

ACTION="$1"
APP="$2"

case "$APP" in
  chromium|brave|n8n) ;;
  *) die "unknown app: $APP (expected chromium, brave or n8n)" ;;
esac

mkdir -p "$APPS_ROOT"
chown "$PANEL_USER:$PANEL_USER" "$APPS_ROOT" 2>/dev/null || true

case "$ACTION" in
  install)
    echo "═══ installing $APP ═══"
    case "$APP" in
      brave)    install_brave ;;
      chromium) install_chromium ;;
      n8n)      install_n8n ;;
    esac
    echo "═══ $APP install finished ═══"
    ;;
  remove) remove_app "$APP" ;;
  probe)  probe_app "$APP" ;;
  *) die "unknown action: $ACTION" ;;
esac
