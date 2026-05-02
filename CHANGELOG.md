# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0](https://github.com/cameronrye/openzim-mcp/compare/v0.9.0...v1.0.0) (2026-05-01)

Includes an end-to-end review pass before tagging — security hardening, correctness fixes, performance work, and a refactor that splits `zim_operations.py` into a `zim/` package via mixin classes. See sections below.

### Features

* **http:** streamable HTTP transport with bearer-token auth, CORS allow-list, and `/healthz`/`/readyz` endpoints
* **http:** safe-default startup check refuses to bind a non-localhost host without an auth token
* **transport:** legacy SSE transport (`--transport sse`) for clients that haven't migrated to streamable-HTTP; bound to localhost only, no auth/CORS middleware
* **docker:** multi-stage, multi-arch (`linux/amd64`, `linux/arm64`) image published to `ghcr.io/cameronrye/openzim-mcp`, runs as non-root with a built-in health check
* **content:** `get_zim_entries` batch tool — fetch up to 50 entries in one call, with per-entry success/error reporting
* **resources:** per-entry `zim://{name}/entry/{path}` resource serves entries with their native MIME type (clients must URL-encode `/` as `%2F` in the path segment)
* **subscriptions:** clients can subscribe to `zim://files` and `zim://{name}`; mtime-polling watcher emits `notifications/resources/updated` when allowed directories or `.zim` files change
* **search:** opaque `cursor` parameter on `search_zim_file` for resumable pagination
* **simple:** intent pattern routes batch retrieval queries to `get_zim_entries`

### Improvements

* **content:** `get_related_articles` resolves relative hrefs against the source entry's directory and detects the content namespace correctly on domain-scheme archives (previously returned nothing)
* **content:** suggestion fallback uses `SuggestionSearcher(archive).suggest(text)` (the prior `archive.suggest()` call did not exist)
* **tools:** `list_zim_files` accepts a case-insensitive `name_filter` substring argument; one shared cache slot regardless of filter value
* **content:** `get_zim_entries` accepts bare entry-path strings paired with a `zim_file_path` default (dicts still work for multi-archive batches)
* **content:** heading-id resolution falls through `id` → mw-headline anchor → preceding `<a name="">` → slug, returning `(id, source)` so consumers can distinguish real anchors from synthetic slugs
* **content:** summary extraction skips USWDS banners and skip-nav blocks above the first `<h1>` (MedlinePlus / NIH / NIST style sites)
* **content:** link extraction drops non-navigable schemes (`javascript:`, `mailto:`, `tel:`, `data:`, `blob:`, `vbscript:`)
* **server:** `__version__` reads from `importlib.metadata`; `serverInfo.version` reports openzim-mcp's actual version (no longer the FastMCP SDK default)

### Removed

* **tools:** advanced-mode tool surface drops 27 → 21. Removed: `warm_cache`, `cache_stats`, `cache_clear`, `get_random_entry`, `diagnose_server_state`, `resolve_server_conflicts`. The cache itself remains; the explicit management tools were dropped.
* **instance:** multi-instance conflict tracking removed; `instance_tracker.py` deleted. HTTP server instances coexist freely.

### Bug Fixes

* **content:** sanitize per-entry paths in `get_zim_entries` and expand test coverage
* **resources:** per-entry `zim://` returns libzim's native MIME type
* **http:** start subscription watcher via wrapped lifespan
* **instance:** relax conflict logic for HTTP transport so multiple HTTP server instances can coexist

### Security

* **errors:** redact absolute paths from MCP error responses (rejected traversals previously leaked the canonical allowed-directory layout)
* **errors:** regex-based path redaction with cross-platform separator handling and tightened lookbehind so wrapped/quoted paths (`(/opt/foo)`, `"/opt/bar"`) no longer slip through
* **diagnostics:** redact filesystem paths and PIDs in `get_server_health` / `get_server_configuration` responses (no longer transport-gated; always redacted)
* **resources:** sanitize URI-decoded entry paths before passing to libzim
* **search:** always sanitize `zim_file_path` in `find_entry_by_title` (previously skipped when `cross_file=True`)
* **prompts:** strip control characters and cap user-supplied arguments before interpolating into MCP prompt bodies; re-check empty after sanitization to avoid empty `('', ...)` tool calls
* **http:** require auth on `OPTIONS /mcp` (the unconditional preflight bypass let unauthenticated callers probe the endpoint)
* **http:** resolve `localhost` before classifying as loopback; warn and fall through to the public-host path when `/etc/hosts` maps it elsewhere
* **rate-limit:** make global + per-operation acquire atomic; concurrent callers no longer transiently over-consume the global bucket
* **rate-limit:** per-client buckets with LRU eviction (10k cap) — infrastructure ready for HTTP context wiring

