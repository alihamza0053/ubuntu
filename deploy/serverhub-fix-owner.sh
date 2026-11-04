#!/usr/bin/env bash
# ServerHub — hand root-owned files of ONE project/website to the panel user
# (runs as root via a single sudoers rule). Installed to
# $PANEL_ROOT/bin/serverhub-fix-owner by deploy/install.sh|update.sh.
#
# Usage: serverhub-fix-owner <project|website> <name>
#
# Dashboards that ran as root left root-owned caches and data behind. Just
# before one starts running as the panel user, its own files are handed over so
# it can keep writing them. Only files owned by root change (PHP upload folders
# may belong to www-data), and nothing outside that one folder is touched.
set -eu

PANEL_USER="${PANEL_USER:-serverhub}"
KIND="${1:-}"
NAME="${2:-}"

case "$KIND" in
  project) BASE=/srv/projects ;;
  website) BASE=/srv/websites ;;
  *) echo "usage: serverhub-fix-owner <project|website> <name>" >&2; exit 2 ;;
esac
case "$NAME" in
  ''|.|..|*[!A-Za-z0-9._-]*) echo "bad name" >&2; exit 2 ;;
esac

DIR="$BASE/$NAME"
[ -d "$DIR" ] && [ ! -L "$DIR" ] || { echo "no such folder: $DIR" >&2; exit 1; }
# -h: change a symlink itself, never what it points at
find "$DIR" -xdev -user root -exec chown -h "$PANEL_USER:$PANEL_USER" {} +
echo "ok"
