"""
Nginx config generation + reload, and Certbot SSL issuance.

Config blocks are written to NGINX_CONFIGS_ROOT (/srv/nginx-configs) and
symlinked into /etc/nginx/sites-enabled/ so the panel user never writes into
/etc/nginx directly. `nginx -t`, `systemctl reload nginx` and `certbot` run
through the restricted sudoers rules.

All subprocess calls use argument lists.
"""
import subprocess
from pathlib import Path

from fastapi import HTTPException

from ..config import settings

SITES_ENABLED = Path("/etc/nginx/sites-enabled")


# ---------- templates ----------

def streamlit_block(domain: str, port: int) -> str:
    return f"""server {{
    listen 80;
    server_name {domain};
    client_max_body_size 64M;
    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
    }}
}}
"""


def _cert_paths(domain: str) -> tuple[str, str] | None:
    """
    Return (fullchain, privkey) if a Let's Encrypt cert exists for `domain`.

    /etc/letsencrypt/live is root-only, and the panel runs as the unprivileged
    `serverhub` user — so a direct stat raises PermissionError (Python 3.12 no
    longer swallows it). We try the filesystem first, then fall back to scanning
    the panel-owned nginx configs (which we CAN read) for a reference to the
    cert — that's how we know SSL was already issued without root access.
    """
    fullchain = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
    privkey = f"/etc/letsencrypt/live/{domain}/privkey.pem"
    try:
        if Path(fullchain).exists() and Path(privkey).exists():
            return fullchain, privkey
        return None
    except OSError:
        pass  # can't stat /etc/letsencrypt as serverhub — use the fallback

    # Fallback: a managed config already referencing this cert ⇒ it exists.
    try:
        for conf in settings.NGINX_CONFIGS_ROOT.glob("*.conf"):
            if fullchain in conf.read_text(encoding="utf-8", errors="ignore"):
                return fullchain, privkey
    except OSError:
        pass
    return None


def project_block(domain: str, port: int, project: str, panel_port: int) -> str:
    """
    A project's nginx block: the Streamlit dashboard at / (websocket-capable),
    plus the per-project public upload portal at /onedrivefiles/ proxied to the
    panel backend (which password-protects it per project).

    SSL-aware: if a Let's Encrypt cert already exists for the domain, emit an
    HTTPS server (and redirect HTTP → HTTPS) so regenerating this block never
    wipes the certificate config certbot added.
    """
    locations = f"""    client_max_body_size 1024M;

    # Public, password-protected upload portal (panel-hosted)
    location = /onedrivefiles {{ return 301 /onedrivefiles/; }}
    location /onedrivefiles/ {{
        proxy_pass http://127.0.0.1:{panel_port}/portal/{project}/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Authorization $http_authorization;
        client_max_body_size 1024M;
    }}

    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
    }}"""

    cert = _cert_paths(domain)
    if not cert:
        # No cert yet — plain HTTP block (certbot adds SSL when you click SSL).
        return f"server {{\n    listen 80;\n    server_name {domain};\n{locations}\n}}\n"

    fullchain, privkey = cert
    ssl_opts = ""
    if Path("/etc/letsencrypt/options-ssl-nginx.conf").exists():
        ssl_opts += "    include /etc/letsencrypt/options-ssl-nginx.conf;\n"
    if Path("/etc/letsencrypt/ssl-dhparams.pem").exists():
        ssl_opts += "    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;\n"

    return f"""server {{
    listen 80;
    server_name {domain};
    location / {{ return 301 https://$host$request_uri; }}
}}

server {{
    listen 443 ssl;
    server_name {domain};
    ssl_certificate {fullchain};
    ssl_certificate_key {privkey};
{ssl_opts}{locations}
}}
"""


def react_block(domain: str, folder: str) -> str:
    return f"""server {{
    listen 80;
    server_name {domain};
    root {settings.WEBSITES_ROOT}/{folder}/dist;
    index index.html;
    location / {{ try_files $uri /index.html; }}
}}
"""


def php_block(domain: str, folder: str) -> str:
    return f"""server {{
    listen 80;
    server_name {domain};
    root {settings.WEBSITES_ROOT}/{folder};
    index index.php index.html;
    location / {{ try_files $uri $uri/ =404; }}
    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/var/run/php/php8.1-fpm.sock;
    }}
}}
"""


def html_block(domain: str, folder: str) -> str:
    return f"""server {{
    listen 80;
    server_name {domain};
    root {settings.WEBSITES_ROOT}/{folder};
    index index.html;
}}
"""


def build_block(entity_type: str, **kw) -> str:
    """Render the right template. entity_type: streamlit/react/php/html."""
    if entity_type == "streamlit":
        return streamlit_block(kw["domain"], kw["port"])
    if entity_type == "react":
        return react_block(kw["domain"], kw["folder"])
    if entity_type == "php":
        return php_block(kw["domain"], kw["folder"])
    if entity_type == "html":
        return html_block(kw["domain"], kw["folder"])
    raise HTTPException(status_code=400, detail=f"Unknown nginx block type: {entity_type}")


# ---------- sudo-wrapped operations ----------

def _sudo(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["sudo", "-n", *args], capture_output=True, text=True, timeout=120)


def test_and_reload() -> str:
    """Run `nginx -t` then reload; raise with the error text on failure."""
    test = _sudo("nginx", "-t")
    if test.returncode != 0:
        raise HTTPException(status_code=500, detail=f"nginx -t failed: {test.stderr or test.stdout}")
    reload = _sudo("systemctl", "reload", "nginx")
    if reload.returncode != 0:
        raise HTTPException(status_code=500, detail=f"nginx reload failed: {reload.stderr}")
    return "nginx reloaded"


def write_site(slug: str, content: str) -> Path:
    """Write a config block, symlink it into sites-enabled, test + reload."""
    settings.NGINX_CONFIGS_ROOT.mkdir(parents=True, exist_ok=True)
    config_path = settings.NGINX_CONFIGS_ROOT / f"{slug}.conf"
    config_path.write_text(content, encoding="utf-8")

    link = SITES_ENABLED / f"{slug}.conf"
    # Symlink via sudo since sites-enabled is root-owned
    _sudo("ln", "-sf", str(config_path), str(link))
    test_and_reload()
    return config_path


def remove_site(slug: str) -> None:
    config_path = settings.NGINX_CONFIGS_ROOT / f"{slug}.conf"
    if config_path.exists():
        config_path.unlink()
    _sudo("rm", "-f", str(SITES_ENABLED / f"{slug}.conf"))
    try:
        test_and_reload()
    except HTTPException:
        pass


def request_ssl(domain: str) -> str:
    """Obtain/renew a Let's Encrypt cert and configure nginx for it."""
    result = _sudo(
        "certbot", "--nginx", "-d", domain,
        "--non-interactive", "--agree-tos", "--redirect",
        "--register-unsafely-without-email",
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"certbot failed: {output[-800:]}")
    return output
