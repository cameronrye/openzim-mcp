# v2 Phase D — Optional ML Accelerators (Design Spec)

**Status:** Draft
**Phase:** D of 6 ([tracking doc](../../v2/README.md))
**Items in scope:** #6 (cross-encoder reranker), #8 (server-side query rewriting / decomposition), #12 (hybrid intent parser), #15 (sentence-embedding sidecar)
**Target:** Four `v2.0.0bN` pre-releases (one per sub-D milestone). Final tag `v2.0.0b4`.
**Date:** 2026-05-20

---

## Goal

Make every model — especially Haiku-class, Llama-3-8B, Mistral-7B, Phi-class — find what it needs in a multi-million-article ZIM archive without burning context on retry loops. Phase D adds four optional ML capabilities behind opt-in extras. Each falls back gracefully to the existing pure-Python path when its extra is missing, and none becomes the default install.

The four items decompose into one coordinated design but ship as four independent sub-D milestones (`v2.0.0b1` → `b4`). Each sub-D is independently shippable and reviewable; the entire spec is one design because the four items share infrastructure (model lifecycle, fallback decorator, telemetry, config, testing patterns).

## Non-goals

- **No required ML at install.** The default `pip install openzim-mcp` install stays lean. Every ML capability is behind one of three extras: `[reranker]`, `[planner]`, `[embeddings]`.
- **No GPU requirement.** Every model targets CPU-fast (<150 ms p95 hot-path). GPU support is not designed for in v2.
- **No HyDE.** Per the v2 README's research findings, hypothetical-document expansion hurts small models. Explicit non-goal — the design must not introduce a HyDE path even as a future-extension hook.
- **No network at runtime.** Models download once at install (or via `openzim-mcp download-models` for air-gapped pre-stage) and load from disk thereafter. Sidecars build offline via the explicit `openzim-mcp build embeddings` CLI.
- **No new ZIM archive format.** Sidecars live next to `.zim` files; the archive itself is read-only and unchanged.
- **No model-trained-on-prod-data.** All bundled models (fastText `.ftz` files) train from the open-source sweep transcripts already in repo. The training data and training script ship in the repo for reproducibility.
- **No multilingual default.** Default model picks (`bge-reranker-base`, `bge-small-en-v1.5`) target English-first archives. Multilingual archives override via env vars; this design documents the override surface but does not ship multilingual defaults.

## Non-goals carried forward from earlier phases

- **No new tool surface.** Tool collapse is Phase F. Phase D plugs into existing tools (`search_zim_file`, `synthesize` mode of `zim_query`, `parse_intent`).
- **No response-contract changes.** Phase B already standardized response shapes. Phase D only adds metadata fields (`_meta.reranked`, `_meta.intent_source`, `_meta.decomposed`).
- **No replacing libzim or Xapian.** Reranker reranks Xapian results; embeddings sidecar fuses semantic results with Xapian results via RRF; both treat Xapian as the canonical source.

---

## Foundational decisions

These apply across all four sub-Ds.

- **Three opt-in extras.** `[reranker]`, `[planner]`, `[embeddings]`. Plus convenience meta-extra `[ml-all]` = all three.
- **Lazy import + lazy load.** No top-level imports of optional libraries. Every ML capability uses `importlib.util.find_spec(...)` for detection and imports the library only inside the function that needs it. Model load is deferred to first use.
- **Graceful fallback contract.** When a model fails to load or a per-call inference fails, the code path logs a `WARNING`, sets a per-process kill switch for that feature, and falls back to the pre-ML behavior. The caller sees no exception.
- **Telemetry by additive event names.** All ML events flow through the existing `_track("<event_name>")` path in `simple_tools.py` (next to `_track("chained_intent_rejected")` at line 541). No new telemetry infrastructure.
- **Single shared model cache.** `~/.cache/openzim-mcp/models/` by default, overridable via `OPENZIM_MODEL_CACHE_DIR`. FastEmbed and any future model store share this root.
- **Air-gapped support via explicit CLI.** A new `openzim-mcp download-models` command pre-stages every model the installed extras need. Idempotent; safe to re-run.
- **Configuration via `MLConfig` composing four sub-configs.** Discoverable via the existing `openzim-mcp config show` CLI.

---

## Sub-D milestones

