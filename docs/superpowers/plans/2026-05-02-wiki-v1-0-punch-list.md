# Wiki v1.0.0 Audit — Punch List

Generated 2026-05-02 against the v1.0.0 changelog. Wiki repo cloned at `/tmp/openzim-mcp.wiki/`. Authoritative source for any conflict: code in `/Users/cameron/Developer/openzim-mcp-v1.0/`.

## Verdict matrix

| Page | Verdict |
|------|---------|
| Home.md | rewrite |
| Quick-Start-Tutorial.md | surgical |
| Installation-Guide.md | surgical |
| Configuration-Guide.md | rewrite (60% fictional env vars) |
| FAQ.md | surgical |
| API-Reference.md | rewrite (missing 7 tools, includes 2 removed) |
| Smart-Retrieval-System-Guide.md | rewrite (60-70% invented) |
| Architecture-Overview.md | rewrite |
| Multi‐Instance-Management-Guide.md | DELETE (feature removed) |
| Performance-Optimization-Guide.md | rewrite |
| Security-Best-Practices.md | rewrite (fictional Python, fabricated env vars) |
| LLM-Integration-Patterns.md | surgical |
| Release-System-Guide.md | surgical |
| Troubleshooting-Guide.md | surgical |

**Tally:** 1 delete, 7 rewrites, 6 surgical.

## Cross-cutting scrubs (apply everywhere)

### Removed tools (grep & purge across all pages)

`warm_cache`, `cache_stats`, `cache_clear`, `get_random_entry`, `diagnose_server_state`, `resolve_server_conflicts`

### Fictional env vars (do not exist in `openzim_mcp/config.py`)

- `OPENZIM_MCP_INSTANCE__*` (entire namespace — feature removed)
- `OPENZIM_MCP_SECURITY__*` (entire namespace — no SecurityConfig)
- `OPENZIM_MCP_SMART_RETRIEVAL__*` (entire namespace)
- `OPENZIM_MCP_METRICS__*` (entire namespace)
- `OPENZIM_MCP_SERVER__MAX_CONCURRENT`, `OPENZIM_MCP_SERVER__REQUEST_TIMEOUT`, `OPENZIM_MCP_SERVER__ENABLE_MONITORING`, `OPENZIM_MCP_SERVER_DESCRIPTION`
- `OPENZIM_MCP_LOGGING__JSON`, `OPENZIM_MCP_LOGGING__SECURITY_EVENTS`
- `OPENZIM_MCP_CONTENT__CONVERT_HTML`, `OPENZIM_MCP_CONTENT__PRESERVE_FORMATTING`

### Real env-var surface (from `openzim_mcp/config.py` + `defaults.py`)

- Top-level: `OPENZIM_MCP_SERVER_NAME`, `OPENZIM_MCP_TOOL_MODE` (simple/advanced), `OPENZIM_MCP_TRANSPORT` (stdio/http/sse), `OPENZIM_MCP_HOST`, `OPENZIM_MCP_PORT`, `OPENZIM_MCP_AUTH_TOKEN`, `OPENZIM_MCP_CORS_ORIGINS`, `OPENZIM_MCP_WATCH_INTERVAL_SECONDS` (default 5, 1-60), `OPENZIM_MCP_SUBSCRIPTIONS_ENABLED` (default true)
- Cache: `OPENZIM_MCP_CACHE__ENABLED`, `__MAX_SIZE`, `__TTL_SECONDS`, `__PERSISTENCE_ENABLED`, `__PERSISTENCE_PATH`
- Content: `OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH` (default 100000, min 100), `__SNIPPET_LENGTH`, `__DEFAULT_SEARCH_LIMIT`
- Logging: `OPENZIM_MCP_LOGGING__LEVEL`, `__FORMAT`
- Rate limit: `OPENZIM_MCP_RATE_LIMIT__ENABLED`, `__REQUESTS_PER_SECOND` (default 10.0), `__BURST_SIZE` (≤1000), `__PER_OPERATION_LIMITS` (nested dict)

