# openzim-mcp Roadmap

**Status:** Latest release **v2.1.7** (2026-06-04) — PyPI `2.1.7` and `ghcr.io/cameronrye/openzim-mcp:2.1.7` / `:latest`, GitHub Release with assets. v2.0.0 GA shipped 2026-05-27 (as `:2.0.0`); the v2.0.x/v2.1.x line has been kept current via beta-sweep fixes plus the v2.1.0 native-libzim reader features.

This document tracks open work past v2.0.0. Everything here is **additive**: opt-in extras, optional sidecars, or dispatch tuning. None of it changes the v2 tool surface or response contract.

The next release tag is **v2.5.0** (minor, additive). v3 is reserved for a future breaking change (libzim major bump or a deeper surface restructure).

---

## Foundational decisions (carried forward)

- **ML accelerators are opt-in via extras.** Default install stays lean.
- **Offline-first.** Sidecars and models load from disk; build steps are explicit operator commitments.
- **Markdown for prose, JSON for navigation; no XML in tool responses.**
- **Backward compat at the data layer.** Sidecars live next to `.zim` files; absence is reported gracefully.
- **Clean breaks land at major versions only.** v2.5 ships zero wire-format changes.

---

## Open items

### Phase D follow-ons (triggered work, behind extras)

Phase D shipped `#6` cross-encoder reranker and `#8` Tier 1 rules-based query rewriting at v2.0.0b1, then deliberately deferred three items pending live evidence. Each has a **measurable trigger** that justifies cutting a follow-up design spec.

#### sub-D-3 — Hybrid intent parser + Tier 2 decomposition (`#8` Tier 2 + `#12`)

**Current state.** [`openzim_mcp/intent_parser.py`](../openzim_mcp/intent_parser.py) is regex-based with 19 weighted patterns. Confidence < 0.7 routes to a low-confidence path; confidence < 0.55 marks "low confidence" with a footer.

**Target.** Hybrid path: regex stays as the fast path; below confidence 0.7, route to a small intent classifier (fastText / distilled sentence-transformer / lightweight rules-tree). Tier 2 decomposition adds entity-then-property lookups for multi-hop queries like "what year did the inventor of X die." Behind `pip install openzim-mcp[planner]`.

**Trigger to design.** After v2.0.0b1 deploy and ≥2 weeks of live telemetry shows EITHER:

- ≥5% of `parse_intent` calls land in the existing low-confidence path (regex confidence < 0.7), OR
- Small-model transcript review surfaces multi-hop queries that the regex path fails on at ≥1 per 100 queries.

**Status as of 2026-05-27.** Beta sweep cycles (b2 → b13) drove the regex path to roughly 99% accuracy on labeled queries. No live evidence has met either trigger. If neither fires by 2026-07-19 (8 weeks post-sub-D-2 deploy), formally close sub-D-3 as "not justified by live evidence."