| Milestone | Items | Extra | Tag | Why this order |
|-----------|-------|-------|-----|----------------|
| **sub-D-1** | #6 cross-encoder reranker | `[reranker]` | `v2.0.0b1` | Smallest scope, biggest immediate relevance win, establishes the lazy-ML + fallback patterns the other items inherit |
| **sub-D-2** | #8 Tier 1 query rewriting (rules-based) | (none — base install) | `v2.0.0b2` | Zero deps; every downstream item benefits from a cleaner query upstream. Lift the floor for free. |
| **sub-D-3** | #8 Tier 2 + #12 hybrid intent parser | `[planner]` | `v2.0.0b3` | Tier-2 + classifier share a model; ship together. Live evidence from sub-D-2 informs what the rules-based pass misses. |
| **sub-D-4** | #15 embeddings sidecar + hybrid retrieval | `[embeddings]` | `v2.0.0b4` | Heaviest scope (build CLI, sidecar format, RRF plumbing). Plugs into a stable reranker (sub-D-1) and classifier (sub-D-3). |

Each milestone ships with its own live-MCP smoke pass before its release PR merges. No mass-release at the end of Phase D — discover regressions early.

---

## Sub-D-1 — Cross-encoder reranker (#6)

### What it does

When `[reranker]` is installed, search-shaped tools (`search_zim_file`, `search_with_filters`, `search_all`) and `synthesize` mode silently rerank Xapian top-N results using a cross-encoder model. Caller surface unchanged; relevance improves ~30 pp on content-fragment queries.

### Activation surface

- `simple_tools.py:_handle_search` — Xapian returns top-N (default N=50), `BGEReranker.rerank(query, results, top_k=requested_limit)` produces the final order. When `BGEReranker.get()` returns None (extra absent or kill-switched), skip cleanly.
- `simple_tools.py:_handle_filtered_search` + `_handle_search_all` — same shape.
- `synthesize.py:_collect_passages` — rerank passage candidates before the citation block is assembled. Phase C #10 explicitly anticipates this hook.
- `simple_tools.py:_handle_tell_me_about` — NOT reranked. Entity-driven queries are already canonical-title resolved; rerank adds cost without value.
- **Skip-on-short-query gate:** when query has <4 word tokens, skip rerank. Single-word entity queries dominate the Xapian-score-1.0 canonical-title hit; the cross-encoder is wasted there. Cheap gate; avoids ~40% of needless rerank calls per the live-MCP sweep traffic patterns.

### Module structure

```
openzim_mcp/ml/reranker.py    # ~250 LOC
    class BGEReranker:
        - get() classmethod, lazy singleton, thread-safe init
        - score_pairs(pairs) -> List[float], batch-score (query, passage) pairs
        - rerank(query, candidates, top_k) -> List[Candidate]
```

### Library: FastEmbed

