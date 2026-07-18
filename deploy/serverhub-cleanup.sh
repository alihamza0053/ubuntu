#!/usr/bin/env bash
# ServerHub — system cleanup helper (runs as root via a single sudoers rule).
# Installed to $PANEL_ROOT/bin/serverhub-cleanup by deploy/install.sh|update.sh.
#
# Usage: serverhub-cleanup <task> [task…]
#   apt      apt autoremove + clean the package download cache
#   journal  shrink systemd journal logs (keep the last 3 days)
#   tmp      delete /tmp and /var/tmp files untouched for over a day
#   logs     delete rotated/compressed logs under /var/log (*.gz, *.1, …)
#   pip      delete pip download caches (all users)
#   docker   remove dangling docker images + build cache (never containers)
#   ram      flush filesystem caches from RAM (sync + drop_caches)
#
# Every task is safe to repeat: it only ever removes caches, expired temp
# files and already-rotated logs — never live data, containers or configs.
set -u

human() {  # bytes -> human readable
  awk -v b="${1:-0}" 'BEGIN{ split("B KB MB GB TB", u);
    for (i=1; b>=1024 && i<5; i++) b/=1024; printf "%.1f %s", b, u[i] }'
}

disk_used() { df -B1 --output=used / | tail -1 | tr -d ' '; }

START_DISK=$(disk_used)

run_apt() {
  echo "── apt: autoremove unused packages + clean download cache ──"
  apt-get -y autoremove --purge 2>&1 | tail -5
  apt-get -y autoclean >/dev/null 2>&1
  apt-get clean
  echo "apt cache cleaned"
}

run_journal() {
  echo "── journal: keep only the last 3 days ──"
  if command -v journalctl >/dev/null 2>&1; then
    journalctl --vacuum-time=3d 2>&1 | tail -3
  else
    echo "journalctl not available — skipped"
  fi
}

run_tmp() {
  echo "── tmp: delete /tmp and /var/tmp files older than 1 day ──"
  local count=0
  for base in /tmp /var/tmp; do
    [ -d "$base" ] || continue
    # Only plain files/symlinks untouched >1 day; leave sockets, X11 dirs and
    # systemd-private mounts alone. Errors (files vanishing mid-walk) ignored.
    while IFS= read -r -d '' f; do
      rm -f -- "$f" 2>/dev/null && count=$((count + 1))
    done < <(find "$base" -mindepth 1 \
               \( -name ".X11-unix" -o -name "systemd-private-*" \
                  -o -name ".font-unix" -o -name ".ICE-unix" \) -prune \
               -o \( -type f -o -type l \) -mtime +1 -print0 2>/dev/null)
    # Sweep now-empty directories (best-effort)
    find "$base" -mindepth 1 -type d -empty \
      ! -name ".X11-unix" ! -name ".font-unix" ! -name ".ICE-unix" \
      -delete 2>/dev/null || true
  done
  echo "removed $count old temp file(s)"
}

run_logs() {
  echo "── logs: delete rotated logs under /var/log ──"
  local before
  before=$(du -sb /var/log 2>/dev/null | cut -f1)
  find /var/log -type f \( -name "*.gz" -o -name "*.xz" -o -name "*.old" \
    -o -regex ".*\.[0-9]+" \) -delete 2>/dev/null || true
  local after
  after=$(du -sb /var/log 2>/dev/null | cut -f1)
  echo "freed $(human $(( ${before:-0} - ${after:-0} ))) of rotated logs"
}

run_pip() {
  echo "── pip: delete download caches ──"
  local total=0 d
  for d in /root/.cache/pip /home/*/.cache/pip /srv/serverhub/.cache/pip; do
    if [ -d "$d" ]; then
      total=$(( total + $(du -sb "$d" 2>/dev/null | cut -f1 || echo 0) ))
      rm -rf -- "$d" 2>/dev/null || true
    fi
  done
  echo "freed $(human "$total") of pip cache"
}

run_docker() {
  echo "── docker: remove dangling images + build cache ──"
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    # Deliberately NOT `system prune`: that would delete stopped containers,
    # which panel apps rely on (a stopped app must be startable again).
    docker image prune -f 2>&1 | tail -2
    docker builder prune -f 2>&1 | tail -2
  else
    echo "docker not installed/running — skipped"
  fi
}

run_ram() {
  echo "── ram: flush filesystem caches ──"
  local before after
  before=$(free -b | awk '/^Mem:/{print $7}')
  sync
  echo 3 > /proc/sys/vm/drop_caches
  after=$(free -b | awk '/^Mem:/{print $7}')
  echo "available RAM: $(human "${before:-0}") → $(human "${after:-0}")"
  echo "note: Linux reuses free RAM for disk cache automatically — high usage"
  echo "      by cache is normal and not a problem."
}

if [ "$#" -eq 0 ]; then
  echo "usage: serverhub-cleanup <apt|journal|tmp|logs|pip|docker|ram> …" >&2
  exit 1
fi

for task in "$@"; do
  case "$task" in
    apt)     run_apt ;;
    journal) run_journal ;;
    tmp)     run_tmp ;;
    logs)    run_logs ;;
    pip)     run_pip ;;
    docker)  run_docker ;;
    ram)     run_ram ;;
    *)       echo "unknown task: $task (skipped)" ;;
  esac
  echo ""
done

END_DISK=$(disk_used)
FREED=$(( START_DISK - END_DISK ))
[ "$FREED" -lt 0 ] && FREED=0
echo "═══ cleanup finished — disk space freed: $(human "$FREED") ═══"
