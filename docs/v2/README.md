
# openzim-mcp v2 — Release Tracking

**Status:** Planning
**Target:** v2.0.0 (major release)
**Started:** 2026-05-08
**Owner:** @cameronrye

This document tracks the v2 release. v2 is a major version bump dedicated to making openzim-mcp dramatically more useful to **smaller, less capable LLMs** (Haiku-class, Llama-3-8B, Mistral-7B, Phi). A model with a 32K-128K context cannot brute-force a multi-million-article ZIM archive, so the server's intelligence determines whether the model finds what it needs.

The work is decomposed into six phases, each independently shippable as a pre-release (`v2.0.0a1`, `v2.0.0b1`, …). Per-phase design specs live in [`docs/superpowers/specs/`](../superpowers/specs/) and are created as each phase begins.

---

## Foundational decisions

These apply across all phases; per-phase specs do not re-litigate them.

- **Clean breaks allowed.** v2 is a major release — no deprecation period. Removed tools and renamed parameters land in a single `v2.0.0` tag. v1.x continues to receive critical security fixes only.
- **ML accelerators are opt-in via extras.** Anything heavier than pure-Python BM25 ships behind `pip install openzim-mcp[reranker]`, `[embeddings]`, etc. The default install stays lean. Lazy model loading; graceful fallback when a model is missing.
- **Offline-first.** Every accelerator must work without network access at runtime. Models are downloaded once at install (or via an explicit `openzim-mcp download-models` CLI) and cached locally.
- **Backward compat at the data layer.** v2 changes the MCP tool surface and response shapes, but does not change `.zim` archive format expectations. Sidecar files (Phase E) live next to `.zim` files and are optional.
- **Markdown for prose, JSON for navigation; no XML in tool responses.** Per token-economy research, XML underperforms for small models.

---

## Phase status

| Phase | Theme | Items | Status | Spec |
|-------|-------|-------|--------|------|
| **A** | Quality wins, non-breaking | #1, #2, #4, #5, #14 | **Shipped (v2.0.0a1)** | [2026-05-08-v2-phase-a-quality-wins-design.md](../superpowers/specs/2026-05-08-v2-phase-a-quality-wins-design.md) |
| **B** | Response contract | #3, #13 | **Shipped (v2.0.0a2)** | [2026-05-08-v2-phase-b-response-contract-design.md](../superpowers/specs/2026-05-08-v2-phase-b-response-contract-design.md) |
| **C** | New retrieval primitives | #7, #10, #11 | **Shipped (v2.0.0a4)** | [2026-05-09-v2-phase-c-retrieval-primitives-design.md](../superpowers/specs/2026-05-09-v2-phase-c-retrieval-primitives-design.md) |
| **D** | Optional ML accelerators | #6, #8, #12, #15 | Planned | _TBD_ |
| **E** | Offline build artifacts | #16, #17 | Planned | _TBD_ |
| **F** | Tool surface v2 | #9 | Planned | _TBD_ |

Each phase's spec is created via the brainstorming workflow when that phase begins. The spec link gets filled in when the design is approved.

---

## Phase A — Quality wins, non-breaking

**Goal:** Ship five targeted improvements that make existing tools dramatically smarter for small models, without changing any tool signature or response shape. Releasable as a regular minor version even on the v1.x line if needed.

**Why first:** No breaking changes, no new dependencies, fastest path to user-visible quality. Validates the v2 effort with low risk.

### #1 — Use libzim native query-aware snippets

**Original target.** Use libzim's `SearchIterator.getSnippet()` which returns the actual matched passage with highlighting, replacing the prior "decompress + take first two paragraphs" approach.

**What shipped (v2.0.0a1).** A pure-Python query-aware rewrite in [`content_processor.create_snippet`](../../openzim_mcp/content_processor.py): the snippet is now the first paragraph containing a whole-word match for any query term (instead of the lead paragraph), and up to 5 matches inside the slice are wrapped in `**bold**` for visibility. This delivers the _query-relevance_ and _highlighting_ outcomes of the original target.

**What did NOT ship.** The libzim-native code path. `python-libzim` 3.9.0 exposes `Searcher` / `SearchResultSet` but does NOT surface `SearchIterator.getSnippet()` — the iterator yields plain entry-path strings. Calling the C++ libzim `getSnippet` API would require an upstream binding change (or a custom CFFI shim, which is out of scope for v2 alpha). The Python path still decompresses the entry per hit, so the perf-target half of the original design has not been realized.

