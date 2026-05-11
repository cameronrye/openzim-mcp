# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0a8] — 2026-05-11 (alpha pre-release)

Re-cut of v2.0.0a7 — the v2.0.0a7 tag exists but its GitHub Release
failed to publish because `pip-audit` surfaced two upstream urllib3
CVEs (CVE-2026-44431 / 44432) that landed in the audit database
between the v2.0.0a6 and v2.0.0a7 builds. v2.0.0a8 carries the same
v2.0.0a7 content plus the urllib3 → 2.7.0 bump that closes the CVEs.
Also adjusts `make security` to pass `--skip-editable` so pip-audit
doesn't fail looking for the local package on PyPI mid-release.

Defect + opportunity batch on top of v2.0.0a6, found by end-to-end
testing against a real Wikipedia ZIM (118 GB, 27.2M entries,
Feb 2026 snapshot). 14 defects fixed, 8 opportunities added.
1388 tests pass (+13 from new test modules); no regressions.

### Fixed — Phase A (snippets, infobox, typo fallback)

- **#14: `_typo_variants` now reaches `"Photosythesis"` → `"Photosynthesis"`.**
  v2.0.0a4 shipped only transposition + deletion edits — mathematically
  unable to recover the missing `'n'` (insertion). Added insertion +
  substitution against the full a-z alphabet, length-gated at ≥ 5 chars
  to bound cost (~700 variants for a 13-char input; ≤ 10 ms/call).
- **#1: snippet highlighter no longer produces malformed markdown.**
  `_highlight_terms` previously wrapped query terms verbatim, producing
  `**Artificial **photosynthesis****`, `_****Berlin****_`, and
  `[**Photosynthesis**](**Photosynthesis** "**Photosynthesis**")` when
  the match landed inside existing bold / italic / link constructs.
  Added a skip regex covering paired emphasis runs and full
  `[text](href "tooltip")` link constructs (deliberately not bare
  parens, so prose like `(also called assimilation)` keeps its
  highlighting).
- **#1: snippet fallback to stem-prefix substring match.** When no
  whole-word match existed, the snippet used to drop to the lead
  paragraph. Now it falls back to a stem-prefix substring (first ⅔ of
  the query term) so `"photosynthesis"` catches paragraphs mentioning
  `"photosynthetic"` instead of returning the article's unrelated lead.
- **Op1: snippets drop the duplicate `# <Title>` H1.** `create_snippet`
  accepts an optional `title=`; `_get_entry_snippet` forwards the
  entry title so the heading that already appears in the result row
  doesn't burn 5–15 tokens per result.
- **#2 / Op5: infobox extraction tracks parent-section context.**
  `extract_infobox` now prefixes labels with their parent
  `<th colspan>` heading row, so a Berlin infobox renders
  `Area — City/State` / `Population — City/State` instead of three
  identical `City/State` rows. Also skips rows whose nearest table
  ancestor isn't the infobox (handles nested chronology / coords
  microformats) and rejects `<th>` / `<td>` candidates borrowed from
  inside nested tables.
- **Op6: strip image-caption / hatnote / sidebar / navbox / inline
  citation noise.** `UNWANTED_HTML_SELECTORS` now drops `figure`,
  `figcaption`, `.thumb`, `.thumbcaption`, `.gallery`, `.hatnote`,
  `.sidebar`, `.navbox`, `.metadata.mbox-small`, `sup.reference`,
  `.reference`, `.mw-collapsible-toggle`, and the `.geo-*` coordinate
  microformats. Article leads now start with the actual prose, not
  `Schematic of … For other uses, see X (disambiguation). Part of a
  series on … 52°31'07"N 13°24'16"E …`.

### Fixed — Phase B (response contract)

- **#3 / Op8: `zim_query` accepts a `cursor` parameter.** Tools advertised
  opaque base64 cursors in their responses, but the simple-mode
  `zim_query` tool only took an integer `offset` — the cursors were
  decorative. Now decoded; `s.o` populates `options["offset"]` and the
  per-tool state is preserved. Length-capped at 2 KB
  defense-in-depth.

### Fixed — Phase C (primitives)

- **#9 / #7: `get_section` table rendering now matches `get_zim_entry`.**
  The bundle's `rendered_markdown` was built with `compact=False` while
  `get_zim_entry` rendered with `compact=True`. Result: `get_section
  "Geography"` returned pipe-soup tables while the surrounding article
  fetch path showed `[Table N: M rows x P cols - pass compact=False to
  expand]` placeholders. Bundle and search-snippet rendering paths now
  both apply `compact=True`, so the markdown is consistent everywhere.
- **#10 / D8: synthesize attribution carries the `#section_id` suffix.**
  `_locate_passage` couldn't find passages containing `**bold**`
  highlight markers inside the bundle's plain markdown — every citation
  fell back to entry-level (`section_id: null`). Now strips `**`
  markers before locating so attribution resolves correctly.
- **#10 / D5: synthesize strips natural-language interrogative prefix.**
  `synthesize=True` with `"tell me about Berlin"` previously fed the
  entire phrase to BM25 — returning Irving Berlin songs, Nat King Cole
  albums, and a graffiti article instead of the canonical Berlin
  entry. Intent-parses first, hands only the topic to the search
  stage; preserves the original query for response echo.
- **#10 / D8 / Op4: response dedupe + link-strip in compact mode.**
  `passages[].text_markdown` previously duplicated `answer_markdown`
  verbatim (~50% token bloat on every synthesize call). In compact
  mode, passages now omit the body text. Wikipedia link-soup
  (`[text](href "tooltip")`) is also stripped from passages — small
  models can't follow inline links from inside tool responses anyway.
- **Op3: `get_section` supports narrow scoping.** New
  `include_subsections=False` parameter on `get_section_data` (and the
  `narrow section X of Y` / `just section X of Y` query syntax in
  simple mode) ends the slice at the next heading of any level, so a
  caller can fetch just the H2 lead paragraphs without the cascading
  H3 sub-tree.
- **Op2: compact structure response carries per-heading summaries.**
  The 80-char `summary` field is derived from each section's body
  preview so a small model can choose which section to drill into,
  not just see which exist.

### Fixed — namespace / metadata / `tell me about`

- **D2: `browse namespace C` no longer crashes on new-scheme archives.**
  Legacy code built a full 27 M-entry list before slicing 50 rows out
  of it — slow, memory-hostile, and triggered "session expired" errors
  on real Wikipedia archives. New `_browse_new_scheme_c_paginated`
  pages directly through the entry-id range.
- **D3: `browse namespace W` returns the actual W entries.** New-scheme
  archives keep W off libzim's iterable surface, but the well-known
  paths (`W/mainPage`, `W/favicon`, ...) are reachable via
  `has_entry_by_path`. New `_browse_new_scheme_w_paginated` probes
  them so the response matches `list_namespaces`' count.
- **D11: metadata previews cap at 800 chars.** Wikipedia ZIMs store
  `M/Title` as a full HTML document (~1 MB) rather than the bare title
  string. The `metadata for <archive>` call previously returned 980 KB,
  starving every other metadata field. Each entry is now capped with
  a `[truncated, N chars total]` marker.
