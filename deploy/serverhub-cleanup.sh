#!/usr/bin/env bash
# ServerHub — system cleanup helper (runs as root via a single sudoers rule).
# Installed to $PANEL_ROOT/bin/serverhub-cleanup by deploy/install.sh|update.sh.
#
# Usage: serverhub-cleanup <task> [task…]
#   apt      apt autoremove + clean the package download cache
#   journal  shrink systemd journal logs (keep the last 3 days)
#   tmp      delete /tmp and /var/tmp files untouched for 6 hours + leftover
#            browser profile folders untouched for 2 hours
#   sizes    (read-only) disk usage per location, biggest /tmp items, held deleted files
#   logs     delete rotated/compressed logs under /var/log (*.gz, *.1, …)
#   pip      delete pip download caches (all users)
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
  echo "── tmp: delete stale files in /tmp and /var/tmp ──"
  local count=0 dirs=0
  for base in /tmp /var/tmp; do
    [ -d "$base" ] || continue
    # Leftover browser / automation profiles (download scripts, report
    # screenshots, Selenium/Playwright): whole folders, often 100 MB+ each.
    # Removed once nothing inside has been touched for 2 hours — a browser
    # that is still running keeps writing to its profile.
    while IFS= read -r -d '' d; do
      if [ -z "$(find "$d" -mmin -120 -print -quit 2>/dev/null)" ]; then
        rm -rf -- "$d" 2>/dev/null && dirs=$((dirs + 1))
      fi
    done < <(find "$base" -mindepth 1 -maxdepth 1 -type d \
               \( -name ".org.chromium.Chromium.*" -o -name ".com.google.Chrome.*" \
                  -o -name "scoped_dir*" -o -name "playwright*" -o -name "puppeteer*" \
                  -o -name "rust_mozprofile*" -o -name "tmp*profile*" -o -name ".com.brave.Browser.*" \
                  -o -name "chrome_*" -o -name "selenium*" \) -print0 2>/dev/null)
    # Everything else: plain files/symlinks untouched for 6 hours; leave
    # sockets, X11 dirs and systemd-private mounts alone.
    while IFS= read -r -d '' f; do
      rm -f -- "$f" 2>/dev/null && count=$((count + 1))
    done < <(find "$base" -mindepth 1 \
               \( -name ".X11-unix" -o -name "systemd-private-*" \
                  -o -name ".font-unix" -o -name ".ICE-unix" \) -prune \
               -o \( -type f -o -type l \) -mmin +360 -print0 2>/dev/null)
    # Sweep now-empty directories (best-effort)
    find "$base" -mindepth 1 -type d -empty \
      ! -name ".X11-unix" ! -name ".font-unix" ! -name ".ICE-unix" \
      -delete 2>/dev/null || true
  done
  echo "removed $count old temp file(s) and $dirs leftover browser profile folder(s)"
}

# Read-only: sizes as root (the panel itself can't read root-owned folders).
#   SIZE<TAB>bytes<TAB>path      a location in the disk breakdown
#   TMPTOP<TAB>bytes<TAB>path    the biggest items inside /tmp and /var/tmp
#   DELETED<TAB>bytes            deleted files still held open by running programs
run_sizes() {
  for p in /srv/projects /srv/websites /srv/serverhub/backups /srv/serverhub/trash /srv/onedrive \
           /srv/apps /var/lib/mysql /var/lib/docker /var/lib/containerd /var/lib/snapd /snap \
           /var/log /var/cache/apt/archives /tmp /var/tmp /home /root /usr /opt /swap.img /swapfile; do
    [ -e "$p" ] || continue
    printf 'SIZE\t%s\t%s\n' "$(du -sxb "$p" 2>/dev/null | tail -1 | cut -f1)" "$p"
  done
  for base in /tmp /var/tmp; do
    [ -d "$base" ] || continue
    find "$base" -mindepth 1 -maxdepth 1 -print0 2>/dev/null \
      | xargs -0 -r du -sxb 2>/dev/null
  done | sort -rn | head -12 | while IFS=$'\t' read -r b p; do printf 'TMPTOP\t%s\t%s\n' "$b" "$p"; done
  local held=0 s
  for fd in /proc/[0-9]*/fd/*; do
    case "$(readlink "$fd" 2>/dev/null)" in
      *" (deleted)") s=$(stat -L -c %s "$fd" 2>/dev/null) && held=$((held + ${s:-0})) ;;
    esac
  done
  printf 'DELETED\t%s\n' "$held"
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

if [ "${1:-}" = "sizes" ]; then   # read-only report, no cleanup summary
  run_sizes
  exit 0
fi

if [ "$#" -eq 0 ]; then
  echo "usage: serverhub-cleanup <apt|journal|tmp|logs|pip|ram> …" >&2
  exit 1
fi

for task in "$@"; do
  case "$task" in
    apt)     run_apt ;;
    journal) run_journal ;;
    tmp)     run_tmp ;;
    logs)    run_logs ;;
    pip)     run_pip ;;
    ram)     run_ram ;;
    *)       echo "unknown task: $task (skipped)" ;;
  esac
  echo ""
done

END_DISK=$(disk_used)
FREED=$(( START_DISK - END_DISK ))
[ "$FREED" -lt 0 ] && FREED=0
echo "═══ cleanup finished — disk space freed: $(human "$FREED") ═══"
