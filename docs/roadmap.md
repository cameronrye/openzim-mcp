# openzim-mcp Roadmap

**Status:** Latest release **v2.4.3** (2026-06-15) — PyPI `2.4.3` and `ghcr.io/cameronrye/openzim-mcp:2.4.3` / `:latest`, GitHub Release with assets. v2.0.0 GA shipped 2026-05-27 (as `:2.0.0`); the v2.0.x/v2.1.x line was kept current via beta-sweep fixes plus the v2.1.0 native-libzim reader features. **v2.2.0 shipped the first v2.5 roadmap item — `#17` archive-type presets (the v2.5.0a1 milestone)** — validated against the live superuser (sotoki v3.0.2) archive in the v2.2.0 reprobe; v2.2.1 was a Docker stdio-default fix. **v2.3.0 shipped `#16` — the inbound link-graph sidecar (the v2.5.0a2 milestone).** **v2.4.0 (2026-06-09) shipped the v2.5.0a3 items** (`#199` dispatch-eval scoping, `#18` `zim_get_section` raw-text) and the `#16` sidecar-v2 follow-ups (`builder_version` meta + per-edge `anchor_text`, finer `build` CLI errors) — PRs #277/#279/#280/#281.

This document tracks open work past v2.0.0. Everything here is **additive**: opt-in extras, optional sidecars, or dispatch tuning. None of it changes the v2 tool surface or response contract.

v3 is reserved for a future breaking change (libzim major bump or a deeper surface restructure). **Release cadence note:** the additive v2.5 items are shipping incrementally on the normal **v2.2.x+** minor/patch line (e.g. `#17` landed in v2.2.0), not as standalone `v2.5.0aN` pre-releases. The `v2.5.0` tag is retained below as the rollup marker for when the in-scope set lands; the per-milestone `v2.5.0aN` labels are bookkeeping, not literal release tags.

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

**Current state.** [`openzim_mcp/intent_parser.py`](../openzim_mcp/intent_parser.py) is regex-based with 26 weighted patterns. Confidence < 0.7 routes to a low-confidence path; confidence < 0.55 marks "low confidence" with a footer.

**Target.** Hybrid path: regex stays as the fast path; below confidence 0.7, route to a small intent classifier (fastText / distilled sentence-transformer / lightweight rules-tree). Tier 2 decomposition adds entity-then-property lookups for multi-hop queries like "what year did the inventor of X die." Behind `pip install openzim-mcp[planner]`.

**Trigger to design.** After v2.0.0b1 deploy and ≥2 weeks of live telemetry shows EITHER:

- ≥5% of `parse_intent` calls land in the existing low-confidence path (regex confidence < 0.7), OR
- Small-model transcript review surfaces multi-hop queries that the regex path fails on at ≥1 per 100 queries.

**Status (updated 2026-06-08; decision due 2026-07-19).** Beta sweep cycles (b2 → b13) drove the regex path to roughly 99% accuracy on labeled queries, and no live evidence has met either trigger. **The trigger is not an auto-computed in-process rate** and was never promised as one: the per-call `<!-- intent=… cert=… -->` marker appended to every response exposes each `parse_intent` confidence, so an operator recovers the low-confidence rate (the fraction with `cert < 0.7`) by grepping their own transcript/log retention across the window; the second leg (multi-hop failures) is a qualitative transcript review. As of 2026-06-08 no such operator evidence and no transcript-review report has surfaced. **Default outcome:** absent an operator report before 2026-07-19, sub-D-3 formally closes as "not justified by live evidence" (recorded in CHANGELOG) and reopens only if the trigger later fires in the field.