- **D6 / Op7: `tell me about <topic>` auto-fetches on title-index hit.**
  When the top BM25 result wasn't a strong-title match (Xapian ranked
  `List of songs about Berlin` above the canonical `Berlin` article),
  the response used to render the search list. Now falls back to
  `find_entry_by_title_data`; promotes any score-1.0 result past the
  BM25 ranking and inlines the article body.

### CI / quality

- **3 new test modules, 47 additional assertions** covering each fix:
  `test_typo_variants_v2a7.py`, `test_content_processor_fixes_v2a7.py`,
  `test_v2a7_fixes_helpers.py`. End-to-end proof that `"Photosythesis"`
  resolves through the full call path (mock archive + suggester); perf
  guard against quadratic regressions in `_typo_variants`; cursor
  garbage-rejection; metadata cap on both long and short values.
- **Goldens regenerated** (all strict improvements): pipe-soup infobox
  snippet → clean lead-paragraph snippet for Einstein; H1 dedup +
  section attribution on the Berlin / Munich synthesize fixtures.
- **Test infra**: explicit `encoding="utf-8"` on golden read/write so
  non-ASCII characters in goldens survive Windows runners.
- **SonarCloud quality gate**: factored shared test setup
  (`_make_simple_handler`, `_build_metadata_mock_archive`,
  `_wire_typo_fallback_archive`) and namespace browse-payload shape
  (`_new_scheme_browse_payload`, `_materialise_paths`) so new-code
  duplication stays under 3%.

## [2.0.0a6] — 2026-05-11 (alpha pre-release)

Bugfix-only follow-up to v2.0.0a4 after a two-pass review of the
shipped Phase A/B/C surface. 13 defects fixed; no new tools, no
wire-format breaks. Existing tests stay green (1344 passed) and a few
new tests pin down the corrected behaviour.

### Fixed — Phase A (`_meta` envelope, snippets, fuzzy fallback)

- **`format_footer` recovery branch now covers every empty-result `reason`.**
  Responses carrying `reason="no_xapian_index"` or `"bad_namespace"`
  previously fell through to the success branch and emitted a useless
  "~0 tokens" footer. They now render archive-shaped recovery hints
  ("No full-text index on this archive. Try `find_entry_by_title` or
  `browse_namespace`." / "Unknown namespace. Try `list_namespaces`…").
- **`create_snippet` no longer slices `**term**` mid-tag.** When the
  highlighted snippet exceeded `snippet_length` and the second
  truncation landed inside a bold marker, the result was a runaway-bold
  fragment (`…**ter`). The truncation now detects an unpaired trailing
  `**` and strips the dangling segment before appending `...`.
- **Spec §14.4: surface `alt_spelling` suggestions when a fuzzy hit
  is returned.** `find_entry_by_title_data` now adds the resolved
  typo-corrected title to `_meta.suggestions[]` so callers can see
  *which* correction the server applied and decide whether to accept
  it. Previously suggestions only appeared when zero results were
  found.
- **`tokens_est` is now omitted from `_meta` when the tokenizer is
  unavailable** (spec §5). Callers can distinguish "tokenizer
  unavailable" from "zero-token response". `format_footer` falls back
  to char-count when the field is absent.

### Fixed — Phase B (cursor)

- **`CursorPayload.v` comment refreshed.** The inline comment said
  "currently 1" while `CURRENT_VERSION = 2`; replaced with a stable
  reference to the module constant so it can't drift again.

### Fixed — Phase C (bundle, get_section, synthesize)

- **`_locate_passage` whitespace-run offset mapping.** The
  normalized→original-offset walk could exit pointing inside a
  whitespace run that `md_norm` had collapsed to one space, attributing
  citations to the prior section when two section boundaries sat
  either side of the run. The mapper now advances past any remaining
  whitespace so the returned offset always lands on the first
  non-space character of the match.
- **`get_section` truncation surfaces `_meta.total_chars`.** Truncation
  set `_meta.truncated=True` but omitted the source-length context.
  Callers now see how much of the section was elided. `more_at_offset`
  remains absent because `get_section` truncation is not resumable.
- **`archive_by_name` collision on duplicate `.stem`.** Two ZIMs with
  the same filename in different directories (`en/wiki.zim` and
  `fr/wiki.zim`) silently overwrote each other in synthesize's
  archive-lookup dict, causing the bundle for the first archive's hit
  to be fetched from the second archive — i.e., citation poisoning.
  Duplicate stems are now detected at archive enumeration and
  disambiguated with a `~N` suffix (`wiki`, `wiki~2`) with a warning
  log. Single-archive synthesise is unaffected.
- **`get_entry_summary(compact=True)` no longer ignores the `compact`
  flag.** The Phase C bundle migration silently routed compact
  callers through `bundle["rendered_markdown"]`, which is rendered
  with `compact=False` (pipe-soup tables, no oversized-table
  placeholders). Compact requests now bypass the bundle and re-render
  through `_extract_html_summary(compact=True)` so Phase A #2's table
  trimming applies. `compact=False` (the default) still benefits from
  the bundle's shared HTML parse.
- **Cache keys for `path_mapping:`, `binary_meta:`, and `ns_entries:`
  now include an `<mtime_ns>:<size>` invalidation token.** Atomic ZIM
  file replacement (the typical monthly Wikipedia refresh) previously
  left stale resolved paths, binary metadata, and namespace listings
  in cache until LRU eviction. The bundle cache already did this; the
  helper has been extracted to `bundle.archive_stat_token()` and
  applied across all four.
- **`synthesize._extract_passages` no longer double-renders the
  snippet through `html_to_plain_text`.** `search_top_k` already
  returns plain-markdown snippets via `create_snippet`; the
  BeautifulSoup→html2text round-trip risked mangling `**bold**`
  highlight markers. Trust the upstream pipeline; a regression test
  pins the behaviour.

### Test suite

- 1344 passed, 50 skipped (one more than the v2.0.0a4 baseline; added
  `test_extract_passages_preserves_bold_highlight_markers`).
- Updated `test_zim_operations.py` and `test_content_tools.py` cache-key
  assertions for the new stat-token format.
- Updated `test_synthesize.py` to drop the `content_processor` arg
  from `_extract_passages` and use plain-markdown snippet fixtures.

## [2.0.0a4] — 2026-05-10 (alpha pre-release)

v2 Phase C, part 2: completes the retrieval-primitives phase. Adds the
`get_section` tool (#7) and the `zim_query(synthesize=True)` mode (#10)
on top of the EntryBundle infrastructure that shipped in v2.0.0a3.
**No wire-format breaks** — both new surfaces are additive.

### #7 — New tool `get_section`

```
get_section(zim_file_path, entry_path, section_id, *, max_chars=None)
  → Union[GetSectionResponse, ToolErrorPayload]
```

Returns a single section's body (~500-1500 tokens — small-model sweet
spot per parent-document-retrieval research) plus full metadata.
`section_id` values come from `get_table_of_contents`
(`TocHeading.section_id`). On miss, returns
`tool_error("section_not_found", extras={"available_section_ids": [...]
})` so the model can self-correct.

The data layer slices `EntryBundle.rendered_markdown[char_start:char_end]`
where the bundle's section ranges include subsections (a parent heading's
`char_end` extends to the next heading at the same or higher level).
Parent sections therefore return the full subtree body. `max_chars`
truncates the body and sets `truncated=True` plus `_meta.truncated=True`
in the envelope for budget-aware clients.

### #10 — New `zim_query(synthesize=True)` mode