### Deleted artifacts referenced as live

- `instance_tracker.py` — purged in 1.0
- `~/.openzim_mcp_instances/` — no longer created
- `instance_tracking` block in `get_server_health` response — never emitted

### PID redaction

Every example showing `process_id: 12345` or `server_pid: 12345` must be `[REDACTED]`. Unconditional in 1.0 (`security.py` `_ABS_PATH_RE` + tools/server_tools.py).

### Real `get_server_health` response shape

`{timestamp, status, server_name, uptime_info{process_id:"[REDACTED]", started_at}, configuration, cache_performance{enabled, size, max_size, ttl_seconds, hits, misses, hit_rate}, health_checks, recommendations, warnings}`

### Real `get_server_configuration` response shape

`{configuration{allowed_directories, allowed_directories_count, cache_enabled, cache_max_size, cache_ttl_seconds, content_max_length, content_snippet_length, search_default_limit, config_hash, server_pid:"[REDACTED]"}, diagnostics{validation_status, warnings, recommendations}, timestamp}`

## Tool surface (21 advanced tools as of 1.0)

| Category | Tools |
|----------|-------|
| File | `list_zim_files` (NEW: `name_filter`) |
| Content | `get_zim_entry` (NEW: `content_offset`), `get_zim_entries` (NEW batch, ≤50) |
| Navigation | `browse_namespace`, `walk_namespace`, `search_with_filters`, `get_search_suggestions` |
| Metadata | `get_zim_metadata`, `get_main_page`, `list_namespaces` |
| Structure | `get_article_structure`, `extract_article_links`, `get_entry_summary`, `get_table_of_contents`, `get_binary_entry`, `get_related_articles` |
| Server | `get_server_health`, `get_server_configuration` |
| Search | `search_zim_file` (NEW: `cursor`), `search_all`, `find_entry_by_title` |

Plus simple-mode tool `zim_query` (default), 3 prompts (`research`/`summarize`/`explore`), and resources (`zim://files`, `zim://{name}`, `zim://{name}/entry/{path}`).

## Per-page punch lists

### Home.md — rewrite

- Line 5: drop "NEW: Binary Content Retrieval!" banner; replace with v1.0 hero (HTTP transport, dual mode, batch, per-entry resources, subscriptions)
- Line 47: demote Binary Content from lead Enterprise feature
- Line 79: version 0.8.0 → 1.0.0
- Line 82: test coverage claim 90%+ → match README ("80%+")
- Add: dual-mode mention (Simple default), HTTP/Deployment link, Prompts and Resources mentions

### Quick-Start-Tutorial.md — surgical

- Lines 56-63 / 240-245: replace fabricated "Expected Output" block with real banner from `main.py:118-128` ("OpenZIM MCP server started in SIMPLE mode (...)" + "Allowed directories: ...")
- Line 199: qualify health-check verification ("in Advanced mode...") or rewrite as Simple-mode NL example
- Add: one-liner on default Simple mode + `--mode advanced`
- Add: HTTP/Docker quick-start option pointing to new deployment guide

### Installation-Guide.md — surgical

- Line 9: verify Python 3.13 claim against `pyproject.toml`
- Lines 203-205: replace "Docker Installation (Coming Soon)" with real instructions (`ghcr.io/cameronrye/openzim-mcp:1.0.0`, multi-arch, non-root, healthcheck)
- Lines 240-245: same banner-output fix as Quick-Start
- Add: HTTP transport quick-start (`--transport http`, auth token, host/port, safe-default refusal); mode selection note

### Configuration-Guide.md — rewrite

