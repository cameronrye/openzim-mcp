# Deployment Guide — Design

## Background

[README.md:41](../../../README.md#L41) advertises a "Deployment Guide" at
`https://github.com/cameronrye/openzim-mcp/wiki/Deployment-Guide`, but no such
page exists. The link is a promise that needs a target.

The README already carries the substance of a deployment guide
(HTTP-transport behaviour, env-var table at line 1369+, safe-startup checks,
Docker image tag), but it isn't structured for someone who lands with the
question "how do I run this thing in production?" — that audience needs
end-to-end recipes, not a feature pitch interleaved with reference material.

## Goal

Give operators a single document they can read top-to-bottom and end up with a
working `--transport http` deployment, without having to reverse-engineer the
README.

## Non-goals

- Non-Docker (systemd) deployments — Docker is the supported path
- Kubernetes manifests
- nginx config — Caddy is the worked example; nginx gets one sentence
- Backup/restore — ZIM files are read-only static archives, out of scope
- Monitoring stack (Prometheus/Grafana) — out of scope
- stdio-mode setup — the README quick-start covers this

## Decision: in-repo, not wiki

The guide lives at `docs/deployment.md` in the main repo, not on the GitHub
wiki. The README link at line 41 changes from the wiki URL to a relative path
`docs/deployment.md`.

**Why in-repo:**

- Reviewable via PR
- Versioned with the code (a v1.0.0 deploy guide stays correct on the v1.0.0
  tag even after v1.1 ships)
- One source of truth — no risk of wiki drift
- The wiki was never populated, so changing the link costs nothing

**Why not also mirror to the wiki:** a CI sync action is moving parts to
maintain on a solo-maintained repo for negligible benefit.

## Document structure

Hybrid: a short topic-driven reference up top, then two end-to-end recipes
that cite back to the reference. Length target ~400-600 lines.

### 1. When to use this guide

One paragraph. stdio users (Claude Desktop, Cursor as a local subprocess)
should stay on the README. This guide is for `--transport http` long-running
deployments — homelab servers, Tailscale tailnets, public VPSes.

### 2. Reference (the "knobs" section)

Short, scannable. Each sub-section is a few sentences plus a code block.

- **Transport choice** — `stdio` (default), `http` (recommended for
  deployments), `sse` (legacy; refuses non-localhost binds without a token).
  Spell out the safe-default-startup behaviour: HTTP refuses to bind a
  non-localhost host without `OPENZIM_MCP_AUTH_TOKEN` set.
- **Bearer-token auth** — how to generate (`openssl rand -hex 32`), where to
  set it (`OPENZIM_MCP_AUTH_TOKEN` env), timing-safe comparison note, the
  attempted token is never logged.
- **CORS allow-list** — `OPENZIM_MCP_CORS_ORIGINS` is a JSON array, wildcard
  `*` is rejected at startup, exact origins only.
- **Health probes** — `/healthz` (liveness, always 200 if process is up),
  `/readyz` (readiness, 200 only if at least one allowed dir is readable).
  Both endpoints are auth-exempt so probes work cleanly.
- **Resource subscriptions** — `OPENZIM_MCP_WATCH_INTERVAL_SECONDS` (default
  5s), `OPENZIM_MCP_SUBSCRIPTIONS_ENABLED=false` to disable.
- **Pointer back** to the README's full env-var table rather than
  duplicating it. (Anchors the reader; one source of truth for the table.)

### 3. Recipe 1: Docker Compose on a LAN host (with Tailscale variant)

End-to-end, copy-paste-able.

**Prereqs section:**

- Docker + Docker Compose installed
- A directory of ZIM files (link to Kiwix Library)
- A generated bearer token (`openssl rand -hex 32`)

**`docker-compose.yml`:**

- Service uses `ghcr.io/cameronrye/openzim-mcp:1.0.0` (pinned tag, with a
  one-line note on why pinning matters)
- Port published as `127.0.0.1:8000:8000` (LAN-only by default)
- ZIM directory mounted read-only at `/data/zim`
- `OPENZIM_MCP_*` env block: `TRANSPORT=http`, `HOST=0.0.0.0` (inside
  container; the host-side `127.0.0.1` bind handles exposure),
  `PORT=8000`, `AUTH_TOKEN`, `ALLOWED_DIRECTORIES=/data/zim`
- Healthcheck: `curl -f http://localhost:8000/readyz`
- `restart: unless-stopped`

**Verification:**

- `curl http://127.0.0.1:8000/readyz` returns 200
- An authed `tools/list` call returns the expected tool count

**Client config snippet:**

- Claude Desktop / Cursor JSON pointing at the HTTP URL with the bearer
  token in the `Authorization` header. (Implementation-time check: confirm
  the exact MCP client config schema currently in use — the snippet must
  match what Claude Desktop and Cursor accept today.)

**Tailscale callout (boxed note, not a separate recipe):**

- Change the host port bind from `127.0.0.1:8000:8000` to
  `<tailnet-ip>:8000:8000` (get it from `tailscale ip -4`)
- Confirm the host firewall blocks 8000 on the public interface
- Everything else is identical
- One sentence on why this works: the bearer token + tailnet ACLs are the
  trust boundary; no public TLS needed because the tailnet is encrypted

### 4. Recipe 2: VPS with Caddy + automatic TLS

Builds on Recipe 1's `docker-compose.yml` with two changes: (a) add a `caddy`
service in the same file, (b) drop the host port publish from the
openzim-mcp service so 8000 is reachable only on the internal Docker network.
The recipe shows the full updated file rather than a diff.

**Prereqs section:**

- A VPS with a public IP
- A DNS A/AAAA record pointing at it
- Ports 80 and 443 open
- Same bearer token + ZIM dir as Recipe 1

**Compose additions:**

- `caddy` service using the official `caddy` image
- Volumes for `caddy_data` and `caddy_config` (cert persistence)
- Bind 80 and 443 publicly; the openzim-mcp service drops back to internal
  network only (no host port published)
- `Caddyfile` mounted into the caddy container

**`Caddyfile` (~6 lines):**

```
your.host.example {
    reverse_proxy openzim-mcp:8000
}
```

Caddy auto-provisions a Let's Encrypt cert and forwards `Authorization`
headers untouched.

**nginx pointer (one sentence):** users who already run nginx can substitute
it for Caddy — the only requirement is forwarding the `Authorization` header
unchanged. No worked example.

**Verification:**

- `curl -v https://your.host.example/healthz` shows a valid TLS chain
- An authed `tools/list` call against `https://your.host.example/mcp`
  succeeds

**Hardening checklist:**

- Token rotation cadence (rotate token, restart container)
- Set `OPENZIM_MCP_CORS_ORIGINS` to your client's exact origin if a browser
  client connects directly
- Confirm the container runs as non-root (already does in the published
  image — sentence to that effect)
- Log review: tail `docker compose logs -f openzim-mcp` for auth failures

### 5. Operations

Short — a few hundred words.

- **Upgrades** — `docker compose pull && docker compose up -d`. Why pin the
  tag (predictable rollouts; explicit upgrade is a deliberate action, not a
  surprise from a `:latest` pull).
- **Watching logs** — what normal startup looks like, what an auth failure
  looks like, how resource-subscription notifications appear.
- **Common failure modes:**
  - Server refuses to start: usually non-localhost host without a token, or
    rejected wildcard CORS. Error message points at which.
  - 401 from clients: token missing or wrong. Curl one-liner to test.
  - 403/CORS errors in browser clients: missing or wrong
    `OPENZIM_MCP_CORS_ORIGINS`.
  - `/readyz` failing: `OPENZIM_MCP_ALLOWED_DIRECTORIES` not mounted or not
    readable inside the container.

## Files changed

| File | Change |
| --- | --- |
| `docs/deployment.md` | New file. The structure above. |
| `README.md` | Line 41: replace `https://github.com/cameronrye/openzim-mcp/wiki/Deployment-Guide` with `docs/deployment.md`. No other edits. |

## Open questions

None — design is closed.

## Out-of-band followups

- If the wiki page is later requested by users (analytics, issues), revisit
  whether to mirror via CI. Default is to do nothing.
- If the guide grows past ~800 lines, split into `deployment.md` (recipes)
  and `deployment-reference.md` (reference). Not anticipated for v1.