**Reference design.** Previous draft of the fastText classifier path preserved at commit [`a92d04e`](https://github.com/cameronrye/openzim-mcp/commit/a92d04e).

#### sub-D-4 — Embeddings sidecar + hybrid retrieval (`#15`)

**Current state.** No semantic search. Pure Xapian BM25 is the only relevance signal beyond the cross-encoder reranker (which reranks Xapian's top-50). Semantic-divergent queries ("the chemical that makes leaves green") have no path to canonical matches that don't share lexical tokens.

**Target.** Behind `pip install openzim-mcp[embeddings]`. A build-time CLI generates `<archive>.zim.semantic.faiss` next to the archive (≈32 GB per multi-million-article archive, 3–4 hour build time). At query time, hybrid retrieval: Xapian top-K + semantic top-K → RRF fuse (k=60) → rerank.

**Trigger to design.** After v2.0.0b1 deploy and ≥4 weeks of live telemetry shows BOTH:

- Reranker hit rate is meaningful (≥15% of search-tool calls past the skip-on-short-query gate), AND
- Operators or end-users report that semantic-divergent queries consistently miss in Xapian-only search even with the reranker active.

**Status (updated 2026-06-08; closes with sub-D-3 on 2026-07-19).** Telemetry is still not collected at the required granularity and there are no operator reports. As with sub-D-3, both legs are operator-observable rather than server-aggregated: the reranker emits a per-call INFO line and the four `reranker_*` counters in the `zim_health` server-health report give the hit-rate denominator (see [extras-reranker.md](extras-reranker.md)), while the semantic-miss leg is inherently qualitative (operator / end-user reports). As of 2026-06-08 neither leg has produced evidence. **Default outcome:** absent both legs before 2026-07-19, sub-D-4 formally closes alongside sub-D-3 as "not justified by live evidence" (recorded in CHANGELOG) and reopens only if the triggers later fire.

**Reference design.** Previous draft preserved at commit [`a92d04e`](https://github.com/cameronrye/openzim-mcp/commit/a92d04e).

### Phase E — Offline build artifacts

Independent of runtime code; both items add operator-build commands that produce optional sidecars. Default behavior is unchanged.

#### `#16` — Inbound link-graph sidecar — ✅ **SHIPPED in v2.3.0 (PR #274)**

**Shipped scope.** `openzim-mcp build link-graph <archive>.zim` produces `<archive>.zim.linkgraph.sqlite` next to the archive (integer-keyed SQLite sidecar). At runtime, `zim_links(direction="inbound", entry_path=...)` returns pages that link TO the entry, ranked by linker importance, cursor-paginated. Strict staleness refusal: if the archive's UUID no longer matches the one recorded at build time (the archive was rebuilt or replaced), the call returns a structured `inbound_sidecar_unavailable` error; absence is reported the same way rather than raising.

**Shipped scope (design spec removed post-ship).** Full vertical slice — build CLI + integer-keyed SQLite sidecar + runtime inbound read ranked by linker importance + `"inbound"` enum promotion, strict staleness refusal, graceful absence. Sidecar **v2** (`builder_version` meta + per-edge `anchor_text`) and finer `build` CLI errors followed in v2.4.0 (PRs #279, #280).

#### `#17` — Archive-type presets — ✅ **SHIPPED (a1) in v2.2.0**

**Target (met for a1).** Detect archive type via the `M`-namespace metadata + heuristics on `Creator` / `Name` / `Title`. Each detected type has a preset that adjusts snippet shape and summary style. Presets are data, not code — bundled [`openzim_mcp/data/presets.toml`](../openzim_mcp/data/presets.toml), with `OPENZIM_MCP_PRESETS_OVERRIDE_PATH` deep-merge and per-archive pins. See [the design spec](specs/2026-06-04-v2.5-archive-type-presets-design.md).

**Shipped a1 scope.** Deterministic classifier ([`archive_types.py`](../openzim_mcp/archive_types.py)) detects all four types + `generic` and surfaces `_meta.detected_type` / `_meta.detection_confidence`. Behavior presets attach to `wikipedia` (explicit baseline) and `stackexchange` (`q_and_a` summary + wider snippet) only; `_meta.preset_applied` flags shaped responses. No tool-surface or response-contract change.

**Reprobe outcome (v2.2.0, live superuser sotoki v3.0.2).** Detection lands `stackexchange`/`high`. The `q_and_a` selector matches the sole `"N AnswersN"` heading on every real Q&A page (sotoki pluralizes even N=1 → `"1 Answers1"`); the answer-submission form is stripped, so there is no false-match, and zero-answer pages fall back to first-section. `max_paragraphs = 3` validated for SE search snippets. The selector token and `max_paragraphs` are confirmed — no change needed.

**Deferred to a2 (pure data + minor refinement).**

- `wiktionary` (`gloss`) and `ted` (transcript) behavior presets — detected and reported today, but no behavior preset; adding them needs a new `summary_style` value + selection logic, not just data.
- **Score-prefix cleanup:** SE answer sections open with a bare vote-score line (e.g. `3`, `18`) that becomes the first token of the `q_and_a` summary. Harmless within the 200-word window; a candidate trim for a2.
- The default-namespace seam and intent-parser priors remain out of scope per the spec's Non-goals.

### v2.0 surface refinements pending v2.5

Open commitments referenced from production code (`openzim_mcp/tools/`) and tests. None breaks v2.0 callers.

#### `#199` — `zim_query` natural-language dispatch for three `zim_get` sub-modes

**Current state.** Phase F's `zim_query` natural-language router still dispatches `zim_get` only via its default `entry` sub-mode. The `summary`, `toc`, and `structure` sub-modes are reachable when called as explicit advanced tools, but `zim_query` does not select them from natural prose.

**Target.** Description tuning and/or probe-set relaxation on the dispatch path so phrases like "give me a summary of X" or "show the table of contents for X" route to the right sub-mode. Captured at GitHub issue `#199`.

**Status — ✅ SHIPPED in v2.4.0 (PR #281).** Resolved as a measurement artifact, not a dispatch defect: the `zim_query` answer to a prose "summarize / outline / TOC / main-page" request is a working outcome, and the probe set already tags those probes `either_acceptable`. `analyze.py` now counts a `zim_query` dispatch as correct for the four prose sub-mode classes (scoped so a `zim_query` regression on operational classes stays visible). Model-verified: `zim_get-summary`/`-structure`/`-toc`/`-main-page` clear ≥70% on both the committed rc1 run and a fresh qwen3-8b-q4 sweep; operational classes unchanged. Description tuning (path A) was unnecessary and is not done. (Design spec removed post-ship.)

#### `#18` — `zim_get_section` true raw-text path

**Current state.** [`openzim_mcp/tools/zim_get_section.py`](../openzim_mcp/tools/zim_get_section.py) accepts `compact: bool` for surface uniformity with `zim_query` / `zim_get`, but at v2.0 the parameter is a no-op: section bodies always ship in the bundle's compact rendering so the slice shape matches `zim_get(view="full")` output on the same article.

**Target.** Wire a true raw-text path so `compact=False` returns the unrendered section body, matching the rendering contract the other tools already honour. Schema-additive — no caller has to opt in.

**Status — ✅ SHIPPED in v2.4.0 (PR #277).** `compact` is threaded through the bundle pipeline with a render-mode-keyed cache; `compact=False` returns full tables instead of `[Table N: …]` placeholders. Default `True` preserves all existing behaviour; no `*_description.md` change. (Design spec removed post-ship.)

#### `zim_get` `compact` default revisit

**Current state.** [`openzim_mcp/tools/zim_get.py`](../openzim_mcp/tools/zim_get.py) defaults `compact=False` at v2.0 to preserve v1.x payload sizing. Small-model callers must opt in to compaction.

**Target.** Revisit the default after adoption telemetry shows whether small-model callers consistently pass `compact=True`. If usage skews heavily one way, flip the default in v2.5. Schema-compatible either direction; the change is documentation + a constructor default.

#### `zim_links` `"inbound"` direction enum promotion — ✅ **IMPLEMENTED with `#16`**

`"inbound"` is now present in the `direction` enum. Schema-additive; no caller had to change. Shipped in **v2.3.0** alongside `#16` (PR #274).

---

## v2.5 milestones (proposed)

| Milestone | Items | Status / Tag |
| --- | --- | --- |
| **v2.5.0a1** | `#17` archive-type presets ([spec](specs/2026-06-04-v2.5-archive-type-presets-design.md) — snippet + summary seams, detect all 4 types, behavior for Wikipedia/Stack Exchange) | ✅ **Shipped in v2.2.0** (reprobe-validated; a2 follow-ons noted above) |
| **v2.5.0a2** | `#16` link-graph sidecar + `build` CLI + `zim_links` `"inbound"` enum promotion | ✅ **Shipped in v2.3.0** (PR #274); sidecar **v2** follow-ups — `builder_version` + per-edge `anchor_text` (PR #280) + finer `build` CLI errors (PR #279) — **shipped in v2.4.0** |
| **v2.5.0a3** | `#199` dispatch-eval `either_acceptable` scoping + `#18` `zim_get_section` raw-text path | ✅ **Shipped in v2.4.0** (PRs #277, #281) |
| **v2.5.0a4** | sub-D-3 if triggered + `zim_get` `compact` default revisit (telemetry-driven) | sub-D-3 → **close-by-default 2026-07-19** unless a field trigger fires (see status above); compact revisit _TBD_ |
| **v2.5.0a5** | sub-D-4 if triggered | **close-by-default 2026-07-19** unless triggers fire (see status above) |
| **v2.5.0** | Final after all triggered items ship (closed sub-Ds annotated in CHANGELOG) | _TBD_ |

The deferred Phase D sub-Ds are conditional — if their triggers never fire, v2.5 ships with `#16` + `#17` + `#199` only, and sub-D-3 / sub-D-4 formally close with a CHANGELOG entry citing the lack of live evidence. As of 2026-06-08 no field evidence has been collected and both triggers are operator-observable only (not server-aggregated; see each sub-D's status), so the standing decision is **close-by-default on 2026-07-19** unless an operator report arrives first.

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
