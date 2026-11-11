# MeshScout Deployment Guide

This guide documents deployment models for MeshScout.
MeshScout supports two operational targets:
1. Desktop Offline Mode: Local workstation operation with local SQLite storage.
2. Hosted Community Mode: Multi-user containerized service behind a TLS reverse proxy.

---

## 1. Operational Models

MeshScout operates in either desktop mode or hosted community mode.

### Desktop Offline Mode

Desktop mode runs directly on a local workstation.
It requires no network access.
All mutations and preferences persist to `~/.meshscout/mesh_state.db`.

To install and run desktop mode:

```bash
pip install .[web]
meshscout serve --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080` in a web browser.
In desktop mode, users modify node statuses and home coordinates directly.

### Hosted Community Mode

Hosted mode runs MeshScout as a shared community planning portal.
Public visitors run link budget calculations and viewshed analyses.
Visitor home coordinates remain isolated in browser local storage.
Only authenticated club coordinators can alter shared infrastructure status.

Set the following environment variables to activate hosted mode:
- `MESHSCOUT_HOSTED_MODE=1`: Enables coordinator authentication guards.
- `MESHSCOUT_CLUB_TOKEN`: Secret token required for mutating API endpoints.

---

## 2. Container Deployment via Docker Compose

MeshScout provides a rootless container bundle.
The container runs as non-root user `meshscout` (UID 1000).
It stores state in `/data/mesh_state.db`.

### Prerequisites

- Docker Engine 24.0 or newer
- Docker Compose v2

### Quickstart

1. Navigate to the project directory:

```bash
cd /path/to/MeshScout
```

2. Export the coordinator token:

```bash
export MESHSCOUT_CLUB_TOKEN="generate-a-secure-random-token"
```

3. Launch the container stack:

```bash
docker compose up -d
```

4. Verify service health:

```bash
curl -f http://localhost:8000/api/status
```

---

## 3. Reverse Proxy Configuration

Always run hosted community deployments behind a TLS-terminating reverse proxy.

### Caddy Configuration

Caddy provisions automatic Let's Encrypt TLS certificates.
Add this block to `/etc/caddy/Caddyfile`:

```caddy
mesh.example.org {
    encode gzip zstd

    reverse_proxy localhost:8000 {
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }
}
```

Reload Caddy:

```bash
sudo systemctl reload caddy
```

### Nginx Configuration

Add this server block to `/etc/nginx/sites-available/meshscout`:

```nginx
server {
    listen 80;
    server_name mesh.example.org;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name mesh.example.org;

    ssl_certificate /etc/letsencrypt/live/mesh.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mesh.example.org/privkey.pem;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Reload Nginx:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 4. Coordinator Authentication

In hosted mode, mutation endpoints require the club secret token.
Send the token in the `X-Club-Token` header or `Authorization: Bearer <token>`.

### Example Status Update

```bash
curl -X POST http://localhost:8000/api/sites/status \
  -H "Content-Type: application/json" \
  -H "X-Club-Token: your-token-here" \
  -d '{"site_id": "VT-PEAK-01", "status": "active_on_air"}'
```

Unauthenticated mutation requests receive HTTP 403 Forbidden.
Public read requests and RF evaluations require no authentication token.
