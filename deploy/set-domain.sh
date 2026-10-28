#!/usr/bin/env bash
# ServerHub — put the panel on a domain (and get HTTPS for it).
#
#   sudo bash deploy/set-domain.sh panel.example.com you@example.com
#
# 1. checks the domain's DNS points at this server
# 2. sets it as the panel's nginx server_name and reloads nginx
# 3. gets a Let's Encrypt certificate + HTTP→HTTPS redirect (when an email is given)
# Safe to re-run; changing to a new domain is the same command.
set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"
SITE=/etc/nginx/sites-available/serverhub

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo." >&2; exit 1; }
if ! [[ "$DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$ ]]; then
  echo "usage: sudo bash deploy/set-domain.sh panel.example.com [email-for-ssl]" >&2
  exit 2
fi
[ -f "$SITE" ] || { echo "$SITE not found — is the panel installed?" >&2; exit 1; }

echo "==> Checking DNS for $DOMAIN"
SERVER_IP="$(curl -4 -fsS --max-time 8 https://api.ipify.org 2>/dev/null || true)"
DNS_IP="$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk 'NR==1 {print $1}')"
echo "    $DOMAIN → ${DNS_IP:-(no A record yet)}   this server → ${SERVER_IP:-unknown}"
DNS_OK=yes
if [ -z "$DNS_IP" ] || { [ -n "$SERVER_IP" ] && [ "$DNS_IP" != "$SERVER_IP" ]; }; then
  DNS_OK=no
  echo "    WARNING: the domain doesn't point at this server yet. Add an A record:"
  echo "             $DOMAIN  →  ${SERVER_IP:-<public IP of this server>}"
  echo "             (the nginx name is set anyway; SSL is skipped until DNS is right)"
fi

echo "==> Setting the panel's domain in nginx"
cp -p "$SITE" "$SITE.bak-$(date +%Y%m%d-%H%M%S)"
# every server_name line in the panel site (the HTTP block and, if present, the
# HTTPS block certbot added) gets the new domain
sed -i -E "s/^([[:space:]]*server_name)[[:space:]]+[^;]*;/\1 $DOMAIN;/" "$SITE"
if nginx -t 2>/dev/null; then
  systemctl reload nginx
  echo "    http://$DOMAIN/ now serves the panel"
else
  echo "    nginx rejected the change — restoring the previous file"
  cp -p "$(ls -t "$SITE".bak-* | head -1)" "$SITE"
  nginx -t
  exit 1
fi

if [ -z "$EMAIL" ]; then
  echo "==> No email given — skipping SSL. For HTTPS later:"
  echo "    sudo bash $0 $DOMAIN you@example.com"
  exit 0
fi
if [ "$DNS_OK" = no ]; then
  echo "==> SSL skipped — fix the A record above, wait a few minutes, then run this again."
  exit 0
fi

echo "==> Getting the SSL certificate"
if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect; then
  echo
  echo "Done: https://$DOMAIN/"
else
  echo "certbot failed. Common causes: port 80 closed in the firewall, or the server"
  echo "isn't reachable from the internet (e.g. a local VM behind NAT)."
  exit 1
fi
