# Live tests

End-to-end tests that spawn a real `openzim-mcp` subprocess and exercise
behavior unreachable from in-process unit tests: HTTP transport, SSE
transport, MCP prompts over the wire, mtime-driven subscriptions, and
cache persistence across restarts.

## How to run

```bash
make test-live                       # all live tests (incl. docker if daemon up)
make test-live-docker                # docker tests only (auto-skips w/o daemon)
uv run pytest -m live                # equivalent of make test-live
uv run pytest -m "live and not docker"  # skip the slow docker build
uv run pytest -m live tests/live/test_live_http.py  # one file
```

These tests are **excluded from the default `make test` run** via
`addopts = -m 'not live'` in `pyproject.toml`. Opt in with `-m live`.

The `docker` marker is layered on top of `live` for tests that
additionally need the docker CLI and a reachable daemon — they
auto-skip otherwise, so you don't need to remember to filter.

## Requirements

- A directory containing at least one `.zim` file.
  Default: `~/Developer/zim`. Override with `ZIM_TEST_DATA_DIR`.
- Free loopback ports: each test asks the kernel for a fresh port via
  `127.0.0.1:0`, so they don't collide with each other or with anything
  else on the machine.
- The local `openzim_mcp` package (run via `python -m openzim_mcp`); the
  fixture uses `sys.executable` so the source tree is exercised, not
  whatever is installed on `PATH`.

## What each file covers (mapped to CHANGELOG v1.0.0)

| File | v1.0 features |
|------|---------------|
| `test_live_http.py` | HTTP transport (auth, CORS allow-list, `/healthz`, `/readyz`, `OPTIONS /mcp` requires auth, safe-default refusal of public-host bind without token, two-instance coexistence) |
| `test_live_sse.py` | Legacy SSE transport (`--transport sse`), safe-default refusal |
| `test_live_prompts.py` | MCP prompts (`/research`, `/summarize`, `/explore`) including v1.0 sanitization (control-char strip, length cap, ask-for-input fallback) |
| `test_live_subscriptions.py` | `MtimeWatcher` + `notifications/resources/updated` over streamable-HTTP |
| `test_live_cache_persistence.py` | Cache `persistence_path` survives a graceful shutdown / restart |
| `test_live_docker.py` | `docker build` + `docker run` smoke: image boots, runs as `appuser` (uid 10001), `/healthz`+`/readyz` work, bearer auth on `/mcp`, `HEALTHCHECK` directive present. Auto-skips when docker daemon unavailable. First build may take ~10 min; subsequent runs reuse layer cache (~20s). |

## Intentionally not live-tested

**Per-client HTTP rate-limiting (CHANGELOG: "infrastructure ready for
HTTP context wiring").** The per-`(client_id, operation)` token-bucket
logic is fully exercised by `tests/test_rate_limiter.py`. As of v1.0.0
the HTTP layer (`openzim_mcp/http_app.py`) does not yet read a client
identifier off any header — every request is charged against
`client_id="default"`. Once the HTTP middleware is wired to populate
`client_id` from `X-Client-Id` (or whatever scheme lands), add a
`test_live_rate_limit.py` here that fires N requests under M distinct
client IDs and asserts:

1. Per-client buckets isolate one noisy neighbour from another.
2. After 10k+ distinct client IDs, LRU eviction kicks in (the cap
   defined in `RateLimitConfig`).

_(Docker image build/run is now covered by `test_live_docker.py`; it
auto-skips when the daemon isn't reachable, so it costs nothing on
machines without docker.)_

## Adding a new live test

1. Add the file under `tests/live/`.
2. Mark it: `pytestmark = pytest.mark.live`.
3. Use `spawn_live_server` (factory fixture) for any subprocess: it
   handles port allocation, env composition (auth token, CORS,
   persistence path, etc.), readiness polling, and teardown.
4. Use `expect_failed_startup(...)` for cases that should refuse to
   start (e.g. safe-default-host check).

The fixture file `conftest.py` is a Tier-1 read for understanding the
spawn/teardown contract.
