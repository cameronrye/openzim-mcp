# HTTP Deployment Guide

This guide covers running OpenZIM MCP over HTTP for self-hosted single-user
scenarios (homelab, Tailscale, VPS). For multi-user setups, see "Limits" at
the bottom.

## 1. Generate an auth token

The HTTP transport requires a bearer token unless you bind to localhost only.
Generate one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Treat the token like a password.** It is the only credential between any
network attacker and full read access to your ZIM corpus. Store it in a
secret manager or in an environment file with restricted permissions
(`chmod 600`). Never commit it to a repository.

## 2. Quick start with Docker

```bash
docker run -d \
  --name openzim-mcp \
  -p 8000:8000 \
  -e OPENZIM_MCP_AUTH_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))") \
  -v /path/to/zim/files:/data:ro \
  ghcr.io/cameronrye/openzim-mcp:latest
```

The container will refuse to start without `OPENZIM_MCP_AUTH_TOKEN` because
it binds to `0.0.0.0`. Test with:

```bash
curl http://localhost:8000/healthz
# → {"status":"ok"}
```

## 3. Reverse proxy with TLS

Bind the server to localhost behind a reverse proxy that handles TLS.

### Caddy

```caddyfile
mcp.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

(Caddy auto-provisions Let's Encrypt certs.)

### nginx

```nginx
server {
    listen 443 ssl http2;
    server_name mcp.example.com;
    ssl_certificate     /etc/letsencrypt/live/mcp.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";  # streamable HTTP needs this
    }
}
```

## 4. systemd unit (non-Docker)

```ini
# /etc/systemd/system/openzim-mcp.service
[Unit]
Description=OpenZIM MCP Server
After=network.target

[Service]
Type=simple
User=openzim
Group=openzim
EnvironmentFile=/etc/openzim-mcp/env  # contains OPENZIM_MCP_AUTH_TOKEN=...
ExecStart=/usr/local/bin/openzim-mcp --transport http --host 127.0.0.1 --port 8000 /var/lib/openzim/zims
Restart=on-failure
RestartSec=5

# Hardening
ProtectSystem=strict
ProtectHome=yes
ReadOnlyPaths=/var/lib/openzim/zims
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
```

## 5. Tailscale

Bind to `0.0.0.0:8000` inside the tailnet, restrict access via Tailscale ACLs.
Even though the listener is exposed on the host's tailnet IP, only authorized
nodes can reach it. The auth token is still required (defense in depth).

## 6. CORS

If a browser-based MCP client needs to talk to the server directly, set the
`OPENZIM_MCP_CORS_ORIGINS` env var or `cors_origins` config field to a JSON
array of allowed origins. Wildcard `*` is rejected at startup.

```bash
OPENZIM_MCP_CORS_ORIGINS='["http://localhost:5173","https://app.example.com"]'
```

## 7. Resource subscriptions

When the watch interval is enabled (default: 5 s, controlled via
`OPENZIM_MCP_WATCH_INTERVAL_SECONDS`), the server emits
`notifications/resources/updated` to any client that has subscribed:

* `zim://files` — fires when a `.zim` file is added to or removed from an
  allowed directory.
* `zim://{name}` — fires when the mtime of `{name}.zim` changes (replacement).

Subscriptions can be disabled at startup with
`OPENZIM_MCP_SUBSCRIPTIONS_ENABLED=false`.

## 8. Token rotation

1. Generate a new token (Section 1).
2. Update the env var (`/etc/openzim-mcp/env` or container env).
3. Restart the server: `systemctl restart openzim-mcp` or
   `docker restart openzim-mcp`.

There is no revocation list — the old token stops working as soon as the
server reads the new env var on startup.

## 9. If the token leaks

Rotate immediately (Section 8). Audit your access logs (failed auth attempts
log source IP and a `reason` field, but never log the attempted token, so
you cannot search for the leaked value in your own logs). If you have any
doubts about who used the token while it was leaked, treat all data
accessed through this server as observed by an attacker.

## Limits — single-user only

This release supports a single shared bearer token. There is no per-user
identity, no audit trail per principal, no token revocation list. If you
need multi-user access, that is a different design (deferred to 1.x or 2.0).