```python
{
    "query": str,
    "answer_markdown": str,        # passages + inline [cite: ...] markers
    "passages": list[SynthesizePassage],
    "citations": list[Citation],
    "archives_searched": list[str],
    "fallback_used": Literal["xapian_score", "rrf_fusion", "reranker"],
    "total_chars": int,
    "total_words": int,
    "_meta": MetaEnvelope,
}
```

Pure retrieval + concatenation; no LLM generation. The seven-stage
pipeline (in `openzim_mcp/synthesize.py`):

1. **Per-archive search** — Xapian top-K hits (`search_top_k` helper
   on `ZimOperations`).
2. **RRF fusion** — Reciprocal Rank Fusion (k=60) when multiple archives
   are searched; identity passthrough for single-archive
   (`fallback_used="xapian_score"` vs `"rrf_fusion"`).
3. **Identity rerank** — placeholder for Phase D's cross-encoder.
4. **Passage extraction** — libzim snippets rendered to markdown.
5. **Section attribution** — best-effort lookup via `EntryBundle`;
   passages get `cite_id = "{archive}/{entry_path}#{section_id}"`
   when the snippet text is found in a section's char range. Bundle
   build failures keep the cite_id at entry level.
6. **Budget enforcement** — `output_char_budget` truncates the last
   passage; subsequent passages are dropped.
7. **Render + citations** — passages joined with `\n\n` and inline
   `[cite: ...]` markers; structured `Citation` list deduplicated by
   `cite_id`.

Zero hits returns an empty response with `_meta.reason="0_hits"`.

### Other

- Extended `tool_error()` with an `extras: Optional[Dict[str, Any]]`
  kwarg so error payloads can carry self-correction hints (e.g. the
  `available_section_ids` list above) without `# type: ignore` at
  call sites.
- New tests: `tests/test_get_section.py` (4),
  `tests/test_synthesize.py` (~20 unit + 3 end-to-end),
  `tests/test_golden_v2_phase_c.py` (3 `get_section` + 3 `synthesize`
  snapshots, deterministic via the new `v2_phase_c_zim` heading-rich
  fixture). `test_response_contract` exempts both new tools from the
  list-pagination contract while still asserting `_meta` is present.
- The Phase A `_meta` envelope continues to attach on every response.
  `_meta.truncated` is now correctly forwarded by `get_section_data`
  on truncation (was a hidden gap in earlier scaffolding).

## [2.0.0a3] — 2026-05-10 (alpha pre-release)

v2 Phase C, part 1: EntryBundle infrastructure and the four-tool collapse.
**One wire-format break** (TOC heading field rename). Phase C's other two
items — #7 `get_section` and #10 `synthesize` mode — are deferred to a
later alpha; their TypedDicts ship in this release as forward-declared
contract surface.

### #11 EntryBundle (internal — collapses four tools)

First touch of an entry runs ONE HTML parse → produces a single
`EntryBundle` value cached at `bundle:v2c:{validated_path}:{entry_path}`.
The four content-shape tools `get_entry_summary`, `get_table_of_contents`,
`get_article_structure`, and `extract_article_links` collapse from
independent HTML re-parsers to thin slicers over the bundle. First touch
parses HTML once; subsequent calls (across all four tools, in any order)
hit the bundle cache.

Removed legacy per-tool cache prefixes: `summary_data:`, `toc_data:`,
`structure_data:`, `links_full:v2b:`. Wire formats unchanged for
`get_entry_summary`, `get_article_structure`, `extract_article_links`.

### Breaking — `get_table_of_contents`

| Field | Before | After |
|---|---|---|
| TOC heading identifier | `heading["id"]` | `heading["section_id"]` |
| TOC list element type | `dict[str, Any]` | `TocHeading` TypedDict |

The value is unchanged (still `resolve_heading_id()`'s output with slug
fallback). The new field name is what `get_section(section_id=...)` will
consume in the next alpha. The old `id_source` field is dropped
(debugging-only, not a contract surface).

### Forward-declared TypedDicts (no behavior yet)

The following TypedDicts ship in `openzim_mcp/tool_schemas.py` as part of
this release so a4's implementation tasks don't have to re-litigate the
contract surface. They aren't returned by any tool yet.

- `GetSectionResponse` — for #7 `get_section` (a4)
- `SynthesizeResponse`, `Citation`, `SynthesizePassage` — for #10
  synthesize mode on `zim_query` (a4)
- `EntryBundle`, `SectionMeta`, `InfoboxField`, `InfoboxData`,
  `LinkBuckets` — bundle internals (already used by the four-tool collapse)
- `TocHeading` — already used (wire format)

### Configuration

`OpenZimMcpConfig.synthesize` block added with defaults `top_n=5`,
`per_archive_k=10`, `output_char_budget=4800`. Inert until `synthesize`
mode ships.

### Other

- New module: `openzim_mcp/bundle.py` — `extract_entry_bundle`,
  `get_or_build_bundle`.
- New tests: `tests/test_bundle.py` (15 tests covering bundle
  determinism, parent/child range nesting, eviction-rebuild identity).
- Cross-tool shared-bundle assertion in `tests/test_structured_tool_output.py`
  guards the "one parse per entry across all four tools" invariant.
- Housekeeping: removed stale `[[tool.mypy.overrides]] module = ['libzim']`
  from `pyproject.toml`. Added GitHub labels `v2`, `v2-phase-a/b/c`;
  applied `v2`/`v2-phase-b` retroactively to PR #111.

### Deferred to a later alpha

- **#7 `get_section`** — section-level retrieval by `section_id`. The
  `GetSectionResponse` TypedDict ships now; the data layer and tool
  registration land in a4.
- **#10 `synthesize`** — `zim_query(synthesize=True)` mode. The
  `SynthesizeResponse`/`Citation`/`SynthesizePassage` TypedDicts and
  `SynthesizeConfig` ship now; the pipeline (`openzim_mcp/synthesize.py`,
  per-archive search, RRF fusion, passage extraction, section attribution,
  citation rendering, budget enforcement) lands in a4.

## [2.0.0a2] — 2026-05-09 (alpha pre-release)

v2 Phase B: response-contract migration. **Wire-format break** for every
list-returning tool. v1.x users upgrading must update response-shape parsing.
See [docs/superpowers/specs/2026-05-08-v2-phase-b-response-contract-design.md](docs/superpowers/specs/2026-05-08-v2-phase-b-response-contract-design.md)
for the full design.

### Breaking — pagination contract

Every list-returning tool now returns the same five contract keys:
`results`, `next_cursor`, `total`, `done`, `page_info`.