### Correctness

* **search:** reject mismatched `cursor` and `query` arguments instead of silently applying the cursor's offsets to a different query
* **cache:** stop caching error sentinels and zero-result responses (previously a transient libzim error or index warmup poisoned the cache for the full TTL); audit follow-up extends the gate to `get_search_suggestions`, `get_entry_summary`, `get_table_of_contents`
* **cache:** treat empty-string cache values as hits, not misses
* **content:** resolve redirects to their target before rendering; cache the resolved path so subsequent lookups skip the chain; reject redirect cycles and chains deeper than `MAX_REDIRECT_DEPTH = 10`
* **content:** instantiate `html2text.HTML2Text` per call to eliminate a shared-state race that corrupted concurrent conversions
* **content:** preserve Unicode in heading slugs (Arabic, Chinese, Cyrillic, Japanese ZIMs no longer produce empty TOC anchors); disambiguate duplicate heading slugs with `_2`, `_3` suffixes
* **content:** drop trailing punctuation from path tokens extracted by the simple-tools `get_zim_entries` parser
* **simple-tools:** dispatch the `get_zim_entries` intent (was silently falling through to `search_zim_file`); honor explicit `zim_file_path` for `walk_namespace`, `find_by_title`, and `related` intents
* **subscriptions:** detect same-size ZIM replacements via mtime change (size-only detection silently missed identical-size replacements)
* **validation:** `browse_namespace` and `walk_namespace` parameter checks now raise `OpenZimMcpValidationError` instead of `OpenZimMcpArchiveError` or markdown error strings; bound `walk_namespace` `limit` to `[1, 500]` per the documented contract
* **validation:** validate `get_zim_entries` batch size before charging rate-limit so an oversized batch doesn't increment the limiter

### Performance

* **search:** skip-counter pagination in `_perform_filtered_search` (offset=900, limit=10 went from ~1000 backend calls to ~10)
* **content:** `get_entries` groups by ZIM file and opens each archive once
* **navigation:** cache namespace listings per `(archive, namespace)`; pagination now slices from cache instead of re-scanning
* **search:** hoist `Searcher` construction in `_find_entry_by_search` (up to 5 Xapian opens collapse to 1)
* **suggestions:** Strategy 2 uses libzim's `SuggestionSearcher` instead of a strided ID scan that skipped 95% of entries on large archives
* **subscriptions:** `SubscriberRegistry` is set-backed for O(1) subscribe/unsubscribe/clear; broadcast fans out concurrently with per-call `wait_for` timeout so one slow subscriber doesn't stall the watcher

### Refactoring

* **zim:** split `zim_operations.py` (3557 → 39 lines, pure shim) into a `zim/` package with `_SearchMixin`, `_ContentMixin`, `_StructureMixin`, `_NamespaceMixin`. Public API preserved via re-exports
* **simple-tools:** extract `IntentParser` into `intent_parser.py` (parsing logic now unit-testable without `ZimOperations` mocks)
* **config:** unify `RateLimitConfig` into a single Pydantic `BaseModel`; `per_operation_limits` is now reachable from environment variables and JSON config
* **defaults:** default cache `persistence_path` to `~/.cache/openzim-mcp` (absolute) rather than `.openzim_mcp_cache` (relative to CWD)
* **defaults:** relocate `MAX_REDIRECT_DEPTH` and `SUBSCRIPTION_SEND_SECONDS` to `defaults.py` (matches existing project pattern)
* **resources:** offload blocking `list_zim_files_data` directory scan via `asyncio.to_thread`
* **resources:** extract `_resolve_zim_name` helper, replacing duplicated inline ZIM-name match loops
* **simple-tools:** intent confidence boost capped (low-priority intents with extracted params can no longer overtake higher-priority param-less intents)
* **prompts:** dedupe ask-for-args message into a `_ask_for_args(prompt_name)` helper

### Hardening (other)

* **cache:** validate values are JSON-serializable at write time when persistence is enabled (previously `default=str` silently coerced non-JSON types)
* **security:** add an unconditional `..` pattern to path normalization so embedded `foo..bar` traversal candidates trigger the regex layer
* **exceptions:** drop `details` from `Exception.args` so it no longer leaks into `repr()` and tracebacks
* **main:** route startup banner through the logger (now respects `OPENZIM_MCP_LOGGING__LEVEL`)
* **simple-tools:** consistently append low-confidence note across all intents (was missing on `search_all`, `walk_namespace`, `find_by_title`, `related`)