- Line 36: "Advanced Mode: 15 tools" → 21 tools
- Lines 96-101: delete fictional `CONTENT__CONVERT_HTML`/`PRESERVE_FORMATTING`
- Line 116: delete fictional `LOGGING__JSON`
- Lines 142-157: delete fictional `SERVER_DESCRIPTION`/`SERVER__*`
- Lines 159-237: delete entire `OPENZIM_MCP_SECURITY__*` and `OPENZIM_MCP_INSTANCE__*` sections (none exist)
- Lines 239-296: delete entire `OPENZIM_MCP_SMART_RETRIEVAL__*` section
- Lines 298-345: rewrite "Complete Configuration Reference" against real config schema
- Lines 451-476: delete `MONITORING__`/`METRICS__` sections
- Line 484: replace `diagnose_server_state` example with `get_server_configuration`
- Add: full HTTP transport block, subscription block, cache persistence block, rate-limit block

### FAQ.md — surgical

- Lines 204-206: rewrite multi-instance answer ("Multiple HTTP instances coexist freely; no conflict tooling needed")
- Lines 304-312: drop "Docker container support" and "Enhanced multi-instance management" from Future Plans
- Add: Q on HTTP/network/Docker; Q on Simple vs Advanced mode; Q on resource subscriptions; Q on binary content; Q on batch retrieval

### API-Reference.md — rewrite

- Line 11 `list_zim_files`: add `name_filter` param
- Lines 41-66 `search_zim_file`: add `cursor` param, mark `query` conditionally required
- Lines 68-97 `get_zim_entry`: add `content_offset` param; `min_length` is **100** not 1000
- Line 124 `get_main_page`: clarify resolution via `archive.main_entry` with W fallback
- Lines 754-808 `get_server_health`: replace fabricated response with real shape; PID `[REDACTED]`; remove `instance_tracking` block
- Lines 811-857 `get_server_configuration`: replace fictional response shape; PID `[REDACTED]`
- Lines 859-913: delete `diagnose_server_state` (removed)
- Lines 915-964: delete `resolve_server_conflicts` (removed)
- Lines 966-1006: delete fictional response envelope and error code table
- Add 7 missing tools: `get_zim_entries`, `walk_namespace`, `get_related_articles`, `search_all`, `find_entry_by_title`, `zim_query` (cross-ref)
- Add: MCP Resources section, Subscriptions section, Prompts section, path-redaction note

### Smart-Retrieval-System-Guide.md — rewrite