| Tool | What changed |
|---|---|
| `search_zim_file` | `total_results` → `total`; `pagination` block flattened; `next_cursor` at top level; `cursor` accepted as input |
| `search_all` | `per_file` → `results`; per-archive blocks each carry the new contract via `result` field; cursor lives only at the per-archive level |
| `search_with_filters` | now returns structured dict (was markdown); same shape as `search_zim_file` plus `namespace_filter`/`content_type_filter` |
| `find_entry_by_title` | gets the contract; `done=true`, `total=len(results)` always |
| `get_search_suggestions` | `suggestions` → `results`; `count` removed |
| `browse_namespace` | `entries` → `results`; `total_in_namespace` → `total`; `total_in_namespace_is_lower_bound` → `page_info.total_is_lower_bound`; `has_more` removed |
| `walk_namespace` | `cursor` input/output type changes from `int` to opaque `str`; `entries` → `results`; `total` is always `null`; `total_entries` deprecated alias removed |
| `list_namespaces` | `namespaces[<letter>].entry_count` → `total`; payload at top level (no `result` wrapper) |
| `extract_article_links` | **`kind` is now required (default `"internal"`)**; single category per call; `internal_links`/`external_links`/`media_links` parallel arrays removed; `category_totals: {internal, external, media}` added |
| `list_zim_files` | `files` → `results`; `count` → `total` |
| `get_related_articles` | `outbound_results` → `results`; anticipates Phase E inbound-link feature |
| `get_zim_entries` (batch) | gets the contract; `done=true`, `total=len(results)` |

### Breaking — TypedDict everywhere

