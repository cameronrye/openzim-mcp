# Search-engine-style `zim_query` (Design Spec)

**Status:** Draft
**Date:** 2026-05-15
**Target:** v2.0.0a14 (sweep candidate)

---

## Goal

Make `zim_query` behave like a search engine for natural-language questions: take a query like *"who are some famous people from big rapids, michigan"* and return the most relevant section excerpt (the *Notable people* section of *Big Rapids, Michigan*) as the featured answer, plus a candidate space of alternative articles and sections that a follow-up turn can pivot to.

Today the same query short-circuits entity resolution because the query has more than 4 tokens ([`synthesize.py:540`](../../../openzim_mcp/synthesize.py#L540)), so no canonical article gets promoted, and there is no notion that the answer lives in a specific section of one article.

## Non-goals

- **No new tool, no new intent, no new module.** Localized edits to four existing files; one small new helper function in `title_promotion.py`.
- **No curated question-pattern table.** No mapping of question shapes to section names.
- **No curated section-name synonyms.** No `{notable_people: ["Notable people", "Famous residents", ...]}` table.
- **No Wikipedia-shaped assumptions.** Section ranking uses each archive's own section headings — works equally on Stack Exchange, Wikitravel, Project Gutenberg, medical wikis.
- **No new ontology, no English-stopword list.** The design has zero curated artifacts left after the brainstorm pass dropped the stopword strip.
- **No server-side multi-turn state.** Multi-round refinement emerges from the response shape exposing handles (cite_ids, section_ids) the caller can pass back. The server stays stateless per call.
- **No new ML deps, no embeddings, no reranker.** Pure lexical token overlap.
- **No cross-archive question-answering reasoning.** Cross-article scope is handled by surfacing `considered_articles` so the caller can pivot — not by the server reasoning across multiple articles.

## Foundational principles

1. **The archive supplies the vocabulary.** Section ranking is "does this query share tokens with the section headings *this article actually has*." We never assert what a section "should" be called.
2. **The LLM is the reasoner.** The MCP server's job is to be a great index + reader. Question-answering composition happens turn-by-turn at the caller, not in the server.
3. **Honest tradeoffs over Wikipedia-only polish.** Pure token overlap will miss `"famous people" ↔ "Notable people"` synonyms. The miss is covered by `considered_sections` in the response, not by a curated table.

## Decisions captured during brainstorming

| Decision | Choice |
|---|---|
| Architecture shape | **Localized edits, no new module.** One shared helper in `title_promotion.py`; entity-resolution edits in both `synthesize.py` and `simple_tools.py`; affinity stage + response fields in `synthesize.py`/`tool_schemas.py`. No new intent. No new tool. |
| Dual-path coverage | **Both `tell_me_about` (default) and `synthesize` paths** get the greedy tail probe (Change A). Section-affinity boost (Change B) and `considered_*` handles (Change C) are synthesize-only — the default path keeps its markdown-string contract. See "Default-mode vs synthesize-mode coverage". |
| Response shape | **Featured excerpt + fallbacks.** Lead with one section excerpt; expose alternative articles and alternative sections as handles. |
| Query scope | **All single-entity questions, plus cross-article fallback.** When no entity resolves, fall back to existing BM25 + the new affinity boost across all hits. |
| Entity resolution | **Greedy length-down tail probe.** Try trailing 4 tokens, then 3, then 2, then 1 against each archive's title index. First hit wins. |
| Section ranking | **Token-overlap affinity boost.** Multiply RRF score by `1.5` when query and section heading share ≥ 0.25 of the heading's tokens. |
| Stopword/question-word stripping | **None.** Adds curation surface for no measurable win (see "Why no stopword strip" below). |
| Synonym buckets / question templates | **None.** Curated artifacts shifted the design toward Wikipedia-shaped assumptions; dropped. |

---

## Architecture

Four changes across existing files (Change A applies to two parallel code paths via a shared helper):

| Change | File | Function / location | Why here |
|---|---|---|---|
| A₀ — Shared greedy tail-iterator helper | [`title_promotion.py`](../../../openzim_mcp/title_promotion.py) | New `iter_query_tails(query, max_len=4, min_len=1)` | Both paths need the same tail-generation logic. Drying it once keeps the entity-extraction heuristic in one place. |
| A₁ — Greedy tail probe in synthesize path | [`synthesize.py`](../../../openzim_mcp/synthesize.py) | `_promote_title_match` ([line 498](../../../openzim_mcp/synthesize.py#L498)) | Replace the 4-token short-circuit with a tail probe that iterates `iter_query_tails(query)` and resolves each candidate via `title_match_hit`. |
| A₂ — Greedy tail probe in tell_me_about path | [`simple_tools.py`](../../../openzim_mcp/simple_tools.py) | `_promote_topic_via_title_index` ([line 2141](../../../openzim_mcp/simple_tools.py#L2141)) | The default-mode path the motivating query routes through. Without this, the motivating query is unchanged in default mode — `find_title_match` is called with the full prose topic and returns nothing. |
| B — Section-heading affinity boost | [`synthesize.py`](../../../openzim_mcp/synthesize.py) | New stage after `_attribute_sections` ([line 242](../../../openzim_mcp/synthesize.py#L242)), called from the synthesize orchestrator | Section attribution already runs; affinity scoring as a post-attribution stage keeps the change contained. |
| C — `considered_articles` + `considered_sections` in response | [`tool_schemas.py`](../../../openzim_mcp/tool_schemas.py) + [`synthesize.py`](../../../openzim_mcp/synthesize.py) response builder | Add fields to `SynthesizeResponse` TypedDict; populate in `synthesize_query` after passage capping. | `SynthesizeResponse` is the only structured response shape we're extending. The default-mode `tell_me_about` keeps its current markdown-string contract (see "Default-mode vs synthesize-mode" below). |

No new module. No new intent in [`intent_parser.py`](../../../openzim_mcp/intent_parser.py). No new tool. Tunable constants land in [`constants.py`](../../../openzim_mcp/constants.py).

### Default-mode vs synthesize-mode coverage

The motivating query *"who are some famous people from big rapids, michigan"* takes **two different code paths** depending on whether the caller sets `synthesize=True`:

| Path | Caller flag | Today | After this plan |
|---|---|---|---|
| Default (`_handle_tell_me_about`) | `synthesize=False` (default) | `find_title_match(topic)` probes the full prose string, returns nothing, falls through to BM25 search noise | A₂ + A₀: tail probe resolves `Big_Rapids,_Michigan`, fetches and returns the article body (markdown string). Entity correct, but no section targeting. |
| Synthesize (`_handle_synthesize_query`) | `synthesize=True` | 4+ token short-circuit skips title-index probe entirely | A₁ + A₀ + B + C: tail probe resolves the entity, affinity boost picks `#Notable_people` as the featured passage, response carries `considered_articles` + `considered_sections` handles. |

The full Google-style featured-snippet experience requires `synthesize=True`. The default mode gets correct entity resolution and the article body — strictly better than today's BM25-noise outcome, but not section-targeted. Auto-routing question-shaped queries with substantive intent beyond the entity to synthesize mode is a **future enhancement**, out of scope for this plan.

---

## Change A — Greedy tail probe (entity resolution)

Replace the token-count gate in `_promote_title_match`:

**Current** ([`synthesize.py:540`](../../../openzim_mcp/synthesize.py#L540)):
```python
_content_query_token_count = 4
if len(_re.findall(r"[a-z0-9]+", query.lower())) > _content_query_token_count:
    return top_hits
```

**Replace with:** greedy length-down tail probe.

```
tokens = tokenize(query)        # lowercase word tokens, in order
for tail_len in (4, 3, 2, 1):
    if tail_len > len(tokens):
        continue
    candidate = " ".join(tokens[-tail_len:])
    for archive, archive_name in zip(archives, archives_searched):
        hit = title_match_hit(archive, candidate)
        if isinstance(hit, dict) and hit.get("path"):
            return _promote(hit, top_hits, archive_name)
return top_hits
```

The strong-top-hit short-circuit ([`synthesize.py:529`](../../../openzim_mcp/synthesize.py#L529)) still runs first — when BM25 already returned a strong title match at rank 1, no probe runs.

**Why greedy length-down:** entities tend to be the longest sub-tail that still resolves. *"big rapids michigan"* is a better resolution than *"michigan"* — both probably hit the title index, but the former is the more specific entity. Trying 4→3→2→1 picks the most specific.

**Cost:** up to 4 cheap title-index probes per archive on the worst case, when no probe hits until the 1-token tail (or none of them do). Title-index probes are microseconds — bounded by `archive_count × 4`, negligible.

## Change B — Section-heading affinity boost

New stage in the synthesize pipeline, runs after `_attribute_sections`, before `_enforce_budget`:

```
# bundle["sections"] is the existing list used by _attribute_sections
# Each entry: {"id": str, "title": str, "char_start": int, "char_end": int}
section_title_by_id = {s["id"]: s["title"] for s in bundle.get("sections", [])}
query_tokens = tokenize(query)                       # lowercase [a-z0-9]+

for passage in passages:
    cite_id = passage["cite_id"]                     # existing SynthesizePassage field
    if "#" not in cite_id:
        continue                                      # article-level citation, no section
    section_id = cite_id.split("#", 1)[1]
    heading = section_title_by_id.get(section_id, "")
    heading_tokens = set(tokenize(heading))
    if not heading_tokens:
        continue
    overlap = heading_tokens & set(query_tokens)
    affinity = len(overlap) / len(heading_tokens)
    if affinity >= AFFINITY_THRESHOLD:                # default 0.25
        passage["score"] *= AFFINITY_BOOST            # default 1.5

passages.sort(key=lambda p: p["score"], reverse=True)
```

The exact attribute access (`passage["score"]` vs `passage.score`) follows whatever shape `SynthesizePassage` already uses in [`synthesize.py`](../../../openzim_mcp/synthesize.py) — the implementation plan resolves this against the current type def.

**Tunable constants** in [`constants.py`](../../../openzim_mcp/constants.py):

| Constant | Default | Rationale |
|---|---|---|
| `SECTION_AFFINITY_THRESHOLD` | `0.25` | One matching token in a 4-token heading qualifies. Conservative — won't fire on 1-of-10 weak overlaps. |
| `SECTION_AFFINITY_BOOST` | `1.5` | Won't dominate strong BM25 hits (a top-ranked passage with score 1.0 beats a rank-3 passage at 0.6 × 1.5 = 0.9). Only flips ranking among already-competitive passages. |

Both are tuneable in beta-test sweeps.

**Tokenization:** lowercase + `re.findall(r"[a-z0-9]+", text)`. No stopword strip — see "Why no stopword strip" below.

**No-op cases:**
- Passage has no `#section_id` (article-level citation) → skipped.
- Section heading not found in bundle → skipped.
- Empty heading or empty query → skipped.
- No token overlap → no boost.

## Change C — Response shape (multi-round handles)

Two new top-level fields on `SynthesizeResponse`:

```json
{
  "answer_markdown": "...",
  "citations": [...],
  "fallback_used": "rrf_fusion",
  "considered_articles": [
    {"archive": "wikipedia_en_all_maxi_2026-02", "path": "Big_Rapids_Township,_Michigan", "title": "Big Rapids Township, Michigan", "score": 0.42},
    {"archive": "wikipedia_en_all_maxi_2026-02", "path": "Ferris_State_University", "title": "Ferris State University", "score": 0.38}
  ],
  "considered_sections": [
    {"section_id": "History",          "title": "History"},
    {"section_id": "Geography",        "title": "Geography"},
    {"section_id": "Demographics",     "title": "Demographics"},
    {"section_id": "Government",       "title": "Government"},
    {"section_id": "Education",        "title": "Education"}
  ]
}
```

**`considered_articles`:** top 3–5 hits *not* selected as the featured citation. Drawn from the post-promotion `top_hits` list, minus whichever ended up rendered. Each entry exposes the same `archive` + `path` the caller can pass to `get_zim_entries`.

**`considered_sections`:** all sections of the featured article's bundle, minus the featured section. Drawn from the bundle's section list. Each entry exposes the `section_id` the caller can pass to `get_section`.

Both fields are *optional* on the response model — empty list when no candidates exist (e.g. cross-archive question with no entity-resolved article).

**Compact-mode rendering** ([`compact_renderers.py`](../../../openzim_mcp/compact_renderers.py)): appended to the existing rendered output as two short markdown tails, subject to the existing 6000-char hard cap. Truncated if necessary — full structured payload is always available via `structuredContent`.

```
### Other articles
- Big_Rapids_Township,_Michigan
- Ferris_State_University

### Other sections in this article
- History
- Geography
- Demographics
- Government
- Education
```

**JSON mode:** fields emitted directly on the structured payload.

---

## Data flow walkthrough

For *"who are some famous people from big rapids, michigan"*:

1. **Intent parser** ([`intent_parser.py:599`](../../../openzim_mcp/intent_parser.py#L599)) matches `who are` → `tell_me_about`, `topic="some famous people from big rapids, michigan"`. *(Unchanged.)*
2. **`tell_me_about` handler** runs `synthesize(query=topic)`. *(Unchanged.)*
3. **Per-archive BM25 + RRF fusion** ([`synthesize.py:82`](../../../openzim_mcp/synthesize.py#L82)). Top hits include `Big_Rapids,_Michigan`, `Big_Rapids_Township,_Michigan`, plus lexical noise. *(Unchanged.)*
4. **Change A — `_promote_title_match` tail probe:** trailing 4 tokens *"from big rapids michigan"* → no title hit. Trailing 3 *"big rapids michigan"* → `title_match_hit` resolves to `Big_Rapids,_Michigan`. Promote to rank 1.
5. **`_extract_passages` + `_attribute_sections`** ([`synthesize.py:242`](../../../openzim_mcp/synthesize.py#L242)): pull snippet windows, attribute each to `Big_Rapids,_Michigan#Notable_people`, `…#History`, `…#Geography`, etc. *(Unchanged.)*
6. **Change B — affinity boost:** query tokens `{who, are, some, famous, people, from, big, rapids, michigan}`.
   - `Notable_people` heading → `{notable, people}`. Overlap `{people}`. Affinity `1/2 = 0.5` ≥ 0.25. **Boost ×1.5.**
   - `History` → `{history}`. Overlap `{}`. No boost.
   - `Geography` → `{geography}`. No boost.
   - `Demographics` → `{demographics}`. No boost.
7. Re-sort. `…#Notable_people` passage at rank 1.
8. **`_enforce_budget` + `_build_citations`** ([`synthesize.py:331`](../../../openzim_mcp/synthesize.py#L331)): render featured passage with `cite_id = Big_Rapids,_Michigan#Notable_people`. *(Unchanged.)*
9. **Change C — response builder:** populate `considered_articles` (Big_Rapids_Township, Ferris_State_University, …) + `considered_sections` (History, Geography, Demographics, …).

Caller gets back: featured passage with names + handles to pivot to History, Geography, etc. on the follow-up turn.

---

## Why no stopword strip

The brainstorm pass initially proposed a small English stopword/question-word strip (~20 words) to clean the query before tokenization. Walking through the affinity math showed the strip is essentially inert:

**Affinity is normalized by *heading length*, not query length.** Adding `{who, are, some, from}` to query tokens doesn't change the intersection (those tokens aren't in any section heading) and doesn't change the denominator. The score is identical with or without the strip.

**For Change A**, the greedy length-down probe finds the entity without help — *"from big rapids michigan"* misses on the title index, then *"big rapids michigan"* hits. Cost is up to 3 extra cheap probes when the entity is short. Title-index probes are microseconds.

Dropping the strip removes:
- All curated English vocabulary from the design.
- The non-English-archive edge case (e.g. French Wikipedia "qui est" stripping).
- A "what's the default stopword list" review question.

Net: zero curated artifacts in the final design.

---

## Edge cases and failure modes

| Case | Behavior |
|---|---|
| No entity resolves (tail probe finds nothing in any archive) | Falls through to existing BM25 + RRF. Affinity boost (Change B) still runs against whatever section attribution produces. |
| Entity resolves but no section heading shares tokens with query | No boost fires. Featured passage is BM25 rank 1 — usually the article lead. `considered_sections` still surfaces all sections for follow-up. |
| Cross-article question (*"jazz musicians from Detroit"*) | Tail probe resolves *Detroit*; affinity rarely matches strongly (sections are *History*, *Government*, etc., not *Jazz musicians*). Response leads with BM25 top hit; `considered_articles` surfaces alternatives the caller can pivot to. |
| Archive has no section structure (Project Gutenberg single-file book, single-page Stack Exchange answer) | `_attribute_sections` returns article-level cite_id, affinity scorer has nothing to score, behavior degenerates to today's BM25. No regression. |
| Query is exact existing title (*"Photosynthesis"*) | Strong-top-hit short-circuit at [`synthesize.py:529`](../../../openzim_mcp/synthesize.py#L529) fires first. Tail probe never runs. Behavior unchanged. |
| Empty query after `tell_me_about` strip (*"tell me about "*) | Handled at [`simple_tools.py:429`](../../../openzim_mcp/simple_tools.py#L429); never reaches synthesize. Unchanged. |
| Tail probe ties (4-token tail and 3-token tail both hit) | Greedy: 4-token wins. Won't happen in practice unless someone has a 4-token title indexed; deterministic by ordering. |
| Affinity ties (two sections both score 0.5) | Tie broken by original BM25 score (existing secondary sort). Deterministic. |
| Same query token appears in multiple section headings (*"History"* and *"Early history"*) | Both get boosted. Existing dedup in citations handles the rest. |
| Non-English archive | No stopword strip means no English bias. Tokenization (`[a-z0-9]+`) drops accented characters — a known limitation, but the existing pipeline has the same property. No regression from this design. |

---

## Performance

- **Change A:** up to 4 extra `title_match_hit` calls per archive on the worst case. Each is the cheap title-index path, not full search. Bounded by `archive_count × 4`, sub-millisecond.
- **Change B:** O(passages × sections) token-set intersections, capped at ~30 passages × ~30 sections = 900 small set ops. Sub-millisecond.
- **Change C:** response payload grows by ~5 article handles + ~20 section handles. Compact-mode hard cap (6000 chars) still applies; the tails truncate first if needed.

No new caches, no new deps.

---

## Testing

**Unit tests** ([`tests/`](../../../tests/)):

- `_promote_title_match` greedy tail probe — parameterized cases:
  - Single-token entity (*"detroit"*) — 1-token tail hits.
  - Multi-token entity (*"big rapids michigan"*) — 3-token tail hits, longer tails miss.
  - No-entity-tail (*"how do plants make food"*) — all tail lengths miss, falls through.
  - Entity at the front of the query — tail probe still finds it via shorter tails.
  - Adversarial overlap (*"who is who"*) — bounded probe terminates.
  - Query with only stopwords — no entity found, falls through.
  - Empty query — graceful no-op.
  - Strong-top-hit short-circuit still wins when BM25 already returned the canonical title.
- Section affinity scorer — heading/query pairs:
  - `"famous people"` × `"Notable people"` → affinity 0.5, boosts.
  - `"famous people"` × `"History"` → 0.0, no boost.
  - `"people"` × `"People"` → 1.0, boosts.
  - Identical query and heading → 1.0, boosts.
  - Empty heading → skipped.
  - Threshold boundary (0.25 exact) → boosts.
- Response builder:
  - `considered_articles` populated correctly, excludes the featured citation's article.
  - `considered_sections` populated correctly, excludes the featured citation's section, capped at the bundle's section count.
  - Compact-mode rendering under the 6000-char cap; both tails truncate before structured fields drop.
  - JSON-mode emission.

**Live beta-test sweep** (per the [a-series methodology](../../../README.md)): the design lands in a new alpha, then gets sweep-tested against the 118 GB Wikipedia ZIM.

Adversarial sweep set:
- The motivating query: *"who are some famous people from big rapids, michigan"* — verify featured passage is in `Big_Rapids,_Michigan#Notable_people`.
- Wikipedia question-shape battery: *"history of Detroit"*, *"geography of Iceland"*, *"economy of Vietnam"*, *"notable people from Big Rapids"*, *"famous residents of Detroit"*. Each should pull the right section.
- Cross-article scope: *"jazz musicians from Detroit"*, *"WWII battles in Africa"*. Verify `considered_articles` surfaces useful pivots even when the featured passage is wrong.
- Existing adversarial set from the [a-series memory](../../../memory) still passes — single-word topics, politeness-tail variants, canonical-with-disambig-twin (Berlin, Tokyo, Mercury, Apollo 11), single-edit typos, chained-intent queries. Confirms no regression from the 4+ token short-circuit removal.
- Non-Wikipedia archive smoke test if available — Stack Exchange or Wikitravel ZIM with a question whose answer is in a known section. Verify the affinity boost matches against *that archive's* section vocabulary, not Wikipedia's.

Beta-test findings cycle back as new unit tests, same as a8 → a13.

---

## Open questions

None at spec-write time. All decisions captured above.

## Risks

- **Affinity boost dominates strong BM25 in a way we didn't anticipate.** Mitigation: the boost factor (`1.5`) is conservative; a top BM25 hit (score 1.0) still beats a rank-3 hit at `0.6 × 1.5 = 0.9`. Tune in sweep.
- **Greedy tail probe pulls wrong entity when query has multiple proper nouns** (e.g. *"battles between Rome and Carthage"* — does the 2-token tail *"and carthage"* miss but *"carthage"* resolve? Yes — that's the correct entity for this query, but the same logic applied to *"X versus Y"* might pick the wrong side). Mitigation: the existing strong-top-hit short-circuit ([`synthesize.py:529`](../../../openzim_mcp/synthesize.py#L529)) catches the case where BM25 already found the right entity at rank 1. Beta-test sweep will surface remaining cases.
- **`considered_sections` token cost.** A Wikipedia city article has ~20 sections; serialized that's ~500 bytes. Compact mode handles via the 6000-char cap; structured mode is unbounded but small. Monitor in sweep.
