<p align="center">
  <img src="https://raw.githubusercontent.com/cameronrye/openzim-mcp/main/website/assets/favicon.svg" alt="OpenZIM MCP Logo" width="120" height="120">
</p>

<h1 align="center">OpenZIM MCP Server</h1>

<p align="center">
  <strong>Transform static ZIM archives into dynamic knowledge engines for AI models</strong>
</p>

<p align="center">
  <a href="https://github.com/cameronrye/openzim-mcp/actions/workflows/test.yml"><img src="https://github.com/cameronrye/openzim-mcp/workflows/CI/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/cameronrye/openzim-mcp"><img src="https://codecov.io/gh/cameronrye/openzim-mcp/branch/main/graph/badge.svg" alt="codecov"></a>
  <a href="https://github.com/cameronrye/openzim-mcp/actions/workflows/codeql.yml"><img src="https://github.com/cameronrye/openzim-mcp/workflows/CodeQL%20Security%20Analysis/badge.svg" alt="CodeQL"></a>
  <a href="https://sonarcloud.io/summary/new_code?id=cameronrye_openzim-mcp"><img src="https://sonarcloud.io/api/project_badges/measure?project=cameronrye_openzim-mcp&metric=security_rating" alt="Security Rating"></a>
</p>

<p align="center">
  <a href="https://badge.fury.io/py/openzim-mcp"><img src="https://badge.fury.io/py/openzim-mcp.svg" alt="PyPI version"></a>
  <a href="https://pypi.org/project/openzim-mcp/"><img src="https://img.shields.io/pypi/pyversions/openzim-mcp" alt="PyPI - Python Version"></a>
  <a href="https://pypi.org/project/openzim-mcp/"><img src="https://img.shields.io/pypi/dm/openzim-mcp" alt="PyPI - Downloads"></a>
  <a href="https://github.com/cameronrye/openzim-mcp/releases"><img src="https://img.shields.io/github/v/release/cameronrye/openzim-mcp" alt="GitHub release"></a>
</p>

<p align="center">
  <a href="https://github.com/psf/black"><img src="https://img.shields.io/badge/code%20style-black-000000.svg" alt="Code style: black"></a>
  <a href="https://pycqa.github.io/isort/"><img src="https://img.shields.io/badge/%20imports-isort-%231674b1?style=flat&labelColor=ef8336" alt="Imports: isort"></a>
  <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/type%20checked-mypy-blue" alt="Type checked: mypy"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="https://github.com/cameronrye/openzim-mcp/issues"><img src="https://img.shields.io/github/issues/cameronrye/openzim-mcp" alt="GitHub issues"></a>
  <a href="https://github.com/cameronrye/openzim-mcp/pulls"><img src="https://img.shields.io/github/issues-pr/cameronrye/openzim-mcp" alt="GitHub pull requests"></a>
  <a href="https://github.com/cameronrye/openzim-mcp/graphs/contributors"><img src="https://img.shields.io/github/contributors/cameronrye/openzim-mcp" alt="GitHub contributors"></a>
  <a href="https://github.com/cameronrye/openzim-mcp/stargazers"><img src="https://img.shields.io/github/stars/cameronrye/openzim-mcp?style=social" alt="GitHub stars"></a>
</p>

---