**Follow-up.** Open an upstream [python-libzim issue](https://github.com/openzim/python-libzim/issues) requesting that `SearchIterator.getSnippet()` be exposed on the binding. When that lands, swap the body of `_get_entry_snippet` in [`openzim_mcp/zim/content.py`](../../openzim_mcp/zim/content.py) to call the native API and keep the Python `create_snippet` as a fallback for paths that don't go through the search iterator (e.g., suggestion search).

**Reference:** [openzim/javascript-libzim SEARCH_SNIPPETS_IMPLEMENTATION.md](https://github.com/openzim/javascript-libzim/blob/main/SEARCH_SNIPPETS_IMPLEMENTATION.md).

### #2 — Trim tables and infoboxes instead of pipe-soup

**Current state.** [`openzim_mcp/content_processor.py`](../../openzim_mcp/content_processor.py) configures `html2text` with `ignore_tables=False`, so Wikipedia infoboxes serialize to many lines of `|`-separated markdown that burn tokens without being readable.

**Target.** Detect `.infobox` / `.vcard` containers and emit them as compact key/value lists. For non-infobox tables over a configurable row threshold, replace with a placeholder (`[Table: 47 rows × 6 cols — use \`get_table\` to expand]`) and expose retrieval via either an option on `get_zim_entry` or a new dedicated tool (decided in Phase A spec).

### #4 — Structured suggestions on empty / low-confidence results

**Current state.** [`openzim_mcp/zim/search.py:352-368`](../../openzim_mcp/zim/search.py) returns markdown prose recovery hints when search yields zero results. Small models follow concrete next-step lists more reliably than narrative prose.

**Target.** Every list-returning tool, on empty or very-low-relevance results, includes a structured `suggestions` block: alternate spellings, broader/narrower terms, alternate ZIM files, and a machine-readable `reason` field (`no_xapian_index`, `0_hits`, `low_relevance`, `bad_namespace`). Phase A keeps the existing markdown response and adds the structured block alongside; Phase B may collapse the duplication.

### #5 — Token-count and `more_available` metadata

**Current state.** No response carries token-count or "more available" signals. A model has no basis to budget context use beyond character-counting the response itself.

**Target.** Every response includes a `_meta` envelope: `{tokens_est, truncated, more_at_offset, total_chars}`. Estimate via a fast tokenizer (likely `tiktoken` for the GPT-style approximation; we don't need exactness, just an order-of-magnitude signal that's close enough for budgeting). Phase A adds the field alongside existing payloads; Phase B canonicalizes its location.

### #14 — Typo-tolerant `find_entry_by_title`

**Current state.** [`openzim_mcp/zim/search.py:1067-1238`](../../openzim_mcp/zim/search.py) uses a 5-variant case ladder plus `SuggestionSearcher`. "Photosythesis" returns nothing.

**Target.** When the case ladder + `SuggestionSearcher` return nothing or only low-score matches (< 0.7), apply a Levenshtein-1 expansion against suggestion candidates and re-rank. Keep the cache; cap the expansion at a small candidate set to bound cost.

---

## Phase B — Response contract

**Goal:** Standardize how every list-returning tool paginates and how every response carries metadata. One coordinated breaking change.

**Why now (not later):** Once the v2 ML and primitive work in C/D starts touching tool internals, retrofitting a contract change becomes painful. Doing it second concentrates churn.

### #3 — Standard pagination contract

**Current state.** Search uses opaque base64 cursors (`{o, l, q}`). [`openzim_mcp/tools/search_tools.py`](../../openzim_mcp/tools/search_tools.py) `browse_namespace` and `walk_namespace` use offset/limit. Some tools return `next_cursor`, some don't. `extract_article_links` uses offset-only.

**Target.** Every list-returning tool returns `{results, next_cursor, total, done, page_info}`. Cursor-based by default; integer offsets remain accepted as a convenience but are no longer exposed in responses. Cursors are opaque base64 JSON.

### #13 — `structuredContent` everywhere

**Current state.** v1.1.0 already moved most tools to MCP `structuredContent`. Stragglers that still return JSON-as-string: `get_zim_metadata`, `list_namespaces`, `get_table_of_contents`, `get_article_structure`, `extract_article_links`, `get_search_suggestions`, `get_binary_entry`. These force the model to parse strings inside text payloads.

**Target.** All structured returns flow through `structuredContent`. Markdown remains for prose-shaped tools (`get_zim_entry` body, search snippets) but with consistent `_meta` siblings.

---

## Phase C — New retrieval primitives

**Goal:** Add the capabilities a small model actually needs to navigate large archives — section-level retrieval, server-fused answers, and the precomputed index that powers both.

**Why third:** Builds on the response-contract work in B. Pre-computing infoboxes in #11 also fixes #2 properly (which Phase A handles via on-the-fly stripping).

### #11 — Pre-computed section + infobox index

**Current state.** [`openzim_mcp/content_processor.py`](../../openzim_mcp/content_processor.py) re-parses HTML on every call to `get_entry_summary`, `get_table_of_contents`, `get_article_structure`, `extract_article_links`. The existing LRU cache ([`openzim_mcp/cache.py`](../../openzim_mcp/cache.py)) caches each independently.

**Target.** First touch of an entry runs a single extractor that emits `{infobox, sections: [{id, title, summary, char_range}], links, structure}` and stores the bundle in the LRU. All four tools above become bundle lookups. Section `char_range` enables #7.

### #7 — `get_section` tool

**Current state.** No section-level retrieval. A model that wants section 7 of a 110K-char article must compute the byte offset itself (tedious) or page through `content_offset`. [`openzim_mcp/zim/content.py:95-100`](../../openzim_mcp/zim/content.py) explicitly notes this gap.

**Target.** New tool `get_section(zim_file_path, entry_path, section_id)` returns the full section (≈500-1500 tokens — the small-model sweet spot per parent-document-retrieval research). Section IDs come from #11's index or the existing TOC anchor resolution.

### #10 — Server-side `synthesize` mode

**Current state.** Simple mode in [`openzim_mcp/simple_tools.py`](../../openzim_mcp/simple_tools.py) returns either a search list or a truncated article body. The Perplexity Sonar pattern (pre-fused answer with citations) is more useful for small models.

**Target.** `zim_query` gains a `synthesize=true` option (or it becomes a separate intent route) that retrieves top-N reranked passages, concatenates them with `[cite: A/Berlin#Geography]` markers, and returns ~800-1500 tokens of grounded snippet plus a citation list. No LLM generation — pure retrieval + concatenation. When the reranker (Phase D) is unavailable, falls back to top-N by Xapian score.

---

## Phase D — Optional ML accelerators

**Goal:** Add three optional ML capabilities behind extras, each with a graceful pure-Python fallback. None becomes the default.

**Why fourth:** Each depends on the response shape from B and the section bundles from C to be useful. Doing ML before structure means rebuilding integration points twice.

### #6 — Cross-encoder reranker

**Current state.** Pure Xapian BM25 is the only relevance signal. Wikipedia title queries are entity-driven, but content-fragment queries ("the chemical that makes leaves green") need semantic re-ranking.

**Target.** Behind `pip install openzim-mcp[reranker]`. Default model: `BAAI/bge-reranker-base` (~80 MB, ~92 ms per batch of 50 on CPU). Pattern: Xapian top-50 → rerank → top-5 to model. Multilingual archives can opt into `jina-reranker-v3`. Model load is lazy; first call pays the latency.

**Reference:** [Reranker benchmark](https://aimultiple.com/rerankers).

### #8 — Server-side query rewriting / decomposition

**Current state.** [`openzim_mcp/intent_parser.py`](../../openzim_mcp/intent_parser.py) is 19 weighted regex patterns for intent routing. There is no query rewriting (lowercase entity normalization, stopword handling, "did you mean") and no decomposition for multi-hop questions.

**Target.** Two tiers. **Tier 1 (no extras):** rules-based query rewriting — lowercase normalization, common-misspelling map, stopword-aware phrase detection, simple "X of Y" decomposition into entity-then-property lookups. **Tier 2 (`[planner]` extra):** a small distilled classifier or rules-tree for harder cases. Research is unanimous that HyDE hurts small models — we explicitly skip it.

### #12 — Hybrid intent parser (regex + classifier fallback)

**Current state.** [`openzim_mcp/intent_parser.py`](../../openzim_mcp/intent_parser.py) marks anything below confidence 0.55 as "low confidence" and appends a footer; below 0.7 is "moderate." This noise rate is high enough to be a UX problem.

**Target.** Regex remains the fast path. When confidence < 0.7, route to a small intent classifier (fastText, distilled sentence-transformer, or a lightweight rules-tree on query shape: has-quote, has-question-word, length, capitalization pattern). Classifier ships in the same `[planner]` extra as #8.

### #15 — Sentence-embedding sidecar (optional)

**Current state.** No semantic search. Models like `bge-small-en-v1.5` (33 MB, 384-dim) over an HNSWlib index could enable true semantic retrieval, especially valuable for older archives whose Xapian index is sparse or missing.

**Target.** Behind `pip install openzim-mcp[embeddings]`. A build-time CLI generates `<archive>.zim.semantic.faiss` next to the archive. At query time, hybrid retrieval: Xapian top-K + semantic top-K → RRF fuse (k=60) → rerank. Building is opt-in per archive; default behavior is unchanged. Out-of-scope decisions (which embedding model, index format, build CLI shape) move to Phase D's spec.

---

## Phase E — Offline build artifacts

**Goal:** Ship an `openzim-mcp build` CLI that produces optional sidecar files at archive-load or pre-deployment time.

**Why fifth:** Independent of all runtime code; can ship after D without blocking it.

### #16 — Inbound link-graph sidecar

**Current state.** [`openzim_mcp/zim/content.py`](../../openzim_mcp/zim/content.py) `get_related_articles` is outbound-only. Inbound link discovery was removed in v0.9.0 because the runtime cost is prohibitive on a multi-million-article archive.

**Target.** `openzim-mcp build link-graph <archive>.zim` produces `<archive>.zim.linkgraph.sqlite` (or similar) with reverse-edge indexes. At runtime, `get_related_articles(direction="inbound")` becomes a SQLite lookup. Sidecar is optional; absence is reported gracefully.

### #17 — Archive-type presets

**Current state.** Wikipedia, Wiktionary, Stack Exchange, and TED-style ZIMs behave differently (encyclopedic prose vs. dictionary entries vs. Q&A vs. transcripts), but the server treats them uniformly. Models waste turns discovering archive shape.

**Target.** Detect archive type via the `M`-namespace metadata + heuristics on `Creator`/`Name`/`Title`. Each detected type has a preset that adjusts: snippet shape, summary style, default namespace for unfiltered queries, and intent-parser priors. Presets are data, not code — `openzim_mcp/presets/wikipedia.toml` etc. Users can override per-archive in config.

---

## Phase F — Tool surface v2

**Goal:** Collapse the 21-tool advanced-mode surface (currently in [`openzim_mcp/tools/`](../../openzim_mcp/tools/)) to roughly 8 well-named tools, informed by everything learned in A-E.

**Why last:** The right tool boundaries depend on which primitives exist (#7, #10, #11) and which accelerators are wired in (#6, #8). Doing this first would mean redesigning the surface again in v2.1.

### #9 — Collapse 21 → ~8 tools

**Current state.** Real overlap exists: `search_zim_file` / `search_all` / `search_with_filters` are three flavors of one operation. `get_zim_entry` / `get_zim_entries` / `get_main_page` are three flavors of "fetch entry." `browse_namespace` / `walk_namespace` differ only in pagination shape.

**Target.** Approximate target surface (final list decided in Phase F's spec):

1. `zim_query` — natural-language entry point (simple mode, kept)
2. `zim_search` — unified search (collapses search_zim_file + search_all + search_with_filters; cross-archive via param)
3. `zim_get` — unified entry fetch (collapses get_zim_entry + get_zim_entries + get_main_page; batch via list param)
4. `zim_get_section` — section-level retrieval from Phase C
5. `zim_browse` — namespace listing (collapses browse_namespace + walk_namespace)
6. `zim_metadata` — archive metadata + namespace listing + main-page pointer
7. `zim_links` — outbound + inbound (Phase E) link discovery; replaces extract_article_links + get_related_articles
8. `zim_health` — server health + configuration (collapses get_server_health + get_server_configuration)

`find_entry_by_title`, `get_search_suggestions`, `get_entry_summary`, `get_table_of_contents`, `get_article_structure`, `get_binary_entry` collapse into options or sub-modes of the unified tools above. Final consolidation decided in spec.

**Reference:** [The MCP Tax](https://www.mmntm.net/articles/mcp-context-tax) — Haiku-class models show ~49% failure rate against bloated tool schemas.

---

## Out of scope for v2

- Network-fetching tools. v2 stays offline-only.
- A built-in summarization LLM. Synthesize mode (#10) is retrieval + concatenation, not generation.
- A separate UI / web interface. The website at [`website/`](../../website/) remains a docs / demo site, not a query UI.
- Multi-archive federated search beyond what `search_all` already does. Cross-archive retrieval improvements roll into Phase B/C work.
- Replacing libzim. v2 builds on libzim 9+; no fork, no replacement.

---

## Per-phase spec process

For each phase, when work begins:

1. Brainstorm the phase against this tracking doc to refine scope and approaches.
2. Write a spec to `docs/superpowers/specs/YYYY-MM-DD-v2-phase-<X>-<topic>-design.md`.
3. Update the **Phase status** table above with the spec link and status (`In Design` → `In Progress` → `Shipped`).
4. Generate an implementation plan via the writing-plans skill.
5. Execute, review, ship as `v2.0.0aN` / `v2.0.0bN` pre-releases.

When all six phases ship, tag `v2.0.0`. v1.x branches become security-only.

## Tracking

- All v2 PRs use the label `v2`.
- Per-phase work uses additional labels: `v2-phase-a`, …, `v2-phase-f`.
- This document is updated as decisions land. Treat the **Phase status** table as source of truth for "where are we."
