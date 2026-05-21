# v2 Phase D (trimmed) — Optional ML Accelerators (Design Spec)

**Status:** Draft
**Phase:** D of 6 ([tracking doc](../../v2/README.md))
**Items in scope:** #6 (cross-encoder reranker), #8 Tier 1 (rules-based query rewriting)
**Deferred from this spec:** #8 Tier 2, #12 (hybrid intent parser), #15 (embeddings sidecar). See "Deferred to follow-up specs" below for measurable triggers.
**Target:** Two `v2.0.0bN` pre-releases (one per sub-D milestone). Final tag `v2.0.0b2`.
**Date:** 2026-05-20

---

## Goal

Make every model — especially Haiku-class, Llama-3-8B, Mistral-7B, Phi-class — find what it needs in a multi-million-article ZIM archive without burning context on retry loops. Phase D adds two ML-adjacent capabilities, ships them, then measures real-world impact before designing the more speculative items.

The trim is deliberate: the post-a17 → a25 sweep cycles drove the regex path to roughly 99% accuracy on labeled queries, and live traffic is dominated by entity queries where Xapian's canonical-title-match already returns score 1.0. The full Phase D (#6/#8/#12/#15) was designed to address relevance gaps we *expect* but don't yet *measure*. Ship the two items that pay off regardless (#6 + #8 Tier 1), instrument them, then decide what's actually missing.

## Non-goals

- **No required ML at install.** The default `pip install openzim-mcp` stays lean. Reranker capability is behind one opt-in extra: `[reranker]`. Tier 1 query rewriting is in the base install but rules-based — no model, no extra.
- **No GPU requirement.** Target CPU-fast (<150 ms p95 hot-path). GPU is not designed for.
- **No HyDE.** Per the v2 README's research, hypothetical-document expansion hurts small models. Explicit non-goal — the design must not introduce a HyDE path even as a future-extension hook.
- **No network at runtime.** The reranker model downloads once at install (or via `openzim-mcp download-models` for air-gapped pre-stage) and loads from disk thereafter.
- **No bundled ML models.** With sub-D-3 deferred, no fastText `.ftz` files ship in the wheel.
- **No new ZIM archive format.** No sidecars in this spec (sidecar work moves to sub-D-4's deferred follow-up spec).
- **No multilingual default.** Default reranker (`bge-reranker-base`) targets English-first archives. Multilingual archives override via env var; this design documents the override surface but does not ship a multilingual default.

## Non-goals carried forward from earlier phases

- **No new tool surface.** Tool collapse is Phase F. Phase D plugs into existing tools (`search_zim_file`, `synthesize` mode of `zim_query`, `parse_intent`).
- **No response-contract changes.** Phase B already standardized response shapes. Phase D only adds metadata fields (`_meta.reranked`).
- **No replacing libzim or Xapian.** Reranker reranks Xapian results; Xapian remains the canonical source.

---

## Foundational decisions

These apply across both sub-Ds.

- **One opt-in extra (`[reranker]`).** sub-D-2 lives in the base install (rules-based, no model).
- **Lazy import + lazy load.** No top-level imports of optional libraries. The reranker path uses `importlib.util.find_spec(...)` for detection and imports FastEmbed only inside the function that needs it. Model load is deferred to first use.
- **Graceful fallback contract.** When the reranker model fails to load or a per-call inference fails, the code path logs a `WARNING`, sets a per-process kill switch for that feature, and falls back to Xapian-only ranking. The caller sees no exception.
- **First-call model fetch has an aggressive timeout.** Default 5 s. If the timeout fires, log a one-line "model not staged; run `openzim-mcp download-models` to pre-stage" message and disable the reranker for the rest of the process. **No 30-second hangs on the first query in an offline deployment.**
- **Telemetry by additive event names.** ML events flow through the existing `_track("<event>")` path in `simple_tools.py` (next to `_track("chained_intent_rejected")` at line 541). No new telemetry infrastructure.
- **Shared model cache.** `~/.cache/openzim-mcp/models/fastembed/` by default, overridable via `OPENZIM_MODEL_CACHE_DIR`. The cache layout supports future extras without churn.
- **Air-gapped support via explicit CLI.** A new `openzim-mcp download-models` command pre-stages every model the installed extras need. Idempotent; safe to re-run.
- **Configuration via `MLConfig` composing two sub-configs.** Discoverable via the existing `openzim-mcp config show` CLI. The schema is sized to today's scope; deferred sub-Ds add their sub-configs when they ship.

---

## Sub-D milestones

| Milestone | Items | Extra | Tag | Why this order |
|-----------|-------|-------|-----|----------------|
| **sub-D-1** | #6 cross-encoder reranker | `[reranker]` | `v2.0.0b1` | Smallest scope, biggest immediate relevance win on the queries that benefit, establishes lazy-ML + fallback patterns for any future ML extras |
| **sub-D-2** | #8 Tier 1 query rewriting (rules-based) | (none — base install) | `v2.0.0b2` | Zero deps; every model benefits from a cleaner query upstream. Lift the floor for free. |

Each milestone ships with its own live-MCP smoke pass before its release PR merges. **Sub-D-1 deploy gates a 2-week telemetry review** before sub-D-2 enters writing-plans — telemetry should confirm the reranker fires at a useful rate (target: ≥15% of search-tool calls past the skip-on-short-query gate, with measurable rerank-score divergence from Xapian ordering) and surface unexpected operator-side failures (model download timeouts, FastEmbed wheel-build issues on niche platforms).

---

## Sub-D-1 — Cross-encoder reranker (#6)

### What it does

When `[reranker]` is installed, search-shaped tools (`search_zim_file`, `search_with_filters`, `search_all`) and `synthesize` mode silently rerank Xapian top-N results using a cross-encoder model. Caller surface unchanged; relevance improves on content-fragment queries.

### Activation surface

- `simple_tools.py:_handle_search` — Xapian returns top-N (default N=50), `BGEReranker.rerank(query, results, top_k=requested_limit)` produces the final order. When `BGEReranker.get()` returns None (extra absent or kill-switched), skip cleanly.
- `simple_tools.py:_handle_filtered_search` + `_handle_search_all` — same shape.
- `synthesize.py:_collect_passages` — rerank passage candidates before the citation block is assembled. Phase C #10 explicitly anticipates this hook. Adds ~50 ms per synthesize call; within Phase C's latency budget.
- `simple_tools.py:_handle_tell_me_about` — **not reranked.** Entity-driven queries are already canonical-title resolved; rerank adds cost without value.
- **Skip-on-short-query gate:** when query has fewer than `min_query_tokens` (default 4) word tokens, skip rerank. Single-word entity queries dominate the Xapian-score-1.0 canonical-title hit; the cross-encoder is wasted there. Cheap gate; expected to short-circuit a large share of live-MCP traffic.

### Module structure

```
openzim_mcp/ml/__init__.py    # feature-detection registry (sized for future extras)
openzim_mcp/ml/reranker.py    # ~250 LOC
    class BGEReranker:
        - get() classmethod, lazy singleton, thread-safe init
        - score_pairs(pairs) -> List[float], batch-score (query, passage) pairs
        - rerank(query, candidates, top_k) -> List[Candidate]
openzim_mcp/ml/fallback.py    # shared ml_fallback decorator
openzim_mcp/ml/cli/download.py  # `openzim-mcp download-models` entrypoint
```

### Library: FastEmbed

- `fastembed>=0.4.0,<1.0`. ONNX-backed. No torch dependency.
- Install footprint: ~150 MB total (`fastembed` + transitive `onnxruntime` + `tokenizers` + `huggingface_hub`).
- CPU benchmark: ~50 ms for batch=50 of `bge-reranker-base` ONNX. Well under the 150 ms p95 budget.
- Default model: `Xenova/bge-reranker-base-onnx` (~80 MB), download-on-first-use, cached in `~/.cache/openzim-mcp/models/fastembed`.

### Risk mitigations baked into the design

**1. First-call model download UX (risk: 30 s hang on offline deployments).**

- `BGEReranker.get()` wraps the model fetch in a 5-second timeout (configurable via `RerankerConfig.first_call_timeout_seconds`).
- On timeout, log exactly: `WARNING: reranker model not staged; run \`openzim-mcp download-models\` to pre-stage. Falling back to Xapian-only ranking for this process.`
- Kill-switch sets `_reranker_disabled = True`; no retries.
- The `openzim-mcp download-models` CLI exists at GA. Documented in install instructions and in the warning message above.

**2. Edge-platform wheel availability (risk: FastEmbed wheels missing on Alpine / ARM32 / FreeBSD).**

- The `[reranker]` extra stays optional. Base install is unaffected.
- CI tests `pip install openzim-mcp[reranker]` on the supported matrix (Linux glibc x86_64 + ARM64, macOS x86_64 + ARM64, Windows x86_64). Edge platforms are explicitly out of scope.
- Documented as a "supported platforms for `[reranker]`" section in `docs/v2/extras-reranker.md`.

**3. Model identity drift (risk: HuggingFace updates the model; reproducibility breaks).**

- Pin model id in `RerankerConfig.model_id`; treat config bumps as the only knob.
- Log model id + file hash on first load (one-time INFO log) so operators can audit.
- A future `openzim-mcp ml status` CLI (out of scope for sub-D-1) would surface the loaded model's checksum.

### Fallback contract

- Model load fails (corrupt cache, OOM, ImportError, network timeout) → kill switch + structured WARNING + Xapian-only for the rest of the process.
- Per-call exception (tokenizer overflow, model crash) → log WARNING once per process, return input candidates in their Xapian order. Never raise to caller.
- Telemetry: `_track("reranker_engaged" | "reranker_skipped" | "reranker_failed")`. The `reranker_skipped` event distinguishes the short-query gate from disabled state via a `reason` field: `short_query | disabled | not_installed`.

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
    first_call_timeout_seconds: float = 5.0
    cache_dir: Path | None = None      # None → FastEmbed default under model_cache_dir
```

### Testing

- Unit: mock `TextRerank.rerank()` and assert candidate ordering + envelope shape. Mock the timeout behavior to assert the kill-switch fires correctly.
- Integration: `tests/ml/test_reranker_integration.py` builds an in-process reranker against a 3-doc test corpus; asserts predictable reorder. `@pytest.mark.requires_reranker` keyed off `importlib.util.find_spec("fastembed")`.
- Telemetry assertion: `_reranker_engaged` counter increments once per qualifying search hit; `_reranker_skipped` increments on short queries.
- Performance test: rerank batch of 50 in <150 ms p95 on the CI runner.
- Edge-platform test: `pip install openzim-mcp[reranker]` smoke job in CI for each supported platform/Python combination. Failure on an unsupported platform is documented, not fixed.

### Performance budget

- p95 added latency per search query (when reranker fires): ≤120 ms on a modern CPU.
- p95 added latency per search query (when skip-on-short-query gate fires): ≤1 ms (cheap token-count check).
- First-call cold start: ≤2 s (model already on disk). First call without pre-stage: 5 s timeout → fallback.

---

## Sub-D-2 — Tier 1 query rewriting (#8 partial)

### What it does

Every query, before any pattern matching, runs through four rules-based rewrite passes. Zero extras, zero models, zero ML dependencies. Lands in the BASE install so all downstream items inherit a cleaner query. Lift the floor for every model immediately.

### Four rule families

Each idempotent, each loop-safe (same shape as existing `_strip_param_leaks` / `_strip_trailing_politeness` patterns in `intent_parser.py`):

**1. Lowercase-entity normalization.** Pulls scattered `.lower()` calls in the `_tokenize_for_relevance` path into a named pass. Title-promotion's case-preserving path is untouched.

**2. Common-misspelling map (title-index-first lookup).**

Ship `openzim_mcp/data/misspellings.txt` — ~200 entries seeded from Wikipedia's "List of common misspellings." Loaded once at module init; the map is `dict[str, str]` keyed on lowercase word.

**Risk mitigation baked in:** before substituting, probe the title index for the original token. If the original has a canonical hit (score ≥ 0.95), skip the rewrite. This eliminates the false-positive class where a user types a real proper noun that happens to look like a misspelling (`Bilogy` as a surname, `Photosythesis` as an obscure band name, etc.). The probe is ~1 ms and cached.

Cap at ~500 entries to keep the lookup cheap. Annotate the file with the upstream Wikipedia revision timestamp so maintenance is auditable.

**3. Stopword-aware phrase detection.** When the topic carries `the / a / an / of` as leading or interleaved token, use the title index as the oracle: if the leading-stopword form has a canonical hit (`The Beatles`, `Of Mice and Men`), keep it; otherwise strip the leading article. One title-index probe per ambiguous query (~1 ms; piggybacks on the existing title-index cache where possible).

**4. Simple "X of Y" decomposition.** `population of Berlin` → `(entity=Berlin, attribute=population)`. Routes to the existing subject-attribute extraction in `simple_tools.py:_handle_tell_me_about` (the post-a16 P4-D1/P6-D1 hardened path). Two regex shapes:

- `<attribute_word> of <entity>`
- `<entity>'s <attribute>` (genitive)

**NOT in Tier 1:** multi-hop questions ("what year did the inventor of X die"). Those are deferred to a future sub-D-3 spec if live evidence warrants.

**Explicit non-rule:** HyDE. No hypothetical-document synthesis. Documented as a locked-in non-goal.

### Module structure

```
openzim_mcp/intent_parser.py (existing, 1345 lines)
    Extends the existing strip chain. Add four new methods following the
    same idempotent-loop shape:
        - _normalize_topic_case(query)
        - _apply_misspelling_map(query, title_index)
        - _detect_stopword_phrase(query, title_index)
        - _decompose_x_of_y(query)
    All called from parse_intent BEFORE pattern matching.

openzim_mcp/data/misspellings.txt   # new, ~200 lines + upstream-revision header
```

The misspelling and stopword-phrase rules need a title-index handle for the false-positive-mitigation probe. Pass it in optionally; when unavailable (unit tests without an archive), those rules degrade to no-ops — the rest of Tier 1 still runs.

### Risk mitigations baked into the design

**1. Behavior changes on upgrade for every user (risk: silent regressions).**

- Run the existing `tests/test_post_a*_beta_fixes.py` regression suite as a pinned baseline before merge.
- Add a Tier-1 regression suite (`tests/test_query_rewrite_tier1.py`) with per-rule positive AND no-op cases — explicit assertions that already-correct queries pass through unchanged.
- Live MCP smoke pass before merging the release PR (already in methodology).

**2. Misspelling-map false positives (risk: silent rewrite of real proper nouns to wrong articles).**

- Title-index-first lookup, as documented in rule #2.
- Pin a "do not rewrite" exclusion list in the same data file for words confirmed to be real proper nouns (e.g., `Bilogy → SKIP`).
- The exclusion list grows over time; sub-D-2's plan documents the process.

**3. Rule-order interactions (risk: subtle bugs from composed rules).**

- Idempotent loop pattern: each rule runs until its output stops changing, then the next rule runs. Already proven in the `_strip_*` chain.
- Unit tests cover per-rule and per-rule-pair compositions.

**4. Stopword-phrase probe latency on every query (risk: throughput regressions on high-volume deployments).**

- Cache hits piggyback on the existing title-index cache.
- `QueryRewriteConfig.stopword_phrase_probe = False` is an operator-side kill switch.

### Configuration

```python
class QueryRewriteConfig(BaseModel):
    enabled: bool = True
    misspelling_map_path: Path | None = None  # None → bundled default
    misspelling_exclusion_path: Path | None = None  # None → bundled default
    stopword_phrase_probe: bool = True
```

### Telemetry

`_track("query_rewritten", details={"rules_applied": [...]})` — observability without printing rewritten text (PII-safe). The `rules_applied` list lets operators see which rules fire most.

### Testing

- Unit: parametrized test cases per rule family — fix side, no-op side (already-correct), embedding-safety side (don't eat substrings).
- Title-index-first lookup: parametrized tests with a mocked title-index returning hits/no-hits for known queries to verify the false-positive mitigation fires correctly.
- Regression guards: pin the misspelling-map row count + sample entries so future contributors can't silently delete entries; pin the upstream revision timestamp in the file header.
- Live-MCP integration: extend the existing `tests/test_post_a*_beta_fixes.py` regression set with Tier-1 expected outputs.

---

## Cross-cutting infrastructure

These touch sub-D-1 and are designed to be reused by future ML extras without churn.

### Feature-detection registry

```python
# openzim_mcp/ml/__init__.py
@dataclass(frozen=True)
class MLFeatures:
    reranker: bool   # fastembed importable

@functools.cache
def detect() -> MLFeatures:
    """Single source of truth for which extras are installed. Cached per
    process; uses importlib.util.find_spec — no side effects, no model
    loads. Sized for today's scope; new fields added when their sub-Ds
    ship."""
```

### Shared fallback decorator

```python
# openzim_mcp/ml/fallback.py
def ml_fallback(*, feature: str, on_failure: Callable[..., T]) -> Callable:
    """Wrap an ML call: on first exception, log WARNING with stack,
    set a per-process kill switch for that feature, route all future
    calls to `on_failure`. Idempotent — second failure logs DEBUG only."""
```

Used by `BGEReranker.rerank()`. Pattern is shared across any future ML entry points.

### Telemetry events (new, additive)

```
reranker_engaged
reranker_skipped (reason=short_query | disabled | not_installed)
reranker_failed
query_rewritten (rules_applied=[...])
ml_feature_disabled (feature=reranker, reason=load_error | timeout | kill_switch | env)
```

All flow through the existing `_track("<event>")` path. No new telemetry infrastructure.

### Model cache directory

`~/.cache/openzim-mcp/models/` by default. Overridable via `OPENZIM_MODEL_CACHE_DIR` (env) or `model_cache_dir` in `Config`. FastEmbed gets `Path(OPENZIM_MODEL_CACHE_DIR) / "fastembed"`.

### Air-gapped deployments

`openzim-mcp download-models` CLI command pre-stages every model the installed extras need. Today: only the reranker model. Idempotent — re-running checks the cache and only fetches missing files.

### Configuration top-level

```python
class MLConfig(BaseModel):
    reranker: RerankerConfig = RerankerConfig()
    query_rewrite: QueryRewriteConfig = QueryRewriteConfig()

# Config (existing) gains:
class Config(BaseModel):
    ...existing fields...
    ml: MLConfig = MLConfig()
```

The schema is sized to today's scope. Deferred sub-Ds add their sub-configs when they ship — no pre-commitment.

### Testing infrastructure

```
tests/ml/                              # ML tests live here
    conftest.py                        # shared fixtures, requires_* markers
    test_reranker_unit.py
    test_reranker_integration.py       # @pytest.mark.requires_reranker
    test_query_rewrite_tier1.py        # no marker — base install
    test_ml_registry.py                # MLFeatures + ml_fallback
```

CI matrix adds one new job per supported Python version: `extras-reranker` (install `[reranker]`, run integration tests). The `extras-none` path is the default existing CI. Total CI runtime impact: ~1.1x baseline (the integration tests are small).

### Pyproject extras structure

```toml
[project.optional-dependencies]
reranker = [
    "fastembed>=0.4.0,<1.0",
]
```

Install footprint: `pip install openzim-mcp[reranker]` → ~150 MB.

When sub-D-3 or sub-D-4 enter design, their extras will be added without restructuring.

### Documentation

`docs/v2/extras-reranker.md` covers: what `[reranker]` does, install command, expected memory/disk/latency cost, supported platforms list, how to verify it's active, how to disable it (`OPENZIM_RERANKER_DISABLE=1`), sample observability-output snippet, troubleshooting (model-not-staged, timeout-on-first-call).

### Release pacing

Two sub-Ds → two `v2.0.0bN` releases. Each ships with its own live-MCP smoke pass before merging. **2-week telemetry review gates sub-D-2's writing-plans:** sub-D-1 deploys, we collect `reranker_engaged` / `reranker_skipped` / `reranker_failed` event distributions for two weeks, then decide whether sub-D-2 still makes sense and whether deferred sub-Ds need follow-up specs.

---

## Deferred to follow-up specs

The original Phase D design included two more items. Both are deferred from this spec pending live evidence. Each has a measurable trigger that would justify cutting a follow-up spec.

### Deferred sub-D-3 — Hybrid intent parser + Tier 2 decomposition (#8 Tier 2 + #12)

**Trigger to design:** after sub-D-1 + sub-D-2 ship and two weeks of live telemetry shows:

- ≥5% of `parse_intent` calls land in the existing low-confidence path (regex confidence < 0.7), OR
- Small-model transcript review surfaces multi-hop queries (`what year did the inventor of X die`) that the regex path fails on at a rate of ≥1 per 100 queries.

If the trigger fires, cut a `sub-D-3-design.md` spec covering the fastText classifier path (already designed in the previous draft of this spec — preserved in git history at commit `a92d04e`). If the trigger does NOT fire within 8 weeks of sub-D-2 deploy, formally close sub-D-3 as "not justified by live evidence."

### Deferred sub-D-4 — Embeddings sidecar + hybrid retrieval (#15)

**Trigger to design:** after sub-D-1 ships and four weeks of live telemetry shows:

- Reranker hit rate is meaningful (≥15% of search-tool calls past the skip-on-short-query gate) AND
- Operators or end-users report that semantic-divergent queries ("the chemical that makes leaves green") consistently miss in Xapian-only search even with the reranker active.

The sub-D-4 follow-up spec would cover the sidecar file format, build CLI, hybrid retrieval, RRF fusion (designed in the previous draft, preserved at commit `a92d04e`). The 32 GB sidecar cost and 3-4 hour build time mean this is a deliberate operator commitment; live evidence is necessary to justify the design effort.

### Why these triggers, not "always build"

The post-a17 → a25 sweep cycles taught us that the regex path is more capable than expected and that live traffic is more entity-dominated than the v2 README anticipated. Building #12 and #15 ahead of evidence ships complexity that may not be exercised. The triggers above turn "we think this would help" into "the data shows this is needed."

---

## Release plan

| Sub-D | Tag | Owns | Spec link |
|-------|-----|------|-----------|
| sub-D-1 | `v2.0.0b1` | #6 reranker | This doc § sub-D-1 |
| sub-D-2 | `v2.0.0b2` | #8 Tier 1 | This doc § sub-D-2 |

After both sub-Ds ship, the Phase D row in [`docs/v2/README.md`](../../v2/README.md) flips to **Shipped (trimmed; v2.0.0b2)**. Deferred items move to a separate "Deferred from Phase D" row with their trigger conditions documented.

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
- Exact rule-order test matrix for Tier 1. Sub-D-2 plan.
- Whether the `openzim-mcp download-models` CLI uses `click` or `argparse`. Sub-D-1 plan. (Probably `click` — already a tested ecosystem in similar projects.)

---

## Why this design

**It matches v2's foundational decisions.** The v2 tracking doc commits to "ML accelerators are opt-in via extras." Sub-D-1 ships one. The doc commits to "offline-first" — lazy-load FastEmbed, explicit `download-models` pre-stage, aggressive first-call timeout all satisfy that.

**It builds on what's already mature.** Sub-D-1 reranker plugs into search + synthesize, both well-tested through Phase C and the post-a15 → a25 sweeps. Sub-D-2 Tier 1 extends the existing `_strip_*` chain in `intent_parser.py` that's been hardened across 11 sweep cycles.

**It's incrementally shippable.** Each sub-D is a separate release. A user who installs only `[reranker]` gets meaningful relevance lift on the queries that benefit. A deployment that doesn't want any ML stays on the base install with sub-D-2's rule-based lift only.

**It defers speculation until evidence.** The sub-D-3 (#12) and sub-D-4 (#15) items in the original Phase D plan were designed against expected — not measured — relevance gaps. The trimmed spec ships what's clearly valuable, instruments it, then decides what else is actually needed. This is the same "narrow scope, widen on evidence" pattern the post-a15 → a25 beta sweeps have validated 11 times.

**The infrastructure pays for itself with one extra.** Feature-detection registry, fallback decorator, telemetry events, model cache layout — all designed to support future ML extras without churn. With only `[reranker]` shipping, the marginal cost of "designed for many" vs "designed for one" is small.

**It locks in YAGNI on multilingual, HyDE, and on-the-fly model upgrades.** Three speculative paths that would have bloated the spec. All documented as explicit non-goals.