**Reference design.** Previous draft of the fastText classifier path preserved at commit [`a92d04e`](https://github.com/cameronrye/openzim-mcp/commit/a92d04e).

#### sub-D-4 — Embeddings sidecar + hybrid retrieval (`#15`)

**Current state.** No semantic search. Pure Xapian BM25 is the only relevance signal beyond the cross-encoder reranker (which reranks Xapian's top-50). Semantic-divergent queries ("the chemical that makes leaves green") have no path to canonical matches that don't share lexical tokens.

**Target.** Behind `pip install openzim-mcp[embeddings]`. A build-time CLI generates `<archive>.zim.semantic.faiss` next to the archive (≈32 GB per multi-million-article archive, 3–4 hour build time). At query time, hybrid retrieval: Xapian top-K + semantic top-K → RRF fuse (k=60) → rerank.

**Trigger to design.** After v2.0.0b1 deploy and ≥4 weeks of live telemetry shows BOTH:

- Reranker hit rate is meaningful (≥15% of search-tool calls past the skip-on-short-query gate), AND
- Operators or end-users report that semantic-divergent queries consistently miss in Xapian-only search even with the reranker active.

**Status as of 2026-05-27.** Telemetry not yet collected at the required granularity. No operator reports.

**Reference design.** Previous draft preserved at commit [`a92d04e`](https://github.com/cameronrye/openzim-mcp/commit/a92d04e).

### Phase E — Offline build artifacts

Independent of runtime code; both items add operator-build commands that produce optional sidecars. Default behavior is unchanged.

#### `#16` — Inbound link-graph sidecar

**Current state.** [`openzim_mcp/zim/content.py`](../openzim_mcp/zim/content.py) `get_related_articles` is outbound-only. Inbound link discovery was removed in v0.9.0 because the runtime cost is prohibitive on a multi-million-article archive.

**Target.** `openzim-mcp build link-graph <archive>.zim` produces `<archive>.zim.linkgraph.sqlite` (or similar) with reverse-edge indexes. At runtime, `get_related_articles(direction="inbound")` becomes a SQLite lookup. Sidecar is optional; absence is reported gracefully.

**Build cost.** Estimated 30–60 minutes per multi-million-article archive (single-pass entry walk + bulk SQLite insert). Storage: ~500 MB – 2 GB per archive depending on link density.

#### `#17` — Archive-type presets

**Current state.** Wikipedia, Wiktionary, Stack Exchange, and TED-style ZIMs behave differently (encyclopedic prose vs. dictionary entries vs. Q&A vs. transcripts), but the server treats them uniformly. Models waste turns discovering archive shape.

**Target.** Detect archive type via the `M`-namespace metadata + heuristics on `Creator` / `Name` / `Title`. Each detected type has a preset that adjusts: snippet shape, summary style, default namespace for unfiltered queries, and intent-parser priors. Presets are data, not code — `openzim_mcp/presets/wikipedia.toml` etc. Users can override per-archive in config.

### v2.0 surface refinements pending v2.5

Open commitments referenced from production code (`openzim_mcp/tools/`) and tests. None breaks v2.0 callers.

#### `#199` — `zim_query` natural-language dispatch for three `zim_get` sub-modes

**Current state.** Phase F's `zim_query` natural-language router still dispatches `zim_get` only via its default `entry` sub-mode. The `summary`, `toc`, and `structure` sub-modes are reachable when called as explicit advanced tools, but `zim_query` does not select them from natural prose.

**Target.** Description tuning and/or probe-set relaxation on the dispatch path so phrases like "give me a summary of X" or "show the table of contents for X" route to the right sub-mode. Captured at GitHub issue `#199`.

**Status as of 2026-05-27.** Tracked for v2.5. Not a regression — there is always a working fallback through the default entry path.

#### `#18` — `zim_get_section` true raw-text path

**Current state.** [`openzim_mcp/tools/zim_get_section.py`](../openzim_mcp/tools/zim_get_section.py) accepts `compact: bool` for surface uniformity with `zim_query` / `zim_get`, but at v2.0 the parameter is a no-op: section bodies always ship in the bundle's compact rendering so the slice shape matches `zim_get(view="full")` output on the same article.

**Target.** Wire a true raw-text path so `compact=False` returns the unrendered section body, matching the rendering contract the other tools already honour. Schema-additive — no caller has to opt in.

#### `zim_get` `compact` default revisit

**Current state.** [`openzim_mcp/tools/zim_get.py`](../openzim_mcp/tools/zim_get.py) defaults `compact=False` at v2.0 to preserve v1.x payload sizing. Small-model callers must opt in to compaction.

**Target.** Revisit the default after adoption telemetry shows whether small-model callers consistently pass `compact=True`. If usage skews heavily one way, flip the default in v2.5. Schema-compatible either direction; the change is documentation + a constructor default.

#### `zim_links` `"inbound"` direction enum promotion

**Current state.** [`openzim_mcp/tools/zim_links.py`](../openzim_mcp/tools/zim_links.py) deliberately omits `"inbound"` from the direction enum at v2.0 — without the link-graph sidecar (`#16`), it would create a small-model failure mode where the model attempts it, eats an error, and gives up.

**Target.** When `#16` ships, promote `"inbound"` into the direction enum. Schema-additive; no caller has to change.

---

## v2.5 milestones (proposed)

| Milestone | Items | Tag |
| --- | --- | --- |
| **v2.5.0a1** | `#17` archive-type presets ([spec](specs/2026-06-04-v2.5-archive-type-presets-design.md), spec'd 2026-06-04 — snippet + summary seams, detect all 4 types, behavior for Wikipedia/Stack Exchange) | _TBD_ |
| **v2.5.0a2** | `#16` link-graph sidecar + `build` CLI + `zim_links` `"inbound"` enum promotion | _TBD_ |
| **v2.5.0a3** | `#199` `zim_query` sub-mode dispatch + `#18` `zim_get_section` raw-text path | _TBD_ |
| **v2.5.0a4** | sub-D-3 if triggered + `zim_get` `compact` default revisit (telemetry-driven) | _TBD_ |
| **v2.5.0a5** | sub-D-4 if triggered | _TBD_ |
| **v2.5.0** | Final after all triggered items ship (closed sub-Ds annotated in CHANGELOG) | _TBD_ |

The deferred Phase D sub-Ds are conditional — if their triggers never fire, v2.5 ships with `#16` + `#17` + `#199` only, and sub-D-3 / sub-D-4 formally close with a CHANGELOG entry citing the lack of live evidence.

---

## Out of scope for v2.5

- **HyDE** (hypothetical document expansion). Hurts small models per the v2 research; explicit non-goal.
- **Network-fetching tools.** Offline-only.
- **A built-in summarization LLM.** Synthesize mode (`#10`, shipped in v2.0.0a4) is retrieval + concatenation, not generation.
- **Multi-archive federated search beyond what `search_all` already does.**
- **Replacing libzim.** v2.5 builds on libzim 9+.
- **Tool surface changes.** Phase F locked the surface at v2.0.0.

---

## Per-item spec process

For each item, when work begins:

1. Verify the trigger (for sub-D-3 / sub-D-4) or confirm scope (for `#16` / `#17` / `#199`).
2. Brainstorm against this roadmap to refine scope and approaches.
3. Write a design spec in `docs/specs/YYYY-MM-DD-v2.5-<item>-design.md` (create the directory on first use).
4. Update the milestones table above with the spec link and status.
5. Generate an implementation plan via the writing-plans skill.
6. Execute, review, ship as `v2.5.0aN` / `v2.5.0bN` pre-release.

When all in-scope items ship (or formally close), tag `v2.5.0`.

## Tracking

- All v2.5 PRs use the label `v2.5`.
- Per-item labels: `v2.5-sub-d-3`, `v2.5-sub-d-4`, `v2.5-link-graph`, `v2.5-presets`, `v2.5-dispatch`.
- This document is the source of truth for "where are we." Update as decisions land.
