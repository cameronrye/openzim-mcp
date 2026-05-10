# v2 Phase C — New Retrieval Primitives (Design Spec)

**Status:** Draft
**Phase:** C of 6 ([tracking doc](../../v2/README.md))
**Items in scope:** #11 (pre-computed section + infobox bundle), #7 (`get_section` tool), #10 (server-side `synthesize` mode on `zim_query`)
**Target:** `v2.0.0a3`
**Date:** 2026-05-09

---

## Goal

Give a smaller, less capable LLM the primitives it needs to navigate a multi-million-article ZIM archive: section-level retrieval, server-fused answers, and the precomputed index that powers both. Phase C lands three coordinated changes:

1. **#11 EntryBundle.** First touch of an entry (via any of four content-shape tools) runs **one** HTML parse → produces a single `EntryBundle` value `{rendered_markdown, sections, links, infobox, …}` → caches it in the existing LRU. The four tools `get_entry_summary`, `get_table_of_contents`, `get_article_structure`, `extract_article_links` collapse from independent HTML re-parsers into thin slicers over that bundle.
2. **#7 `get_section`.** New tool that fetches a single section by `section_id` from the bundle. Returns ~500-1500 tokens — the small-model sweet spot per parent-document-retrieval research. Section IDs are the same anchor scheme `get_table_of_contents` already exposes (existing TOC field `id` is renamed to `section_id` for clarity, and `toc` is tightened from `list[dict[str, Any]]` to a `list[TocHeading]` TypedDict).
3. **#10 `synthesize` mode.** `zim_query` gains `synthesize: bool = False`. When `True`, the simple-tools handler dispatches to a passage-extraction pipeline that returns top-N libzim snippets concatenated with `[cite: archive/entry_path#section_id]` markers plus a structured citation list. Pure retrieval + concatenation, no LLM generation. Falls back to Xapian-only ranking in Phase C; Phase D's reranker will plug in between extraction and assembly.

These ship as a single bundled PR off `v2-phase-c` (matching Phase A and Phase B precedent). #7 and #10 both depend on the #11 bundle; splitting would either ship a bundle nobody calls (#11 alone) or build the consumers on a hot path that re-parses HTML (no #11). The trio is the natural unit.

> **Note on FastMCP wrapping (Phase B carryover):** FastMCP wraps every `Union[<Response>, ToolErrorPayload]` return in a top-level `{"result": ...}` envelope on the wire. Phase C's new responses (`GetSectionResponse`, `SynthesizeResponse`) inherit this convention. Tests use the wrapper-tolerant unwrap pattern from Phase B (`payload = structured["result"] if "result" in structured else structured`).

## Non-goals

- **No reranker.** Phase D ships `[reranker]` extra. Phase C's synthesize pipeline includes an identity rerank stage; Phase D injects the cross-encoder there.
- **No bundle sidecars.** Persistent bundle artifacts on disk are Phase E. Phase C's bundle lives only in the in-process LRU.
- **No `zim_query` rewrite.** Non-synthesize calls to `zim_query` keep returning the existing markdown string. Converting `zim_query` to a fully structured response across all modes is a Phase F concern.
- **No tool removals.** The four tools that #11 collapses keep their wire formats and remain registered. Only their internal data source moves to the bundle.
- **No new ML dependencies.** Phase C introduces zero Python deps. Existing `tiktoken`/libzim/BeautifulSoup cover everything.
- **No sub-section pagination.** A single section is always returned in full (subject to a configurable `max_chars` truncation). If a section exceeds the cap, callers fall back to `get_zim_entry` with `content_offset`. Revisit only if tests surface real pain.
- **No archive nicknames.** Citation `archive` field is `Path(zim_file_path).stem` (basename without `.zim`). Verbose but stable. User-facing nicknames are out of scope.
- **No change to `get_zim_entry`.** It has its own cache and fast path; coupling it to the bundle would force a parse on every fetch. The bundle layer is parallel.
- **No change to error semantics.** Errors continue to flow as `ToolErrorPayload` data with `error: True`, per Phase B.

## Foundational decisions inherited from the v2 tracking doc

