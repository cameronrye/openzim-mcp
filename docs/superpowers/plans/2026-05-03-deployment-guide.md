# Deployment Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `docs/deployment.md` to satisfy the wiki-link promise in the README, and update the README link to point at the new doc.

**Architecture:** One new in-repo Markdown file plus a one-line README edit. The doc has a hybrid shape: a short reference section explaining each deployment-relevant config knob, followed by two end-to-end recipes (LAN/Tailscale, VPS+Caddy), followed by a short operations section.

**Tech Stack:** Markdown only. Pre-commit hooks include `markdownlint` (it auto-fixes blank-line-after-bold and similar style issues — let it run, then re-stage).

**Source spec:** [`docs/superpowers/specs/2026-05-03-deployment-guide-design.md`](../specs/2026-05-03-deployment-guide-design.md)

**Working branch:** `main` (per user direction; matches the prior `c7f1164 remove: outdated docs` flow).

---

## Background facts the engineer needs

These are confirmed from the README and Dockerfile — use them as written, do not invent variants:

**Confirmed env vars** (from [README.md:1362-1380](../../../README.md#L1362-L1380)):

| Var | Default | Notes |
| --- | --- | --- |
| `OPENZIM_MCP_TRANSPORT` | `stdio` | `stdio` / `http` / `sse` |
| `OPENZIM_MCP_HOST` | `127.0.0.1` | non-loopback requires token |
| `OPENZIM_MCP_PORT` | `8000` | |
| `OPENZIM_MCP_AUTH_TOKEN` | unset | required for non-loopback HTTP/SSE |
| `OPENZIM_MCP_CORS_ORIGINS` | empty | JSON array; `*` rejected |
| `OPENZIM_MCP_SUBSCRIPTIONS_ENABLED` | `true` | |
| `OPENZIM_MCP_WATCH_INTERVAL_SECONDS` | `5` | clamped 1–60 |

**Confirmed Docker image facts** (from [Dockerfile](../../../Dockerfile)):

- Image: `ghcr.io/cameronrye/openzim-mcp:1.0.0`
- Already sets `OPENZIM_MCP_TRANSPORT=http`, `OPENZIM_MCP_HOST=0.0.0.0`, `OPENZIM_MCP_PORT=8000` as ENV — recipes do **not** need to set these
- ENTRYPOINT: `python -m openzim_mcp /data` (positional arg = allowed dir)
- VOLUME: `/data` — ZIM files mount here
- HEALTHCHECK: `curl -fsS http://localhost:8000/readyz` already baked in
- Runs as non-root (`appuser` UID 10001)
- EXPOSE 8000

**README link to update:** [README.md:41](../../../README.md#L41), the substring `https://github.com/cameronrye/openzim-mcp/wiki/Deployment-Guide` becomes `docs/deployment.md`.

---

### Task 1: Confirm Claude Desktop / Cursor HTTP+token client config

The spec flagged this as needing implementation-time verification. The README's MCP-client snippets only show stdio (`command` + `args`). HTTP-transport client config varies between clients and is the most likely thing to bit-rot in this doc.

**Files:** none modified — this is a research step.

- [ ] **Step 1: Check Claude Desktop docs**

Search for the current schema for connecting Claude Desktop to a remote MCP server over HTTP with a bearer token. Likely sources: `https://modelcontextprotocol.io/`, `https://docs.anthropic.com/en/docs/claude-code/mcp`, the official Anthropic MCP docs.

What we want to know: in `claude_desktop_config.json`, what does an HTTP+bearer entry look like? Is it `"url"` and `"headers"`? Is it `"type": "http"`? Does Claude Desktop even support HTTP transport yet, or is it stdio-only with `mcp-remote` as a bridge?

- [ ] **Step 2: Check Cursor docs**

Same question for Cursor's MCP settings. Cursor has historically supported HTTP MCP servers natively.

- [ ] **Step 3: Decide which clients to show in the recipe**

Outcomes and what to do for each:

- **Both clients support HTTP+bearer natively with a stable schema** → show both JSON snippets in Recipe 1.
- **Only Cursor supports it natively, Claude Desktop needs `mcp-remote`** → show Cursor JSON, show the `mcp-remote` bridge command for Claude Desktop, with a one-sentence note that Anthropic is expected to add native HTTP support and the recipe will be updated then.
- **Schema is unstable / under-documented** → show a plain `curl` smoke-test against `https://your.host/mcp` (the URL+token is what matters; the JSON wrapping is per-client) and link out to each client's own docs.

Pick whichever outcome matches reality and use it in Task 4.

- [ ] **Step 4: Record what you found in a scratch note**

Keep the verbatim JSON / command(s) on hand — Task 4 step 4 pastes them into the recipe.

No commit for this task.

---

### Task 2: Create `docs/deployment.md` with skeleton + intro

This task creates the file and writes the top-of-document content. Subsequent tasks fill in each section.

**Files:**

- Create: `docs/deployment.md`

- [ ] **Step 1: Create the file with the skeleton**

Write `docs/deployment.md` with the following content. Section bodies for §2–§5 are stubs that later tasks fill in — keep them as-is for now so the document compiles cleanly.

````markdown
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

*(filled in by Task 3)*

## Recipe 1: Docker Compose on a LAN host

*(filled in by Task 4)*

## Recipe 2: VPS with Caddy and automatic TLS

*(filled in by Task 5)*

## Operations

*(filled in by Task 6)*
````

- [ ] **Step 2: Run markdownlint to check formatting**

Run:

```bash
pre-commit run markdownlint --files docs/deployment.md
```

Expected: PASS, or auto-fix and PASS on a re-run. If it auto-modifies the file, accept the changes and continue.

- [ ] **Step 3: Visual check**

Open the file and confirm:

- All four section headers are present
- The intro paragraph reads cleanly
- Anchor links in the Contents block match the section header slugs (markdownlint will not catch broken anchors — eyeball them)

- [ ] **Step 4: Commit**

```bash
git add docs/deployment.md
git commit -m "docs(deployment): add guide skeleton"
```

---

### Task 3: Fill in the Reference section

**Files:**

- Modify: `docs/deployment.md` — replace the `*(filled in by Task 3)*` line under `## Reference: deployment-relevant configuration`.

- [ ] **Step 1: Replace the placeholder with the reference content**

Use Edit to replace the line `*(filled in by Task 3)*` (under the `## Reference: deployment-relevant configuration` header) with this content:

````markdown
The README contains the full environment variable table at [Configuration Options](../README.md#configuration-options). This section explains the subset that matters for deployment, with the operational reasoning behind each one.

### Transport choice (`OPENZIM_MCP_TRANSPORT`)

| Value | Use it for | Notes |
| --- | --- | --- |
| `stdio` (default) | Local clients launching the server as a subprocess | Don't deploy this. The README quick-start covers it. |
| `http` | All long-running deployments | Recommended. Bearer-token auth, CORS, health probes. |
| `sse` | Legacy clients still on Server-Sent Events | No auth/CORS/health middleware. **Refuses to start** if bound to anything other than `127.0.0.1` / `::1` / `localhost`. |

The `http` transport refuses to bind a non-loopback host (e.g. `0.0.0.0`) unless `OPENZIM_MCP_AUTH_TOKEN` is set. This is a startup check, not a runtime one — a misconfigured server fails fast with a clear error.

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
````

- [ ] **Step 2: Run markdownlint**

```bash
pre-commit run markdownlint --files docs/deployment.md
```

Expected: PASS (auto-fix and re-run if needed).

- [ ] **Step 3: Visual check**

Read through the section. Confirm every variable name is one of the seven in the "Background facts" table at the top of this plan — do not introduce names that don't exist in the README.

- [ ] **Step 4: Commit**

```bash
git add docs/deployment.md
git commit -m "docs(deployment): add reference section"
```

---

### Task 4: Fill in Recipe 1 (LAN + Tailscale callout)

**Files:**

- Modify: `docs/deployment.md` — replace the `*(filled in by Task 4)*` line under `## Recipe 1: Docker Compose on a LAN host`.

- [ ] **Step 1: Replace the placeholder with the recipe content**

Use Edit. The client-config snippet below uses **placeholder syntax** that you must replace based on your Task 1 research before pasting. Look for `<<<CLIENT_SNIPPET>>>` and substitute the real JSON or fallback content.

````markdown
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
- **Token via env, not hard-coded**. Put it in a `.env` file next to the compose file (and add `.env` to `.gitignore`). The image's defaults already set `TRANSPORT=http`, `HOST=0.0.0.0`, `PORT=8000`, so they're not repeated here.

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

<<<CLIENT_SNIPPET>>>

### Tailscale variant

To reach the server from your tailnet instead of the LAN, change exactly one line in `docker-compose.yml`:

```yaml
    ports:
      - "100.x.y.z:8000:8000"  # your Tailscale IPv4, from `tailscale ip -4`
```

Then make sure the host firewall blocks port 8000 on the public interface (it should already, since you're not publishing on `0.0.0.0`). The bearer token plus tailnet ACLs are your trust boundary; you don't need TLS because the tailnet itself is encrypted.
````

- [ ] **Step 2: Replace `<<<CLIENT_SNIPPET>>>` with the result of Task 1**

Pick the variant that matches what you found:

**Variant A — both Claude Desktop and Cursor support HTTP+bearer natively:**

````markdown
Add to your client's MCP config. Substitute the host, port, and token.

**Claude Desktop** (`claude_desktop_config.json`):

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

**Cursor** (Settings → MCP):

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
````

(Adjust the JSON keys to whatever Task 1 found — the structure above is illustrative; if the real schema is different, write the real one.)

**Variant B — Claude Desktop needs `mcp-remote`, Cursor is native:**

````markdown
Add to your client's MCP config. Substitute the host, port, and token.

**Cursor** (Settings → MCP) — native HTTP support:

```json
{
  "mcpServers": {
    "openzim-mcp": {
      "url": "http://127.0.0.1:8000/mcp",
      "headers": { "Authorization": "Bearer YOUR_TOKEN_HERE" }
    }
  }
}
```

**Claude Desktop** — bridge stdio to HTTP via `mcp-remote`:

```json
{
  "mcpServers": {
    "openzim-mcp": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "http://127.0.0.1:8000/mcp",
        "--header",
        "Authorization: Bearer YOUR_TOKEN_HERE"
      ]
    }
  }
}
```

(`mcp-remote` is a community bridge maintained by the MCP project. Native HTTP support in Claude Desktop is on the roadmap; this guide will switch to the native form once it ships.)
````

**Variant C — schema is unclear or under-documented:**

````markdown
Connect any MCP client that supports the streamable HTTP transport by pointing it at `http://127.0.0.1:8000/mcp` with an `Authorization: Bearer YOUR_TOKEN_HERE` header. Each client wraps this differently in its config; consult your client's MCP documentation for the exact JSON.

A bare smoke test:

```bash
curl -sf -X POST http://127.0.0.1:8000/mcp \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```
````

- [ ] **Step 3: Run markdownlint**

```bash
pre-commit run markdownlint --files docs/deployment.md
```

Expected: PASS.

- [ ] **Step 4: Sanity-check the YAML in your head**

The compose snippet has indentation that markdownlint won't validate. Confirm that:

- Top-level keys (`services:`) have zero indent
- Service names (`openzim-mcp:`) have two-space indent
- Service properties (`image:`, `ports:`, etc.) have four-space indent
- List items under `ports:`/`volumes:` have six-space indent + dash

If your editor has a YAML linter, paste the snippet through it.

- [ ] **Step 5: Commit**

```bash
git add docs/deployment.md
git commit -m "docs(deployment): add LAN/Tailscale recipe"
```

---

### Task 5: Fill in Recipe 2 (VPS + Caddy)

**Files:**

- Modify: `docs/deployment.md` — replace the `*(filled in by Task 5)*` line under `## Recipe 2: VPS with Caddy and automatic TLS`.

- [ ] **Step 1: Replace the placeholder with the VPS recipe**

Use Edit:

````markdown
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

```
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
````

- [ ] **Step 2: Run markdownlint**

```bash
pre-commit run markdownlint --files docs/deployment.md
```

Expected: PASS.

- [ ] **Step 3: YAML sanity-check**

Same checks as Task 4 step 4 — indentation matters. The Caddyfile is not YAML; it's a Caddy DSL, where leading whitespace is decorative.

- [ ] **Step 4: Commit**

```bash
git add docs/deployment.md
git commit -m "docs(deployment): add VPS recipe with Caddy"
```

---

### Task 6: Fill in the Operations section

**Files:**

- Modify: `docs/deployment.md` — replace the `*(filled in by Task 6)*` line under `## Operations`.

- [ ] **Step 1: Replace the placeholder with the operations content**

Use Edit:

````markdown
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
- **`/readyz` returns 503.** The configured ZIM directory isn't readable from inside the container. Check the volume mount path (host side and `/data` side) and that the mount isn't empty. Permissions: the in-container user is UID 10001; the host directory needs to be world-readable or owned by UID 10001.
- **Subscriptions stop firing.** Confirm `OPENZIM_MCP_SUBSCRIPTIONS_ENABLED` isn't set to `false`. If a client claims it subscribed but never gets updates, check that the subscribe call actually returned a successful response — clients silently treating a failed subscription as success is a known footgun.
````

- [ ] **Step 2: Run markdownlint**

```bash
pre-commit run markdownlint --files docs/deployment.md
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add docs/deployment.md
git commit -m "docs(deployment): add operations section"
```

---

### Task 7: Update the README link

**Files:**

- Modify: [README.md:41](../../../README.md#L41) — replace the wiki URL with a relative link to the new doc.

- [ ] **Step 1: Read the current line for context**

```bash
grep -n "Deployment-Guide\|Deployment Guide" README.md
```

Expected: shows line 41 (the v1.0.0 callout containing `[Deployment Guide](https://github.com/cameronrye/openzim-mcp/wiki/Deployment-Guide)`).

- [ ] **Step 2: Replace the URL**

Use Edit:

- `old_string`: `[Deployment Guide](https://github.com/cameronrye/openzim-mcp/wiki/Deployment-Guide)`
- `new_string`: `[Deployment Guide](docs/deployment.md)`

- [ ] **Step 3: Verify the link target exists**

```bash
test -f docs/deployment.md && echo "target exists"
```

Expected: `target exists`.

- [ ] **Step 4: Run markdownlint on the README**

```bash
pre-commit run markdownlint --files README.md
```

Expected: PASS (the README already passes lint; this is a single-line change so should be fine).

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs(readme): point Deployment Guide link at docs/deployment.md"
```

---

### Task 8: Final verification

**Files:** none modified — this is a verification-only task.

- [ ] **Step 1: Run the full pre-commit suite on changed files**

```bash
pre-commit run --files docs/deployment.md README.md
```

Expected: all checks PASS.

- [ ] **Step 2: Confirm no broken internal links inside `docs/deployment.md`**

The doc references:

- `../README.md#quick-start` (in the intro)
- `../README.md#configuration-options` (in the reference section)

Verify both anchors exist:

```bash
grep -n "^## Quick Start\|^## Configuration Options" README.md
```

Expected: two matches. (Markdown anchors are derived from header text — `## Quick Start` becomes `#quick-start`, `### Configuration Options` becomes `#configuration-options`.) If the README's section names differ, update the anchors in `docs/deployment.md` to match.

- [ ] **Step 3: End-to-end read-through**

Read `docs/deployment.md` top to bottom one time. Look for:

- Any leftover `*(filled in by Task N)*` placeholders (there should be none)
- Any `<<<CLIENT_SNIPPET>>>` marker (Task 4 should have replaced it)
- Tone/flow breaks where one task's prose meets the next
- Any var name not in the Background-facts table at the top of this plan

Fix anything off, commit if you did, then move on.

- [ ] **Step 4: Confirm git history is clean**

```bash
git log --oneline -10
```

Expected last commits (in this order, most recent first):

1. `docs(readme): point Deployment Guide link at docs/deployment.md`
2. `docs(deployment): add operations section`
3. `docs(deployment): add VPS recipe with Caddy`
4. `docs(deployment): add LAN/Tailscale recipe`
5. `docs(deployment): add reference section`
6. `docs(deployment): add guide skeleton`
7. `docs: spec for Deployment Guide` (already on `main` from before the plan ran)

If any commit is missing, the corresponding task's content is unstaged or uncommitted — go back and resolve.

- [ ] **Step 5: Push (optional, user's call)**

The plan does not push automatically. Confirm with the user whether to push to `origin/main` or leave the commits local. If the user says push:

```bash
git push origin main
```

---

## Spec coverage check

Cross-reference of spec requirements → task that implements them:

| Spec section | Task |
| --- | --- |
| Decision: in-repo doc, README link change | Task 2 (file creation), Task 7 (README) |
| §1 "When to use this guide" | Task 2 |
| §2 Reference (Transport, Auth, CORS, Health, Subscriptions, README pointer) | Task 3 |
| §3 Recipe 1 (Compose, prereqs, verification, client snippet, Tailscale callout) | Task 4 |
| §4 Recipe 2 (Compose+Caddy, Caddyfile, nginx pointer, verification, hardening) | Task 5 |
| §5 Operations (upgrades, logs, failure modes) | Task 6 |
| Implementation-time check on MCP client config schema | Task 1 |
| Length target ~400-600 lines | All — natural outcome of the section content above |

No gaps.
