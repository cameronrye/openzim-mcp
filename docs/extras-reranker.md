# [reranker] Extra — Cross-Encoder Search Reranking

The `[reranker]` extra adds cross-encoder relevance reranking on top of
Xapian's BM25 results. When installed, `zim_query` search intents and
`synthesize` mode silently produce more relevant top-K results on
content-fragment queries. The advanced `zim_search` tool returns raw
Xapian ranking and is not reranked. Caller surface is unchanged.

## Install

```bash
pip install openzim-mcp[reranker]
```

Install footprint: roughly 200 MB of Python packages (FastEmbed +
onnxruntime + tokenizers + huggingface_hub). Installing the extra is
**not** enough on its own: the cross-encoder model (~1.1 GB for the
default `BAAI/bge-reranker-base`) is never fetched by the server, so a
second step is required — see
[Staging the model](#staging-the-model-required).

The model is read from FastEmbed's model cache
(`$FASTEMBED_CACHE_PATH`, defaulting to `<tempdir>/fastembed_cache`);
set `OPENZIM_MCP_ML__RERANKER__CACHE_DIR` to pin a persistent location.
Pinning it is strongly recommended: the default cache lives under the
system temp directory, so a reboot or a temp sweeper discards the
staged model and rerank goes quiet until you stage it again.

## Supported platforms

The `[reranker]` extra is supported on (wheel availability):

- Linux glibc x86_64 and ARM64
- macOS x86_64 and ARM64
- Windows x86_64

CI exercises the extra on Linux x86_64 (Python 3.12/3.13) only — the
`test-reranker` job in `test.yml`.

Edge platforms (Alpine, FreeBSD, ARM32) are not part of the supported
matrix; FastEmbed wheels may not be available there. The base install
(`pip install openzim-mcp`) is unaffected.

## Staging the model (required)

The server never downloads the model. `ml.reranker.allow_model_download`
defaults to `false`, so the runtime loads the cross-encoder from the
local cache only — the MCP `instructions` payload tells callers this
server reads content from local archives, and an unannounced 1.1 GB
fetch to huggingface.co on someone's first question contradicts that.

Stage it once, on a machine with network access:

```bash
openzim-mcp download-models
```

Idempotent — safe to re-run; it checks the cache and fetches only what
is missing. It honours `OPENZIM_MCP_ML__RERANKER__CACHE_DIR`, so run it
with the same cache directory the server uses.

If the model is not in the cache, the first rerank-eligible query falls
back to Xapian-only ranking for the rest of the process and logs a
WARNING naming this command. Search still works; results are simply
ranked by Xapian alone.

Operators who would rather trade the offline guarantee for convenience
can opt back into the old behaviour:

```bash
export OPENZIM_MCP_ML__RERANKER__ALLOW_MODEL_DOWNLOAD=true
```

With that set, the first rerank-eligible query fetches the model from
HuggingFace, bounded by `first_call_timeout_seconds` (default 15 s) —
and the "content is read from local archives" statement in the server's
instructions no longer tells the whole story for that deployment.

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
export OPENZIM_MCP_ML__RERANKER__ALLOW_MODEL_DOWNLOAD=false
export OPENZIM_MCP_ML__RERANKER__CACHE_DIR=/var/lib/openzim-mcp/models
```

(The `__` double-underscore delimits nested config sections.)

## Telemetry

Reranker activity in `zim_query` search paths flows through the existing
`_track()` counter path; `synthesize`-mode rerank emits the same
`telemetry: <event>` INFO log lines but does not increment the counters.
Event names (all use dot-separator):

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
operators running in simple tool mode, who don't have access to the
advanced-mode `zim_health` tool to read the counter directly. Set the
logger to WARNING or higher to suppress them.

A model-load failure (model not staged, timeout, corrupt cache) logs a
one-line WARNING to the configured logger and trips a process-wide kill
switch
(`BGEReranker`'s load-failure latch; mid-inference failures are
separately kill-switched by the `ml_fallback` decorator) — subsequent
search calls emit
`reranker_skipped.not_installed` (because `BGEReranker.get()` returns
None) until the process restarts.

## Troubleshooting

**"reranker model load failed: ... Model downloads are off by default"**
The model is not in the local cache. Run `openzim-mcp download-models`
with the same `CACHE_DIR` the server uses. If you staged it earlier and
it has vanished, the cache is probably still on its default path under
the system temp directory — pin `OPENZIM_MCP_ML__RERANKER__CACHE_DIR`.

**"reranker model load failed: timeout"**
Loading exceeded the configured `first_call_timeout_seconds` (default
15s — sized for ONNX session creation on a warm cache). Raise it via
`OPENZIM_MCP_ML__RERANKER__FIRST_CALL_TIMEOUT_SECONDS` on slow hardware,
or — if you enabled `allow_model_download` — stage the model with
`openzim-mcp download-models` instead of paying the fetch at query time.

**Install fails with "no wheel for fastembed"**
The platform isn't in the supported matrix (see above). Use the base
install without the extra; the server still works, just without rerank.

**Rerank doesn't seem to fire**
Check the `min_query_tokens` gate (default 4 word tokens) and the
`OPENZIM_RERANKER_DISABLE` environment variable. The
`reranker_skipped.*` telemetry counters' relative magnitudes tell you
which gate fired.