> 🆕 **NEW in v1.1.0: Structured tool output!** All 17 JSON-returning tools now emit MCP `structuredContent` alongside the legacy text envelope — no more double-stringified JSON, no more escape soup. Plus a major namespace-handling fix for new-scheme archives (`list_namespaces` / `browse_namespace` / `walk_namespace` were silently broken on Wikipedia-style ZIMs), pagination for `extract_article_links`, case-insensitive `find_entry_by_title` with proper scoring, and CORS support for browser MCP clients. [Learn more →](#whats-new-in-v110)
>
> Still on the v1.0.0 highlights? Streamable HTTP transport, batch entry retrieval, and per-entry resources are documented in the [v1.0.0 section](#whats-new-in-v100).

> **Dual Mode Support:** Choose between Simple mode (1 intelligent natural language tool, default) or Advanced mode (21 specialized tools, plus 3 MCP prompts and 3 MCP resources) to match your LLM's capabilities.

## Built for LLM Intelligence

**OpenZIM MCP transforms static ZIM archives into dynamic knowledge engines for Large Language Models.** Unlike basic file readers, this tool provides *intelligent, structured access* that LLMs need to effectively navigate and understand vast knowledge repositories.

**Why LLMs Love OpenZIM MCP:**

- **Smart Navigation**: Browse by namespace (articles, metadata, media) instead of blind searching
- **Context-Aware Discovery**: Get article structure, relationships, and metadata for deeper understanding
- **Intelligent Search**: Advanced filtering, auto-complete suggestions, and relevance-ranked results
- **Performance Optimized**: Cached operations and pagination prevent timeouts on massive archives
- **Relationship Mapping**: Extract internal/external links to understand content connections

Whether you're building a research assistant, knowledge chatbot, or content analysis system, OpenZIM MCP gives your LLM the structured access patterns it needs to unlock the full potential of offline knowledge archives. No more fumbling through raw text dumps!

**OpenZIM MCP** is a modern, secure, and high-performance MCP (Model Context Protocol) server that enables AI models to access and search [ZIM format](https://en.wikipedia.org/wiki/ZIM_(file_format)) knowledge bases offline.

[ZIM](https://en.wikipedia.org/wiki/ZIM_(file_format)) (Zeno IMproved) is an open file format developed by the [openZIM project](https://openzim.org/), designed specifically for offline storage and access to website content. The format supports high compression rates using Zstandard compression (default since 2021) and enables fast full-text searching, making it ideal for storing entire Wikipedia content and other large reference materials in relatively compact files. The openZIM project is sponsored by Wikimedia CH and supported by the Wikimedia Foundation, ensuring the format's continued development and adoption for offline knowledge access, especially in environments without reliable internet connectivity.

## Features

- **Dual Mode Support**: Choose between Simple mode (1 intelligent natural language tool, default) or Advanced mode (21 specialized tools)
- **Streamable HTTP Transport**: 🆕 Run as a long-running service over HTTP — bearer-token auth, CORS, health endpoints, multi-arch Docker image, and resource subscriptions
- **Batch Entry Retrieval**: 🆕 Fetch up to 50 entries per call with `get_zim_entries` — pairs naturally with HTTP, where round-trip cost matters
- **Per-Entry MCP Resources**: 🆕 Stream individual entries via `zim://{name}/entry/{path}` with native MIME types — browse HTML, PDFs, and images directly
- **Resource Subscriptions**: 🆕 Clients subscribe to `zim://files` and `zim://{name}` and receive `notifications/resources/updated` when archives change
- **Multi-Archive Search**: Search every ZIM file at once with `search_all` — no need to know which archive holds the answer
- **MCP Prompts**: Pre-built workflow slash commands (`/research`, `/summarize`, `/explore`) that orchestrate multi-step ZIM operations
- **Find Entries by Title**: Resolve titles to entry paths instantly with `find_entry_by_title` — case-insensitive, optionally cross-file
- **Binary Content Retrieval**: Extract PDFs, images, videos, and other embedded media for multi-agent workflows
- **Security First**: Comprehensive input validation and path traversal protection
- **High Performance**: Intelligent caching and optimized ZIM file operations
- **Smart Retrieval**: Automatic fallback from direct access to search-based retrieval for reliable entry access
- **Well Tested**: 80%+ test coverage with comprehensive test suite
- **Modern Architecture**: Modular design with dependency injection
- **Type Safe**: Full type annotations throughout the codebase
- **Configurable**: Flexible configuration with validation
- **Observable**: Structured logging and health monitoring

## What's new in v1.1.0

### Structured tool output

The 17 JSON-returning tools now emit MCP `structuredContent` alongside the legacy `content[].text` envelope. Old clients keep parsing the text JSON; new clients read the dict directly. The biggest beneficiary is `search_all`, whose `per_file[].result` field used to be a pre-rendered markdown blob escaped twice through `json.dumps` — it's now a real nested dict.

The four prose/markdown tools (`search_zim_file`, `search_with_filters`, `get_zim_entry`, `get_main_page`) and the simple-mode `zim_query` stay on `-> str` by design.

### Namespace handling, fixed

In new-scheme ZIM archives (the modern format used by current Kiwix Wikipedia builds), libzim's iterable surface only exposes the C namespace and reaches metadata through `archive.metadata_keys`. The previous code parsed the first character of each entry path *as* the namespace, so `Evolution` looked like namespace `'E'`, `Bob_Dylan` like `'B'`, `favicon.png` like `'F'` — including emoji buckets like `'🐜'`. `search_with_filters(namespace='C')` was silently dropping ~95% of legitimate hits.

`list_namespaces`, `browse_namespace`, `walk_namespace`, and the `namespace=` filter now branch on `archive.has_new_namespace_scheme`: new-scheme C uses `entry_count` as an authoritative total, M is enumerated from `metadata_keys`, W is surfaced via `has_main_entry` / `has_illustration`. Old-scheme archives are unaffected.

### Pagination for `extract_article_links`

`extract_article_links` previously dumped every internal/external/media link in one call. On a heavily-linked Wikipedia article (~6k links) that was ~400 KB and overflowed the response token budget. The tool now accepts `limit` / `offset` / `kind` parameters; full counts ship in `total_internal_links` / `total_external_links` / `total_media_links` so callers can size the next page. Parsed extraction is cached once per entry and sliced in-memory (~40× speedup on cached pages).

### Smarter `find_entry_by_title`

The fast path was case-sensitive, so `"evolution"` against an archive titled `"Evolution"` missed and fell through to suggestion fallback with a hardcoded `score: 0.8`. Now the fast path tries five case variants × C/A namespaces; suggestion results get rank-derived scores in (0, 0.95] so an exact case-insensitive match (promoted to 1.0) always outranks partials.

### Per-entry resource size caps

`zim://{name}/entry/{path}` now caps text bodies at 256 KB UTF-8 with a notice pointing at `get_zim_entry` for paged reads. Oversize binary bodies are *refused* (not silently clipped, since a sliced PDF/PNG won't open) — callers should use `get_binary_entry`, which has explicit `max_size_bytes` and a `truncated` flag.

### Simple mode actually works

`_register_simple_tools` was also calling `_register_advanced_tools`, so simple-mode clients received every advanced tool's schema in the prompt anyway — defeating the entire point of the mode and inflating prefill into the multi-thousand-token range. Fixed: simple mode now registers exactly one tool (`zim_query`). Confirmed against llama.cpp's MCP webui — single-turn prompt size dropped from ~6,200 tokens to ~1,100.

### CORS for browser MCP clients

Two additions to the HTTP transport's CORS layer:

- `MCP-Protocol-Version` is now in `allow_headers`. Browser MCP clients send this on every post-init request per the MCP spec; without it, the second preflight returned `400 Disallowed CORS headers` and the connection dropped.
- `DELETE` is now in `allow_methods`. The MCP streamable-HTTP SDK uses DELETE for explicit session termination.

### Polish

- `get_server_health` now reports a real `started_at` and `uptime_seconds` instead of `"unknown"`.
- Configuration redaction format changed from the misleading `...data` to unambiguous `<redacted>/data`.
- Server-tools timestamps go through a single `_utc_now_iso()` helper so a response no longer mixes timezone-aware UTC with naive local.
- `zim_query("")` rejects empty input upfront with example queries instead of falling through to a no-op search.
- `get_search_suggestions` schema now documents the 2-character minimum.
- The "cache hit rate is low" warning waits until ≥50 accesses before commenting (previously fired at 22% during normal session warm-up).
- `get_zim_entry`'s truncation tail now reads "of body content" so callers can tell the limit applies to the body, not the wrapper headers.

## What's new in v1.0.0

### Streamable HTTP transport

Run OpenZIM MCP as a long-running service. Pass `--transport http` (or set `OPENZIM_MCP_TRANSPORT=http`) and the server boots a Starlette app on `127.0.0.1:8000` by default with:

- **Bearer-token auth** — set `OPENZIM_MCP_AUTH_TOKEN`; comparison is timing-safe and the attempted token is never logged.
- **Safe-default startup check** — the server *refuses* to bind a non-localhost host without a token. (Bind `127.0.0.1` for local-only access; put a reverse proxy in front for TLS.)
- **CORS allow-list** — explicit origins via `OPENZIM_MCP_CORS_ORIGINS`; wildcard `*` is rejected at startup.
- **Health endpoints** — `/healthz` (liveness) and `/readyz` (at least one allowed dir is readable). Both exempt from auth so probes work cleanly.
- **Multi-arch Docker image** — `ghcr.io/cameronrye/openzim-mcp:1.1.1`, builds for `linux/amd64` and `linux/arm64`, runs as non-root.

Legacy SSE transport is also available via `--transport sse` (or `OPENZIM_MCP_TRANSPORT=sse`) for clients that haven't migrated to streamable-HTTP. SSE does **not** apply the bearer-token / CORS / health-endpoint middleware, so the server *refuses* to start with `--transport sse` bound to anything other than `127.0.0.1`/`::1`/`localhost`. For exposed deployments use `--transport http`.

### Batch entry retrieval

`get_zim_entries` fetches up to 50 entries in one call. Per-entry failures don't abort the batch — each result includes its `index` from the input order plus either `content` (success) or `error` (failure). Different `zim_file_path` values are allowed in one batch, so a multi-archive workflow can fan out from a single search. Single-archive batches can pass bare path strings paired with a top-level `zim_file_path` default, so the call site stays flat instead of dict-heavy.

### Per-entry MCP resources

`zim://{name}/entry/{path}` exposes individual entries with their native MIME type:

- HTML and text entries return text bodies (`text/html`, `text/plain`, `application/json`, ...).
- Binary entries (images, PDFs) return raw bytes (FastMCP base64-wraps them).

**Encoding requirement:** clients MUST URL-encode `/` as `%2F` in the `{path}` segment. FastMCP's URI template engine treats `/` as a segment separator, so a literal slash won't route. Example: `zim://wikipedia_en/entry/C%2FClimate_change`. (This is a constraint of the current `mcp[cli]` SDK.)

### Resource subscriptions

Subscribe to `zim://files` or `zim://{name}` and the server emits `notifications/resources/updated` whenever the directory contents change or a `.zim` file is replaced. Polling interval is configurable (`OPENZIM_MCP_WATCH_INTERVAL_SECONDS`, default 5 s) and the feature can be disabled with `OPENZIM_MCP_SUBSCRIPTIONS_ENABLED=false`. Implementation note: this depends on a private FastMCP attribute (`_mcp_server`) for handler registration.

### Polish & fixes

**Smarter archive handling**

- `get_related_articles` resolves relative hrefs against the source entry's directory and identifies the content namespace correctly on domain-scheme archives (previously returned nothing).
- Suggestion fallback uses `SuggestionSearcher(archive).suggest(text)` (the prior `archive.suggest()` call didn't exist).
- `list_zim_files` gains a case-insensitive `name_filter` substring argument; one shared cache slot regardless of filter value.
- `search_zim_file` accepts an opaque `cursor` parameter; passing the cursor alone resumes pagination without restating the query.

**Cleaner content extraction**

- Heading-id resolution falls through `id` → mw-headline anchor → preceding `<a name="">` → slug, returning `(id, source)` so consumers can distinguish real anchors from synthetic slugs.
- Summary extraction skips USWDS banners and skip-nav blocks above the first `<h1>` (MedlinePlus / NIH / NIST style sites).
- Link extraction drops non-navigable schemes (`javascript:`, `mailto:`, `tel:`, `data:`, `blob:`, `vbscript:`).
- Per-entry paths sanitized in `get_zim_entries`.

**Server hygiene**

- `__version__` reads from `importlib.metadata`; `serverInfo.version` reports openzim-mcp's actual version (no longer the FastMCP SDK default).
- HTTP transport's subscription watcher starts via wrapped lifespan.
- Per-entry `zim://` returns libzim's native MIME (was returning a placeholder).

**Streamlined scope**

v1.0.0 reduces the advanced-mode tool surface from 27 to 21 by removing administrative/inspection helpers that didn't pull their weight: `warm_cache`, `cache_stats`, `cache_clear`, `get_random_entry`, `diagnose_server_state`, and `resolve_server_conflicts`. The cache itself remains; the explicit management tools were dropped. Multi-instance conflict tracking was removed entirely — `instance_tracker.py` is gone — which means HTTP server instances coexist freely without configuration warnings.

**Review pass**

End-to-end review pass before tagging: tightened path/PID redaction in error and diagnostics responses, locked `OPTIONS /mcp` behind auth, fixed cache poisoning on transient libzim errors, resolved redirects before rendering with cycle detection, preserved Unicode in heading slugs (Arabic, Chinese, Cyrillic, Japanese), made rate-limiting atomic, and split `zim_operations.py` into a `zim/` package via mixin classes.

## What's new in v0.9.0

### Multi-archive search

`search_all` queries every ZIM file in your allowed directories at once and merges the results — no need to know which archive holds the answer.

### MCP Prompts

Three pre-built workflows you can invoke as slash commands in MCP-aware clients:

- `/research <topic>` — search across all archives, then drill into top hits
- `/summarize <zim_file_path> <entry_path>` — TOC + summary + key links
- `/explore <zim_file_path>` — high-level briefing of a ZIM's contents

### Find entries by title

`find_entry_by_title` resolves a title (or partial title) to one or more entry paths, with case-insensitive matching. Cheaper than full-text search when you already know the article name.

### Power-user tools

- `walk_namespace` — deterministic cursor-paginated namespace iteration (vs. `browse_namespace` which samples)
- `get_related_articles` — outbound link-graph neighbours of a given entry

### MCP Resources

First use of the MCP **resources** primitive — your client's resource browser and `@`-mention picker now see ZIM files directly:

- `zim://files` — index of all available ZIM files
- `zim://{name}` — overview of one ZIM (metadata, namespaces, main page preview)
- `zim://{name}/entry/{path}` *(new in 1.0.0)* — single entry served with native MIME type (clients must URL-encode `/` as `%2F` in the path segment)

### Reliability fixes

- Namespace listing now deterministically surfaces minority namespaces (M, W, X, I) that random sampling could miss
- Search filtering uses streaming scan instead of a hard 1000-hit cap (rare-mime-type filters now return matches that were previously hidden)
- Error messages route by failure mode first (no more "check disk space" for "entry not found")

## Quick Start

### Installation

```bash
# Install from PyPI as an isolated CLI tool (recommended)
uv tool install openzim-mcp

# Or install into your current environment with pip
pip install openzim-mcp
```

### Development Installation

For contributors and developers:

```bash
# Clone the repository
git clone https://github.com/cameronrye/openzim-mcp.git
cd openzim-mcp

# Install dependencies
uv sync

# Install development dependencies
uv sync --dev
```

### Prepare ZIM Files

Download ZIM files (e.g., Wikipedia, Wiktionary, etc.) from the [Kiwix Library](https://library.kiwix.org/) and place them in a directory:

```bash
mkdir ~/zim-files
# Download ZIM files to ~/zim-files/
```

### Running the Server

```bash
# Simple mode (default) - 1 intelligent natural language tool
openzim-mcp /path/to/zim/files
python -m openzim_mcp /path/to/zim/files

# Advanced mode - all 21 specialized tools
openzim-mcp --mode advanced /path/to/zim/files
python -m openzim_mcp --mode advanced /path/to/zim/files

# For development (from source)
uv run python -m openzim_mcp /path/to/zim/files
uv run python -m openzim_mcp --mode advanced /path/to/zim/files

# Or using make (development)
make run ZIM_DIR=/path/to/zim/files
```

### Tool Modes

OpenZIM MCP supports two modes:

- **Simple Mode** (default): Provides 1 intelligent tool (`zim_query`) that accepts natural language queries
- **Advanced Mode**: Exposes all 21 specialized MCP tools for maximum control

### MCP Configuration

Add the appropriate snippet to your MCP client's config file (`claude_desktop_config.json`, Cursor's MCP settings, etc.). The `mcpServers` wrapper is required by Claude Desktop, Cursor, and most other MCP clients.

**Simple Mode (default):**

```json
{
  "mcpServers": {
    "openzim-mcp": {
      "command": "openzim-mcp",
      "args": ["/path/to/zim/files"]
    }
  }
}
```

**Advanced Mode:**

```json
{
  "mcpServers": {
    "openzim-mcp-advanced": {
      "command": "openzim-mcp",
      "args": ["--mode", "advanced", "/path/to/zim/files"]
    }
  }
}
```

Alternative configuration using Python module:

```json
{
  "mcpServers": {
    "openzim-mcp": {
      "command": "python",
      "args": [
        "-m",
        "openzim_mcp",
        "/path/to/zim/files"
      ]
    }
  }
}
```

For development (from source):

```json
{
  "mcpServers": {
    "openzim-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/openzim-mcp",
        "run",
        "python",
        "-m",
        "openzim_mcp",
        "/path/to/zim/files"
      ]
    }
  }
}
```

## Development

### Running Tests

```bash
# Run all tests
make test

# Run tests with coverage
make test-cov

# Run specific test file
uv run pytest tests/test_security.py -v

# Run tests with ZIM test data (comprehensive testing)
make test-with-zim-data

# Run integration tests only
make test-integration

# Run tests that require ZIM test data
make test-requires-zim-data
```

### ZIM Test Data Integration

OpenZIM MCP integrates with the official [zim-testing-suite](https://github.com/openzim/zim-testing-suite) for comprehensive testing with real ZIM files:

```bash
# Download essential test files (basic testing)
make download-test-data

# Download all test files (comprehensive testing)
make download-test-data-all

# List available test files
make list-test-data

# Clean downloaded test data
make clean-test-data
```

The test data includes:

- **Basic files**: Small ZIM files for essential testing
- **Real content**: Actual Wikipedia/Wikibooks content for integration testing
- **Invalid files**: Malformed ZIM files for error handling testing
- **Special cases**: Embedded content, split files, and edge cases

Test files are automatically organized by category and priority level.

### Code Quality

```bash
# Format code
make format

# Run linting
make lint

# Type checking
make type-check

# Run all checks
make check
```

### Project Structure

```text
openzim-mcp/
├── openzim_mcp/                # Main package
│   ├── __init__.py             # Package init, exports __version__ via importlib.metadata
│   ├── __main__.py             # Module entry point (`python -m openzim_mcp`)
│   ├── main.py                 # CLI entry point and arg parsing
│   ├── server.py               # MCP server setup, transport selection
│   ├── http_app.py             # Streamable HTTP / SSE transport, auth, CORS, health
│   ├── config.py               # Pydantic config + env var bindings
│   ├── defaults.py             # Default values and tunables
│   ├── security.py             # Path validation, traversal protection, sanitization
│   ├── error_messages.py       # User-facing error message catalog
│   ├── exceptions.py           # Custom exception hierarchy
│   ├── cache.py                # LRU cache with TTL
│   ├── rate_limiter.py         # Per-client + global token-bucket rate limiting
│   ├── content_processor.py    # HTML→text, heading-id, link extraction
│   ├── async_operations.py     # asyncio helpers and timeouts
│   ├── timeout_utils.py        # Timeout primitives
│   ├── subscriptions.py        # MtimeWatcher and SubscriberRegistry
│   ├── simple_tools.py         # Simple-mode `zim_query` tool
│   ├── intent_parser.py        # Natural-language intent parsing
│   ├── types.py                # Shared TypedDicts
│   ├── constants.py            # Shared constants
│   ├── zim_operations.py       # Backward-compat shim re-exporting from zim/ package
│   ├── zim/                    # ZIM access (split from monolithic zim_operations.py)
│   │   ├── __init__.py         # ZimOperations facade composed of mixins
│   │   ├── archive.py          # Archive open/close, file listing, name resolution
│   │   ├── content.py          # Entry retrieval, summaries, batch get
│   │   ├── namespace.py        # Namespace listing, browse, walk
│   │   ├── search.py           # Full-text + suggestion search; cursor pagination
│   │   └── structure.py        # Article structure, links, related articles
│   └── tools/                  # MCP tool registrations
│       ├── __init__.py
│       ├── file_tools.py       # list_zim_files
│       ├── content_tools.py    # get_zim_entry, get_zim_entries
│       ├── search_tools.py     # search_zim_file, search_all, find_entry_by_title
│       ├── navigation_tools.py # browse_namespace, walk_namespace, search_with_filters, get_search_suggestions
│       ├── structure_tools.py  # get_article_structure, extract_article_links, get_entry_summary, get_table_of_contents, get_binary_entry
│       ├── metadata_tools.py   # get_zim_metadata, get_main_page, list_namespaces
│       ├── server_tools.py     # get_server_health, get_server_configuration
│       ├── resource_tools.py   # MCP resources (zim://files, zim://{name}/...)
│       └── prompts.py          # MCP prompts (/research, /summarize, /explore)
├── tests/                      # Test suite (pytest)
├── website/                    # GitHub Pages site source
├── pyproject.toml              # Project configuration
├── Makefile                    # Development commands
├── Dockerfile                  # Multi-stage container build
└── README.md                   # This file
```

---

## API Reference

### Available Tools

### list_zim_files - List all ZIM files in allowed directories

**Optional parameters:**

- `name_filter` (string, default: ""): Case-insensitive substring; only files whose filename contains it are returned. Empty string lists everything. Useful for narrowing large listings (e.g. `"wikipedia"`, `"nginx"`).

### search_zim_file - Search within ZIM file content

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `query` (string): Search query term — required unless `cursor` is provided.

**Optional parameters:**

- `limit` (integer, default: 10): Maximum number of results to return
- `offset` (integer, default: 0): Starting offset for results (for pagination)
- `cursor` (string): Opaque pagination token from a previous result's `next_cursor`. When provided, overrides `offset`/`limit` with the values encoded in the token, and supplies `query` if it was not given explicitly. Cursors are only valid for the query they were issued for.

### get_zim_entry - Get detailed content of a specific entry in a ZIM file

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path, e.g., 'A/Some_Article'

**Optional parameters:**

- `max_content_length` (integer, default: 100000, minimum: 1000): Maximum length of returned content

**Smart Retrieval Features:**

- **Automatic Fallback**: If direct path access fails, automatically searches for the entry and uses the exact path found
- **Path Mapping Cache**: Caches successful path mappings for improved performance on repeated access
- **Enhanced Error Guidance**: Provides clear guidance when entries cannot be found, suggesting alternative approaches
- **Transparent Operation**: Works seamlessly regardless of path encoding differences (spaces vs underscores, URL encoding, etc.)

### get_zim_entries - Batch retrieve multiple ZIM entries in one call

Pairs naturally with HTTP transport, where round-trip cost matters. Up to 50 entries per batch. Each entry resolves independently — per-entry failures do not abort the batch.

**Required parameters:**

- `entries` (list): Either a list of entry-path strings (paired with `zim_file_path` default) OR a list of `{zim_file_path, entry_path}` dicts (for multi-archive batches). Limit: 50 per batch.

**Optional parameters:**

- `zim_file_path` (string): Default archive path; required if `entries` are bare strings, optional when each dict carries its own.
- `max_content_length` (integer): Per-entry max content length.

**Returns:**
JSON `{"results": [...], "succeeded": N, "failed": N}`. Each result includes `index` (input order), `success`, and either `content` or `error`.

**Notes:**
Rate limit is charged per entry, not per batch (anti-bypass).

### get_zim_metadata - Get ZIM file metadata from M namespace entries

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file

**Returns:**
JSON string containing ZIM metadata including entry counts, archive information, and metadata entries like title, description, language, creator, etc.

### get_main_page - Get the main page entry from W namespace

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file

**Returns:**
Main page content or information about the main page entry.

### list_namespaces - List available namespaces and their entry counts

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file

**Returns:**
JSON string containing namespace information with entry counts, descriptions, and sample entries for each namespace (C, M, W, X, etc.).

### browse_namespace - Browse entries in a specific namespace with pagination

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `namespace` (string): Namespace to browse (C, M, W, X, A, I, etc.)

**Optional parameters:**

- `limit` (integer, default: 50, range: 1-200): Maximum number of entries to return
- `offset` (integer, default: 0): Starting offset for pagination

**Returns:**
JSON string containing namespace entries with titles, content previews, and pagination information.

### walk_namespace - Deterministic cursor-paginated namespace iteration

Unlike `browse_namespace` (which samples and may cap at 200 entries on large archives), `walk_namespace` scans the archive by entry ID from `cursor` onward. Pair the returned `next_cursor` with a follow-up call to walk the rest. `done: true` indicates iteration is complete. Use this for exhaustive enumeration — e.g. dumping every `M/*` metadata entry, or finding an entry whose path doesn't follow common patterns.

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `namespace` (string): Namespace to walk (C, M, W, X, A, I, etc.)

**Optional parameters:**

- `cursor` (integer, default: 0): Entry ID to resume from
- `limit` (integer, default: 200, range: 1–500): Max entries per page

**Returns:**
JSON with `entries`, `next_cursor`, and `done` flag.

### search_with_filters - Search within ZIM file content with advanced filters

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `query` (string): Search query term

**Optional parameters:**

- `namespace` (string): Optional namespace filter (C, M, W, X, etc.)
- `content_type` (string): Optional content type filter (text/html, text/plain, etc.)
- `limit` (integer, default: 10, range: 1-100): Maximum number of results to return
- `offset` (integer, default: 0): Starting offset for pagination

**Returns:**
Filtered search results with namespace and content type information.

### search_all - Search across every ZIM file in the allowed directories

Returns merged per-file results so the caller doesn't need to know which file holds the information. Files that can't be searched (corrupt, no full-text index) are skipped without aborting the rest.

**Required parameters:**

- `query` (string): Search query term

**Optional parameters:**

- `limit_per_file` (integer, default: 5, range: 1–50): Max hits per ZIM file
- `limit` (integer): Alias for `limit_per_file`. If both are provided, `limit_per_file` wins.

**Returns:**
JSON containing per-file result groups and counts of files searched, files-with-results, and files that failed.

### find_entry_by_title - Resolve a title to one or more entry paths

Cheaper than full-text search when the caller knows the article title. Tries an exact normalized `C/<Title>` match first (fast path), then falls back to libzim's title-indexed suggestion search.

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file (used unless `cross_file=true`)
- `title` (string): Title or partial title to resolve (case-insensitive)

**Optional parameters:**

- `cross_file` (boolean, default: false): If true, search across all allowed ZIM files
- `limit` (integer, default: 10, range: 1–50): Max results to return

**Returns:**
JSON with `query`, ranked `results`, `fast_path_hit` flag, and `files_searched` count.

### get_search_suggestions - Get search suggestions and auto-complete

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `partial_query` (string): Partial search query (minimum 2 characters)

**Optional parameters:**

- `limit` (integer, default: 10, range: 1-50): Maximum number of suggestions to return

**Returns:**
JSON string containing search suggestions based on article titles and content.

### get_article_structure - Extract article structure and metadata

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path, e.g., 'C/Some_Article'

**Returns:**
JSON string containing article structure including headings, sections, metadata, and word count.

### extract_article_links - Extract internal and external links from an article

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path, e.g., 'C/Some_Article'

**Returns:**
JSON string containing categorized links (internal, external, media) with titles and metadata.

### get_related_articles - Find articles related to a given entry via outbound links

Composes `extract_article_links` and deduplicates internal links, returning up to `limit` outbound targets. (Inbound discovery was removed — it required a bounded full-archive scan that was too expensive for interactive use; reach for full-text search instead.)

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Source entry, e.g. 'C/Some_Article'

**Optional parameters:**

- `limit` (integer, default: 10, range: 1–100): Max results

**Returns:**
JSON with `outbound_results`.

### get_entry_summary - Get a concise article summary

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path, e.g., 'C/Some_Article'

**Optional parameters:**

- `max_words` (integer, default: 200, range: 10-1000): Maximum number of words in the summary

**Returns:**
JSON string containing a concise summary extracted from the article's opening paragraphs, with metadata including title, word count, and truncation status.

**Features:**

- Extracts opening paragraphs while removing infoboxes, navigation, and sidebars
- Provides quick article overview without loading full content
- Useful for LLMs to understand article context before deciding to read more

### get_table_of_contents - Extract hierarchical table of contents

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path, e.g., 'C/Some_Article'

**Returns:**
JSON string containing a hierarchical tree structure of article headings (h1-h6), suitable for navigation and content overview.

**Features:**

- Hierarchical tree structure with nested children
- Includes heading levels, text, and anchor IDs
- Provides heading count and maximum depth statistics
- Enables LLMs to navigate directly to specific sections

### get_binary_entry - Retrieve binary content from a ZIM entry

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path, e.g., 'I/image.png' or 'I/document.pdf'

**Optional parameters:**

- `max_size_bytes` (integer): Maximum size of content to return (default: 10MB). Content larger than this will return metadata only.
- `include_data` (boolean): If true (default), include base64-encoded data. Set to false to retrieve metadata only.

**Returns:**

JSON string containing:

- `path`: Entry path in ZIM file
- `title`: Entry title
- `mime_type`: Content type (e.g., "application/pdf", "image/png")
- `size`: Size in bytes
- `size_human`: Human-readable size (e.g., "1.5 MB")
- `encoding`: "base64" when data is included, null otherwise
- `data`: Base64-encoded content (if include_data=true and under size limit)
- `truncated`: Boolean indicating if content exceeded size limit

**Use Cases:**

- Retrieve PDFs for processing with PDF parsing tools
- Extract images for vision models or OCR tools
- Get video/audio files for transcription services
- Enable multi-agent workflows with specialized content processors

---

## Examples

### Listing ZIM files

```json
{
  "name": "list_zim_files"
}
```

Response:

```plain
Found 1 ZIM files in 1 directories:

[
  {
    "name": "wikipedia_en_100_2025-08.zim",
    "path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "directory": "C:\\zim",
    "size": "310.77 MB",
    "modified": "2025-09-11T10:20:50.148427"
  }
]
```

### Searching ZIM files

```json
{
  "name": "search_zim_file",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "query": "biology",
    "limit": 3
  }
}
```

Response:

```plain
Found 51 matches for "biology", showing 1-3:

## 1. Taxonomy (biology)
Path: Taxonomy_(biology)
Snippet: #  Taxonomy (biology) Part of a series on
---
Evolutionary biology
Darwin's finches by John Gould

  * Index
  * Introduction
  * [Main](Evolution "Evolution")
  * Outline

## 2. Protein
Path: Protein
Snippet: #  Protein A representation of the 3D structure of the protein myoglobin showing turquoise α-helices. This protein was the first to have its structure solved by X-ray crystallography. Toward the right-center among the coils, a prosthetic group called a heme group (shown in gray) with a bound oxygen molecule (red).

## 3. Ant
Path: Ant
Snippet: #  Ant Ants
Temporal range: Late Aptian – Present
---
Fire ants
[Scientific classification](Taxonomy_\(biology\) "Taxonomy \(biology\)")
Kingdom:  | [Animalia](Animal "Animal")
Phylum:  | [Arthropoda](Arthropod "Arthropod")
Class:  | [Insecta](Insect "Insect")
Order:  | Hymenoptera
Infraorder:  | Aculeata
Superfamily:  |
Latreille, 1809[1]
Family:  |
Latreille, 1809
```

### Getting ZIM entries

```json
{
  "name": "get_zim_entry",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "entry_path": "Protein"
  }
}
```

Response:

```plain
# Protein

Path: Protein
Type: text/html
## Content

#  Protein

A representation of the 3D structure of the protein myoglobin showing turquoise α-helices. This protein was the first to have its structure solved by X-ray crystallography. Toward the right-center among the coils, a prosthetic group called a heme group (shown in gray) with a bound oxygen molecule (red).

**Proteins** are large biomolecules and macromolecules that comprise one or more long chains of amino acid residues. Proteins perform a vast array of functions within organisms, including catalysing metabolic reactions, DNA replication, responding to stimuli, providing structure to cells and organisms, and transporting molecules from one location to another. Proteins differ from one another primarily in their sequence of amino acids, which is dictated by the nucleotide sequence of their genes, and which usually results in protein folding into a specific 3D structure that determines its activity.

A linear chain of amino acid residues is called a polypeptide. A protein contains at least one long polypeptide. Short polypeptides, containing less than 20–30 residues, are rarely considered to be proteins and are commonly called peptides.

... [Content truncated, total of 56,202 characters, only showing first 1,500 characters] ...
```

### Smart Retrieval in Action

**Example: Automatic path resolution**

```json
{
  "name": "get_zim_entry",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "entry_path": "C/Test Article"
  }
}
```

Response (showing smart retrieval working):

```plain
# Test Article

Requested Path: C/Test Article
Actual Path: C/Test_Article
Type: text/html

## Content

# Test Article

This article demonstrates the smart retrieval system automatically handling
path encoding differences. The system tried "C/Test Article" directly,
then automatically searched and found "C/Test_Article".

... [Content continues] ...
```

### get_server_health - Get server health and statistics

No parameters required.

**Returns:**

- Overall status (`healthy` / `warning` / `error`)
- Cache performance metrics (hits, misses, hit rate, size)
- Directory and ZIM-file accessibility checks
- Recommendations and warnings
- Sanitized configuration summary

**Example Response:**

```json
{
  "timestamp": "2026-05-03T10:42:11.123456",
  "status": "healthy",
  "server_name": "openzim-mcp",
  "uptime_info": {
    "process_id": "[REDACTED]",
    "started_at": "2026-05-03T10:30:00"
  },
  "configuration": {
    "allowed_directories": 1,
    "cache_enabled": true,
    "config_hash": "abc12345..."
  },
  "cache_performance": {
    "enabled": true,
    "size": 4,
    "max_size": 100,
    "hit_rate": 0.62
  },
  "health_checks": {
    "directories_accessible": 1,
    "zim_files_found": 3,
    "permissions_ok": true
  },
  "recommendations": [],
  "warnings": []
}
```

### get_server_configuration - Get detailed server configuration

No parameters required.

**Returns:**
Comprehensive server configuration plus diagnostics. Sensitive fields (PIDs, raw filesystem paths) are redacted/sanitized — diagnostic output is intended to be safe to paste into bug reports.

**Example Response:**

```json
{
  "configuration": {
    "server_name": "openzim-mcp",
    "allowed_directories": ["[REDACTED]/zim"],
    "allowed_directories_count": 1,
    "cache_enabled": true,
    "cache_max_size": 100,
    "cache_ttl_seconds": 3600,
    "content_max_length": 100000,
    "content_snippet_length": 1000,
    "search_default_limit": 10,
    "config_hash": "abc12345...",
    "server_pid": "[REDACTED]"
  },
  "diagnostics": {
    "validation_status": "ok",
    "warnings": [],
    "recommendations": []
  },
  "timestamp": "2026-05-03T10:42:11.123456"
}
```

### Additional Search Examples

**Computer-related search:**

```json
{
  "name": "search_zim_file",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "query": "computer",
    "limit": 2
  }
}
```

Response:

```plain
Found 39 matches for "computer", showing 1-2:

## 1. Video game
Path: Video_game
Snippet: #  Video game First-generation _Pong_ console at the Computerspielemuseum Berlin
---
Platforms

## 2. Protein
Path: Protein
Snippet: #  Protein A representation of the 3D structure of the protein myoglobin showing turquoise α-helices. This protein was the first to have its structure solved by X-ray crystallography. Toward the right-center among the coils, a prosthetic group called a heme group (shown in gray) with a bound oxygen molecule (red).
```

**Getting detailed content:**

```json
{
  "name": "get_zim_entry",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "entry_path": "Evolution",
    "max_content_length": 1500
  }
}
```

Response:

```plain
# Evolution

Path: Evolution
Type: text/html
## Content

#  Evolution

Part of the Biology series on
---
****
Mechanisms and processes

  * Adaptation
  * Genetic drift
  * Gene flow
  * History of life
  * Maladaptation
  * Mutation
  * Natural selection
  * Neutral theory
  * Population genetics
  * Speciation

... [Content truncated, total of 110,237 characters, only showing first 1,500 characters] ...
```

### Advanced Knowledge Retrieval Examples

**Getting ZIM metadata:**

```json
{
  "name": "get_zim_metadata",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim"
  }
}
```

Response:

```json
{
  "entry_count": 100000,
  "all_entry_count": 120000,
  "article_count": 80000,
  "media_count": 20000,
  "metadata_entries": {
    "Title": "Wikipedia (English)",
    "Description": "Wikipedia articles in English",
    "Language": "eng",
    "Creator": "Kiwix",
    "Date": "2025-08-15"
  }
}
```

**Browsing a namespace:**

```json
{
  "name": "browse_namespace",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "namespace": "C",
    "limit": 5,
    "offset": 0
  }
}
```

Response:

```json
{
  "namespace": "C",
  "total_in_namespace": 80000,
  "offset": 0,
  "limit": 5,
  "returned_count": 5,
  "has_more": true,
  "entries": [
    {
      "path": "C/Biology",
      "title": "Biology",
      "content_type": "text/html",
      "preview": "Biology is the scientific study of life..."
    }
  ]
}
```

**Filtered search:**

```json
{
  "name": "search_with_filters",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "query": "evolution",
    "namespace": "C",
    "content_type": "text/html",
    "limit": 3
  }
}
```

**Getting article structure:**

```json
{
  "name": "get_article_structure",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "entry_path": "C/Evolution"
  }
}
```

Response:

```json
{
  "title": "Evolution",
  "path": "C/Evolution",
  "content_type": "text/html",
  "headings": [
    {"level": 1, "text": "Evolution", "id": "evolution"},
    {"level": 2, "text": "History", "id": "history"},
    {"level": 2, "text": "Mechanisms", "id": "mechanisms"}
  ],
  "sections": [
    {
      "title": "Evolution",
      "level": 1,
      "content_preview": "Evolution is the change in heritable traits...",
      "word_count": 150
    }
  ],
  "word_count": 5000
}
```

**Getting article summary:**

```json
{
  "name": "get_entry_summary",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "entry_path": "C/Evolution",
    "max_words": 100
  }
}
```

Response:

```json
{
  "title": "Evolution",
  "path": "C/Evolution",
  "content_type": "text/html",
  "summary": "Evolution is the change in heritable characteristics of biological populations over successive generations. These characteristics are the expressions of genes, which are passed from parent to offspring during reproduction...",
  "word_count": 100,
  "is_truncated": true
}
```

**Getting table of contents:**

```json
{
  "name": "get_table_of_contents",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "entry_path": "C/Evolution"
  }
}
```

Response:

```json
{
  "title": "Evolution",
  "path": "C/Evolution",
  "content_type": "text/html",
  "toc": [
    {
      "level": 1,
      "text": "Evolution",
      "id": "evolution",
      "children": [
        {
          "level": 2,
          "text": "History of evolutionary thought",
          "id": "history",
          "children": []
        },
        {
          "level": 2,
          "text": "Mechanisms",
          "id": "mechanisms",
          "children": []
        }
      ]
    }
  ],
  "heading_count": 15,
  "max_depth": 4
}
```

**Getting search suggestions:**

```json
{
  "name": "get_search_suggestions",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "partial_query": "bio",
    "limit": 5
  }
}
```

Response:

```json
{
  "partial_query": "bio",
  "suggestions": [
    {"text": "Biology", "path": "C/Biology", "type": "title_start_match"},
    {"text": "Biochemistry", "path": "C/Biochemistry", "type": "title_start_match"},
    {"text": "Biodiversity", "path": "C/Biodiversity", "type": "title_start_match"}
  ],
  "count": 3
}
```

### Server Management and Diagnostics Examples

**Getting server health:**

```json
{
  "name": "get_server_health"
}
```

Response:

```json
{
  "status": "healthy",
  "server_name": "openzim-mcp",
  "uptime_info": {
    "process_id": "[REDACTED]",
    "started_at": "2026-05-03T10:30:00"
  },
  "cache_performance": {
    "enabled": true,
    "size": 15,
    "max_size": 100,
    "hit_rate": 0.85
  }
}
```

---

## ZIM Entry Retrieval Best Practices

### Smart Retrieval System

OpenZIM MCP implements an intelligent entry retrieval system that automatically handles path encoding inconsistencies common in ZIM files:

**How It Works:**

1. **Direct Access First**: Attempts to retrieve the entry using the provided path exactly as given
2. **Automatic Fallback**: If direct access fails, automatically searches for the entry using various search terms
3. **Path Mapping Cache**: Caches successful path mappings to improve performance for repeated access
4. **Enhanced Error Guidance**: Provides clear guidance when entries cannot be found

**Benefits for LLM Users:**

- **Transparent Operation**: No need to understand ZIM path encoding complexities
- **Single Tool Call**: Eliminates the need for manual search-first methodology
- **Reliable Results**: Consistent success across different path formats (spaces vs underscores, URL encoding, etc.)
- **Performance Optimized**: Cached mappings improve repeated access speed

**Example Scenarios Handled Automatically:**

- `C/Test Article` → `C/Test_Article` (space to underscore conversion)
- `C/Café` → `C/Caf%C3%A9` (URL encoding differences)
- `A/Some-Page` → `A/Some_Page` (hyphen to underscore conversion)

### Usage Recommendations

**For Direct Entry Access:**

```json
{
  "name": "get_zim_entry",
  "arguments": {
    "zim_file_path": "/path/to/file.zim",
    "entry_path": "C/Article_Name"
  }
}
```

**When Entry Not Found:**
The system will automatically provide guidance:

```
Entry not found: 'A/Article_Name'.
The entry path may not exist in this ZIM file.
Try using search_zim_file() to find available entries,
or browse_namespace() to explore the file structure.
```

---

## Important Notes and Limitations

### Content Length Requirements

- The `max_content_length` parameter for `get_zim_entry` must be at least 1000 characters
- Content longer than the specified limit will be truncated with a note showing the total character count

### Search Behavior

- Search results may include articles that contain the search terms in various contexts
- Results are ranked by relevance but may not always be directly related to the primary meaning of the search term
- Search snippets provide a preview of the content but may not show the exact location where the search term appears

### File Format Support

- Currently supports ZIM files (Zeno IMproved format)
- Tested with Wikipedia ZIM files (e.g., `wikipedia_en_100_2025-08.zim`)
- File paths must be properly escaped in JSON (use `\\` for Windows paths)

---

## Configuration

OpenZIM MCP supports configuration through environment variables with the `OPENZIM_MCP_` prefix:

```bash
# Cache configuration
export OPENZIM_MCP_CACHE__ENABLED=true
export OPENZIM_MCP_CACHE__MAX_SIZE=200
export OPENZIM_MCP_CACHE__TTL_SECONDS=7200

# Content configuration
export OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH=200000
export OPENZIM_MCP_CONTENT__SNIPPET_LENGTH=2000
export OPENZIM_MCP_CONTENT__DEFAULT_SEARCH_LIMIT=20

# Logging configuration
export OPENZIM_MCP_LOGGING__LEVEL=DEBUG
export OPENZIM_MCP_LOGGING__FORMAT="%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Server configuration
export OPENZIM_MCP_SERVER_NAME=my_openzim_mcp_server
```

### Configuration Options

| Setting | Default | Description |
|---------|---------|-------------|
| `OPENZIM_MCP_TOOL_MODE` | `simple` | Tool surface: `simple` (one `zim_query` tool) or `advanced` (21 specialized tools). Controlled by `--tool-mode` on the CLI as well. |
| `OPENZIM_MCP_TRANSPORT` | `stdio` | Transport protocol: `stdio`, `http`, or `sse`. |
| `OPENZIM_MCP_HOST` | `127.0.0.1` | HTTP/SSE bind host. Non-loopback hosts require `OPENZIM_MCP_AUTH_TOKEN`. |
| `OPENZIM_MCP_PORT` | `8000` | HTTP/SSE bind port. |
| `OPENZIM_MCP_AUTH_TOKEN` | *(unset)* | Bearer token required when binding HTTP/SSE to a non-loopback interface. |
| `OPENZIM_MCP_CORS_ORIGINS` | *(empty)* | JSON array of allowed CORS origins for the HTTP transport. Wildcard `*` is rejected. |
| `OPENZIM_MCP_ALLOWED_HOSTS` | *(empty)* | JSON array of public-facing hostnames the HTTP transport accepts in the `Host` header (e.g. `["mcp.example.com"]`). Loopback is always allowed; this extends it for reverse-proxy and Tailscale-serve deployments. Wildcard `*` is rejected. |
| `OPENZIM_MCP_SUBSCRIPTIONS_ENABLED` | `true` | Enable MCP resource subscriptions (HTTP transport only). When `false`, `subscribe` calls succeed but no updates fire. |
| `OPENZIM_MCP_WATCH_INTERVAL_SECONDS` | `5` | Polling interval (1–60s) for the subscription mtime watcher. |
| `OPENZIM_MCP_CACHE__ENABLED` | `true` | Enable/disable caching |
| `OPENZIM_MCP_CACHE__MAX_SIZE` | `100` | Maximum cache entries |
| `OPENZIM_MCP_CACHE__TTL_SECONDS` | `3600` | Cache TTL in seconds |
| `OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH` | `100000` | Max content length |
| `OPENZIM_MCP_CONTENT__SNIPPET_LENGTH` | `1000` | Max snippet length |
| `OPENZIM_MCP_CONTENT__DEFAULT_SEARCH_LIMIT` | `10` | Default search result limit |
| `OPENZIM_MCP_LOGGING__LEVEL` | `INFO` | Logging level |
| `OPENZIM_MCP_LOGGING__FORMAT` | `%(asctime)s - %(name)s - %(levelname)s - %(message)s` | Log message format |
| `OPENZIM_MCP_SERVER_NAME` | `openzim-mcp` | Server instance name |

---

## Security Features

- **Path Traversal Protection**: Secure path validation prevents access outside allowed directories
- **Input Sanitization**: All user inputs are validated and sanitized
- **Resource Management**: Proper cleanup of ZIM archive resources
- **Error Handling**: Sanitized error messages prevent information disclosure
- **Type Safety**: Full type annotations prevent type-related vulnerabilities

---

## Performance Features

- **Intelligent Caching**: LRU cache with TTL for frequently accessed content
- **Resource Pooling**: Efficient ZIM archive management
- **Optimized Content Processing**: Fast HTML to text conversion
- **Lazy Loading**: Components initialized only when needed
- **Memory Management**: Proper cleanup and resource management

---

## Testing

The project includes comprehensive testing with 80%+ coverage using both mock data and real ZIM files:

### Test Categories

- **Unit Tests**: Individual component testing with mocks
- **Integration Tests**: End-to-end functionality testing with real ZIM files
- **Security Tests**: Path traversal and input validation testing
- **Performance Tests**: Cache and resource management testing
- **Format Compatibility**: Testing with various ZIM file formats and versions
- **Error Handling**: Testing with invalid and malformed ZIM files

### Test Infrastructure

OpenZIM MCP uses a hybrid testing approach:

1. **Mock-based tests**: Fast unit tests using mocked libzim components
2. **Real ZIM file tests**: Integration tests using official zim-testing-suite files
3. **Automatic test data management**: Download and organize test files as needed

### Test Data Sources

- **Built-in test data**: Basic test files included in the repository
- **zim-testing-suite integration**: Official test files from the OpenZIM project
- **Environment variable support**: `ZIM_TEST_DATA_DIR` for custom test data locations

```bash
# Run tests with coverage report
make test-cov

# View coverage report
open htmlcov/index.html

# Run comprehensive tests with real ZIM files
make test-with-zim-data
```

### Test Markers

Tests are organized with pytest markers:

- `@pytest.mark.requires_zim_data`: Tests requiring ZIM test data files
- `@pytest.mark.integration`: Integration tests
- `@pytest.mark.slow`: Long-running tests

---

## Monitoring

OpenZIM MCP provides built-in monitoring capabilities:

- **Health Checks**: Server health and status monitoring
- **Cache Metrics**: Cache hit rates and performance statistics
- **Structured Logging**: JSON-formatted logs for easy parsing
- **Error Tracking**: Comprehensive error logging and tracking

---

## Versioning

This project uses [Semantic Versioning](https://semver.org/) with automated version management through [release-please](https://github.com/googleapis/release-please).

### Automated Releases

Version bumps and releases are automated based on [Conventional Commits](https://www.conventionalcommits.org/):

- **`feat:`** - New features (minor version bump)
- **`fix:`** - Bug fixes (patch version bump)
- **`feat!:`** or **`BREAKING CHANGE:`** - Breaking changes (major version bump)
- **`perf:`** - Performance improvements (patch version bump)
- **`docs:`**, **`style:`**, **`refactor:`**, **`test:`**, **`chore:`** - No version bump

### Release Process

The project uses an **improved, consolidated release system** with automatic validation:

1. **Automatic** (Recommended): Push conventional commits → Release Please creates PR → Merge PR → Automatic release
2. **Manual**: Use GitHub Actions UI for direct control over releases
3. **Emergency**: Push tags directly for critical fixes

**Key Features:**

- **Zero-touch releases** from main branch
- **Automatic version synchronization** validation
- **Comprehensive testing** before every release
- **Improved error handling** and rollback capabilities
- **Branch protection** prevents broken releases

The release flow is implemented in [`.github/workflows/release-please.yml`](.github/workflows/release-please.yml) and [`.github/workflows/release.yml`](.github/workflows/release.yml).

### Commit Message Format

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

**Examples:**

```bash
feat: add search suggestions endpoint
fix: resolve path traversal vulnerability
feat!: change API response format
docs: update installation instructions
```

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests (`make check`)
5. **Use conventional commit messages** (`git commit -m 'feat: add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Development Guidelines

- Follow PEP 8 style guidelines
- Add type hints to all functions
- Write tests for new functionality
- Update documentation as needed
- **Use conventional commit messages** for automatic versioning
- Ensure all tests pass before submitting

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- [Kiwix](https://www.kiwix.org/) for the ZIM format and libzim library
- [MCP](https://modelcontextprotocol.io/) for the Model Context Protocol
- The open-source community for the excellent libraries used in this project

---

Made with ❤️ by [Cameron Rye](https://rye.dev)
