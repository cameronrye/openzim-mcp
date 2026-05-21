# [reranker] Extra — Cross-Encoder Search Reranking

The `[reranker]` extra adds cross-encoder relevance reranking on top of
Xapian's BM25 results. When installed, search-shaped tools and
`synthesize` mode silently produce more relevant top-K results on
content-fragment queries. Caller surface is unchanged.

## Install

```bash
pip install openzim-mcp[reranker]
```

Install footprint: roughly 200 MB of Python packages (FastEmbed +
onnxruntime + tokenizers + huggingface_hub). The cross-encoder model
itself is downloaded lazily on first use (~1.1 GB for the default
`BAAI/bge-reranker-base`) and cached in your HuggingFace home.

## Supported platforms

The `[reranker]` extra is tested on:
- Linux glibc x86_64 and ARM64
- macOS x86_64 and ARM64
- Windows x86_64

Edge platforms (Alpine, FreeBSD, ARM32) are not part of the supported
matrix; FastEmbed wheels may not be available there. The base install
(`pip install openzim-mcp`) is unaffected.

## Pre-staging models for offline deployment

By default, the first call after install downloads `BAAI/bge-reranker-base`
(~1.1 GB) from HuggingFace. Operators running in air-gapped environments
should pre-stage:

```bash
openzim-mcp download-models
```

Idempotent — safe to re-run. Without pre-staging, the first MCP query
that triggers rerank has a 15-second timeout; on timeout the reranker
falls back to Xapian-only ranking for the rest of the process and logs
a structured warning.

## Verifying it's active

After installing the extra, the MCP server log emits a one-line INFO
record on first rerank:

```
reranker loaded: model_id=BAAI/bge-reranker-base fastembed=0.x.y
```

Telemetry events also fire (see below) — `reranker_engaged` counts
indicate the reranker is doing real work; `reranker_skipped.*` counts
indicate the various bypass paths.

## Disabling rerank without uninstalling

Three knobs, listed in priority order:

1. Environment variable: `OPENZIM_RERANKER_DISABLE=1`
2. Config: `ml.reranker.enabled = false`
3. Uninstall the extra: `pip uninstall fastembed`

The skip-on-short-query gate (`ml.reranker.min_query_tokens`, default 4)
bypasses rerank for queries with fewer than 4 word tokens — entity
queries like `Berlin` or `Photosynthesis` get the canonical-title hit
from Xapian directly without rerank cost. Set `min_query_tokens = 0` to
disable the gate.

## Configuration

All knobs documented in `RerankerConfig` (see `openzim_mcp/config.py`).
Set via environment variables with the `OPENZIM_MCP_` prefix:

```bash
export OPENZIM_MCP_ML__RERANKER__ENABLED=true
export OPENZIM_MCP_ML__RERANKER__MIN_QUERY_TOKENS=4
export OPENZIM_MCP_ML__RERANKER__FINAL_TOP_K=10
export OPENZIM_MCP_ML__RERANKER__FIRST_CALL_TIMEOUT_SECONDS=15.0
```

(The `__` double-underscore delimits nested config sections.)

## Telemetry

Reranker activity flows through the existing `_track()` path with these
event names (all use dot-separator):

- `reranker_engaged` — fires when the cross-encoder actually scored
  results (i.e., the returned candidates have `rerank_score` set).
- `reranker_skipped.not_installed` — `[reranker]` extra absent or
  disabled via env/config.
- `reranker_skipped.no_results` — Xapian returned zero candidates;
  nothing to rerank.
- `reranker_skipped.passthrough` — the reranker ran but bypassed
  scoring. Two causes:
  - The skip-on-short-query gate fired (`min_query_tokens` not met)
  - A mid-inference failure tripped the `ml_fallback` decorator, which
    returned input candidates sliced to `top_k` (Xapian order preserved)

Each reranker event also emits a single INFO-level log line per call
of the form `telemetry: <event>`. This makes engagement observable to
operators running in simple tool mode, who don't have access to
`get_server_health` to read the counter directly. Set the logger to
WARNING or higher to suppress them.

A model-load failure (timeout, network error) logs a one-line WARNING
to the configured logger and trips a process-wide kill switch via
`ml_fallback` — subsequent search calls emit
`reranker_skipped.not_installed` (because `BGEReranker.get()` returns
None) until the process restarts.

## Troubleshooting

**"reranker model load failed: timeout"**
The first-call download exceeded the configured
`first_call_timeout_seconds` (default 15s — sized for ONNX session
creation on a warm cache). Run `openzim-mcp download-models` once to
pre-stage; the next server start will use the cached model. On slower
hardware or cold-cache fetches, raise the timeout via
`OPENZIM_MCP_ML__RERANKER__FIRST_CALL_TIMEOUT_SECONDS`.

**Install fails with "no wheel for fastembed"**
The platform isn't in the supported matrix (see above). Use the base
install without the extra; the server still works, just without rerank.

**Rerank doesn't seem to fire**
Check the `min_query_tokens` gate (default 4 word tokens) and the
`OPENZIM_RERANKER_DISABLE` environment variable. The
`reranker_skipped.*` telemetry counters' relative magnitudes tell you
which gate fired.
