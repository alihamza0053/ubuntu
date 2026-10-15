#!/usr/bin/env bash
# ServerHub — PostgreSQL helper (runs as root via a single sudoers rule).
# Installed to $PANEL_ROOT/bin/serverhub-postgres by deploy/install.sh|update.sh.
#
# Usage: serverhub-postgres <install|configure|status|restart>
#   install    apt install PostgreSQL, then `configure`
#   configure  (re)write the locked-down config below and reload
#   status     installed / running / version (one line each)
#   restart    restart the service (after a config change)
#
# The config this writes:
#   * listens on 127.0.0.1 / ::1 only — never reachable from the internet
#   * every database user may connect ONLY to the database with its own name
#     (pg_hba `sameuser`), with a scram-sha-256 password; anything else is refused
#   * the panel user (serverhub) may act as the postgres admin over the local
#     socket only (peer auth + ident map) — no admin password exists at all
#   * memory/connections sized from this machine's RAM so it can't starve
#     the dashboards, plus timeouts that end stuck queries and idle sessions
set -eu

PANEL_USER="${PANEL_USER:-serverhub}"

pg_version() { ls /etc/postgresql 2>/dev/null | sort -V | tail -1; }
# On Debian/Ubuntu `postgresql.service` is only an umbrella that returns at
# once; the real server is postgresql@<ver>-main.
cluster_unit() { echo "postgresql@$(pg_version)-main"; }

wait_ready() {   # up to 40 s for the server to accept connections
  for _ in $(seq 1 40); do
    pg_isready -q -h /var/run/postgresql 2>/dev/null && return 0
    sleep 1
  done
  return 1
}

show_logs() {
  local ver; ver=$(pg_version)
  echo "--- last PostgreSQL log lines ---"
  tail -n 25 "/var/log/postgresql/postgresql-${ver}-main.log" 2>/dev/null || true
  journalctl -u "$(cluster_unit)" -n 15 --no-pager 2>/dev/null || true
}

start_server() {
  systemctl enable postgresql "$(cluster_unit)" >/dev/null 2>&1 || true
  systemctl restart "$(cluster_unit)" 2>&1 || true
  wait_ready
}

configure() {
  local ver dir ram_mb shared cache maint
  ver=$(pg_version)
  [ -n "$ver" ] || { echo "PostgreSQL is not installed"; exit 1; }
  dir="/etc/postgresql/$ver/main"
  mkdir -p "$dir/conf.d"
  # keep Ubuntu's originals once, to roll back to if our config won't start
  [ -f "$dir/pg_hba.conf.orig" ] || cp -p "$dir/pg_hba.conf" "$dir/pg_hba.conf.orig"
  [ -f "$dir/pg_ident.conf.orig" ] || cp -p "$dir/pg_ident.conf" "$dir/pg_ident.conf.orig"

  ram_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
  shared=$(( ram_mb / 10 ));  [ "$shared" -lt 128 ] && shared=128;  [ "$shared" -gt 2048 ] && shared=2048
  cache=$(( ram_mb / 4 ));    [ "$cache" -lt 256 ] && cache=256
  maint=$(( ram_mb / 32 ));   [ "$maint" -lt 64 ] && maint=64;      [ "$maint" -gt 512 ] && maint=512

  cat > "$dir/conf.d/serverhub.conf" <<EOF
# Written by ServerHub (serverhub-postgres configure) — re-run to regenerate.
listen_addresses = 'localhost'
port = 5432
password_encryption = scram-sha-256
max_connections = 100
superuser_reserved_connections = 3
shared_buffers = ${shared}MB
effective_cache_size = ${cache}MB
maintenance_work_mem = ${maint}MB
work_mem = 8MB
# end stuck work instead of letting it pile up
idle_in_transaction_session_timeout = '10min'
lock_timeout = '1min'
# log slow queries so they can be found
log_min_duration_statement = 3000
EOF

  cat > "$dir/pg_hba.conf" <<'EOF'
# Written by ServerHub (serverhub-postgres configure) — re-run to regenerate.
# TYPE  DATABASE  USER      ADDRESS        METHOD
# admin: only the postgres OS user and the panel user, over the local socket
local   all       postgres                 peer map=serverhub
# every other user: only its OWN database (same name), with a password, from this machine
local   sameuser  all                      scram-sha-256
host    sameuser  all       127.0.0.1/32   scram-sha-256
host    sameuser  all       ::1/128        scram-sha-256
# anything else is refused
local   all       all                      reject
host    all       all       0.0.0.0/0      reject
host    all       all       ::/0           reject
EOF

  cat > "$dir/pg_ident.conf" <<EOF
# Written by ServerHub. MAPNAME  SYSTEM-USER  PG-USER
serverhub  postgres       postgres
serverhub  ${PANEL_USER}  postgres
EOF
  chown postgres:postgres "$dir/pg_hba.conf" "$dir/pg_ident.conf" "$dir/conf.d/serverhub.conf"
  chmod 640 "$dir/pg_hba.conf" "$dir/pg_ident.conf"

  if ! start_server; then
    echo "PostgreSQL did not start with the new config — restoring the original one."
    show_logs
    cp -p "$dir/pg_hba.conf.orig" "$dir/pg_hba.conf"
    cp -p "$dir/pg_ident.conf.orig" "$dir/pg_ident.conf"
    mv -f "$dir/conf.d/serverhub.conf" "$dir/conf.d/serverhub.conf.failed" 2>/dev/null || true
    start_server || true
    exit 1
  fi
  # Nobody may connect to the maintenance databases except the admin
  runuser -u postgres -- psql -X -q -c "REVOKE ALL ON DATABASE postgres FROM PUBLIC;" >/dev/null
  runuser -u postgres -- psql -X -q -d template1 -c "REVOKE ALL ON DATABASE template1 FROM PUBLIC;" >/dev/null
  echo "configured PostgreSQL $ver (shared_buffers ${shared}MB, localhost only)"
}

case "${1:-}" in
  install)
    export DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1   # no service-restart chatter
    apt-get update -qq
    apt-get install -y -qq postgresql postgresql-contrib >/dev/null
    configure
    ;;
  configure) configure ;;
  restart)
    if start_server; then echo "restarted"; else echo "PostgreSQL did not start"; show_logs; exit 1; fi
    ;;
  status)
    ver=$(pg_version)
    if [ -z "$ver" ]; then echo "installed=no"; exit 0; fi
    echo "installed=yes"
    echo "version=$ver"
    # really accepting connections — not just the umbrella unit being "active"
    if pg_isready -q -h /var/run/postgresql 2>/dev/null; then echo "running=yes"; else echo "running=no"; fi
    ;;
  *) echo "usage: serverhub-postgres <install|configure|status|restart>" >&2; exit 2 ;;
esac
