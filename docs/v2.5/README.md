# openzim-mcp v2.5 — Release Tracking

**Status:** Planning
**Target:** v2.5.0 (minor release, additive)
**Started:** 2026-05-24
**Owner:** @cameronrye
**Predecessor:** [v2 tracker](../v2/README.md) (v2.0.0 final cuts after Phase F)

This document tracks v2.5 — a minor release that collects everything deferred from v2 that is **additive** (extras-gated, sidecar-based, or otherwise optional). Nothing in v2.5 breaks the v2 tool surface or response contract.

The work is grouped into two themes. Each item ships independently as a `v2.5.0aN` / `v2.5.0bN` pre-release, then the final `v2.5.0` tag cuts once all in-scope items ship OR are formally closed.

---

## Why v2.5, not v3

All items are additive: opt-in extras (`[planner]`, `[embeddings]`), optional sidecars (`<archive>.zim.linkgraph.sqlite`, `<archive>.zim.semantic.faiss`), and data-only presets (`presets/wikipedia.toml`). None changes the v2 tool surface or response shapes. Semantic versioning argues minor.

v3 would be reserved for a future breaking change — e.g., a libzim major version bump, or a deeper tool-surface restructure beyond Phase F.

---

## Foundational decisions (inherited from v2)

These continue to apply.

- **ML accelerators are opt-in via extras.** Default install stays lean.
- **Offline-first.** Sidecars and models load from disk; build steps are explicit operator commitments.
- **Markdown for prose, JSON for navigation; no XML in tool responses.**
- **Backward compat at the data layer.** Sidecars live next to `.zim` files and are optional; absence is reported gracefully.

---

## Theme 1 — Items deferred from Phase D

The [v2 Phase D design spec](../superpowers/specs/2026-05-20-v2-phase-d-ml-accelerators-design.md) shipped #6 (cross-encoder reranker) and #8 Tier 1 (rules-based query rewriting) at v2.0.0b1, then deliberately deferred three items pending live evidence. Each has a **measurable trigger** that would justify cutting a follow-up design spec.

### sub-D-3 — Hybrid intent parser + Tier 2 decomposition (#8 Tier 2 + #12)

**Current state.** [`openzim_mcp/intent_parser.py`](../../openzim_mcp/intent_parser.py) is regex-based with 19 weighted patterns. Confidence < 0.7 routes to a low-confidence path; confidence < 0.55 marks "low confidence" with a footer.

**Target.** Hybrid path: regex stays as the fast path; below confidence 0.7, route to a small intent classifier (fastText / distilled sentence-transformer / lightweight rules-tree). Tier 2 decomposition adds entity-then-property lookups for multi-hop queries like "what year did the inventor of X die." Behind `pip install openzim-mcp[planner]`.

**Trigger to design.** After v2.0.0b1 deploy (already shipped) and ≥2 weeks of live telemetry shows EITHER:

- ≥5% of `parse_intent` calls land in the existing low-confidence path (regex confidence < 0.7), OR
- Small-model transcript review surfaces multi-hop queries that the regex path fails on at ≥1 per 100 queries.

**Status as of 2026-05-24.** Beta sweep cycles (b2 → b13) have driven the regex path to roughly 99% accuracy on labeled queries. No live evidence has met either trigger. If neither fires by 2026-07-19 (8 weeks post-sub-D-2 deploy), formally close sub-D-3 as "not justified by live evidence."