## [0.9.0](https://github.com/cameronrye/openzim-mcp/compare/v0.8.3...v0.9.0) (2026-04-30)

### Features

* **search:** `search_all` queries every ZIM file in allowed directories at once and merges results
* **search:** `find_entry_by_title` resolves a title (or partial title) to entry paths, case-insensitive, optionally cross-file
* **prompts:** MCP prompts (`/research`, `/summarize`, `/explore`) for multi-step ZIM workflows
* **resources:** MCP resources `zim://files` (index of all ZIM files) and `zim://{name}` (per-archive overview)
* **navigation:** `walk_namespace` for deterministic cursor-paginated namespace iteration (vs. `browse_namespace` which samples)
* **content:** `get_random_entry` to sample a random article
* **content:** `get_related_articles` returns link-graph nearest neighbours (outbound, inbound, or both)
* **server:** `warm_cache`, `cache_stats`, and `cache_clear` for inspecting and managing the in-memory cache

### Bug Fixes

* namespace listing deterministically surfaces minority namespaces (M, W, X, I) that random sampling could miss
* search filtering uses streaming scan instead of a hard 1000-hit cap, so rare-mime-type filters return matches that were previously hidden
* error messages route by failure mode first (no more "check disk space" for "entry not found")
* phantom server-instance conflicts are no longer reported (TOCTOU re-check before raising)

## [0.8.3](https://github.com/cameronrye/openzim-mcp/compare/v0.8.2...v0.8.3) (2026-01-30)

### Bug Fixes

* fix logo URL in README.md to use absolute GitHub raw URL for PyPI display ([README.md](README.md))
* resolve GitHub code scanning alert #133 - variable defined multiple times in security.py ([security.py](openzim_mcp/security.py))
* resolve GitHub code scanning alert #134 - mixed import styles in test_main.py ([test_main.py](tests/test_main.py))
* remove unused `contextlib` import from security.py (flake8 fix)

## [0.8.2](https://github.com/cameronrye/openzim-mcp/compare/v0.8.1...v0.8.2) (2026-01-29)

### Bug Fixes

* fix search pagination when offset exceeds total results ([zim_operations.py](openzim_mcp/zim_operations.py))
* improve exception handling in instance tracker for Python 3 compatibility ([instance_tracker.py](openzim_mcp/instance_tracker.py))
* add fallback to stderr for logging during shutdown ([instance_tracker.py](openzim_mcp/instance_tracker.py))
* improve Windows process checking with debug logging ([instance_tracker.py](openzim_mcp/instance_tracker.py))
* fix release workflow to skip automatic GitHub release creation ([release-please.yml](.github/workflows/release-please.yml))
* resolve linting issues in simple_tools.py and content_tools.py

## [0.8.1](https://github.com/cameronrye/openzim-mcp/compare/v0.7.1...v0.8.1) (2026-01-29)

### Features

