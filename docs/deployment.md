# Deployment Guide

This guide covers running OpenZIM MCP as a long-running HTTP service. If you only want to use OpenZIM MCP locally with Claude Desktop, Cursor, or another MCP client launching it as a subprocess, stay on the [README quick-start](../README.md#quick-start) — that path uses stdio transport and doesn't need any of this.

Use this guide if you want to:

- Run OpenZIM MCP on a homelab server and connect from other machines on your LAN
- Expose OpenZIM MCP over Tailscale to your tailnet
- Host a public, TLS-protected OpenZIM MCP endpoint on a VPS

The guide assumes Docker is your deployment substrate. The published image at `ghcr.io/cameronrye/openzim-mcp` is multi-arch (`linux/amd64`, `linux/arm64`), runs as a non-root user, and ships with a `/readyz` healthcheck already wired up.

## Contents

- [Reference: deployment-relevant configuration](#reference-deployment-relevant-configuration)
- [Recipe 1: Docker Compose on a LAN host](#recipe-1-docker-compose-on-a-lan-host) (with Tailscale variant)
- [Recipe 2: VPS with Caddy and automatic TLS](#recipe-2-vps-with-caddy-and-automatic-tls)
- [Operations](#operations)

## Reference: deployment-relevant configuration

The README contains the full environment variable table at [Configuration Options](../README.md#configuration-options). This section explains the subset that matters for deployment, with the operational reasoning behind each one.

### Transport choice (`OPENZIM_MCP_TRANSPORT`)

| Value | Use it for | Notes |
| --- | --- | --- |
| `stdio` (default) | Local clients launching the server as a subprocess | Don't deploy this. The README quick-start covers it. |
| `http` | All long-running deployments | Recommended. Bearer-token auth, CORS, health probes. |
| `sse` | Legacy clients still on Server-Sent Events | No auth/CORS/health middleware. **Refuses to start** if bound to anything other than `127.0.0.1` / `::1` / `localhost`. |

The `http` transport refuses to bind a non-loopback host (e.g. `0.0.0.0`) unless `OPENZIM_MCP_AUTH_TOKEN` is set. This is a startup check, not a runtime one — a misconfigured server fails fast with a clear error.

### Bind host and port (`OPENZIM_MCP_HOST`, `OPENZIM_MCP_PORT`)

`OPENZIM_MCP_HOST` defaults to `127.0.0.1` for the bare `openzim-mcp` CLI but is set to `0.0.0.0` inside the published Docker image — containers need to listen on all interfaces because the host's port-publish (`-p 127.0.0.1:8000:8000` etc.) is what controls external exposure. The recipes below take advantage of this: the container always binds `0.0.0.0:8000`, and Docker decides which host interfaces can reach it.

`OPENZIM_MCP_PORT` defaults to `8000`. Override it (and the host-side port mapping) only if 8000 collides with another service.

### Bearer-token auth (`OPENZIM_MCP_AUTH_TOKEN`)

Generate a token:

```bash
openssl rand -hex 32
```

Set it as `OPENZIM_MCP_AUTH_TOKEN` in the server's environment. Clients send it as `Authorization: Bearer <token>`.

The server compares tokens with a constant-time function (resistant to timing attacks) and never logs the attempted token, so a leaked log file does not leak the token. Rotate by setting a new value and restarting the container; there is no in-flight rotation.

### CORS allow-list (`OPENZIM_MCP_CORS_ORIGINS`)

Required only if a browser client (a web app calling the MCP server directly via `fetch`) connects. Format is a JSON array of exact origins:

```bash
OPENZIM_MCP_CORS_ORIGINS='["https://app.example.com","https://localhost:5173"]'
```

The wildcard `*` is rejected at startup. Listing exact origins is a deliberate constraint — wildcard CORS combined with bearer-token auth is the canonical recipe for token theft via a malicious site.

If no browser client connects (you're hitting the endpoint from another server, a CLI client, or a desktop MCP client), leave this unset.

### Health probes: `/healthz` and `/readyz`

| Endpoint | Returns 200 when | Use for |
| --- | --- | --- |
| `/healthz` | The process is alive and responding | Liveness — restart the container if this fails |
| `/readyz` | At least one configured ZIM directory is readable | Readiness — pull from load balancer if this fails |

Both endpoints are exempt from auth so probes work without distributing tokens to your monitoring stack. The published Docker image already wires `/readyz` to `HEALTHCHECK`, so `docker ps` shows accurate health out of the box.

### Resource subscriptions (`OPENZIM_MCP_SUBSCRIPTIONS_ENABLED`, `OPENZIM_MCP_WATCH_INTERVAL_SECONDS`)

When enabled (default), clients subscribed to `zim://files` or `zim://{name}` receive `notifications/resources/updated` whenever a `.zim` file appears, disappears, or is replaced in a configured directory. The watcher polls — it does not use inotify — so the latency is bounded by `OPENZIM_MCP_WATCH_INTERVAL_SECONDS` (default 5s, clamp 1–60s).

Disable with `OPENZIM_MCP_SUBSCRIPTIONS_ENABLED=false` if your clients don't use subscriptions; the watcher then doesn't run and `subscribe` calls succeed but never fire updates.

## Recipe 1: Docker Compose on a LAN host

This recipe puts OpenZIM MCP on a single host, reachable from the rest of your LAN over plain HTTP plus a bearer token. There's no TLS — the bearer token is the only thing protecting the endpoint, so this recipe is appropriate for trusted networks (a home LAN, a Tailscale tailnet) and **not** for anything reachable from the public internet.

### Prereqs

- Docker and Docker Compose v2 installed on the host
- A directory of `.zim` files (download from the [Kiwix Library](https://library.kiwix.org/))
- A generated bearer token:

  ```bash
  openssl rand -hex 32
  ```

### `docker-compose.yml`

```yaml
services:
  openzim-mcp:
    image: ghcr.io/cameronrye/openzim-mcp:1.0.0
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"
    volumes:
      - /srv/zim:/data:ro
    environment:
      OPENZIM_MCP_AUTH_TOKEN: "${OPENZIM_MCP_AUTH_TOKEN}"
```

What's intentional here:

- **Pinned tag** (`:1.0.0`, not `:latest`). Upgrades are deliberate — `docker compose pull` is a thing you do, not a thing that happens to you.
- **Host port bound to `127.0.0.1`**. The container listens on all interfaces (the image's default `OPENZIM_MCP_HOST=0.0.0.0`), but Docker's port publish restricts external exposure to loopback. The Tailscale variant below lifts this restriction by binding to a specific interface.
- **Read-only ZIM mount** (`:ro`). The server only reads ZIM files; mounting read-only ensures a server compromise can't damage them.
- **Token via env, not hard-coded.** Put it in a `.env` file next to the compose file (and add `.env` to `.gitignore`). The image's defaults already set `TRANSPORT=http`, `HOST=0.0.0.0`, `PORT=8000`, so they're not repeated here.

`/srv/zim` is an example. Adjust to wherever your ZIM files live.

### Start it

```bash
echo "OPENZIM_MCP_AUTH_TOKEN=$(openssl rand -hex 32)" > .env
docker compose up -d
```

### Verify

```bash
# Liveness
curl -sf http://127.0.0.1:8000/healthz && echo " healthz ok"

# Readiness (will fail if /srv/zim is empty or unreadable)
curl -sf http://127.0.0.1:8000/readyz && echo " readyz ok"

# Authed RPC call: list available tools
TOKEN=$(grep OPENZIM_MCP_AUTH_TOKEN .env | cut -d= -f2)
curl -sf -X POST http://127.0.0.1:8000/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | head -c 500
```

If `tools/list` returns a JSON envelope with a `result.tools` array, you're up.

### Connect a client

Add OpenZIM MCP to your client's MCP config. Substitute the host, port, and token. Cursor supports remote HTTP MCP servers natively; Claude Desktop currently does not — it needs the `mcp-remote` bridge, which translates Claude Desktop's stdio expectations into HTTP calls. Anthropic is expected to add native HTTP support eventually; this guide will switch to the native form once it ships.

**Cursor** (`~/.cursor/mcp.json` for global, or `.cursor/mcp.json` for project-local):

```json
{
  "mcpServers": {
    "openzim-mcp": {
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN_HERE"
      }
    }
  }
}
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows). Requires Node.js on the client host (`mcp-remote` runs via `npx`):

```json
{
  "mcpServers": {
    "openzim-mcp": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote@latest",
        "http://127.0.0.1:8000/mcp",
        "--header",
        "Authorization:Bearer YOUR_TOKEN_HERE"
      ]
    }
  }
}
```

The `Authorization:Bearer` form (no space after the colon) matches `mcp-remote`'s documented header syntax. The token lives directly in the config file and is visible in `ps` output on the client machine while `mcp-remote` is running — treat the file as a secret: don't commit `claude_desktop_config.json` to a shared repo and keep its filesystem permissions tight (`chmod 600` on Unix).

### Tailscale variant

To reach the server from your tailnet instead of the LAN, change exactly one line in `docker-compose.yml`:

```yaml
    ports:
      - "100.x.y.z:8000:8000"  # your Tailscale IPv4, from `tailscale ip -4`
```

Then make sure the host firewall blocks port 8000 on the public interface (it should already, since you're not publishing on `0.0.0.0`). The bearer token plus tailnet ACLs are your trust boundary; you don't need TLS because the tailnet itself is encrypted.

## Recipe 2: VPS with Caddy and automatic TLS

This recipe puts OpenZIM MCP on a public VPS, fronted by Caddy for automatic Let's Encrypt TLS. The bearer token is still the auth boundary; TLS prevents a network observer from stealing it in transit.

### Prereqs

- A VPS with a public IPv4 (and optionally IPv6)
- A domain name with an A record (and optional AAAA) pointing at the VPS
- Ports 80 and 443 open on the VPS firewall (Caddy needs both for the HTTP-01 ACME challenge and TLS service)
- Same bearer token and ZIM directory as Recipe 1

### `docker-compose.yml`

This is the LAN compose file with two changes: a `caddy` service is added, and the openzim-mcp service no longer publishes a host port (it's reachable only on the internal Docker network).

```yaml
services:
  openzim-mcp:
    image: ghcr.io/cameronrye/openzim-mcp:1.0.0
    restart: unless-stopped
    expose:
      - "8000"
    volumes:
      - /srv/zim:/data:ro
    environment:
      OPENZIM_MCP_AUTH_TOKEN: "${OPENZIM_MCP_AUTH_TOKEN}"

  caddy:
    image: caddy:2
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"  # HTTP/3
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - openzim-mcp

volumes:
  caddy_data:
  caddy_config:
```

### `Caddyfile`

```text
zim.example.com {
    reverse_proxy openzim-mcp:8000
}
```

That's it. Caddy provisions a certificate on first request (and renews automatically), terminates TLS, and forwards the `Authorization` header to OpenZIM MCP unchanged. Replace `zim.example.com` with your hostname.

> **nginx alternative:** if you already run nginx and prefer it to Caddy, the only requirements are reverse-proxying `/` to `openzim-mcp:8000` and forwarding the `Authorization` header unchanged. nginx will not auto-provision certs, so pair it with Certbot or a similar tool. No worked example here.

### Start it

```bash
echo "OPENZIM_MCP_AUTH_TOKEN=$(openssl rand -hex 32)" > .env
docker compose up -d

# Watch Caddy obtain its certificate (first start only)
docker compose logs -f caddy
```

The first request triggers ACME issuance; subsequent restarts reuse the cached cert from the `caddy_data` volume.

### Verify

```bash
# TLS chain
curl -vsf https://zim.example.com/healthz 2>&1 | grep -E "subject|issuer|HTTP/"

# Authed RPC call
TOKEN=$(grep OPENZIM_MCP_AUTH_TOKEN .env | cut -d= -f2)
curl -sf -X POST https://zim.example.com/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | head -c 500
```

### Hardening checklist

- **Token rotation.** Generate a new token, update `.env`, run `docker compose up -d` to pick up the change. Distribute the new token to clients out-of-band.
- **CORS.** Set `OPENZIM_MCP_CORS_ORIGINS` to the exact origins of any browser clients that connect directly. Skip if no browser clients connect.
- **Non-root.** The published image already runs as `appuser` (UID 10001). Confirm with `docker compose exec openzim-mcp id` — output should be `uid=10001(appuser)`.
- **Log review.** `docker compose logs -f openzim-mcp` shows auth failures (the attempted token is *not* logged, but the request and outcome are). A burst of 401s from one client usually means a stale token.
- **Read-only ZIM mount.** Already in the compose (`:ro`). Don't remove it.

## Operations

### Upgrades

```bash
# Pull the new image, then recreate containers using it
docker compose pull
docker compose up -d
```

The image tag in `docker-compose.yml` is pinned (`:1.0.0`) — change it to the new version before pulling. Pinning is deliberate: `:latest` makes upgrades a surprise, and the v1 release notes (or future v1.x release notes) tell you when an upgrade involves a breaking change.

### Watching logs

```bash
docker compose logs -f openzim-mcp
```

A clean startup logs the bind host/port and the configured allowed directory. An auth failure logs the route, status, and client IP — *not* the attempted token. A subscription update logs the watched path and the change type (created / replaced / removed).

### Common failure modes

- **Container exits immediately on start.** Almost always one of two startup checks: HTTP transport bound to a non-loopback host without `OPENZIM_MCP_AUTH_TOKEN`, or `OPENZIM_MCP_CORS_ORIGINS` set to a value containing `*`. The startup error message identifies which.
- **Clients get 401 Unauthorized.** Token mismatch. Verify with `curl -H "Authorization: Bearer $TOKEN" http://host/mcp/...`. Don't paste the token into chat or tickets.
- **Browser clients get 403 / CORS errors.** Either `OPENZIM_MCP_CORS_ORIGINS` is unset (and a browser is calling) or the client's origin isn't in the allow-list. The browser console shows the offending origin; add it.
- **`/readyz` returns 503.** None of the configured ZIM directories are readable from inside the container. (With multiple allowed directories, one bad mount is fine — readiness flips only when *all* of them fail.) Check the volume mount path (host side and `/data` side) and that the mount isn't empty. Permissions: the in-container user is UID 10001; the host directory needs to be world-readable or owned by UID 10001.
- **Subscriptions stop firing.** Confirm `OPENZIM_MCP_SUBSCRIPTIONS_ENABLED` isn't set to `false`. If a client claims it subscribed but never gets updates, check that the subscribe call actually returned a successful response — clients silently treating a failed subscription as success is a known footgun.