**Reference design.** Previous draft of the fastText classifier path preserved at commit [`a92d04e`](https://github.com/cameronrye/openzim-mcp/commit/a92d04e).

### sub-D-4 — Embeddings sidecar + hybrid retrieval (#15)

**Current state.** No semantic search. Pure Xapian BM25 is the only relevance signal beyond the cross-encoder reranker (which reranks Xapian's top-50). Semantic-divergent queries ("the chemical that makes leaves green") have no path to canonical matches that don't share lexical tokens.

**Target.** Behind `pip install openzim-mcp[embeddings]`. A build-time CLI generates `<archive>.zim.semantic.faiss` next to the archive (32 GB per multi-million-article archive, 3–4 hour build time). At query time, hybrid retrieval: Xapian top-K + semantic top-K → RRF fuse (k=60) → rerank.

**Trigger to design.** After v2.0.0b1 deploy and ≥4 weeks of live telemetry shows BOTH:

- Reranker hit rate is meaningful (≥15% of search-tool calls past the skip-on-short-query gate), AND
- Operators or end-users report that semantic-divergent queries consistently miss in Xapian-only search even with the reranker active.

**Status as of 2026-05-24.** Telemetry not yet collected at the required granularity. No operator reports.

**Reference design.** Previous draft preserved at commit [`a92d04e`](https://github.com/cameronrye/openzim-mcp/commit/a92d04e).

---

## Theme 2 — Phase E offline build artifacts

Phase E was scoped in the v2 tracker but deferred to v2.5 because it's independent of runtime code and doesn't block v2.0.0 final. Both items add operator-build commands that produce optional sidecars; the default behavior is unchanged.

### #16 — Inbound link-graph sidecar

**Current state.** [`openzim_mcp/zim/content.py`](../../openzim_mcp/zim/content.py) `get_related_articles` is outbound-only. Inbound link discovery was removed in v0.9.0 because the runtime cost is prohibitive on a multi-million-article archive.

**Target.** `openzim-mcp build link-graph <archive>.zim` produces `<archive>.zim.linkgraph.sqlite` (or similar) with reverse-edge indexes. At runtime, `get_related_articles(direction="inbound")` becomes a SQLite lookup. Sidecar is optional; absence is reported gracefully.

**Build cost.** Estimated 30–60 minutes per multi-million-article archive (single-pass entry walk + bulk SQLite insert). Storage: ~500 MB – 2 GB per archive depending on link density.

### #17 — Archive-type presets

**Current state.** Wikipedia, Wiktionary, Stack Exchange, and TED-style ZIMs behave differently (encyclopedic prose vs. dictionary entries vs. Q&A vs. transcripts), but the server treats them uniformly. Models waste turns discovering archive shape.

**Target.** Detect archive type via the `M`-namespace metadata + heuristics on `Creator` / `Name` / `Title`. Each detected type has a preset that adjusts: snippet shape, summary style, default namespace for unfiltered queries, and intent-parser priors. Presets are data, not code — `openzim_mcp/presets/wikipedia.toml` etc. Users can override per-archive in config.

---

## v2.5 milestones (proposed)

| Milestone | Items | Tag |
|-----------|-------|-----|
| **v2.5.0a1** | #17 archive-type presets (smallest scope, data-only) | _TBD_ |
| **v2.5.0a2** | #16 link-graph sidecar + `build` CLI | _TBD_ |
| **v2.5.0a3** | sub-D-3 if triggered | _TBD_ |
| **v2.5.0a4** | sub-D-4 if triggered | _TBD_ |
| **v2.5.0** | Final after all triggered items ship (closed sub-Ds annotated in CHANGELOG) | _TBD_ |

The deferred Phase D sub-Ds are conditional — if their triggers never fire, v2.5 ships with #16 + #17 only and sub-D-3/sub-D-4 formally close with a CHANGELOG entry citing the lack of live evidence.

---

## Out of scope for v2.5

- **HyDE** (hypothetical document expansion). Hurts small models per v2 README research; explicit non-goal carried forward.
- **Network-fetching tools.** v2.5 stays offline-only.
- **A built-in summarization LLM.** Synthesize mode (#10, shipped in v2.0.0a4) is retrieval + concatenation, not generation.
- **Multi-archive federated search beyond what `search_all` already does.**
- **Replacing libzim.** v2.5 builds on libzim 9+.
- **Tool surface changes.** That's Phase F (v2.0.0 final).

---

## Per-item spec process

For each item, when work begins:

1. Verify the trigger (for sub-D-3 / sub-D-4) or confirm scope (for #16 / #17).
2. Brainstorm against this tracking doc to refine scope and approaches.
3. Write a spec to `docs/superpowers/specs/YYYY-MM-DD-v2.5-<item>-design.md`.
4. Update the milestones table above with the spec link and status.
5. Generate an implementation plan via the writing-plans skill.
6. Execute, review, ship as `v2.5.0aN` / `v2.5.0bN` pre-release.

When all in-scope items ship (or formally close), tag `v2.5.0`.

## Tracking

- All v2.5 PRs use the label `v2.5`.
- Per-item labels: `v2.5-sub-d-3`, `v2.5-sub-d-4`, `v2.5-link-graph`, `v2.5-presets`.
- This document is updated as decisions land. Treat the **milestones** table as source of truth for "where are we."
