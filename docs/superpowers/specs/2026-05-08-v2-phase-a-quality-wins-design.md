# v2 Phase A — Quality Wins (Design Spec)

**Status:** Approved
**Phase:** A of 6 ([tracking doc](../../v2/README.md))
**Items in scope:** #1, #2, #4, #5, #14
**Target:** `v2.0.0a1`
**Date:** 2026-05-08

---

## Goal

Make every existing tool in [`openzim_mcp`](../../../openzim_mcp/) substantially smarter for smaller, less capable LLMs (Haiku-class, Llama-3-8B, Mistral-7B, Phi) by improving search snippet quality, content extraction, response metadata, and typo tolerance — **without changing tool signatures or removing tools**. Phase A is the lowest-risk, highest-velocity entry into the v2 release. It validates the v2 effort end-to-end (build, release pipeline, docs) before larger surgery in B–F.

## Non-goals

- No new MCP tools. (`get_section`, `synthesize`, `get_table` etc. are Phase C/F.)
- No tool removals or signature changes. (Tool collapse is Phase F.)
- No ML/embedding deps. (Reranker, classifier, embedding sidecar are Phase D.)
- No precomputed indexes or sidecar files. (Section bundle is Phase C; link graph and presets are Phase E.)
- No standardized pagination contract refactor. (That's Phase B.)
- No migration of remaining JSON-string returns to `structuredContent`. (Also Phase B.)

## Foundational decisions inherited from the v2 tracking doc

1. **Clean breaks allowed** — but Phase A intentionally introduces no breaks at the dict-key / signature layer. Compact-mode empty-result *prose* is rewritten as a footer ([see #4](#4--structured-suggestions-on-empty--low-confidence-results)); `compact=False` paths retain exact v1.2.0 behavior.
2. **ML accelerators opt-in via extras** — Phase A introduces no ML deps. `tiktoken` is included as a core dep because it is a tokenizer library, not an ML model.
3. **Offline-first** — every Phase A capability works without network.
4. **Markdown for prose, JSON for navigation, no XML** — Phase A's `_meta` envelope is JSON-shaped; the prose footer is plain markdown.

---

## Architecture

### New module

[`openzim_mcp/meta.py`](../../../openzim_mcp/meta.py) — central helpers used by every Phase A touchpoint.

| Function | Purpose |
|---|---|
| `tokens_est(rendered: str) -> int` | Lazy-loaded `tiktoken.get_encoding("cl100k_base")` tokenizer. Returns an integer token count for the rendered string. Module-level cache; ~5 ms per call after warmup. |
| `build_meta(*, rendered: str, total_chars: Optional[int] = None, current_offset: int = 0, suggestions: Optional[list[dict]] = None, reason: Optional[str] = None, truncated: bool = False) -> dict` | Constructs the `_meta` envelope. Adds 5% pad for envelope cost. Drops keys whose values are `None` or empty. |
| `format_footer(meta: dict) -> str` | Single-line markdown footer derived from a `_meta` envelope. Returns empty string if `META_FOOTER_ENABLED` is false. |

### Touched modules

| Module | Changes |
|---|---|
| [`openzim_mcp/zim/content.py`](../../../openzim_mcp/zim/content.py) | Wire `SearchIterator.getSnippet()` through `_get_entry_snippet` (#1). Attach `_meta` to `get_zim_entry`/`get_zim_entries`/`get_main_page`/`get_entry_summary` returns (#5). |
| [`openzim_mcp/zim/search.py`](../../../openzim_mcp/zim/search.py) | Use libzim native snippets in search responses (#1). Attach structured `_meta.suggestions[]` to empty/low-confidence responses (#4). Apply `_meta` to `search_zim_file`, `search_all`, `search_with_filters`, `find_entry_by_title`, `get_search_suggestions`, `browse_namespace`, `walk_namespace` (#5). Add Damerau-Levenshtein-1 fallback to `find_entry_by_title` (#14). |
| [`openzim_mcp/content_processor.py`](../../../openzim_mcp/content_processor.py) | New helpers `extract_infobox`, `replace_oversized_tables` (#2). Both gated by compact mode; `compact=False` path unchanged. |
| [`openzim_mcp/simple_tools.py`](../../../openzim_mcp/simple_tools.py) | Append prose footer to compact-mode responses (#5). Surface structured suggestions through compact pipeline (#4). |
| [`openzim_mcp/defaults.py`](../../../openzim_mcp/defaults.py) | New constants (see Configuration). |
| [`pyproject.toml`](../../../pyproject.toml) | Add `tiktoken>=0.7.0` to core `dependencies`. |
| [`README.md`](../../../README.md) | Document `_meta` schema, footer format, infobox/table behavior, fuzzy fallback. |

### What does **not** change

- No tool signatures change. No tool is removed.
- No existing response key is removed or renamed.
- `compact=False` paths continue to produce exactly the v1.2.0 markdown.
- Cache key shapes are unchanged. (Phase A relies on existing LRU cache for snippet results, not new entries.)

---

## The `_meta` envelope

Added as a `_meta` key on every dict-returning tool response. JSON shape:

```json
{
  "tokens_est": 4283,
  "chars": 17034,
  "truncated": true,
  "more_at_offset": 17000,
  "total_chars": 87421,
  "suggestions": [
    {"type": "alt_spelling", "value": "Photosynthesis"},
    {"type": "broader",      "value": "biology"},
    {"type": "alt_archive",  "value": "wikipedia_en_all"}
  ],
  "reason": "low_relevance"
}
```

### Field semantics

| Field | Type | Always present? | Notes |
|---|---|---|---|
| `tokens_est` | int | Yes | `cl100k_base` BPE estimate of the rendered string the model sees, +5% pad. Excludes `_meta` itself. |
| `chars` | int | Yes | Character count of the rendered string. |
| `truncated` | bool | Yes | True iff the underlying content was cut to fit a `max_*` limit. |
| `more_at_offset` | int | Only if `truncated` | Offset to pass on the next call to resume. |
| `total_chars` | int | Only if `truncated` | Total length of the source content. Lets the model compute "how much remains." |
| `suggestions` | list | Only on empty/low results | See [Suggestions schema](#suggestions-schema). Capped at `STRUCTURED_SUGGESTIONS_LIMIT` (default 5). |
| `reason` | enum string | Only on empty/low results | One of: `no_xapian_index`, `0_hits`, `low_relevance`, `bad_namespace`, `bad_query`. |

### Suggestions schema

```json
{"type": "alt_spelling" | "broader" | "narrower" | "alt_archive" | "alt_namespace", "value": "<string>"}
```

Source priority (see [item #4 details](#4--structured-suggestions)):
1. D-L-1 candidates from item #14 (typed `alt_spelling`)
2. `SuggestionSearcher` partial matches (typed `alt_spelling`)
3. Cross-archive hits from other currently-open ZIMs (typed `alt_archive`)
4. Phase E archive-preset broader/narrower terms (typed `broader`/`narrower`) — **stubbed empty in Phase A pending #17.**

## The prose footer

A single-line markdown blockquote, separated from the body by a blank line, appended only in `compact=True` mode (default for simple-mode responses).

### Successful response footer

```
> ~4.2K tokens · 17K of 87K chars · pass `offset=17000` for more
```

Rules:
- `~XK tokens` rounded to one decimal for K-scale, integer for sub-K.
- Char counts shown only when content is truncated; otherwise just `~4.2K tokens`.
- `offset=N` clause shown only when `more_at_offset` present.

### Empty / zero-result footer

```
> No results. Try: `suggestions for Photosynthesis` · `search photosynthesis chlorophyll` · or try ZIM `wikipedia_en_all`
```

Rules:
- One suggestion per dot-separator, max 3 visible (the rest are still in `_meta.suggestions[]`).
- Existing prose recovery hints in [`zim/search.py:352-368`](../../../openzim_mcp/zim/search.py) are removed in favor of this footer to avoid duplication.

### Suppression

- `compact=False` → no footer (verbose output already gives the model what it needs).
- `META_FOOTER_ENABLED=false` env override → no footer (clients that strip-parse markdown).
- Error responses → no footer (existing error envelope is sufficient).

---

## Per-item changes

### #1 — Native query-aware snippets

**Touchpoint:** [`openzim_mcp/zim/content.py:62-72`](../../../openzim_mcp/zim/content.py) (`_get_entry_snippet`).

**Behavior change.** The current path decompresses the entry, runs HTML→text, then takes the first 2 paragraphs via `create_snippet` ([`content_processor.py:432-459`](../../../openzim_mcp/content_processor.py)). New behavior: when invoked from a search context with a `SearchIterator`, call `iterator.getSnippet()` to get libzim's query-aware passage with highlighting. Strip `<mark>`/`</mark>` tags before returning.

**Fallback.** When no `SearchIterator` is available (`find_entry_by_title` paths fed by `SuggestionSearcher`, or libzim versions without `getSnippet()`), retain `create_snippet`'s lead-paragraph behavior. Log once at startup if libzim build lacks the snippet API.

**Snippet length.** Honor existing `snippet_length` config (3000 chars full, 250 chars compact). libzim returns full-length snippets; we trim to config.

### #2 — Tables & infoboxes in compact mode

**Touchpoint:** [`openzim_mcp/content_processor.py`](../../../openzim_mcp/content_processor.py).

**Two new helpers.**

`extract_infobox(soup) -> list[dict]`:
- Detection selectors: `.infobox`, `.vcard`, `table.infobox`. (Wikipedia, Wikiquote, Wiktionary, Wikivoyage all use these.)
- Extracts up to `INFOBOX_KV_LIMIT` (30) `<th>`/`<td>` row pairs from the first matching container per article.
- Returns `[{"label": str, "value": str}]` with whitespace-collapsed string values; nested links flattened to anchor text only.
- The infobox is **removed from the soup** after extraction so it doesn't get pipe-soup'd by `html2text`.
- The extracted KV list is rendered to markdown (one `**Label:** Value` line per row) and prepended to the body.

`replace_oversized_tables(soup, *, row_threshold=8, char_threshold=600)`:
- Walks remaining `<table>` elements in document order.
- "Oversized" if `len(rows) > row_threshold` OR `len(table.get_text()) > char_threshold`.
- Replaces oversized tables with a paragraph: `[Table N: 47 rows × 6 cols — pass compact=False to expand]` where N is the table's 1-based document order.
- Smaller tables pass through unchanged.

**Both helpers run only when `compact=True`.** The full HTML pipeline is preserved when `compact=False` so users who want full table data can still get it.

### #4 — Structured suggestions on empty / low-confidence results

**Touchpoints:** [`openzim_mcp/zim/search.py`](../../../openzim_mcp/zim/search.py) (search, find-by-title, get-suggestions paths), [`openzim_mcp/simple_tools.py`](../../../openzim_mcp/simple_tools.py) (compact pipeline).

**Behavior change.** When a list-returning search/lookup tool produces zero results (or all results below the confidence floor), the response includes:
- `_meta.reason`: a machine-readable enum identifying why.
- `_meta.suggestions[]`: a structured list (capped at 5 entries) of next-step candidates.

**Suggestion sources (priority order):**
1. **`alt_spelling`** — D-L-1 candidates from item #14, only candidates that produce a `SuggestionSearcher` hit.
2. **`alt_spelling`** — Top `SuggestionSearcher` partial matches that didn't clear the relevance threshold.
3. **`alt_archive`** — Quick name match against other currently-open ZIM files. Cheap; reuses existing list_zim_files cache.
4. **`broader` / `narrower`** — Stubbed empty list in Phase A. Filled in Phase E (#17 archive presets).

**Existing behavior.** In `compact=True` mode (the default for simple-mode responses), the current markdown recovery hints in [`zim/search.py:352-368`](../../../openzim_mcp/zim/search.py) are replaced by the new footer (which renders the structured suggestions back into prose). The replacement is one-for-one in information content but more model-readable. In `compact=False` mode, the existing recovery prose is preserved unchanged. The `_meta.suggestions[]` field itself is strictly additive in both modes.

### #5 — Token & char metadata

**Touchpoints:** every dict-returning tool function and every prose-returning tool in compact mode.

**Tokenizer.** `tiktoken.get_encoding("cl100k_base")`, lazy-loaded and module-cached in [`openzim_mcp/meta.py`](../../../openzim_mcp/meta.py). Choice rationale: small (~6 MB BPE tables, no model weights), fast (millions of tokens/sec on CPU), broadly applicable (close enough to Anthropic and Llama tokenizers for budget purposes), well-maintained.

**What gets tokenized.** The string the model actually sees:
- For prose-returning tools: the markdown body that ships in the TextContent block.
- For dict-returning tools: a JSON-serialized form of the response without the `_meta` key (avoiding self-reference). 5% pad added to account for envelope cost.

**Failure mode.** If tiktoken initialization fails (rare; sandboxed environments without disk write access for the BPE cache), log a warning at startup and omit `tokens_est` from `_meta` for that session. Other `_meta` fields continue to populate.

### #14 — Damerau-Levenshtein 1 typo fallback

**Touchpoint:** [`openzim_mcp/zim/search.py:1067-1238`](../../../openzim_mcp/zim/search.py) (`find_entry_by_title`).

**Algorithm.**
1. Existing path runs: 5-variant case ladder, then `SuggestionSearcher`. If any result has `score >= 0.7`, return as today.
2. New fallback engages only when (a) no result clears 0.7 AND (b) `len(query) >= FUZZY_TITLE_MIN_QUERY_LEN` (default 4).
3. Generate D-L-1 variants of `query` over alphabet `[a-z0-9 \-]`: insertions, deletions, substitutions, adjacent transpositions. Bounded to ~7 × len(query), deduped, lowercased.
4. Re-run `SuggestionSearcher` for each variant, collect all results.
5. Apply score penalty: `final_score = suggestion_score * FUZZY_TITLE_SCORE_PENALTY` (default 0.85). Ensures exact matches always rank above fuzzy.
6. Return the top result (or top N up to `limit`).

**Cost bound.** ~7 × len(query) variants × 1 ms per `SuggestionSearcher` call → ≤ 30 ms cold path for typical 5–10 char queries. Cached via existing path-mapping cache for repeat misses.

**Edge cases.**
- Query length < 4 → skip fallback (variants would over-match).
- Query already produced a high-confidence match → skip fallback (don't burn cost on the fast path).
- Variant generates an exact title match → still penalized by 0.85 multiplier; the user sees `score: 0.85` instead of `1.0` so they know it was a fuzzy hit.

---

## Configuration

New constants in [`openzim_mcp/defaults.py`](../../../openzim_mcp/defaults.py):

| Constant | Default | Env var | Description |
|---|---|---|---|
| `TABLE_ROW_THRESHOLD` | 8 | `OPENZIM_MCP_CONTENT__TABLE_ROW_THRESHOLD` | Tables with more rows replaced in compact mode. |
| `TABLE_CHAR_THRESHOLD` | 600 | `OPENZIM_MCP_CONTENT__TABLE_CHAR_THRESHOLD` | Tables with more characters replaced in compact mode. |
| `INFOBOX_KV_LIMIT` | 30 | `OPENZIM_MCP_CONTENT__INFOBOX_KV_LIMIT` | Cap on rows extracted per infobox. |
| `STRUCTURED_SUGGESTIONS_LIMIT` | 5 | `OPENZIM_MCP_SEARCH__STRUCTURED_SUGGESTIONS_LIMIT` | Cap on `_meta.suggestions[]` length. |
| `FUZZY_TITLE_MIN_QUERY_LEN` | 4 | `OPENZIM_MCP_SEARCH__FUZZY_TITLE_MIN_QUERY_LEN` | Minimum query length to trigger D-L-1. |
| `FUZZY_TITLE_SCORE_PENALTY` | 0.85 | `OPENZIM_MCP_SEARCH__FUZZY_TITLE_SCORE_PENALTY` | Multiplier on fuzzy-match scores. |
| `META_FOOTER_ENABLED` | true | `OPENZIM_MCP_RESPONSE__META_FOOTER_ENABLED` | Append prose footer in compact mode. |
| `META_TOKENIZER_ENCODING` | "cl100k_base" | `OPENZIM_MCP_RESPONSE__META_TOKENIZER_ENCODING` | tiktoken encoding name. |

All env-var names follow the existing `OPENZIM_MCP_<group>__<name>` pattern.

---

## Error & edge handling

| Scenario | Behavior |
|---|---|
| libzim build lacks `SearchIterator.getSnippet()` | Fall back to lead-paragraph snippets. Log a single warning at server startup. |
| `tiktoken` initialization fails | Log warning at startup; subsequent `_meta` envelopes omit `tokens_est` and include `chars` only. Server stays up. |
| Archive without `.infobox`/`.vcard` markup (Stack Exchange, MedlinePlus) | `extract_infobox` returns empty list; no extraction; behavior unchanged. |
| Article with multiple infoboxes | Phase A extracts only the first matching container. Multi-infobox handling deferred to Phase C #11. |
| Fuzzy fallback over-triggering | Bounded by 0.85 score penalty + `STRUCTURED_SUGGESTIONS_LIMIT` cap. Exact matches always outrank fuzzy. |
| `tokens_est` for very large responses | Tokenizer handles arbitrary length; cost is linear. No special path needed for Phase A. |
| Meta envelope inflating token count | 5% pad in `tokens_est` covers it. Verified in tests. |

---

## Testing

### Unit tests

New test files (matching existing test layout):
- `tests/unit/test_meta.py` — `tokens_est`, `build_meta`, `format_footer`, edge cases (empty, very long, unicode).
- `tests/unit/test_content_processor_infobox.py` — `extract_infobox` against fixture HTML for Wikipedia, Wikiquote, Wikivoyage.
- `tests/unit/test_content_processor_tables.py` — `replace_oversized_tables` threshold behavior, multi-table ordering, attr preservation.
- `tests/unit/test_search_fuzzy.py` — `_fuzzy_title_candidates` correctness, dedup, alphabet coverage; integration test for `find_entry_by_title("Photosythesis")` against fixture archive.

Updated existing tests:
- All `test_search_*.py` files: add assertions for `_meta` shape on returns.
- `test_content_extraction.py`: add assertions for `_meta` on entry returns.
- `test_simple_tools.py`: add assertions for footer format and content.

### Integration tests

Against existing fixture ZIMs in `tests/data/`:
- End-to-end zero-result query → verify `_meta.suggestions[]` is non-empty, `reason` is set, footer prose matches structured form.
- End-to-end article fetch → verify `_meta.tokens_est > 0`, `chars` matches body length within rounding.
- End-to-end fuzzy fallback → "Photosythesis" or another deliberate misspelling resolves to the real article.
- End-to-end infobox extraction → fetch a known-infobox article in compact mode, verify KV list precedes body and table doesn't appear as pipe-soup.

### Golden file regression

Snapshot the compact-mode output of `tell_me_about` for 5 fixture articles spanning archive types (Wikipedia article with infobox, Wiktionary entry, Stack Exchange Q&A, simple article without tables, article with multiple large tables). Captured at the start of Phase A; tests fail on diff to catch unintended drift.

### Performance budget

| Operation | Budget |
|---|---|
| `tokens_est` per call | ≤ 5 ms after first call |
| Fuzzy fallback per cold miss | ≤ 30 ms |
| Infobox extraction per article | ≤ 10 ms |
| Table replacement per article | ≤ 5 ms |

Asserted in `tests/perf/` (extends existing benchmark harness if present, else introduces a minimal pytest-benchmark setup).

---

## Acceptance criteria

Phase A is shippable as `v2.0.0a1` when all of:

1. All five items (#1, #2, #4, #5, #14) implemented per this spec.
2. Full unit + integration test suite passing on supported Python versions (3.12, 3.13).
3. Golden file regression suite captured and passing.
4. Performance budgets met or exceeded.
5. README updated with new `_meta` schema, footer format, infobox/table behavior, and fuzzy fallback documentation.
6. `tiktoken>=0.7.0` added to core dependencies and reflected in `uv.lock`.
7. CHANGELOG entry under `## [2.0.0a1]` documenting all five items.
8. No tool signature changed; no tool removed; `compact=False` output byte-identical to v1.2.0 on the golden fixtures.

---

## Release plan

- Branch: `v2-phase-a` off `main`.
- One PR per item (5 PRs) targeting the `v2-phase-a` branch, not `main`.
- Merge order, driven by real dependencies:
  1. **#5** (`_meta` plumbing) first — foundation. Other items consume the envelope and helpers.
  2. **#1** (native snippets) and **#2** (tables/infoboxes) next, in parallel — both independent of #5 in principle but ship cleanly on top of it; either order is fine.
  3. **#14** (typo fallback) — depends on #5 for the `_meta` envelope on `find_entry_by_title` returns, and produces the `alt_spelling` candidates that #4 consumes.
  4. **#4** (structured suggestions) last — depends on both #5 (envelope) and #14 (candidate source).
- After all 5 PRs merge, a single `v2-phase-a` → `main` PR for final review and tag.
- Tag: `v2.0.0a1`. Pre-release on PyPI; not promoted to "latest."
- v1.x branches receive no Phase A backports.

---

## Forward references

- `_meta.suggestions[]` includes a slot for `broader`/`narrower` types that Phase E (#17 archive presets) will populate. Phase A leaves this list empty for those types.
- The `_meta` envelope shape may be canonicalized in Phase B (#3 pagination contract, #13 structuredContent migration). Phase A adds it additively; Phase B may reorganize.
- Multi-infobox extraction deferred to Phase C #11 (precomputed section index).
- Cross-archive `alt_archive` suggestions in Phase A use a basename match; Phase D (#8 query rewriting) may improve relevance scoring across archives.