* add article summaries, table of contents, and pagination cursors ([bf5d18f](https://github.com/cameronrye/openzim-mcp/commit/bf5d18fcfecb2e6b03c667565640439b145a4e30))

### Bug Fixes

* remove unused imports in test files for CI linting ([0ddb250](https://github.com/cameronrye/openzim-mcp/commit/0ddb250d49fb627ee7adb41cf3fa52a8caf69172))
* resolve GitHub code scanning alerts ([2ad2c56](https://github.com/cameronrye/openzim-mcp/commit/2ad2c56a6e7a958ed63d6bd23ad975dd80e1e1f0))

### Details

* **Article Summaries** (`get_entry_summary`): Extract concise article summaries from opening paragraphs
  * Removes infoboxes, navigation, and sidebars for clean summaries
  * Configurable `max_words` parameter (10-1000, default: 200)
  * Returns structured JSON with title, summary, word count, and truncation status
  * Useful for quick content preview without loading full articles

* **Table of Contents Extraction** (`get_table_of_contents`): Build hierarchical TOC from article headings
  * Hierarchical tree structure with nested children based on heading levels (h1-h6)
  * Includes heading text, level, and anchor IDs for navigation
  * Provides heading count and maximum depth statistics
  * Enables LLMs to navigate directly to specific article sections

* **Pagination Cursors**: Token-based pagination for easier result navigation
  * Base64-encoded cursor tokens encode offset, limit, and optional query
  * `next_cursor` field in search and browse results for continuation
  * Eliminates need for clients to track pagination state manually

### Enhanced

* **Intent Parsing**: Improved multi-match resolution with weighted scoring
  * Collects all matching patterns before selecting best match
  * Weighted scoring: 70% confidence + 30% specificity
  * Prevents earlier patterns from incorrectly shadowing more specific ones
  * New intent patterns for "toc" and "summary" queries in Simple mode

* **Simple Mode**: Added natural language support for new features
  * "summary of Biology" or "summarize Evolution" for article summaries
  * "table of contents for Biology" or "toc of Evolution" for TOC extraction

## [0.7.1](https://github.com/cameronrye/openzim-mcp/compare/v0.7.0...v0.7.1) (2026-01-28)

### Bug Fixes

* **ci:** handle existing GitHub releases in release workflow ([#54](https://github.com/cameronrye/openzim-mcp/issues/54)) ([63afa3d](https://github.com/cameronrye/openzim-mcp/commit/63afa3d9150a60716b7fa25524beedb806ded84d))

## [0.7.0](https://github.com/cameronrye/openzim-mcp/compare/v0.6.3...v0.7.0) (2026-01-28)

### Features

* add binary content retrieval for PDFs, images, and media files ([#52](https://github.com/cameronrye/openzim-mcp/issues/52)) ([95611c9](https://github.com/cameronrye/openzim-mcp/commit/95611c9135836202d1fc97181d98307c199e3888))

## [0.6.3](https://github.com/cameronrye/openzim-mcp/compare/v0.6.2...v0.6.3) (2025-11-14)

### Bug Fixes

* configure release-please to skip GitHub release creation and handle existing PyPI packages ([b865454](https://github.com/cameronrye/openzim-mcp/commit/b8654546c1a8ea3a90eb3dedfb95c671beaaca98))

## [0.6.2](https://github.com/cameronrye/openzim-mcp/compare/v0.6.1...v0.6.2) (2025-11-14)

### Bug Fixes

* add tag_name parameter to GitHub Release action ([74d393c](https://github.com/cameronrye/openzim-mcp/commit/74d393c600155b303a26d6f066130cb26351cb49))

## [0.6.1](https://github.com/cameronrye/openzim-mcp/compare/v0.6.0...v0.6.1) (2025-11-14)

### Bug Fixes

* resolve CI workflow issues ([4bd6c33](https://github.com/cameronrye/openzim-mcp/commit/4bd6c332548a444c58390889052ebcc417d65094))

## [0.6.0](https://github.com/cameronrye/openzim-mcp/compare/v0.5.1...v0.6.0) (2025-11-14)

### Features

* add dual-mode support with intelligent natural language tool ([#31](https://github.com/cameronrye/openzim-mcp/issues/31)) ([6d97993](https://github.com/cameronrye/openzim-mcp/commit/6d97993a8bda3f20cc65abfeef459f9487b94406))
* enhance GitHub Pages website with dark mode, dynamic versioning, and improved UX ([#22](https://github.com/cameronrye/openzim-mcp/issues/22)) ([977d46a](https://github.com/cameronrye/openzim-mcp/commit/977d46abf61efbafca2bd24142176c3857cc32b8))

## [0.5.1](https://github.com/cameronrye/openzim-mcp/compare/v0.5.0...v0.5.1) (2025-09-16)

### Bug Fixes

* resolve CI/CD status reporting issue for bot commits ([#20](https://github.com/cameronrye/openzim-mcp/issues/20)) ([af23589](https://github.com/cameronrye/openzim-mcp/commit/af235896b4a1afd96269d08d97362ff903e093d5))
* resolve GitHub Actions workflow errors ([#17](https://github.com/cameronrye/openzim-mcp/issues/17)) ([dcda274](https://github.com/cameronrye/openzim-mcp/commit/dcda2749a394a599e3f77a4b64412fa21e65a29d))

## [0.5.0](https://github.com/cameronrye/openzim-mcp/compare/v0.4.0...v0.5.0) (2025-09-15)

### Features

* enhance GitHub Pages site with comprehensive feature showcase ([#14](https://github.com/cameronrye/openzim-mcp/issues/14)) ([c50c69b](https://github.com/cameronrye/openzim-mcp/commit/c50c69b73bc4ec142a2080146644ed9c84da63c4))
* enhance GitHub Pages site with comprehensive feature showcase and uv-first installation ([#15](https://github.com/cameronrye/openzim-mcp/issues/15)) ([f988c5a](https://github.com/cameronrye/openzim-mcp/commit/f988c5a9c7af4acbfe08922a68e11a288f06da70))

### Bug Fixes

* correct CodeQL badge URL to match workflow name ([#13](https://github.com/cameronrye/openzim-mcp/issues/13)) ([7446f74](https://github.com/cameronrye/openzim-mcp/commit/7446f7491d1c0a028a7ba55071b46c73424b58e4))

### Documentation

* Comprehensive documentation update for v0.4.0+ features ([#16](https://github.com/cameronrye/openzim-mcp/issues/16)) ([e1bce58](https://github.com/cameronrye/openzim-mcp/commit/e1bce5816e95beca7adeca92c03dbd551808151f))
* improve installation instructions with PyPI as primary method ([d6f758b](https://github.com/cameronrye/openzim-mcp/commit/d6f758b30836e916933e87a316754cd757cec833))

## [0.4.0](https://github.com/cameronrye/openzim-mcp/compare/v0.3.3...v0.4.0) (2025-09-15)

### Features

* overhaul release system for reliability and enterprise-grade automation ([#9](https://github.com/cameronrye/openzim-mcp/issues/9)) ([ef0f1b8](https://github.com/cameronrye/openzim-mcp/commit/ef0f1b8f2eaac99a1850672088ddc29d28f0bcde))

## [0.3.1](https://github.com/cameronrye/openzim-mcp/compare/v0.3.0...v0.3.1) (2025-09-15)

### Bug Fixes

* add manual trigger support to Release workflow ([b968cf6](https://github.com/cameronrye/openzim-mcp/commit/b968cf661f536183f4ef5fd6374e75a847a0123f))
* ensure Release workflow checks out correct tag for all jobs ([b4a61ca](https://github.com/cameronrye/openzim-mcp/commit/b4a61ca7a034f9eefae2606c4eb9769ef4f79379))

## [0.3.0](https://github.com/cameronrye/openzim-mcp/compare/v0.2.0...v0.3.0) (2025-09-15)

### Features

* add automated version bumping with release-please ([6b4e27c](https://github.com/cameronrye/openzim-mcp/commit/6b4e27c0382bb4cfa16a7e101f012e8355f7c827))

### Bug Fixes

* resolve release-please workflow issues ([68b47ea](https://github.com/cameronrye/openzim-mcp/commit/68b47ea711525e126ec3ed8297808f7779edd87e))

## [0.2.0] - 2025-01-15

### Added

* **Complete Architecture Refactoring**: Modular design with dependency injection
* **Enhanced Security**:
  * Fixed path traversal vulnerability using secure path validation
  * Comprehensive input sanitization and validation
  * Protection against directory traversal attacks
* **Comprehensive Testing**: 80%+ test coverage with pytest
  * Unit tests for all components
  * Integration tests for end-to-end functionality
  * Security tests for vulnerability prevention
* **Intelligent Caching**: LRU cache with TTL support for improved performance
* **Modern Configuration Management**: Pydantic-based configuration with validation
* **Structured Logging**: Configurable logging with proper error handling
* **Type Safety**: Complete type annotations throughout the codebase
* **Resource Management**: Proper cleanup with context managers
* **Health Monitoring**: Built-in health check endpoint
* **Development Tools**:
  * Makefile for common development tasks
  * Black, flake8, mypy, isort for code quality
  * Comprehensive development dependencies

### Changed

* **Project Name**: Changed from "zim-mcp-server" to "openzim-mcp" for consistency
* **Entry Point**: New `python -m openzim_mcp` interface (backwards compatible)
* **Error Handling**: Consistent custom exception hierarchy
* **Content Processing**: Improved HTML to text conversion
* **API**: Enhanced tool interfaces with better validation

### Security

* **CRITICAL**: Fixed path traversal vulnerability in PathManager
* **HIGH**: Added comprehensive input validation
* **MEDIUM**: Sanitized error messages to prevent information disclosure

### Performance

* **Caching**: Intelligent caching reduces ZIM file access overhead
* **Resource Management**: Proper cleanup prevents memory leaks
* **Optimized Processing**: Improved content processing performance

## [0.1.0] - 2024-XX-XX

### Added

* Initial release of ZIM MCP Server
* Basic ZIM file operations (list, search, get entry)
* Simple path management
* HTML to text conversion
* MCP server implementation

### Known Issues (Fixed in 0.2.0)

* Path traversal security vulnerability
* No input validation
* Missing error handling
* No testing framework
* Resource management issues
* Global state management problems