- `fastembed>=0.4.0,<1.0`. ONNX-backed, ~150 MB total install. No torch dependency.
- CPU benchmark: ~50 ms for batch=50 of `bge-reranker-base` ONNX. Well under the 150 ms p95 budget.
- Default model: `Xenova/bge-reranker-base-onnx` (~80 MB), download-on-first-use, cached in `~/.cache/openzim-mcp/models/fastembed`.
- Overrides via env: `OPENZIM_RERANKER_MODEL`, `OPENZIM_RERANKER_CACHE_DIR`, `OPENZIM_RERANKER_DISABLE=1` (kill switch when extra is installed but we don't want it).

### Fallback contract

- Model load fails (corrupt cache, OOM, ImportError) → log `WARNING`, set process-local `_reranker_disabled = True`, every future `get()` returns None. Search continues on Xapian.
- Per-call exception (tokenizer overflow, model crash) → log `WARNING` once per process, return input candidates in their Xapian order. Never raise to caller.
- Telemetry: `_track("reranker_engaged" | "reranker_skipped" | "reranker_failed")`.

### Response shape

- Each result envelope gains `rerank_score: float | None` (None when not reranked).
- Response object gains `_meta.reranked: bool` for branch-on-augmented-ranking detection.
- No tool signature changes; additive metadata only.

### Configuration

```python
class RerankerConfig(BaseModel):
    enabled: bool = True               # only checked when extra importable
    model_id: str = "Xenova/bge-reranker-base-onnx"
    candidate_pool_size: int = 50      # Xapian top-N to rerank
    final_top_k: int = 10              # default response cap; caller override wins
    max_query_length: int = 256
    max_passage_length: int = 512
    min_query_tokens: int = 4          # skip-on-short-query gate
    cache_dir: Path | None = None      # None → FastEmbed default
```

### Testing

- Unit: mock `TextRerank.rerank()` and assert candidate ordering + envelope shape.
- Integration: `tests/ml/test_reranker_integration.py` builds an in-process reranker against a 3-doc test corpus; asserts predictable reorder. `@pytest.mark.requires_reranker` keyed off `importlib.util.find_spec("fastembed")`.
- Telemetry assertion: `_reranker_engaged` counter increments once per search hit.
- Performance test: rerank batch of 50 in <150 ms p95 on the CI runner.

### Performance budget

- p95 added latency per search query: ≤120 ms on a modern CPU.
- First-call cold start: ≤2 s (one-time model download or `openzim-mcp download-models` pre-stage).

---

## Sub-D-2 — Tier 1 query rewriting (#8 partial)

### What it does

Every query, before any pattern matching, runs through five rules-based rewrite passes. Zero extras, zero models, zero ML dependencies. Lands in the BASE install so all downstream items inherit a cleaner query. Lift the floor for every model immediately.

### Five rule families

Each idempotent, each loop-safe (same shape as existing `_strip_param_leaks` / `_strip_trailing_politeness` patterns in `intent_parser.py`):

1. **Lowercase-entity normalization.** Pulls scattered `.lower()` calls in the `_tokenize_for_relevance` path into a named pass. Title-promotion's case-preserving path is untouched.
2. **Common-misspelling map.** Ship `openzim_mcp/data/misspellings.txt` — ~200 entries seeded from Wikipedia's "List of common misspellings." Loaded once at module init; the map is `dict[str, str]` keyed on lowercase word; whole-word substitution (word-boundary anchors). Cap at ~500 entries to keep the lookup cheap.
3. **Stopword-aware phrase detection.** When the topic carries `the / a / an / of` as leading or interleaved token, use the title index as the oracle: if the leading-stopword form has a canonical hit (`The Beatles`, `Of Mice and Men`), keep it; otherwise strip. One extra title-index probe per ambiguous query.
4. **Simple "X of Y" decomposition.** `population of Berlin` → `(entity=Berlin, attribute=population)`. Routes to the existing subject-attribute extraction in `simple_tools.py:_handle_tell_me_about` (the post-a16 P4-D1/P6-D1 hardened path). Two regex shapes:
   - `<attribute_word> of <entity>`
   - `<entity>'s <attribute>` (genitive)
   - **NOT in Tier-1:** multi-hop questions ("what year did the inventor of X die"). Tier-2 + classifier in sub-D-3.
5. **Explicit HyDE skip.** No hypothetical-document synthesis; documented in the spec as a locked-in non-goal.

### Module structure

```
openzim_mcp/intent_parser.py (existing, 1345 lines)
    Extends the existing strip chain. Add four new methods following the
    same idempotent-loop shape:
        - _normalize_topic_case(query)
        - _apply_misspelling_map(query)
        - _detect_stopword_phrase(query, title_index)  # optional title_index
        - _decompose_x_of_y(query)
    All called from parse_intent BEFORE pattern matching.

openzim_mcp/data/misspellings.txt   # new, ~200 lines
```

The stopword-phrase pass requires a title-index handle when called from the live path. Pass it in optionally; when unavailable (unit tests without an archive), the rule degrades cleanly to a no-op.

### Configuration

```python
class QueryRewriteConfig(BaseModel):
    enabled: bool = True
    misspelling_map_path: Path | None = None  # None → bundled default
    stopword_phrase_probe: bool = True
```

### Telemetry

`_track("query_rewritten", details={"rules_applied": [...]})` — observability without printing rewritten text (PII-safe).

### Testing

- Unit: parametrized test cases per rule family — fix side, no-op side (already-correct), embedding-safety side (don't eat substrings).
- Regression guards: pin the misspelling-map row count + sample entries so future contributors can't silently delete entries.
- Live-MCP integration: extend the existing `tests/test_post_a*_beta_fixes.py` regression set with Tier-1 expected outputs.

### Why route decomposition through existing `_handle_tell_me_about`

The subject-attribute extraction path in `simple_tools.py:_handle_tell_me_about` is mature (a17 P1-D1 + post-a15 P4-D1 hardening). Tier-1 reuses it rather than introducing a parallel surface. Sub-D-3's classifier expands this into a true multi-hop decomposer.

---

## Sub-D-3 — Tier 2 query rewriting + hybrid intent parser (#8 + #12)

### What it does

When Tier-1 + regex aren't enough, fall back to a tiny ML classifier — without bloating the default install. Both items share one model and ship together behind a single `[planner]` extra.

### Why ship #8 Tier-2 and #12 together

They fire on the same trigger (low-confidence query shapes) and benefit from sharing a model. Splitting would mean two model loads, two `[planner-X]` extras, and duplicate failure-handling code.

### Classifier: fastText

- `fasttext-wheel>=0.9.2,<1.0`. ~50 MB installed. No torch dependency. CPU-fast (~0.1 ms per classification). Trains in minutes on the existing sweep transcripts.
- Three trained models bundled inside `openzim_mcp/ml/data/`:
  - `intent_classifier.ftz` (~5 MB, quantized): 19-class classifier matching `INTENT_PATTERNS` labels.
  - `decomposition_classifier.ftz` (~3 MB): binary "needs decomposition?" classifier.
  - `decomposition_extractor.ftz` (~5 MB): token-level sequence labeler producing `(entity_span, attribute_span, modifier_span)`.
- Bundled in the wheel, not downloaded at runtime — adds ~15 MB to `[planner]` install. Offline-first; no network at runtime.

### Hybrid intent parser flow (#12)

```
parse_intent(query):
    1. apply Tier-1 rewrites               # sub-D-2
    2. run INTENT_PATTERNS regex match     # existing
    3. if confidence >= 0.7:               # existing
         return regex result               # fast path, ~99% of traffic
    4. else if [planner] installed:
         classifier.predict(query)
         if classifier.confidence >= 0.7:
             return classifier result with rank_origin="classifier"
    5. else:
         existing low-confidence behavior (current footer)
```

### Tier-2 decomposition flow (#8)

```
after intent classification:
    if intent == "tell_me_about" AND query is multi-hop-shaped:
        decomposition_classifier.predict(query)
        if "needs decomposition":
            extractor.predict(query) -> (entity, attribute, modifier)
            issue internal entity-lookup + attribute-lookup chain
            assemble combined response with cite markers
        else:
            fall through to standard tell_me_about
```

### Training data: sweep transcripts already in repo

- `tests/test_post_a*_beta_fixes.py` carries ~1000+ labeled `(query, expected_intent)` pairs from the live MCP sweeps a8 → a25 (estimate based on parametrized test counts; exact yield depends on dedup). Extract into a JSONL dataset (`openzim_mcp/ml/data/training/intent.jsonl`). Quality bar: a per-intent minimum of 30 examples; under-represented intents get synthetic seed examples generated from the regex patterns themselves.
- For decomposition: synthetic dataset generated by templating `(attribute) of (entity)` / `(entity)'s (attribute)` over Wikipedia's category trees. Ship a 5000-row seed set without category-tree dependency.
- Training script (`scripts/train_planner.py`) is reproducible — ships in the repo but NOT in the wheel. CI verifies bundled models are checksum-pinned.

### Module structure

```
openzim_mcp/ml/planner.py             # ~250 LOC
openzim_mcp/ml/intent_classifier.py   # ~150 LOC
openzim_mcp/ml/data/                  # bundled .ftz files
openzim_mcp/ml/data/training/         # JSONL datasets (training reproducibility)
scripts/train_planner.py              # not in wheel
```

### Configuration

```python
class PlannerConfig(BaseModel):
    enabled: bool = True
    intent_model_path: Path | None = None         # None → bundled .ftz
    decomposition_model_path: Path | None = None
    extractor_model_path: Path | None = None
    classifier_confidence_threshold: float = 0.7  # match regex threshold
    decomposition_enabled: bool = True            # finer kill switch
```

### Response shape

- Optional `_meta.intent_source: "regex" | "classifier"` field.
- Optional `_meta.decomposed: bool` when Tier-2 decomposition fired.
- No tool signature changes; additive metadata only.
- Raw classifier scores not exposed to callers — confidence is internal.

### Fallback contract (same shape as sub-D-1)

- Classifier load fails → log WARNING, set `_planner_disabled`, every future `get()` returns None, parse_intent falls back to existing low-confidence footer.
- Classifier prediction returns confidence < 0.7 → treated as if it never ran.
- Telemetry: `_track("intent_classifier_engaged" | "decomposition_engaged" | "planner_failed")`.

### Testing

- Unit: parametrized tests with mocked `fastText.predict()` covering each of 19 intents + binary decomposition gate.
- Integration: `tests/ml/test_planner_integration.py` loads bundled `.ftz` files (only when fasttext importable, skip otherwise); asserts known live-MCP queries route correctly.
- Quality gate: held-out test set (10% of JSONL) achieves ≥90% intent classification accuracy. CI fails if retrain regresses below threshold.

### Why fastText over distilled sentence-transformer

README permits fastText / distilled sentence-transformer / lightweight rules-tree. fastText wins on:
- **Size:** 50 MB vs ~500 MB for sentence-transformers.
- **Speed:** 0.1 ms vs ~10 ms per classification.
- **Dependency surface:** no torch, no transformers.

Sentence-transformer reranking already lives in sub-D-1; sharing torch there doesn't make the planner cheaper.

---

## Sub-D-4 — Embeddings sidecar + hybrid retrieval (#15)

### What it does

True semantic retrieval. Find articles by meaning, not just keyword overlap. Heaviest scope in Phase D because it adds a build-time CLI, a sidecar file format, and hybrid-retrieval plumbing. Ships last so it can plug into a stable reranker (sub-D-1) and a stable classifier-aware intent parser (sub-D-3).

### Sidecar file format: `<archive>.zim.semantic.hnsw`

- Single binary, lives next to the `.zim` file.
- Wraps two artifacts: HNSW index (via `hnswlib`) + parallel `path_id ↔ entry_path` mapping (`<archive>.zim.semantic.paths.sqlite`).
- Header carries: `model_id`, `embedding_dim`, `vector_count`, ZIM archive UUID (for cross-archive safety), HNSW params (`M`, `ef_construction`), schema version.
- Cross-archive safety: load-time UUID check. Sidecar built for archive A won't load against archive B; logs a WARNING and silently disables semantic retrieval for that archive.

### Encoder: `bge-small-en-v1.5` via FastEmbed

- 33 MB. 384-dim. CPU-fast (~5 ms per sentence on modern CPU).
- Already in FastEmbed's first-class registry — shares the model cache + lifecycle code with sub-D-1's reranker. **No new ML library dependency.**
- Configurable via `OPENZIM_EMBEDDING_MODEL` env var. Multilingual archives can opt into `paraphrase-multilingual-MiniLM-L12-v2` or `bge-m3`.

### Build CLI: `openzim-mcp build embeddings <archive.zim>`

```
$ openzim-mcp build embeddings /data/wikipedia_en_all_maxi_2026-02.zim
  Reading archive metadata... 27,200,000 entries, est. embedding budget 2.1 GB
  Embedding entries [████████░░░░░░░] 42% — 3h 12m remaining
  Writing HNSW index... done (1.8 GB)
  Writing paths sqlite... done (480 MB)
  Verifying sidecar... ✓
  Sidecar written to /data/wikipedia_en_all_maxi_2026-02.zim.semantic.hnsw
```

CLI flags:
- `--model <hf_id>` (default: `bge-small-en-v1.5`)
- `--namespace <letter>` (default: `C` — content; can be repeated)
- `--chunk-mode {title,summary,full}` (default: `summary` — embed first 200 tokens of body; cheaper, equally effective per RAG benchmarks)
- `--workers <N>` (default: cpu_count())
- `--resume` (idempotent — picks up from last completed batch)
- `--verify` (load-test the sidecar without writing)

Build time: ~3-4 hours on Wikipedia full archive on a modern CPU. **Build is one-time and idempotent**; rebuild only when the archive changes.

### Runtime hybrid retrieval

```
hybrid_search(query, archive):
    1. Xapian top-K   (default K=50)
    2. if sidecar_loaded(archive):
         encode(query) -> query_vec
         HNSW top-K of query_vec
         RRF fuse (k=60) the two ranked lists
    3. else:
         skip step 2, use Xapian list as-is
    4. if reranker_available:
         rerank top-K -> top-N
    5. return top-N
```

**Reciprocal Rank Fusion** (`RRF score = Σ 1/(k + rank_i)` for k=60 across both lists) — battle-tested, requires no score calibration between Xapian's BM25 and cosine similarity.

### Sidecar discovery

- On archive open in `zim_operations.py`, probe for `<archive>.zim.semantic.hnsw` + `.semantic.paths.sqlite`.
- Both present → lazy-load on first hybrid query.
- One missing or version-mismatched → log INFO, mark archive as "semantic unavailable", continue Xapian-only.
- Per-archive state (not global) — mixed-archive deployments can have some archives with sidecars and some without.

### Storage cost

- Wikipedia full archive (27M entries × 384-dim × float16) ≈ 21 GB raw embeddings.
- HNSW with M=16 adds ~50% overhead → ~32 GB on-disk sidecar.
- For deployments where 32 GB is too much: `--chunk-mode title` produces ~5 GB sidecar (titles only, no body); trade recall for footprint.

### Module structure

```
openzim_mcp/ml/embeddings.py      # ~250 LOC: encoder + HNSW reader
openzim_mcp/ml/sidecar.py         # ~150 LOC: sidecar discovery + load + UUID check
openzim_mcp/ml/cli/build_index.py # ~200 LOC: `openzim-mcp build embeddings` CLI
openzim_mcp/ml/fusion.py          # ~50 LOC: RRF implementation
```

### Configuration

```python
class EmbeddingsConfig(BaseModel):
    enabled: bool = True                   # checked when extra importable
    model_id: str = "bge-small-en-v1.5"
    sidecar_search_paths: List[Path] = []  # extras beyond archive dir
    xapian_top_k: int = 50
    semantic_top_k: int = 50
    rrf_k: int = 60
    require_sidecar: bool = False          # True → error if missing, False → fall back
```

### Fallback contract

- Sidecar missing → semantic retrieval skipped silently, Xapian-only.
- Encoder load fails → log WARNING once, disable for the rest of the process, Xapian-only.
- HNSW query exception → log WARNING, fall back to Xapian-only for that query.
- **Never** fails search outright when a sidecar is unavailable.

### Telemetry

`_track("hybrid_retrieval_engaged" | "hybrid_retrieval_xapian_only" | "sidecar_missing" | "sidecar_version_mismatch")`. Build CLI emits structured progress logs (lines/sec, ETA) for piping into CI dashboards.

### Testing

- Unit: HNSW index round-trip on a 1000-doc synthetic corpus. RRF fusion math against hand-computed expected ranks.
- Integration: `tests/ml/test_hybrid_retrieval.py` with a tiny ZIM + pre-built sidecar fixture asserts known semantic-vs-Xapian divergence (e.g., query "the chemical that makes leaves green" → semantic finds `Chlorophyll`, Xapian misses it).
- Build CLI: smoke test in `tests/ml/test_build_cli.py` — build sidecar for a 10-entry test ZIM, assert byte-for-byte determinism (pin output hash).
- Skip marker `@pytest.mark.requires_embeddings` keyed on `importlib.util.find_spec("hnswlib")`.

### Why HNSW over FAISS

`hnswlib` is a single 2 MB wheel with no transitive deps; FAISS pulls in numpy and sometimes BLAS. Both implement the same HNSW algorithm; at our scale (≤100M vectors per sidecar) hnswlib's perf is competitive.

### Why `bge-small-en-v1.5` over `bge-base`

Small produces 384-dim (vs base's 768), halving storage. Quality difference on Wikipedia-style content is <2 pp; small wins on size by ~50%.

### Why per-archive sidecar, not global

Lets deployments add semantic retrieval to high-value archives (Wikipedia) without paying the build cost on low-traffic ones (Wiktionary, niche StackExchange dumps).

---

## Cross-cutting infrastructure

These touch every sub-D and live in `openzim_mcp/ml/__init__.py` + a few shared modules.

### Feature-detection registry

```python
# openzim_mcp/ml/__init__.py
@dataclass(frozen=True)
class MLFeatures:
    reranker:   bool   # fastembed importable
    planner:    bool   # fasttext importable
    embeddings: bool   # hnswlib importable

@functools.cache
def detect() -> MLFeatures:
    """Single source of truth for which extras are installed. Cached per
    process; importlib.util.find_spec — no side effects, no model loads."""
```

Every ML-aware code path checks `detect()` first. Tests parametrize over synthetic `MLFeatures` to exercise both "extra installed" and "extra missing" branches without touching the import system.

### Shared fallback decorator

```python
# openzim_mcp/ml/fallback.py
def ml_fallback(*, feature: str, on_failure: Callable[..., T]) -> Callable:
    """Wrap an ML call: on first exception, log WARNING with stack,
    set a per-process kill switch for that feature, route all future
    calls to `on_failure`. Idempotent — second failure logs DEBUG only."""
```

Every reranker/classifier/encoder entry point wraps through this. Guarantees the "graceful fallback when a model is missing" contract is implemented exactly once.

### Telemetry events (new, additive)

```
reranker_engaged / reranker_skipped / reranker_failed
query_rewritten (rules_applied=[...])
intent_classifier_engaged / decomposition_engaged
planner_failed
hybrid_retrieval_engaged / hybrid_retrieval_xapian_only
sidecar_missing / sidecar_version_mismatch
ml_feature_disabled (feature=<name>, reason=<load_error|kill_switch|env>)
```

All flow through the existing `_track("<event>")` path in `simple_tools.py:541`. No new telemetry infrastructure.

### Model cache directory

`~/.cache/openzim-mcp/models/` by default. Overridable via `OPENZIM_MODEL_CACHE_DIR` (env) or `model_cache_dir` in `Config`. FastEmbed gets `Path(OPENZIM_MODEL_CACHE_DIR) / "fastembed"`. fastText `.ftz` files live next to the package (bundled, no cache). Sidecars stay next to their `.zim` files.

### Air-gapped deployments

`openzim-mcp download-models` CLI command pre-stages every model the installed extras need. Idempotent — re-running checks cache and only fetches missing files. For `[embeddings]`, also useful before running `openzim-mcp build embeddings` on a no-internet build host.

### Configuration top-level

```python
class MLConfig(BaseModel):
    reranker: RerankerConfig = RerankerConfig()
    query_rewrite: QueryRewriteConfig = QueryRewriteConfig()
    planner: PlannerConfig = PlannerConfig()
    embeddings: EmbeddingsConfig = EmbeddingsConfig()

# Config (existing) gains:
class Config(BaseModel):
    ...existing fields...
    ml: MLConfig = MLConfig()
```

Discoverable via existing `openzim-mcp config show` CLI; each field documented in `config.py` docstrings.

### Testing infrastructure

```
tests/ml/                              # all ML tests live here
    conftest.py                        # shared fixtures, requires_* markers
    test_reranker_unit.py
    test_reranker_integration.py       # @pytest.mark.requires_reranker
    test_query_rewrite_tier1.py        # no marker — base install
    test_planner_unit.py
    test_planner_integration.py        # @pytest.mark.requires_planner
    test_hybrid_retrieval.py           # @pytest.mark.requires_embeddings
    test_build_cli.py
    test_ml_registry.py                # MLFeatures + ml_fallback
```

CI matrix adds two new jobs per Python version: `extras-none` (current behavior, default) and `extras-all` (install `[reranker,planner,embeddings]` and run the integration tests). The existing test surface stays untouched on the no-extras path.

### Pyproject extras structure

```toml
[project.optional-dependencies]
reranker = [
    "fastembed>=0.4.0,<1.0",
]
planner = [
    "fasttext-wheel>=0.9.2,<1.0",
]
embeddings = [
    "fastembed>=0.4.0,<1.0",   # shared with [reranker]
    "hnswlib>=0.8.0,<1.0",
]
ml-all = [
    "openzim-mcp[reranker,planner,embeddings]",
]
```

Install footprints:
- `pip install openzim-mcp[reranker]` → ~150 MB
- `pip install openzim-mcp[planner]` → ~50 MB
- `pip install openzim-mcp[embeddings]` → ~150 MB (shared FastEmbed, only HNSW adds ~2 MB on top)
- `pip install openzim-mcp[ml-all]` → ~200 MB total

### Documentation

Every extra gets a `docs/v2/extras-<name>.md` page covering: what it does, install command, expected memory/disk/latency cost, how to verify it's active, how to disable it, sample observability-output snippet. README's Phase D section will link to these.

### Release pacing

Four sub-Ds → four `v2.0.0bN` releases. Per the existing sweep cadence, **each sub-D ships with its own live-MCP smoke pass before merging the release PR.** No mass-release at the end — discover failures early.

---

## Release plan

| Sub-D | Tag | Owns | Spec link | Plan link |
|-------|-----|------|-----------|-----------|
| sub-D-1 | `v2.0.0b1` | #6 reranker | This doc § sub-D-1 | _TBD by writing-plans_ |
| sub-D-2 | `v2.0.0b2` | #8 Tier 1 | This doc § sub-D-2 | _TBD_ |
| sub-D-3 | `v2.0.0b3` | #8 Tier 2 + #12 | This doc § sub-D-3 | _TBD_ |
| sub-D-4 | `v2.0.0b4` | #15 embeddings + hybrid | This doc § sub-D-4 | _TBD_ |

After all four sub-Ds ship, the Phase D row in [`docs/v2/README.md`](../../v2/README.md) flips to **Shipped (v2.0.0b4)**.

## Per-sub-D PR shape

Each sub-D follows the existing release-PR shape:

1. `feat(v2): Phase D sub-N — <topic>` PR off `main` (matching the `v2-phase-c` precedent).
2. Implementation + tests in one bundle.
3. Live-MCP smoke pass against the deployed prior alpha/beta.
4. Release PR `chore(release): v2.0.0bN — Phase D sub-N shipped`.
5. Tag `v2.0.0bN` pushed to `main` triggers `.github/workflows/release.yml`.

## Open questions deferred to per-plan time

These are NOT spec-level blockers; they'll be settled in the implementation plan for the relevant sub-D:

- Concrete API for the `Candidate` envelope flowing into `rerank()` (existing search result shape vs new wrapper). Sub-D-1 plan.
- Whether `_track()` should grow a structured-fields kwarg or stay string-keyed. Sub-D-1 plan.
- Exact `.ftz` training hyperparameters (epochs, lr, ngram window). Sub-D-3 plan.
- Whether the build CLI uses `click` or `argparse`. Sub-D-4 plan. Probably `click` — already a tested ecosystem.
- HNSW `M` / `ef_construction` defaults — start with hnswlib's recommendations, tune in sub-D-4 plan if needed.

---

## Why this design

**It matches v2's foundational decisions.** The v2 tracking doc commits to "ML accelerators are opt-in via extras." Phase D ships three of them. The doc commits to "offline-first" — bundled fastText models, lazy-load FastEmbed, explicit `build embeddings` CLI, optional `download-models` pre-stage all satisfy that.

**It builds on what's already mature.** Sub-D-1 reranker plugs into search + synthesize, both well-tested through Phase C and the post-a15 → a25 sweeps. Sub-D-2 Tier 1 extends the existing `_strip_*` chain in `intent_parser.py` that's been hardened across 11 sweep cycles. Sub-D-3 classifier trains on the labeled sweep transcripts already in repo. Sub-D-4 sidecar reuses sub-D-1's FastEmbed install for the encoder.

**It's incrementally shippable.** Each sub-D is a separate release. A user who installs only `[reranker]` gets meaningful relevance lift without paying for the other two extras. A deployment that doesn't want any ML stays on the base install indefinitely with no behavior change.

**It defers the hardest scope to last.** Sub-D-4 (embeddings) carries a build CLI, a sidecar format, hybrid retrieval, and the most storage. By the time it ships, the lazy-load patterns from sub-D-1, the model-cache layout from cross-cutting, and the fallback contract from sub-D-1/sub-D-3 are all proven on simpler surfaces.

**It locks in YAGNI on multilingual.** Multilingual archive support is documented as an override surface but not designed for. If real demand surfaces during sub-D-1/sub-D-4 live testing, the spec for sub-D-5 (multilingual) can be cut as a separate phase. Until then, English-first defaults keep the design surface tight.