Every dict-returning tool migrated from `Dict[str, Any]` to a per-tool
TypedDict. FastMCP now emits payloads at the top level of `structuredContent`
with real schemas. FastMCP continues to wrap `Union[<Response>, ToolErrorPayload]` returns in a `{"result": ...}` envelope at the wire level (this is FastMCP's behavior for any `Union` return type with multiple non-None members). Clients that previously parsed `structuredContent.result` keep working. The TypedDict change ensures the inner payload now carries a real schema instead of `Dict[str, Any]`.

Migrated tools (TypedDict-only, no contract): `get_zim_metadata`,
`get_zim_entry`, `get_main_page`, `get_entry_summary`,
`get_table_of_contents`, `get_article_structure`, `get_binary_entry`.

### Cursor format

Cursors are URL-safe base64 JSON: `{v: 2, t: <tool_name>, s: <state>}`.
**Tool-bound** — a search cursor passed to browse raises a clear error.
**Versioned** — adding new fields later doesn't break the wire format.
**Archive-bound** — cursors for archive-specific tools carry `s.ai` (a
short SHA-256 token of the validated archive path); resubmitting a
cursor against a different archive is rejected. v=1 cursors are
rejected so callers re-fetch rather than silently follow stale state.

### Compat shim removed

`openzim_mcp.zim.archive.PaginationCursor` (the v1 cursor class) is removed.
Use `openzim_mcp.pagination.Cursor` instead.

### Other

- New module: `openzim_mcp/pagination.py` — `Cursor.encode/decode`, `CursorMismatchError`.
- New module: `openzim_mcp/tool_schemas.py` — every per-tool response TypedDict.
- New tests: `tests/test_pagination_cursor.py`, `tests/test_response_contract.py`, `tests/test_golden_v2_phase_b.py`.
- The Phase A `_meta` envelope is unchanged in shape and still populates on every response.

## [2.0.0a1] — 2026-05-08

> First v2 pre-release. Phase A of the multi-phase v2 effort. All changes additive at the tool-signature layer; small compact-mode prose change for empty search results (see Changed below).

### Added

* **meta:** every dict-returning tool now includes a `_meta` envelope (`tokens_est`, `chars`, `truncated`, `more_at_offset`, `total_chars`, `suggestions`, `reason`). `tokens_est` uses tiktoken `cl100k_base` with a 5% pad. (#5)
* **simple:** compact-mode responses gain a one-line markdown blockquote footer (`> ~4.2K tokens · ...`). Set `OPENZIM_MCP_META__FOOTER_ENABLED=false` to suppress. (#5)
* **content:** in compact mode, `.infobox` / `.vcard` tables emit a Markdown KV list prepended to the body. (#2)
* **content:** in compact mode, tables exceeding row or character thresholds are replaced with `[Table N: ...]` placeholders. (#2)
* **search:** every search response is query-aware — snippets contain the actual matched passage (with `**bold**` highlights, capped at 5 hits) rather than the article lead. (#1)
* **search:** `_meta.suggestions[]` surfaces typo variants (`alt_spelling`) and other-archive candidates (`alt_archive`) for empty / low-confidence searches. (#4)
* **search:** `find_entry_by_title` fuzzy fallback now triggers whenever no result clears 0.7 (previously only on zero hits). Score and length-gate are configurable via `OPENZIM_MCP_SEARCH__FUZZY_TITLE_*`. (#14)

### Changed

* **simple:** compact-mode empty-result prose now renders via the new footer + structured suggestions instead of the v1.2.0 paragraph. The information is one-for-one; the format is more model-readable. `compact=False` paths retain byte-identical v1.2.0 behavior. (#4)
* **search:** `find_entry_by_title` typo-corrected hits now score `0.85` (was hardcoded `0.7`) by default. (#14)

### Dependencies

* Added `tiktoken>=0.7.0` to core dependencies.

## [1.3.0](https://github.com/cameronrye/openzim-mcp/compare/v1.2.0...v1.3.0) (2026-05-08)


### Features

* v1.2.0 follow-up — refinements + production-readiness improvements ([#106](https://github.com/cameronrye/openzim-mcp/issues/106)) ([e9396ec](https://github.com/cameronrye/openzim-mcp/commit/e9396ec699a62d4b0ec990d1a155b0ae7ddb73dd))

## [1.2.0](https://github.com/cameronrye/openzim-mcp/compare/v1.1.2...v1.2.0) (2026-05-06)


### Features

* **http:** operator-acknowledged auth bypass + rate-limit env-var docs ([#104](https://github.com/cameronrye/openzim-mcp/issues/104)) ([7294b1d](https://github.com/cameronrye/openzim-mcp/commit/7294b1d33dfa40a8e07c7ba67c062cc2d3c741c7))
* v1.2.0 simple-mode tool ergonomics — tell_me_about, bigger snippets, compact pagination ([#103](https://github.com/cameronrye/openzim-mcp/issues/103)) ([212a60a](https://github.com/cameronrye/openzim-mcp/commit/212a60afd7c1e66bd573605925ccbb06261ed27c))

## [1.1.2](https://github.com/cameronrye/openzim-mcp/compare/v1.1.1...v1.1.2) (2026-05-05)


### Bug Fixes

* **server:** mirror cors_origins into SDK transport allowed_origins ([#100](https://github.com/cameronrye/openzim-mcp/issues/100)) ([96001d1](https://github.com/cameronrye/openzim-mcp/commit/96001d1365933cd948027e6291c34d26234792fe))

## [1.1.1](https://github.com/cameronrye/openzim-mcp/compare/v1.1.0...v1.1.1) (2026-05-05)


### Bug Fixes

* walk_namespace, related-articles, and confidence beta-refinement fixes ([#98](https://github.com/cameronrye/openzim-mcp/issues/98)) ([912d346](https://github.com/cameronrye/openzim-mcp/commit/912d34607220d2a3f7b61d0f39cff918d23c3f99))

## [1.1.0](https://github.com/cameronrye/openzim-mcp/compare/v1.0.1...v1.1.0) (2026-05-05)


### Features

* tool responses use MCP structured content (no more double-stringified JSON) ([#96](https://github.com/cameronrye/openzim-mcp/issues/96)) ([5b541ec](https://github.com/cameronrye/openzim-mcp/commit/5b541ec616386128e6a9d105f07c27bc94676265))


### Bug Fixes

* **http:** allow MCP-Protocol-Version header and DELETE method in CORS ([#93](https://github.com/cameronrye/openzim-mcp/issues/93)) ([dbb791e](https://github.com/cameronrye/openzim-mcp/commit/dbb791e5a6b90a229283ee0a6a283615deae6e42))
* namespace, pagination, resources, and find-by-title beta-test fixes ([#92](https://github.com/cameronrye/openzim-mcp/issues/92)) ([4b572ef](https://github.com/cameronrye/openzim-mcp/commit/4b572efa9acdec84551163e0170c3e6569c28151))
* **server:** make simple mode actually expose only zim_query ([#94](https://github.com/cameronrye/openzim-mcp/issues/94)) ([92c725f](https://github.com/cameronrye/openzim-mcp/commit/92c725f0cffd43f592185c0f2173f4c6ca0ef1e4))

## [1.0.1](https://github.com/cameronrye/openzim-mcp/compare/v1.0.0...v1.0.1) (2026-05-04)


### Bug Fixes

* **http:** allow operator-configured Host allowlist ([#90](https://github.com/cameronrye/openzim-mcp/issues/90)) ([c4dad8a](https://github.com/cameronrye/openzim-mcp/commit/c4dad8a4eb0147178ca268403d85f90530290fe4))

## [1.0.0](https://github.com/cameronrye/openzim-mcp/compare/v0.9.0...v1.0.0) (2026-05-03)

Includes an end-to-end review pass before tagging — security hardening, correctness fixes, performance work, and a refactor that splits `zim_operations.py` into a `zim/` package via mixin classes. See sections below.

### Features

* **http:** streamable HTTP transport with bearer-token auth, CORS allow-list, and `/healthz`/`/readyz` endpoints
* **http:** safe-default startup check refuses to bind a non-localhost host without an auth token
* **transport:** legacy SSE transport (`--transport sse`) for clients that haven't migrated to streamable-HTTP; bound to localhost only, no auth/CORS middleware
* **docker:** multi-stage, multi-arch (`linux/amd64`, `linux/arm64`) image published to `ghcr.io/cameronrye/openzim-mcp`, runs as non-root with a built-in health check
* **content:** `get_zim_entries` batch tool — fetch up to 50 entries in one call, with per-entry success/error reporting
* **resources:** per-entry `zim://{name}/entry/{path}` resource serves entries with their native MIME type (clients must URL-encode `/` as `%2F` in the path segment)
* **subscriptions:** clients can subscribe to `zim://files` and `zim://{name}`; mtime-polling watcher emits `notifications/resources/updated` when allowed directories or `.zim` files change
* **search:** opaque `cursor` parameter on `search_zim_file` for resumable pagination
* **simple:** intent pattern routes batch retrieval queries to `get_zim_entries`

### Improvements

* **content:** `get_related_articles` resolves relative hrefs against the source entry's directory and detects the content namespace correctly on domain-scheme archives (previously returned nothing)
* **content:** suggestion fallback uses `SuggestionSearcher(archive).suggest(text)` (the prior `archive.suggest()` call did not exist)
* **tools:** `list_zim_files` accepts a case-insensitive `name_filter` substring argument; one shared cache slot regardless of filter value
* **content:** `get_zim_entries` accepts bare entry-path strings paired with a `zim_file_path` default (dicts still work for multi-archive batches)
* **content:** heading-id resolution falls through `id` → mw-headline anchor → preceding `<a name="">` → slug, returning `(id, source)` so consumers can distinguish real anchors from synthetic slugs
* **content:** summary extraction skips USWDS banners and skip-nav blocks above the first `<h1>` (MedlinePlus / NIH / NIST style sites)
* **content:** link extraction drops non-navigable schemes (`javascript:`, `mailto:`, `tel:`, `data:`, `blob:`, `vbscript:`)
* **server:** `__version__` reads from `importlib.metadata`; `serverInfo.version` reports openzim-mcp's actual version (no longer the FastMCP SDK default)

### Removed

* **tools:** advanced-mode tool surface drops 27 → 21. Removed: `warm_cache`, `cache_stats`, `cache_clear`, `get_random_entry`, `diagnose_server_state`, `resolve_server_conflicts`. The cache itself remains; the explicit management tools were dropped.
* **instance:** multi-instance conflict tracking removed; `instance_tracker.py` deleted. HTTP server instances coexist freely.

### Bug Fixes

* **content:** sanitize per-entry paths in `get_zim_entries` and expand test coverage
* **resources:** per-entry `zim://` returns libzim's native MIME type
* **http:** start subscription watcher via wrapped lifespan
* **instance:** relax conflict logic for HTTP transport so multiple HTTP server instances can coexist

### Security

* **errors:** redact absolute paths from MCP error responses (rejected traversals previously leaked the canonical allowed-directory layout)
* **errors:** regex-based path redaction with cross-platform separator handling and tightened lookbehind so wrapped/quoted paths (`(/opt/foo)`, `"/opt/bar"`) no longer slip through
* **diagnostics:** redact filesystem paths and PIDs in `get_server_health` / `get_server_configuration` responses (no longer transport-gated; always redacted)
* **resources:** sanitize URI-decoded entry paths before passing to libzim
* **search:** always sanitize `zim_file_path` in `find_entry_by_title` (previously skipped when `cross_file=True`)
* **prompts:** strip control characters and cap user-supplied arguments before interpolating into MCP prompt bodies; re-check empty after sanitization to avoid empty `('', ...)` tool calls
* **http:** require auth on `OPTIONS /mcp` (the unconditional preflight bypass let unauthenticated callers probe the endpoint)
* **http:** resolve `localhost` before classifying as loopback; warn and fall through to the public-host path when `/etc/hosts` maps it elsewhere
* **rate-limit:** make global + per-operation acquire atomic; concurrent callers no longer transiently over-consume the global bucket
* **rate-limit:** per-client buckets with LRU eviction (10k cap) — infrastructure ready for HTTP context wiring

### Correctness

* **search:** reject mismatched `cursor` and `query` arguments instead of silently applying the cursor's offsets to a different query
* **cache:** stop caching error sentinels and zero-result responses (previously a transient libzim error or index warmup poisoned the cache for the full TTL); audit follow-up extends the gate to `get_search_suggestions`, `get_entry_summary`, `get_table_of_contents`
* **cache:** treat empty-string cache values as hits, not misses
* **content:** resolve redirects to their target before rendering; cache the resolved path so subsequent lookups skip the chain; reject redirect cycles and chains deeper than `MAX_REDIRECT_DEPTH = 10`
* **content:** instantiate `html2text.HTML2Text` per call to eliminate a shared-state race that corrupted concurrent conversions
* **content:** preserve Unicode in heading slugs (Arabic, Chinese, Cyrillic, Japanese ZIMs no longer produce empty TOC anchors); disambiguate duplicate heading slugs with `_2`, `_3` suffixes
* **content:** drop trailing punctuation from path tokens extracted by the simple-tools `get_zim_entries` parser
* **simple-tools:** dispatch the `get_zim_entries` intent (was silently falling through to `search_zim_file`); honor explicit `zim_file_path` for `walk_namespace`, `find_by_title`, and `related` intents
* **subscriptions:** detect same-size ZIM replacements via mtime change (size-only detection silently missed identical-size replacements)
* **validation:** `browse_namespace` and `walk_namespace` parameter checks now raise `OpenZimMcpValidationError` instead of `OpenZimMcpArchiveError` or markdown error strings; bound `walk_namespace` `limit` to `[1, 500]` per the documented contract
* **validation:** validate `get_zim_entries` batch size before charging rate-limit so an oversized batch doesn't increment the limiter

### Performance

* **search:** skip-counter pagination in `_perform_filtered_search` (offset=900, limit=10 went from ~1000 backend calls to ~10)
* **content:** `get_entries` groups by ZIM file and opens each archive once
* **navigation:** cache namespace listings per `(archive, namespace)`; pagination now slices from cache instead of re-scanning
* **search:** hoist `Searcher` construction in `_find_entry_by_search` (up to 5 Xapian opens collapse to 1)
* **suggestions:** Strategy 2 uses libzim's `SuggestionSearcher` instead of a strided ID scan that skipped 95% of entries on large archives
* **subscriptions:** `SubscriberRegistry` is set-backed for O(1) subscribe/unsubscribe/clear; broadcast fans out concurrently with per-call `wait_for` timeout so one slow subscriber doesn't stall the watcher

### Refactoring

* **zim:** split `zim_operations.py` (3557 → 39 lines, pure shim) into a `zim/` package with `_SearchMixin`, `_ContentMixin`, `_StructureMixin`, `_NamespaceMixin`. Public API preserved via re-exports
* **simple-tools:** extract `IntentParser` into `intent_parser.py` (parsing logic now unit-testable without `ZimOperations` mocks)
* **config:** unify `RateLimitConfig` into a single Pydantic `BaseModel`; `per_operation_limits` is now reachable from environment variables and JSON config
* **defaults:** default cache `persistence_path` to `~/.cache/openzim-mcp` (absolute) rather than `.openzim_mcp_cache` (relative to CWD)
* **defaults:** relocate `MAX_REDIRECT_DEPTH` and `SUBSCRIPTION_SEND_SECONDS` to `defaults.py` (matches existing project pattern)
* **resources:** offload blocking `list_zim_files_data` directory scan via `asyncio.to_thread`
* **resources:** extract `_resolve_zim_name` helper, replacing duplicated inline ZIM-name match loops
* **simple-tools:** intent confidence boost capped (low-priority intents with extracted params can no longer overtake higher-priority param-less intents)
* **prompts:** dedupe ask-for-args message into a `_ask_for_args(prompt_name)` helper

### Hardening (other)

* **cache:** validate values are JSON-serializable at write time when persistence is enabled (previously `default=str` silently coerced non-JSON types)
* **security:** add an unconditional `..` pattern to path normalization so embedded `foo..bar` traversal candidates trigger the regex layer
* **exceptions:** drop `details` from `Exception.args` so it no longer leaks into `repr()` and tracebacks
* **main:** route startup banner through the logger (now respects `OPENZIM_MCP_LOGGING__LEVEL`)
* **simple-tools:** consistently append low-confidence note across all intents (was missing on `search_all`, `walk_namespace`, `find_by_title`, `related`)

### Pre-release fix-up

Final bug-sweep passes after the main review work above. Categorised by area for easier scanning.

* **content/structure:** `_resolve_entry_with_fallback` and `get_binary_entry` now follow the redirect chain (bounded by the shared `MAX_REDIRECT_DEPTH = 10` cap with cycle detection) before calling `entry.get_item()`. Without this the structure, links, TOC, summary, and binary-entry tools all crashed with `RuntimeError` from libzim whenever the requested path was a redirect to the canonical article (the common case for Kiwix-generated ZIMs)
* **content:** `_get_main_page_content` resolves `archive.main_entry` and the fallback `main_page_paths` entries before calling `get_item()`. Most ZIMs point `W/mainPage` at the real article via a redirect; previously this raised on every such archive
* **content:** `get_zim_metadata` resolves redirect entries before reading metadata content
* **content:** `get_related_articles` preserves trailing slash in path resolution and resolves relative links against the post-redirect path
* **zim:** `_resolve_link_to_entry_path` rejects self-referential refs that previously fed back into the resolver
* **search:** `_perform_filtered_search` canonicalises lowercase / long-form namespace input so filters stop silently dropping every result; suggestion cache now skips zero-result responses
* **search:** `search_all` validates effective_limit is in the documented 1-50 range
* **simple-tools:** `get_article` intent forwards `options[content_offset]` so simple-mode pagination works (previously always returned page 1); passthrough intents forward `options[limit]` / `options[offset]`
* **subscriptions:** `broadcast_resource_updated` re-raises `CancelledError` that `gather(return_exceptions=True)` had silently collected, so `stop()` no longer hangs until the next sleep tick
* **subscriptions:** `MtimeWatcher.start()` offloads initial `_scan` via `asyncio.to_thread` to match `_tick`, no longer blocking the ASGI lifespan on slow filesystems
* **subscriptions:** mtime scan offloaded to thread; fan-out cleanup guarded against late exceptions
* **prompts:** switch user-input interpolation delimiter to backticks and preserve quotes in user input
* **rate-limit:** add missing `RATE_LIMIT_COSTS` keys for `find_entry_by_title`, `get_zim_entries`, `get_related_articles` (were silently using the cost=1 default)
* **http:** add `Mcp-Session-Id` to CORS `allow_headers` and `expose_headers` so browser MCP clients can resume sessions
* **main:** catch `pydantic.ValidationError` from `OpenZimMcpConfig` construction and re-surface as `OpenZimMcpConfigurationError` so operators see a clean message instead of a pydantic validation dump
* **cache:** suppress shutdown logging spam; tolerate malformed persisted entries
* **security:** symlink-tighten archive scan; harden error context; sanitise `name_filter`; reject whitespace-only CORS wildcard
* **tools:** `get_binary_entry` docstring example uses keyword `include_data=False` (positional `False` was landing in `max_size_bytes`)
* **packaging:** `Development Status :: 5 - Production/Stable` classifier for the 1.0.0 release

### Final pre-release sweep

* **resource:** `ZimEntryResource.read` and the `zim://files` / `zim://{name}` resource handlers now offload archive opens via `asyncio.to_thread`; previously a single read stalled the HTTP/SSE event loop for every other concurrent client
* **resource:** `ZimEntryResource.read` resolves redirect chains (with cycle detection and the shared `MAX_REDIRECT_DEPTH = 10` cap) before `entry.get_item()`; previously every redirect-stub path crashed with `RuntimeError` from libzim
* **content:** `get_zim_entries` (batch) replaces manual `__enter__`/`__exit__` with a regular `with` block — cleaner cleanup on `BaseException`, no silent swallowing of `__exit__` errors
* **content:** drop `_get_main_page_content`'s `archive._get_entry_by_id(0)` fallback (libzim private API; entry-zero is not the spec's main-page pointer); the inline redirect helper now uses `MAX_REDIRECT_DEPTH` and raises `OpenZimMcpArchiveError` on cycles or chain exhaustion to match the rest of the redirect helpers
* **server:** `OpenZimMcpServer.run()` defaults to `self.config.transport` (translating the short name `'http'` to FastMCP's `'streamable-http'`) and rejects an explicit `transport=` argument that contradicts the configured value — closes the gap where HTTP-mode subscriptions could be wired while a stdio transport was actually started
* **search/structure:** `find_entry_by_title`, `search_all`, and `get_related_articles` raise `OpenZimMcpValidationError` on out-of-range `limit` / `limit_per_file` instead of returning a hand-formatted markdown string, so the tool layer sees a consistent exception shape
* **http:** `_is_loopback_host` adds a 1-second timeout around `socket.gethostbyname("localhost")` so a slow resolver can't hang server startup
* **ci:** drop `pull_request_target` trigger from `test.yml` / `codeql.yml` / `performance.yml` (closes the pwn-request gap where untrusted PR code could exfiltrate secrets); release-please prerelease detection reads the resolved tag name (works for `workflow_dispatch`); release-please bootstrap-sha placeholders removed; Dockerfile uv image pinned to `0.11`
* **make:** `make benchmark` selects via `-k benchmark` (the previously referenced `tests/test_benchmarks.py` does not exist); `make security` no longer swallows bandit / pip-audit non-zero exits, so `make check` (used by `release.yml`) actually fails on findings
* **docs:** `OPENZIM_MCP_TOOL_MODE`, `_TRANSPORT`, `_HOST`, `_PORT`, `_AUTH_TOKEN`, `_CORS_ORIGINS`, `_WATCH_INTERVAL_SECONDS`, `_SUBSCRIPTIONS_ENABLED` documented in the README configuration table; install commands aligned across README / `website/llms.txt` / `website/index.html` (lead with `uv tool install openzim-mcp`); `website/llm.txt` renamed to `website/llms.txt` (matches the [llmstxt.org](https://llmstxt.org) convention) and advertised in the sitemap

## [0.9.0](https://github.com/cameronrye/openzim-mcp/compare/v0.8.3...v0.9.0) (2026-04-30)

### Features

* **search:** `search_all` queries every ZIM file in allowed directories at once and merges results
* **search:** `find_entry_by_title` resolves a title (or partial title) to entry paths, case-insensitive, optionally cross-file
* **prompts:** MCP prompts (`/research`, `/summarize`, `/explore`) for multi-step ZIM workflows
* **resources:** MCP resources `zim://files` (index of all ZIM files) and `zim://{name}` (per-archive overview)
* **navigation:** `walk_namespace` for deterministic cursor-paginated namespace iteration (vs. `browse_namespace` which samples)
* **content:** `get_random_entry` to sample a random article
* **content:** `get_related_articles` returns link-graph nearest neighbours (outbound, inbound, or both)
* **server:** `warm_cache`, `cache_stats`, and `cache_clear` for inspecting and managing the in-memory cache

### Bug Fixes

* namespace listing deterministically surfaces minority namespaces (M, W, X, I) that random sampling could miss
* search filtering uses streaming scan instead of a hard 1000-hit cap, so rare-mime-type filters return matches that were previously hidden
* error messages route by failure mode first (no more "check disk space" for "entry not found")
* phantom server-instance conflicts are no longer reported (TOCTOU re-check before raising)

## [0.8.3](https://github.com/cameronrye/openzim-mcp/compare/v0.8.2...v0.8.3) (2026-01-30)

### Bug Fixes

* fix logo URL in README.md to use absolute GitHub raw URL for PyPI display ([README.md](README.md))
* resolve GitHub code scanning alert #133 - variable defined multiple times in security.py ([security.py](openzim_mcp/security.py))
* resolve GitHub code scanning alert #134 - mixed import styles in test_main.py ([test_main.py](tests/test_main.py))
* remove unused `contextlib` import from security.py (flake8 fix)

## [0.8.2](https://github.com/cameronrye/openzim-mcp/compare/v0.8.1...v0.8.2) (2026-01-29)

### Bug Fixes

* fix search pagination when offset exceeds total results ([zim_operations.py](openzim_mcp/zim_operations.py))
* improve exception handling in instance tracker for Python 3 compatibility ([instance_tracker.py](openzim_mcp/instance_tracker.py))
* add fallback to stderr for logging during shutdown ([instance_tracker.py](openzim_mcp/instance_tracker.py))
* improve Windows process checking with debug logging ([instance_tracker.py](openzim_mcp/instance_tracker.py))
* fix release workflow to skip automatic GitHub release creation ([release-please.yml](.github/workflows/release-please.yml))
* resolve linting issues in simple_tools.py and content_tools.py

## [0.8.1](https://github.com/cameronrye/openzim-mcp/compare/v0.7.1...v0.8.1) (2026-01-29)

### Features

* add article summaries, table of contents, and pagination cursors ([bf5d18f](https://github.com/cameronrye/openzim-mcp/commit/bf5d18fcfecb2e6b03c667565640439b145a4e30))

### Bug Fixes

* remove unused imports in test files for CI linting ([0ddb250](https://github.com/cameronrye/openzim-mcp/commit/0ddb250d49fb627ee7adb41cf3fa52a8caf69172))
* resolve GitHub code scanning alerts ([2ad2c56](https://github.com/cameronrye/openzim-mcp/commit/2ad2c56a6e7a958ed63d6bd23ad975dd80e1e1f0))

### Details

* **Article Summaries** (`get_entry_summary`): Extract concise article summaries from opening paragraphs
  * Removes infoboxes, navigation, and sidebars for clean summaries
  * Configurable `max_words` parameter (10-1000, default: 200)
  * Returns structured JSON with title, summary, word count, and truncation status
  * Useful for quick content preview without loading full articles

* **Table of Contents Extraction** (`get_table_of_contents`): Build hierarchical TOC from article headings
  * Hierarchical tree structure with nested children based on heading levels (h1-h6)
  * Includes heading text, level, and anchor IDs for navigation
  * Provides heading count and maximum depth statistics
  * Enables LLMs to navigate directly to specific article sections

* **Pagination Cursors**: Token-based pagination for easier result navigation
  * Base64-encoded cursor tokens encode offset, limit, and optional query
  * `next_cursor` field in search and browse results for continuation
  * Eliminates need for clients to track pagination state manually

### Enhanced

* **Intent Parsing**: Improved multi-match resolution with weighted scoring
  * Collects all matching patterns before selecting best match
  * Weighted scoring: 70% confidence + 30% specificity
  * Prevents earlier patterns from incorrectly shadowing more specific ones
  * New intent patterns for "toc" and "summary" queries in Simple mode

* **Simple Mode**: Added natural language support for new features
  * "summary of Biology" or "summarize Evolution" for article summaries
  * "table of contents for Biology" or "toc of Evolution" for TOC extraction

## [0.7.1](https://github.com/cameronrye/openzim-mcp/compare/v0.7.0...v0.7.1) (2026-01-28)

### Bug Fixes

* **ci:** handle existing GitHub releases in release workflow ([#54](https://github.com/cameronrye/openzim-mcp/issues/54)) ([63afa3d](https://github.com/cameronrye/openzim-mcp/commit/63afa3d9150a60716b7fa25524beedb806ded84d))

## [0.7.0](https://github.com/cameronrye/openzim-mcp/compare/v0.6.3...v0.7.0) (2026-01-28)

### Features

* add binary content retrieval for PDFs, images, and media files ([#52](https://github.com/cameronrye/openzim-mcp/issues/52)) ([95611c9](https://github.com/cameronrye/openzim-mcp/commit/95611c9135836202d1fc97181d98307c199e3888))

## [0.6.3](https://github.com/cameronrye/openzim-mcp/compare/v0.6.2...v0.6.3) (2025-11-14)

### Bug Fixes

* configure release-please to skip GitHub release creation and handle existing PyPI packages ([b865454](https://github.com/cameronrye/openzim-mcp/commit/b8654546c1a8ea3a90eb3dedfb95c671beaaca98))

## [0.6.2](https://github.com/cameronrye/openzim-mcp/compare/v0.6.1...v0.6.2) (2025-11-14)

### Bug Fixes

* add tag_name parameter to GitHub Release action ([74d393c](https://github.com/cameronrye/openzim-mcp/commit/74d393c600155b303a26d6f066130cb26351cb49))

## [0.6.1](https://github.com/cameronrye/openzim-mcp/compare/v0.6.0...v0.6.1) (2025-11-14)

### Bug Fixes

* resolve CI workflow issues ([4bd6c33](https://github.com/cameronrye/openzim-mcp/commit/4bd6c332548a444c58390889052ebcc417d65094))

## [0.6.0](https://github.com/cameronrye/openzim-mcp/compare/v0.5.1...v0.6.0) (2025-11-14)

### Features

* add dual-mode support with intelligent natural language tool ([#31](https://github.com/cameronrye/openzim-mcp/issues/31)) ([6d97993](https://github.com/cameronrye/openzim-mcp/commit/6d97993a8bda3f20cc65abfeef459f9487b94406))
* enhance GitHub Pages website with dark mode, dynamic versioning, and improved UX ([#22](https://github.com/cameronrye/openzim-mcp/issues/22)) ([977d46a](https://github.com/cameronrye/openzim-mcp/commit/977d46abf61efbafca2bd24142176c3857cc32b8))

## [0.5.1](https://github.com/cameronrye/openzim-mcp/compare/v0.5.0...v0.5.1) (2025-09-16)

### Bug Fixes

* resolve CI/CD status reporting issue for bot commits ([#20](https://github.com/cameronrye/openzim-mcp/issues/20)) ([af23589](https://github.com/cameronrye/openzim-mcp/commit/af235896b4a1afd96269d08d97362ff903e093d5))
* resolve GitHub Actions workflow errors ([#17](https://github.com/cameronrye/openzim-mcp/issues/17)) ([dcda274](https://github.com/cameronrye/openzim-mcp/commit/dcda2749a394a599e3f77a4b64412fa21e65a29d))

## [0.5.0](https://github.com/cameronrye/openzim-mcp/compare/v0.4.0...v0.5.0) (2025-09-15)

### Features

* enhance GitHub Pages site with comprehensive feature showcase ([#14](https://github.com/cameronrye/openzim-mcp/issues/14)) ([c50c69b](https://github.com/cameronrye/openzim-mcp/commit/c50c69b73bc4ec142a2080146644ed9c84da63c4))
* enhance GitHub Pages site with comprehensive feature showcase and uv-first installation ([#15](https://github.com/cameronrye/openzim-mcp/issues/15)) ([f988c5a](https://github.com/cameronrye/openzim-mcp/commit/f988c5a9c7af4acbfe08922a68e11a288f06da70))

### Bug Fixes

* correct CodeQL badge URL to match workflow name ([#13](https://github.com/cameronrye/openzim-mcp/issues/13)) ([7446f74](https://github.com/cameronrye/openzim-mcp/commit/7446f7491d1c0a028a7ba55071b46c73424b58e4))

### Documentation

* Comprehensive documentation update for v0.4.0+ features ([#16](https://github.com/cameronrye/openzim-mcp/issues/16)) ([e1bce58](https://github.com/cameronrye/openzim-mcp/commit/e1bce5816e95beca7adeca92c03dbd551808151f))
* improve installation instructions with PyPI as primary method ([d6f758b](https://github.com/cameronrye/openzim-mcp/commit/d6f758b30836e916933e87a316754cd757cec833))

## [0.4.0](https://github.com/cameronrye/openzim-mcp/compare/v0.3.3...v0.4.0) (2025-09-15)

### Features

* overhaul release system for reliability and enterprise-grade automation ([#9](https://github.com/cameronrye/openzim-mcp/issues/9)) ([ef0f1b8](https://github.com/cameronrye/openzim-mcp/commit/ef0f1b8f2eaac99a1850672088ddc29d28f0bcde))

## [0.3.1](https://github.com/cameronrye/openzim-mcp/compare/v0.3.0...v0.3.1) (2025-09-15)

### Bug Fixes

* add manual trigger support to Release workflow ([b968cf6](https://github.com/cameronrye/openzim-mcp/commit/b968cf661f536183f4ef5fd6374e75a847a0123f))
* ensure Release workflow checks out correct tag for all jobs ([b4a61ca](https://github.com/cameronrye/openzim-mcp/commit/b4a61ca7a034f9eefae2606c4eb9769ef4f79379))

## [0.3.0](https://github.com/cameronrye/openzim-mcp/compare/v0.2.0...v0.3.0) (2025-09-15)

### Features

* add automated version bumping with release-please ([6b4e27c](https://github.com/cameronrye/openzim-mcp/commit/6b4e27c0382bb4cfa16a7e101f012e8355f7c827))

### Bug Fixes

* resolve release-please workflow issues ([68b47ea](https://github.com/cameronrye/openzim-mcp/commit/68b47ea711525e126ec3ed8297808f7779edd87e))

## [0.2.0] - 2025-01-15

### Added

* **Complete Architecture Refactoring**: Modular design with dependency injection
* **Enhanced Security**:
  * Fixed path traversal vulnerability using secure path validation
  * Comprehensive input sanitization and validation
  * Protection against directory traversal attacks
* **Comprehensive Testing**: 80%+ test coverage with pytest
  * Unit tests for all components
  * Integration tests for end-to-end functionality
  * Security tests for vulnerability prevention
* **Intelligent Caching**: LRU cache with TTL support for improved performance
* **Modern Configuration Management**: Pydantic-based configuration with validation
* **Structured Logging**: Configurable logging with proper error handling
* **Type Safety**: Complete type annotations throughout the codebase
* **Resource Management**: Proper cleanup with context managers
* **Health Monitoring**: Built-in health check endpoint
* **Development Tools**:
  * Makefile for common development tasks
  * Black, flake8, mypy, isort for code quality
  * Comprehensive development dependencies

### Changed

* **Project Name**: Changed from "zim-mcp-server" to "openzim-mcp" for consistency
* **Entry Point**: New `python -m openzim_mcp` interface (backwards compatible)
* **Error Handling**: Consistent custom exception hierarchy
* **Content Processing**: Improved HTML to text conversion
* **API**: Enhanced tool interfaces with better validation

### Security

* **CRITICAL**: Fixed path traversal vulnerability in PathManager
* **HIGH**: Added comprehensive input validation
* **MEDIUM**: Sanitized error messages to prevent information disclosure

### Performance

* **Caching**: Intelligent caching reduces ZIM file access overhead
* **Resource Management**: Proper cleanup prevents memory leaks
* **Optimized Processing**: Improved content processing performance

## [0.1.0] - 2024-XX-XX

### Added

* Initial release of ZIM MCP Server
* Basic ZIM file operations (list, search, get entry)
* Simple path management
* HTML to text conversion
* MCP server implementation

### Known Issues (Fixed in 0.2.0)

* Path traversal security vulnerability
* No input validation
* Missing error handling
* No testing framework
* Resource management issues
* Global state management problems