1. **Clean breaks allowed.** Phase C may add fields, change cache keys, and add tools without deprecation periods. v1.x receives no Phase C backports.
2. **ML accelerators opt-in via extras.** Phase C ships zero ML deps; all `synthesize` ranking is Xapian-native or RRF-fused.
3. **Offline-first.** No network code paths.
4. **Markdown for prose, JSON for navigation, no XML.** `get_section.content_markdown` and `synthesize.answer_markdown` are markdown. Citation markers are inline markdown literals.
5. **Phase A `_meta` envelope is canonical.** All Phase C responses carry `_meta`, sibling to the response body keys, populated via the existing `attach_meta()` helper.

## Decisions captured during brainstorming

| Decision | Choice |
|---|---|
| Spec & PR shape | **One spec, one PR.** Trio ships together as `v2.0.0a3`. |
| `synthesize` entry point | **Boolean param on `zim_query`.** Not a new intent, not a new top-level tool. Matches Phase B's `compact` precedent. |
| Multi-archive synthesize scope | **Inherits `zim_query` semantics.** Multi-archive when `zim_file_path` is omitted; single-archive when provided. Citations carry archive identifier in either case. |
| Bundle architecture | **Approach A — slim bundle.** Stores rendered markdown + parsed indices. `char_range` semantics are offsets into `rendered_markdown`. |
| `get_section` tool name | **`get_section`** (matches existing `get_*` naming). Phase F's planned rename to `zim_get_section` happens during the Phase F surface collapse, not now. |
| `get_section` lookup | **Exact match on `section_id`.** No fuzzy matching. On miss, return `tool_error("section_not_found", available_section_ids=[...])` so the model can self-correct. |
| TOC heading shape | **Rename existing `id` field to `section_id`** and tighten `TableOfContentsResponse.toc` from `list[dict[str, Any]]` to `list[TocHeading]` (new TypedDict). The `id` field is already populated by `resolve_heading_id()` with slug fallback — this is the value `get_section(section_id=...)` consumes. The rename + TypedDict tightening are wire-format breaks in v2 alpha. |
| Bundle eviction during pagination | **Silent rebuild.** Bundles are deterministic given `(validated_path, entry_path)`; existing cursor (`{o, l, ep, k}`) doesn't reference bundle generation. |
| Fallback fields on `SynthesizeResponse` | **`fallback_used: Literal["xapian_score", "rrf_fusion", "reranker"]`.** Phase C ships `xapian_score` (single-archive) or `rrf_fusion` (multi-archive); Phase D will start emitting `reranker`. |

---

## Architecture

### New modules

#### `openzim_mcp/bundle.py`

Pure-function bundle extractor and cache-aware accessor. Single source of truth for the parsed-entry intermediate.

```python
def extract_entry_bundle(
    archive: Archive,
    entry_path: str,
    *,
    content_processor: ContentProcessor,
) -> EntryBundle:
    """Run the single HTML parse and produce the bundle. Pure: no caching, no I/O beyond the archive read."""

def get_or_build_bundle(
    archive: Archive,
    entry_path: str,
    *,
    cache: OpenZimMcpCache,
    validated_path: Path,
    content_processor: ContentProcessor,
) -> EntryBundle:
    """Cache-aware accessor. Cache key: f'bundle:v2c:{validated_path}:{entry_path}'."""
```

