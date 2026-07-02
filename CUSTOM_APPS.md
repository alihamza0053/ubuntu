# Deploying your own apps on the panel (Custom Apps + Proxies)

The panel has built-in deploy paths for **static sites** (Websites: React/PHP/HTML),
**Streamlit dashboards** (Projects), and **catalog apps** (Apps). But many apps are
none of those — they're a service you run yourself: a **FastAPI/uvicorn** app, a
**Flask** app, a **Node** server, or a **Docker container** (like
`web_app/` in this repo, a FastAPI + Selenium dashboard with its own Dockerfile).

For those, use the **Proxies** feature: run the app on a local port, then point a
domain (with SSL) at it in one click.

```
Internet ──▶ nginx (:80/:443, your domain, SSL)
                │   reverse proxy (Proxies feature)
                ▼
        127.0.0.1:PORT  ◀── your app (Docker container / uvicorn / Flask / Node)
```

The Proxies feature only does the **domain + SSL + nginx** part. *You* keep the
service running (Docker `--restart`, supervisor, systemd, etc.). Removing a proxy
never stops your service.

---

## Quick start (Docker app — e.g. `web_app/`)

### 1. Make sure Docker is installed
**Apps → Infrastructure → Docker Engine → Install** (one-click), or check with
`docker --version` in the Terminal.

### 2. Build & run your app on a localhost port
Put your app's folder on the server (upload, `git clone`, or `scp`), then in the
panel **Terminal** (or over SSH):

```bash
cd /path/to/web_app          # folder containing the Dockerfile
sudo docker build -t browser-automation .
sudo docker run -d --name browser-automation --restart unless-stopped \
  --shm-size=1g \
  -p 127.0.0.1:9100:8000 \
  -v browser_automation_data:/app \
  browser-automation
```

Key points:
- **`-p 127.0.0.1:9100:8000`** — publish the container's port (`8000` here) to a
  **localhost** port (`9100`). Always bind to `127.0.0.1`, never `0.0.0.0`, so the
  port isn't exposed to the internet directly — nginx is the only public door.
- `--restart unless-stopped` — survives reboots.
- `--shm-size=1g` — needed for Chrome/Selenium apps (prevents crashes).
- `-v name:/path` — persist data the app writes (config/history/screenshots).

The container now appears on the **Docker** page (start/stop/logs).

> Not a Docker app? Same idea — just run it on a localhost port:
> `uvicorn app:app --host 127.0.0.1 --port 9100`, `flask run -h 127.0.0.1 -p 9100`,
> `node server.js` (listening on `127.0.0.1:9100`). To keep a non-Docker app
> running after logout, start it under supervisor or systemd.

### 3. Create the proxy
**Proxies → ＋ New Proxy**:
- **Name**: `browser-automation`
- **Local port**: `9100`

The card shows **service up** (green) once something is listening on that port. If
it says *no service*, start your app first or you'll get a 502.

### 4. Point a domain at it
1. At your DNS host, add an **A record** for the subdomain (e.g. `bot`) →
   your server's IP. Wait for it to resolve (`dig +short bot.yourdomain.com`).
2. On the proxy card, type the domain (`bot.yourdomain.com`) → **Domain**.
   The panel writes the nginx reverse-proxy block and reloads.
3. Click **🔒 SSL** → Let's Encrypt issues a cert and forces HTTPS.

Open `https://bot.yourdomain.com` — your app is live. WebSockets work too (the
proxy block forwards `Upgrade`/`Connection` headers).

---

## How it works (under the hood)

- A proxy is a small DB record: `name` + `upstream_port` + `domain`.
- **Assign domain** generates the same websocket-capable nginx proxy block used
  for Streamlit dashboards
  ([`nginx_service.py`](backend/app/services/nginx_service.py)) into
  `/srv/nginx-configs/proxy-<name>.conf`, symlinks it into nginx, and reloads.
- **SSL** runs Certbot for the domain (auto-renews).
- The **service up / no service** badge is a live TCP check against
  `127.0.0.1:<port>`.

---

## Choosing the right deploy path

| Your app | Use | Notes |
|---|---|---|
| Static React/Vite build | **Websites** (react) | Upload source + Build, or upload `dist/` |
| Plain PHP site | **Websites** (php) | Match the PHP-FPM socket version |
| Static HTML/CSS/JS | **Websites** (html) | |
| Streamlit dashboard | **Projects** | `dashboard/app.py` |
| Catalog tool (code-server, n8n, …) | **Apps** | one-click |
| **Your own FastAPI/Flask/Node/Docker app** | **Proxies** | run on a localhost port, then proxy a domain |
| React frontend **+** PHP API together | **Websites (php)** + edit nginx | add a `try_files $uri /index.html` fallback |

---

## Troubleshooting

- **502 Bad Gateway** — your service isn't running, or it's on a different port, or
  it's bound to `0.0.0.0`/a container IP instead of `127.0.0.1`. Check the Docker
  page logs, and that the published port matches the proxy's port. The proxy card's
  **no service** badge confirms nothing is listening.
- **Certbot fails** — the DNS A record must resolve to this server, and ports
  80/443 must be open in UFW *and* your cloud provider's firewall.
- **App loads but features break** — for apps that build absolute URLs, set the
  app's base URL to your domain (or make it use relative paths) so assets/API
  calls go through the proxy.
- **Works then dies after you log out** — a foreground `uvicorn`/`node` stops when
  your shell closes. Use Docker `--restart unless-stopped`, supervisor, or systemd.
