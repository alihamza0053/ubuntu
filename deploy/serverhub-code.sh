#!/usr/bin/env bash
# ServerHub — code editor helper (runs as root via a single sudoers rule).
# Installed to $PANEL_ROOT/bin/serverhub-code by deploy/install.sh|update.sh.
#
# Usage: serverhub-code <install|nginx|uninstall|status> [port]
#   install       install code-server (VS Code in the browser) from its official .deb
#   nginx <port>  serve it at <panel>/ide/, behind the panel's login check
#   uninstall     remove the /ide/ path and the code-server package
#   status        installed=… version=… nginx=…
#
# code-server itself listens on 127.0.0.1 only. nginx forwards /ide/ to it only
# after asking the panel (auth_request → /api/code/auth) whether the browser's
# editor cookie belongs to a user allowed to use the editor.
set -eu

SITE=/etc/nginx/sites-available/serverhub
SNIPPET_DIR=/etc/nginx/serverhub-panel.d
INCLUDE_LINE="include $SNIPPET_DIR/*.conf;"

install_code_server() {
  if command -v code-server >/dev/null 2>&1; then
    echo "code-server already installed: $(code-server --version | head -1)"
    return
  fi
  local arch ver deb
  arch="$(dpkg --print-architecture)"
  ver="$(curl -fsSL https://api.github.com/repos/coder/code-server/releases/latest \
          | grep -oE '"tag_name": *"v[^"]+' | sed 's/.*"v//')"
  [ -n "$ver" ] || { echo "could not find the latest code-server release" >&2; exit 1; }
  deb="$(mktemp --suffix=.deb)"
  echo "── downloading code-server $ver ($arch) ──"
  curl -fsSL -o "$deb" "https://github.com/coder/code-server/releases/download/v${ver}/code-server_${ver}_${arch}.deb"
  DEBIAN_FRONTEND=noninteractive apt-get install -y "$deb" >/dev/null
  rm -f "$deb"
  echo "✓ code-server $(code-server --version | head -1) installed"
}

setup_nginx() {
  local port="$1"
  case "$port" in ''|*[!0-9]*) echo "usage: serverhub-code nginx <port>" >&2; exit 2 ;; esac
  [ -f "$SITE" ] || { echo "panel nginx site $SITE not found" >&2; exit 1; }
  mkdir -p "$SNIPPET_DIR"
  cat > "$SNIPPET_DIR/ide.conf" <<EOF
# Written by ServerHub (serverhub-code nginx) — the code editor at /ide/.
location = /_serverhub_code_auth {
    internal;
    proxy_pass http://127.0.0.1:8765/api/code/auth;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header Cookie \$http_cookie;
    proxy_set_header X-Original-URI \$request_uri;
}
location @serverhub_code_login {
    return 302 /code;
}
location /ide/ {
    auth_request /_serverhub_code_auth;
    error_page 401 403 = @serverhub_code_login;
    proxy_pass http://127.0.0.1:${port}/;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Accept-Encoding gzip;
    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;
    client_max_body_size 200M;
}
EOF

  local backup=""
  if ! grep -qF "$INCLUDE_LINE" "$SITE"; then
    backup="$SITE.bak-$(date +%Y%m%d-%H%M%S)"
    cp -p "$SITE" "$backup"
    # into every server block of the panel site that serves the panel (the
    # HTTPS one certbot made too): just before its `location / {`
    sed -i "/^[[:space:]]*location \/ {/i\\    $INCLUDE_LINE" "$SITE"
  fi
  if nginx -t 2>/dev/null; then
    systemctl reload nginx
    echo "✓ editor served at /ide/ (port $port, login-checked by the panel)"
  else
    echo "nginx rejected the editor config — restoring" >&2
    [ -n "$backup" ] && cp -p "$backup" "$SITE"
    rm -f "$SNIPPET_DIR/ide.conf"
    nginx -t || true
    exit 1
  fi
}

uninstall_code_server() {
  rm -f "$SNIPPET_DIR/ide.conf"
  if nginx -t 2>/dev/null; then systemctl reload nginx; fi
  if dpkg -s code-server >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get remove -y code-server >/dev/null
  fi
  echo "✓ code-server removed"
}

case "${1:-}" in
  install)   install_code_server ;;
  nginx)     setup_nginx "${2:-}" ;;
  uninstall) uninstall_code_server ;;
  status)
    if command -v code-server >/dev/null 2>&1; then
      echo "installed=yes"
      echo "version=$(code-server --version 2>/dev/null | head -1 | awk '{print $1}')"
    else
      echo "installed=no"
    fi
    if [ -f "$SNIPPET_DIR/ide.conf" ] && grep -qF "$INCLUDE_LINE" "$SITE" 2>/dev/null; then
      echo "nginx=yes"
    else
      echo "nginx=no"
    fi
    ;;
  *) echo "usage: serverhub-code <install|nginx|uninstall|status> [port]" >&2; exit 2 ;;
esac