- Lines 24-38: replace 7-stage diagram with real 4-step flow (cache check → direct → search-derived terms → cache mapping)
- Lines 46-54: rewrite Stage 1 pseudocode to reference real `_get_entry_content_direct`
- Lines 60-65: cache key is `path_mapping:{validated_path}:{entry_path}` (archive-scoped)
- Lines 71-97: drop "Strategy 4 Fuzzy Matching" (doesn't exist); list real candidate-term derivation
- Lines 99-122: delete `score_match` weighting (doesn't exist) — real check is `_is_path_match` first-match
- Lines 125-135: drop `ttl=3600` from `path_cache.set` example
- Lines 138-165: replace invented cache JSON with 1-2 line description
- Lines 169-185: delete confidence-tiered TTL (no confidence value exists)
- Lines 199-216: drop fabricated `Retrieval Method:` line from response example
- Lines 282-295: delete `smart_retrieval_stats` JSON block
- Lines 329-366: delete entire Configuration section (env vars don't exist)
- Lines 380-392: delete `smart_retrieval` block in health response
- Lines 396-420: delete `diagnose_server_state` subsection
- Lines 437-462: rewrite Solutions to reference real cache config
- Lines 481-497: replace `curl` example with real MCP transport call
- Add: smart retrieval also covers `get_binary_entry`/`get_article_structure`/`extract_article_links`/`get_table_of_contents`/`get_entry_summary`
- Add: redirect-following with `MAX_REDIRECT_DEPTH = 10`

### Architecture-Overview.md — rewrite

- Lines 17-20 / 41: drop Instance Tracker from layer diagrams; add HTTP/SSE Transport box, Subscriptions box
- Lines 111-125: rewrite Section 5 — `zim_operations.py` is a 39-line shim; real code is `openzim_mcp/zim/` package with `_SearchMixin`/`_ContentMixin`/`_StructureMixin`/`_NamespaceMixin` composed in `zim/archive.py:184`
- Lines 127-141: delete entire Instance Tracker section
- Lines 205-219: rewrite module tree to mirror current README "Project Structure" — add `http_app.py`, `defaults.py`, `error_messages.py`, `rate_limiter.py`, `async_operations.py`, `timeout_utils.py`, `subscriptions.py`, `simple_tools.py`, `intent_parser.py`, `types.py`, `tools/` package, `zim/` package; remove `instance_tracker.py`
- Lines 222-239: update Module Responsibilities accordingly
- Lines 241-252: drop `security: SecurityConfig`, `instance: InstanceConfig` from `OpenZimMcpConfig` snippet
- Lines 257-269: drop `instance_tracker` arg from DI snippet
- Lines 282-285, 305-311, 412-419: remove `HealthMonitor`/`instance_tracker.get_status()` pseudocode
- Lines 326-341: revisit cache "L1/L2/L3" diagram — actual is single LRU+TTL
- Lines 438-470: delete entire Multi-Instance Management section
- Lines 495-500: rewrite Horizontal Scaling — "instances coexist freely behind a reverse proxy"
- Add: HTTP/SSE transport architecture, Subscriptions subsystem, Dual-mode design, Tools package layout, Resource architecture, Rate limiting, Path/PID redaction

### Performance-Optimization-Guide.md — rewrite

- Lines 22-62: replace fictional health response with real shape; drop `instance_tracking`/`request_metrics`/`smart_retrieval` blocks; PID `[REDACTED]`; cache fields are `hits`/`misses`/`hit_rate` only
- Lines 64-97: delete `diagnose_server_state` subsection (tool removed)
- Lines 99-116: drop Smart Retrieval Hit Rate / Fallback Success Rate KPIs (not exposed)
- Lines 144-182: rewrite `health_monitor.sh` against real JSON-RPC `tools/call` or use `/healthz` (auth-exempt)
- Lines 264-272: drop `openzim_instance_conflicts` Prometheus alert
- Lines 458-486: drop `OPENZIM_MCP_SERVER__MAX_CONCURRENT`, `__REQUEST_TIMEOUT` (not implemented)
- Lines 491-510: delete Multi-Instance Optimization section
- Lines 516-551: scrub `SERVER__MAX_CONCURRENT`/`REQUEST_TIMEOUT` from per-use-case bundles
- Lines 559-569: note that `warm_cache`/`cache_stats`/`cache_clear` tools are removed
- Add: HTTP transport perf section, real cache stats keys, batch retrieval (`get_zim_entries`), search cursor pagination, rate-limit config, multi-archive `search_all`

### Security-Best-Practices.md — rewrite

- Lines 11-49: replace fictional `validate_path_enterprise` block with real `PathValidator.validate_path` reference (`security.py`)
- Lines 53-87: delete fictional `OPENZIM_MCP_SECURITY__*` env vars
- Lines 89-141: delete entire Multi-Instance Security subsection
- Lines 265-279: replace fabricated "Built-in Limits" numbers with real values (content max 100000, sanitize_input max 1000)
- Lines 285-291: delete `LOGGING__JSON`/`__SECURITY_EVENTS`
- Lines 357-358: drop `diagnose_server_state` example
- Lines 415-430: rewrite Production Security Profile against real env vars
- Lines 434-452: drop "(Future)" qualifier on Container Security; reference real Dockerfile (non-root uid 10001, healthcheck, multi-arch ghcr.io)
- Lines 539-543: delete shipped items from "Future Enhancements" (auth, encrypted comm, rate limiting all shipped)
- Add: HTTP transport security model (bearer-token timing-safe, CORS allow-list, safe-default startup, SSE loopback-only, OPTIONS not exempt, /healthz auth-exempt); error path redaction; symlink-tightened archive validation; sanitized name_filter; self-referential refs rejected; prompts hardening; rate limiting atomic acquire; serverInfo.version correctness; SECURITY.md reference

### LLM-Integration-Patterns.md — surgical

- Lines 311-323: replace fictional `EntryNotFound` with real `OpenZimMcpArchiveError`/`OpenZimMcpValidationError`
- Lines 348-355: rewrite as `json.loads(get_server_health())["cache_performance"]["hit_rate"]`
- Lines 396-404: replace `search_across_zims` snippet with `search_all`
- Lines 414-422: rewrite to call real `get_related_articles`
- Lines 230-284: mention `find_entry_by_title` as title-lookup alternative
- Add: `find_entry_by_title`, `search_all`, `get_zim_entries`, `get_entry_summary`/`get_table_of_contents`, `walk_namespace` vs `browse_namespace`, MCP prompts, MCP resources (per-entry with %2F note), Simple mode (`zim_query`), HTTP transport batching considerations

### Release-System-Guide.md — surgical

- Lines 22-23 / 46: add Docker image publishing step to pipeline diagram
- Lines 195-216: replace `.release-please-config.json` snippet with real config (wrapped in `packages: {".": {...}}`, real section names `### Added`/`### Fixed`/etc., `extra-files` for `website/llm.txt`, `skip-github-release: true`, `bump-patch-for-minor-pre-major: false`)
- Lines 222-237 / 241-267: trim workflow snippets or update to real `release-please.yml`/`release.yml` (validate-and-prepare, trusted PyPI publishing, GitHub release notes from CHANGELOG)
- Lines 274-294: drop or update Release Statistics
- Lines 299-331: rewrite PyPI failure troubleshooting around Trusted Publishing
- Lines 376-404: drop Container Registry from Future (already shipped)
- Add: Docker pipeline (multi-arch ghcr.io), `extra-files` website/llm.txt bump, GitHub release split (release-please skip + release.yml creates), PyPI Trusted Publishing, version-sync validation job, tag-release fallback

### Troubleshooting-Guide.md — surgical

- Line 16: replace `diagnose_server_state` reference with `get_server_health` + `get_server_configuration`
- Lines 241-251: note explicit cache-management tools removed; restart is only flush
- Lines 278-305: delete entire Multi-Instance Issues section
- Lines 336-337: replace `diagnose_server_state` with health/config tools
- Add: HTTP transport failure surface (auth refusal, SSE loopback-only, 401 unauthorized, CORS, /etc/hosts remap, /healthz vs /readyz); per-entry resource %2F encoding; subscription troubleshooting; OpenZimMcpConfigurationError replaces pydantic dump; serverInfo.version correctness; path-traversal warning shows `...filename.zim`
- Line 354: drop "check pyproject.toml" — use `python -c "import openzim_mcp; print(openzim_mcp.__version__)"`

## New pages to add

### HTTP-and-Docker-Deployment.md

- `--transport http`/`sse`, host/port, auth token, CORS allow-list
- Safe-default startup check (refuses non-localhost without auth)
- `/healthz` (liveness, no auth) and `/readyz` (at least one allowed dir readable)
- Bearer-token middleware (timing-safe, OPTIONS not exempt)
- Mcp-Session-Id header in CORS allow/expose lists
- Docker image at `ghcr.io/cameronrye/openzim-mcp:1.0.0`, multi-arch, non-root uid 10001, healthcheck
- Reverse-proxy/TLS guidance
- Subscriptions over HTTP

### Resources-Prompts-Subscriptions.md

- Resources: `zim://files`, `zim://{name}`, `zim://{name}/entry/{path}` with %2F encoding caveat
- Prompts: `research`, `summarize`, `explore` (signatures + sample bodies)
- Subscriptions: subscribe to `zim://files` / `zim://{name}`, `notifications/resources/updated`, `OPENZIM_MCP_WATCH_INTERVAL_SECONDS`, `OPENZIM_MCP_SUBSCRIPTIONS_ENABLED`