The extractor:
1. Resolves the entry (including the existing path-fallback search) and fetches the raw HTML.
2. Calls `content_processor.process_mime_content()` once → `rendered_markdown`.
3. Calls `content_processor.extract_html_structure()` once → flat heading list with `resolve_heading_id()`-derived IDs.
4. Calls `content_processor.extract_html_links()` once → categorized link buckets.
5. Detects `.infobox` / `.vcard` containers and emits compact `InfoboxData`.
6. Computes `(char_start, char_end)` for each section by **post-render text matching**: iterate the heading list from `_build_headings(soup)` in document order, and for each heading search `rendered_markdown` starting from `last_match_end` for the pattern `^#{level} re.escape(text)$` (multiline). The renderer (today's `html2text` pipeline) emits headings as plain `## Title` with no anchor suffix, so we anchor on heading text + level rather than an injected sentinel. `char_start` = match start; `char_end` = next heading's `char_start` (or `len(rendered_markdown)` for the last heading).

This deliberately avoids modifying the renderer (which would change the wire output of `get_zim_entry` and friends — all currently relying on plain html2text output). The trade-off is that text-matching has edge cases:

- **Whitespace.** `html2text` collapses runs of whitespace; the bundle extractor normalizes heading text the same way before matching.
- **Markdown-significant chars in headings.** `html2text` escapes `*`, `_`, `[`, etc. The extractor escapes these in the heading text the same way before building the regex.
- **Repeated heading text.** Two `### References` in one entry: disambiguated by document order — the Nth heading from `_build_headings` matches the Nth occurrence found in the markdown.
- **Empty or whitespace-only headings.** `html2text` drops these; `_build_headings` already excludes empty headings, so they don't appear in `bundle["sections"]`.
- **Match failure.** If a heading from `_build_headings` cannot be located in the rendered markdown (extreme edge case — e.g., heading inside a stripped element), drop it from `bundle["sections"]` and log a warning. `get_section` returns `tool_error("section_not_found", ...)` for such IDs.

Sections at the same level are non-overlapping by construction (each `char_end` is the next heading's `char_start`). Nested children's ranges sit inside their parent's range because `_build_headings` walks the soup in document order and child headings appear after their parent in the markdown.

#### `openzim_mcp/synthesize.py`

Pure-function passage extraction and citation rendering. No reranker dependency; the rerank stage is identity in Phase C.

```python
def synthesize_query(
    query: str,
    *,
    archives: Sequence[OpenedArchive],   # opened by the caller (handles multi-archive)
    cache: OpenZimMcpCache,
    content_processor: ContentProcessor,
    config: SynthesizeConfig,
) -> SynthesizeResponse:
    """Pipeline: search → fuse → extract passages → attribute via bundle → render citations → enforce budget."""
```

Pipeline stages live as private helpers within the module: `_per_archive_search`, `_rrf_fuse`, `_extract_passage`, `_attribute_section`, `_render_answer`, `_enforce_budget`.

### Modified modules

| Module | Change |
|---|---|
| `openzim_mcp/zim/content.py` | `_extract_entry_summary_data` reads from `get_or_build_bundle()` instead of running `process_mime_content()` itself. The legacy `summary_data:` cache key disappears. |
| `openzim_mcp/zim/structure.py` | `_extract_table_of_contents_data`, `_extract_article_structure_data`, `_get_or_load_link_extraction` all become bundle slicers. Legacy cache prefixes (`toc_data:`, `structure_data:`, `links_full:v2b:`) disappear. New `_get_section_data()` data-layer method added. |
| `openzim_mcp/tools/structure_tools.py` | New `get_section` tool registration following the Phase B pattern (thin wrapper → `_data` method → `Union[GetSectionResponse, ToolErrorPayload]`). |
| `openzim_mcp/server.py` | `zim_query` gains `synthesize: bool = False`. Return type expands to `Union[str, SynthesizeResponse, ToolErrorPayload]`. |
| `openzim_mcp/simple_tools.py` | New `_handle_synthesize_query` handler. `handle_zim_query` dispatches directly to it when `synthesize=True`, bypassing intent classification. |
| `openzim_mcp/tool_schemas.py` | Adds `EntryBundle`, `SectionMeta`, `InfoboxField`, `InfoboxData`, `LinkBuckets` (internal), `GetSectionResponse`, `SynthesizeResponse`, `Citation`, `SynthesizePassage`, `TocHeading`. Tightens `TableOfContentsResponse.toc` from `list[dict[str, Any]]` to `list[TocHeading]`. |
| `openzim_mcp/config.py` | Adds `SynthesizeConfig` block with `top_n`, `per_archive_k`, `output_char_budget` defaults. |

### Untouched

- `cache.py` — single-LRU API is unchanged; bundle is just another keyed value.
- `pagination.py` — `get_section` is non-paginated; `synthesize` returns fixed top-N.
- `intent_parser.py` — synthesize bypasses intent classification entirely.
- `content_processor.py` — its primitives (`process_mime_content`, `extract_html_structure`, `extract_html_links`, `resolve_heading_id`) are reused by the bundle extractor without modification.

---

## Data shapes

### Internal: the bundle (`tool_schemas.py`)

```python
class SectionMeta(TypedDict):
    id: str                          # from resolve_heading_id() — stable across calls
    title: str                       # heading text
    level: int                       # 1-6
    char_start: int                  # offset into rendered_markdown (inclusive)
    char_end: int                    # offset into rendered_markdown (exclusive)
    parent_id: NotRequired[Optional[str]]

class InfoboxField(TypedDict):
    label: str
    value: str                       # plain text or short markdown

class InfoboxData(TypedDict):
    title: NotRequired[str]
    fields: list[InfoboxField]

class LinkBuckets(TypedDict):
    internal: list[LinkItem]
    external: list[LinkItem]
    media: list[LinkItem]

class EntryBundle(TypedDict):
    entry_path: str
    title: str
    content_type: str
    word_count: int
    char_count: int
    rendered_markdown: str           # the body, all consumers slice this
    sections: list[SectionMeta]
    links: LinkBuckets
    infobox: Optional[InfoboxData]
```

**Invariants** (asserted in `tests/test_bundle.py`):
- `sections` is sorted by `char_start` ascending.
- For sections at the same level, ranges are disjoint.
- For nested children, `parent.char_start <= child.char_start < child.char_end <= parent.char_end`.
- `0 <= char_start < char_end <= len(rendered_markdown)` for every section.
- Section IDs are unique within a single bundle.
- The bundle is deterministic given `(validated_path, entry_path)` — re-running the extractor produces an identical bundle.

### Wire: `get_section` response

```python
class GetSectionResponse(TypedDict):
    entry_path: str
    title: str                       # entry title
    section_id: str
    section_title: str               # heading text
    level: int
    parent_id: Optional[str]
    content_markdown: str
    char_count: int
    word_count: int
    truncated: bool                  # True if max_chars hit
    _meta: MetaEnvelope
```

### Wire: `synthesize` response

```python
class Citation(TypedDict):
    cite_id: str                     # "wikipedia_en_simple_2024-01/A/Berlin#Geography"
    archive: str                     # ZIM basename without .zim
    entry_path: str
    title: str                       # entry title
    section_id: Optional[str]        # None if no bundle / no section match
    section_title: Optional[str]

class SynthesizePassage(TypedDict):
    cite_id: str                     # references one of the Citations
    text_markdown: str               # passage body (≈150-300 tokens)
    rank: int                        # 1-N (post-fusion order)
    score: float                     # Xapian score or RRF fused score

class SynthesizeResponse(TypedDict):
    query: str
    answer_markdown: str             # passages concatenated with inline [cite: ...] markers
    passages: list[SynthesizePassage]
    citations: list[Citation]
    archives_searched: list[str]
    fallback_used: Literal["xapian_score", "rrf_fusion", "reranker"]
    total_chars: int
    total_words: int
    _meta: MetaEnvelope
```

### Wire-format change to `TableOfContentsResponse`

`toc` tightens from `list[dict[str, Any]]` to `list[TocHeading]` (new TypedDict):

```python
class TocHeading(TypedDict):
    section_id: str                  # renamed from existing `id` — value to pass to get_section(section_id=...)
    text: str                        # heading text
    level: int                       # 1-6
    id_source: Literal["id", "descendant_anchor", "preceding_anchor", "slug"]
    children: list["TocHeading"]     # nested headings (recursive)
```

This is a wire-format break: callers reading `heading["id"]` need to read `heading["section_id"]` instead. Phase C is in v2 alpha — the rename clarifies the field's purpose (it's the section identifier for `get_section`, not just a heading anchor) and brings the nested data into Phase B's TypedDict regime, which Phase B's spec scope didn't reach. `id_source` is preserved for callers that care about anchor provenance.

---

## Behavior

### #11 — bundle lifecycle

**First call** to any of `{get_entry_summary, get_table_of_contents, get_article_structure, extract_article_links, get_section}` for a given `(validated_path, entry_path)`:

1. `get_or_build_bundle` checks the cache for `bundle:v2c:{validated_path}:{entry_path}`.
2. Miss → opens the archive (or uses the already-open archive in batch contexts), calls `extract_entry_bundle`, stores under the cache key, returns.
3. Tool slices what it needs from the bundle.

**Subsequent calls** for the same entry hit the bundle cache regardless of which of the five tools is invoked. Single HTML parse cost amortizes across all consumers.

**Eviction.** When the bundle is evicted (LRU pressure or TTL), the next call reruns the extractor. Bundles are deterministic — the rebuild produces an identical value, so cursor-based pagination on `extract_article_links` survives eviction without state reconciliation.

**Cache budget.** Bundles are larger than the legacy per-tool entries (rendered markdown dominates, ≈30-80 KB for a Wikipedia article). Existing LRU `max_size` bounds memory. Default is unchanged for v2.0.0a3; reassess after the bundle code lands and we have observable hit rates.

### #7 — `get_section` semantics

**Happy path.** Bundle lookup → `next((s for s in bundle["sections"] if s["id"] == section_id), None)` → on hit, slice `rendered_markdown[char_start:char_end]` → apply `max_chars` if set → assemble `GetSectionResponse`.

**Miss.** Return `tool_error("section_not_found", message="...", available_section_ids=[s["id"] for s in bundle["sections"]])`. The available IDs travel in the error payload so the model can pick a valid one without a second round trip.

**Truncation.** If the section body exceeds `max_chars` (default falls back to `config.content.max_content_length`), truncate at `max_chars` and set `truncated=True`. Truncation is byte-aligned to the markdown string, not section-aware.

**Compact mode.** Inherits the existing `compact` boolean handling from sibling tools (passes through to the markdown render path of the slice).

### #10 — `synthesize` pipeline

```
zim_query(query, synthesize=True, zim_file_path=...)
    → SimpleToolsHandler.handle_zim_query (synthesize branch)
    → synthesize_query(query, archives=[...], ...)

  Stage 1: per-archive search
    single-archive:   search_zim_file(query, limit=per_archive_k) → list[Hit]
    multi-archive:    search_all(query, per_file_limit=per_archive_k) → list[(archive, list[Hit])]

  Stage 2: fuse
    single-archive:   take first top_n hits as-is; fallback_used="xapian_score"
    multi-archive:    RRF fusion with k=60 across per-archive rankings → top_n; fallback_used="rrf_fusion"

  Stage 3: rerank   (identity in Phase C; Phase D injects cross-encoder here)

  Stage 4: passage extraction
    for each top-N hit:
      passage_text = libzim.SearchIterator.getSnippet()  # already includes match highlighting (Phase A #1 work)

  Stage 5: section attribution
    for each top-N hit:
      bundle = get_or_build_bundle(archive, hit.entry_path, ...)
      section = first s in bundle["sections"] where char_start <= snippet_offset < char_end
      cite_id = f"{archive_stem}/{hit.entry_path}#{section.id}" if section else f"{archive_stem}/{hit.entry_path}"
    # if bundle build raises for an entry: drop the section_id, keep the passage; do not fail the whole call

  Stage 6: assembly
    answer_markdown = "\n\n".join(f"{passage.text}\n[cite: {passage.cite_id}]" for passage in passages)
    citations = [Citation(cite_id=..., archive=..., entry_path=..., title=..., section_id=..., section_title=...) for ...]

  Stage 7: budget enforcement
    accumulate passages until total_chars >= output_char_budget; truncate the last passage if it pushes over.
```

**RRF formula.** `score(d) = Σ over per-archive rankings of 1 / (k + rank(d, ranking))`, with `k=60` (the standard from the Microsoft / Cormack et al. reference). Documents missing from a ranking contribute 0 from that ranking.

**Snippet offset → section attribution.** libzim's `SearchIterator` exposes the matched passage's text but not its byte offset in the source HTML. Phase C's attribution uses a substring search: locate `passage_text` within `bundle["rendered_markdown"]` (after running passage_text through the same markdown render as the bundle, since libzim returns HTML-formatted snippets). On no match, attribution falls back to the entry-level cite (`cite_id` without `#section_id`). This is best-effort; small models can still navigate via the entry path, just with one extra `get_section` call to drill down.

**Zero hits.** Return `SynthesizeResponse` with `passages=[]`, `citations=[]`, `answer_markdown=""`, and `_meta` carrying `reason: "0_hits"` (matches Phase A's structured-suggestion convention; `_meta` is the natural carrier since there's no body to attach to).

**All archives fail to open.** Return `tool_error("no_archives_available", ...)`.

### Defaults (`SynthesizeConfig`)

| Field | Default | Rationale |
|---|---|---|
| `top_n` | 5 | Mid of the README's "top-N" handwave. With ~250-token passages → ~1250 token output, sits in the middle of the 800-1500 budget. |
| `per_archive_k` | 10 | Gives RRF enough candidates to fuse meaningfully without burning Xapian on long tails. |
| `output_char_budget` | 4800 | ≈1200 tokens at 4 chars/token. Budget is on `total_chars` of `answer_markdown`, not including the citation list. |

---

## Operations

- **No new dependencies.**
- **Configuration.** All Phase C knobs live under `config.synthesize.*` (new section in `OpenZimMcpConfig`). Defaults shipped as above; advanced users can override via the existing config-file mechanism.
- **Cache memory.** Bundles dominate per-entry memory (rendered markdown). LRU `max_size` is the only governor. For a Wikipedia-size archive with `max_size=1000` and average bundle ≈50 KB, ceiling is ≈50 MB. Acceptable for the target deployment shape.
- **Logging.** New log lines at debug level: `bundle:v2c hit/miss/build`, `synthesize stage <n> ...`. Info-level on `synthesize` failure paths (per-bundle drop, all-archives-fail).
- **Telemetry.** `_meta` continues to carry token estimates; `SynthesizeResponse._meta` additionally carries `reason: "0_hits"` when applicable.

---

## Testing

| File | Coverage |
|---|---|
| `tests/test_bundle.py` (new) | Bundle determinism (same input → identical bundle); structural invariants; section IDs unique; `parent_id` references resolve; section ranges non-overlapping at same level; eviction round-trip produces identical bundle |
| `tests/test_get_section.py` (new) | Happy path slicing matches `bundle["sections"][i]` ranges; section_id miss returns `tool_error("section_not_found", available_section_ids=[...])`; `max_chars` truncation sets `truncated=True`; entry-not-found path; compact mode |
| `tests/test_synthesize.py` (new) | Single-archive (no fusion, `fallback_used="xapian_score"`); multi-archive RRF (`fallback_used="rrf_fusion"`); zero-hits (`passages=[]`, `_meta.reason=="0_hits"`); per-entry bundle failure (drop attribution, keep passage); citation format exact match; `output_char_budget` enforcement (last passage truncated) |
| `tests/test_golden_v2_phase_c.py` (new) | Snapshots: 3-5 bundles for representative entries; `get_section` for 3-5 (entry, section_id) pairs; `SynthesizeResponse` for 3-5 deterministic-seeded queries |
| `tests/test_structured_tool_output.py` (extend) | Three of the four collapsed tools' wire formats unchanged from Phase B (`get_entry_summary`, `get_article_structure`, `extract_article_links` — existing assertions still pass); `get_table_of_contents` assertions updated for the `id`→`section_id` rename and `TocHeading` TypedDict; bundle built once across multiple-tool calls for the same entry (cache-stats assertion: 1 miss → N hits); new `get_section` and `synthesize` tools covered |
| `tests/test_tool_schemas.py` (extend) | New TypedDicts mypy-clean; FastMCP builds Pydantic schemas from `GetSectionResponse`, `SynthesizeResponse` |
| `tests/test_response_contract.py` (extend) | `get_section` exempted from list-pagination contract (single-section, non-list); `synthesize` exempted (fixed top-N); both verified to carry `_meta` with the standard shape |

**Test infrastructure reuse.** Phase B's wrapper-tolerant unwrap helper (`structured["result"] if "result" in structured else structured`) is the canonical pattern; Phase C tests follow it.

---

## Wire-format changes (CHANGELOG entries)

### Adds

- **New tool: `get_section(zim_file_path, entry_path, section_id, *, max_chars=None)`.** Returns a single section by ID with full metadata. See `GetSectionResponse`.
- **`zim_query.synthesize: bool = False` parameter.** When `True`, returns a structured `SynthesizeResponse` instead of the markdown string.
- **`SynthesizeResponse` shape.** New TypedDict on the wire (returned from `zim_query` only when `synthesize=True`).

### Breaking — `get_table_of_contents`

- **TOC heading field rename: `id` → `section_id`.** Existing callers reading `heading["id"]` must update to `heading["section_id"]`. The value is unchanged (still `resolve_heading_id()`'s output with slug fallback). The new name is what `get_section(section_id=...)` consumes.
- **`toc` schema tightening: `list[dict[str, Any]]` → `list[TocHeading]`.** Phase B left this as a loose dict; Phase C tightens it. Callers using attribute-style access (`heading["text"]`, `heading["level"]`) keep working — this is a schema clarification, not a data-shape change beyond the `id`→`section_id` rename.

### No change

- `get_entry_summary`, `get_article_structure`, `extract_article_links` wire formats are unchanged. Only their internal data source moves to the bundle.
- `get_zim_entry`, `get_zim_entries`, `get_main_page` are entirely untouched.

### Removed (internal only)

- Per-tool cache prefixes `summary_data:`, `toc_data:`, `structure_data:`, `links_full:v2b:` are replaced by the single `bundle:v2c:` key. No wire impact.

---

## Phase boundaries

### Inherited from Phase A
- libzim native snippets (`SearchIterator.getSnippet()`) are the canonical passage source for `synthesize` — Phase A's #1 work made this possible.
- `_meta` envelope continues to populate on every response.
- Structured-suggestion `reason` codes (`0_hits`, `low_relevance`) reused for `synthesize`'s zero-hits path.

### Inherited from Phase B
- TypedDict-based responses with `Union[<Response>, ToolErrorPayload]` annotations — Phase C follows the same pattern for `GetSectionResponse` and `SynthesizeResponse`.
- FastMCP's `{"result": ...}` envelope for Union-return tools — Phase C inherits this; tests use the wrapper-tolerant unwrap.
- `attach_meta()` helper for `_meta` population — used by every Phase C `_data` method.
- Cursor module (`pagination.py`) is unchanged in Phase C; no Phase C tools paginate.

### Hooks for Phase D (cross-encoder reranker)
- `synthesize` pipeline's Stage 3 is identity in Phase C. Phase D injects the cross-encoder there with no change to the surrounding stages.
- `SynthesizeResponse.fallback_used` already accommodates `"reranker"` as a value.
- `SynthesizeConfig` will gain a `reranker_model` knob in Phase D; Phase C's config block is structured to accept additions.

### Hooks for Phase E (offline build artifacts)
- The bundle extractor is a pure function over an open archive; Phase E's CLI can call it directly to produce `<archive>.zim.bundles.sqlite` sidecar (per-entry bundle cache).
- `get_or_build_bundle` can grow a sidecar-aware code path in Phase E without changing its signature.

### Hooks for Phase F (tool surface collapse)
- `get_section` will rename to `zim_get_section` as part of the 21→8 collapse. The data layer (`_get_section_data`) is named consistently with sibling tools so Phase F can rewire the registration without touching the data path.
- `zim_query` becoming a fully structured response across all modes is Phase F. Phase C's `Union[str, SynthesizeResponse, ToolErrorPayload]` is a transitional shape; Phase F unifies it.

---

## Housekeeping (folded into the Phase C PR)

These land as the first commits on `v2-phase-c`, before any feature code, so the PR has a clean lead-in and labels are in place when the PR opens.

1. **Add GitHub labels.** `gh label create v2 --description "v2 effort" --color C5DEF5`; same for `v2-phase-c`. Apply `v2-phase-b` label to PR #111 retroactively. (Labels for `v2-phase-a` may also be created if missing.)
2. **Remove stale `[[tool.mypy.overrides]] module = ['libzim']` block from `pyproject.toml`.** mypy now flags it as "unused section." Single-line cleanup.

---

## Out of scope (explicit deferrals)

| Item | Where it lands |
|---|---|
| Cross-encoder reranker | Phase D (#6) |
| `[planner]` extra (query rewriting / decomposition) | Phase D (#8) |
| Hybrid intent parser (regex + classifier) | Phase D (#12) |
| Sentence-embedding sidecar | Phase D (#15) |
| Persistent bundle sidecars | Phase E |
| Inbound link-graph sidecar | Phase E (#16) |
| Archive-type presets | Phase E (#17) |
| Tool surface collapse (21 → 8) | Phase F (#9) |
| `zim_query` becoming structured-only | Phase F |
| Sub-section pagination of mega-sections | Revisit only if tests surface real pain |
| Archive-nickname citation format | Out — verbose-but-stable basenames are sufficient |
