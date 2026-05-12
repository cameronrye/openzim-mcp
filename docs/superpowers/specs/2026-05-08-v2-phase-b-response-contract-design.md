# v2 Phase B — Response Contract (Design Spec)

**Status:** Draft
**Phase:** B of 6 ([tracking doc](../../v2/README.md))
**Items in scope:** #3 (standard pagination contract), #13 (`structuredContent` everywhere)
**Target:** `v2.0.0a2`
**Date:** 2026-05-08

---

## Goal

Standardize the wire format of every list-returning tool in [`openzim_mcp`](../../../openzim_mcp/) so that smaller, less capable LLMs see one consistent response shape regardless of which tool they call. Phase B does this in two coordinated breaking changes:

1. **Standard pagination contract** — every list-returning tool returns a `PaginatedResponse[T]`-shaped object with the same five contract keys (`results`, `next_cursor`, `total`, `done`, `page_info`) regardless of whether the tool actually paginates.
2. **TypedDict return types** — every dict-returning tool migrates from `Dict[str, Any]` (which FastMCP wraps in a generic `{"result": ...}` envelope with no schema) to a `Union[<SuccessResponse>, ToolErrorPayload]` annotation that produces a real output schema. Because the annotation is a `Union` (the error envelope is in-band), FastMCP wraps the payload in a single uniform `{"result": ...}` envelope on the wire — but the inner content now carries a real schema (`anyOf: [<SuccessTypedDict>, ToolErrorPayload]`). This is one consistent extra layer for every migrated tool, far better than v1's mixed schema-less wrapping.

These ship as one bundled PR off `v2-phase-b` because they're entangled: the pagination contract requires real schemas to be useful, and the schema migration requires a consistent shape to be tractable.

> **Note on FastMCP wrapping:** FastMCP's `func_metadata` (`mcp.server.fastmcp.utilities.func_metadata._try_create_model_and_schema`) wraps every non-single-TypedDict return type — including every `Union[<SuccessResponse>, ToolErrorPayload]` annotation — in a top-level `{"result": ...}` envelope on the wire. Phase B accepts this uniform wrapper deliberately: it's better than v1's schema-less wrapping because the inner content now carries a real schema (`anyOf: [<SuccessTypedDict>, ToolErrorPayload]`), and uniformity ("always look in `result`") is friendlier to small clients than a mixed-shape contract. Tests should assert against `structured["result"]` (or the wrapper-tolerant equivalent `structured.get("result", structured)` — see the helper pattern in [`tests/test_structured_tool_output.py`](../../../tests/test_structured_tool_output.py)).

## Non-goals

- No new tools. Tool surface collapse is Phase F (#9).
- No tool removals. Items become options, not deletions.
- No new ML deps. Phase B introduces no Python deps; the existing `tiktoken` from Phase A and the existing libzim bindings cover everything.
- No change to error semantics. Errors continue to flow as `ToolErrorPayload` data with `error: True`. Switching to MCP `isError` + raised exceptions is a Phase F refactor.
- No change to Phase A's `_meta` envelope. It stays where it is, sibling to the contract keys.
- No change to the resource endpoints in [`tools/resource_tools.py`](../../../openzim_mcp/tools/resource_tools.py). Those return JSON strings via the MCP **resource** surface, which is distinct from the **tool** surface this spec governs.
- No expansion of the cross-archive paging story. `search_all` keeps its single-shot fan-out shape (no top-level pagination across many archives) — that's a Phase F concern.

## Foundational decisions inherited from the v2 tracking doc

1. **Clean breaks allowed.** Phase B is a wire-format break for every list-returning tool. No deprecation period; v1.x branch receives no Phase B backports.
2. **ML accelerators opt-in via extras.** Phase B introduces no ML deps.
3. **Offline-first.** Phase B touches no network code paths.
4. **Markdown for prose, JSON for navigation, no XML.** Phase B is structural; markdown footers from Phase A continue to render unchanged.
5. **Phase A `_meta` envelope is canonical.** Phase B does **not** relocate it; the tracking doc's hint that Phase B "may collapse the duplication" was about empty-result prose, which Phase A already handled.

## Decisions captured during brainstorming

These resolved during the design conversation; the spec does not re-litigate them.

| Decision | Choice |
|---|---|
| Integer `offset` as input | **Kept** alongside `cursor`; if both supplied, `cursor` wins. |
| `done` and `next_cursor` co-presence | **Both always present.** Redundant by design. `done=true` ⟺ `next_cursor=None`. |
| #13 scope | **All dict-returning tools** migrate to TypedDict, not just the seven named in the tracking doc. |
| PR shape | **Single bundled PR** off `v2-phase-b`. |
| Canonical response shape | Approach 1 — uniform `PaginatedResponse`-shaped TypedDict for every list-returning tool, paged or not. |
| `extract_article_links` 3-category problem | **Require `kind`** (default `"internal"`); single category per call. |
| Cursor identity | **Tool-bound** — server rejects cross-tool reuse. Versioned for forward-compat. |
| Error envelope | **Keep error-as-data.** Function returns `Union[<SuccessTypedDict>, ToolErrorPayload]`. |

---

## Architecture

### New module

[`openzim_mcp/pagination.py`](../../../openzim_mcp/pagination.py) — promotes the existing [`PaginationCursor`](../../../openzim_mcp/zim/archive.py#L80-L142) from `zim/archive.py` to a top-level module and extends it with versioning, tool-binding, and per-tool state. Existing imports update.

```python
class CursorState(TypedDict, total=False):
    """Tool-specific state inside a cursor payload."""
    o: int          # offset (search, browse, links)
    l: int          # limit
    q: str          # query (search, search_all per-file)
    ns: str         # namespace (browse_namespace, walk_namespace)
    scan_at: int    # entry id (walk_namespace — replaces today's int cursor)
    ep: str         # entry path (extract_article_links)
    k: str          # kind: "internal" | "external" | "media"
    ct: str         # content_type (search_with_filters)
    ai: str         # archive identity (12-char SHA-256 truncation of validated path)

class CursorPayload(TypedDict):
    v: int                       # cursor version, currently 2 (v=1 cursors are rejected)
    t: str                       # tool name (e.g., "browse_namespace")
    s: CursorState               # tool-specific state

class Cursor:
    @staticmethod
    def encode(*, tool: str, state: CursorState, version: int = 2) -> str: ...
    @staticmethod
    def decode(token: str, *, expected_tool: str) -> CursorPayload:
        # Raises CursorMismatchError on tool mismatch (caller maps to tool_error).
        # Raises ValueError on malformed token or unsupported version.
```

> **Cursor version note.** Implementation shipped at ``v=2`` to bake the ``s.ai``
> archive-identity field into the wire format. ``v=1`` (no ``ai``) is rejected
> by the decoder. Callers building cursors by hand must emit ``v=2`` payloads.

[`openzim_mcp/tool_schemas.py`](../../../openzim_mcp/tool_schemas.py) — central home for the `PageInfo`, per-item, and per-tool response TypedDicts. Tool modules import from here rather than defining inline TypedDicts. This keeps the schema surface auditable in one file and makes it easy to spot drift between tools.

### Touched modules

| Module | Changes |
|---|---|
| [`openzim_mcp/responses.py`](../../../openzim_mcp/responses.py) | No change to `ToolErrorPayload` or `tool_error()`. The Union return annotations live in tool modules. |
| [`openzim_mcp/zim/archive.py`](../../../openzim_mcp/zim/archive.py) | `PaginationCursor` removed (moved to `openzim_mcp/pagination.py`). Imports updated. |
| [`openzim_mcp/zim/search.py`](../../../openzim_mcp/zim/search.py) | All `_data` methods return TypedDict-shaped payloads (`SearchResponse`, `FindEntryResponse`, `SearchSuggestionsResponse`, `SearchAllResponse`). Pagination keys conform to contract; `pagination` nested block removed; `total_results` → `total`; cursors round-trip through `Cursor.encode/decode` with `t="search_zim_file"` etc. |
| [`openzim_mcp/zim/namespace.py`](../../../openzim_mcp/zim/namespace.py) | `browse_namespace_data`, `walk_namespace_data`, `list_namespaces_data` return TypedDict-shaped payloads. `total_in_namespace` → `total`; `total_in_namespace_is_lower_bound` → `page_info.total_is_lower_bound`; `walk_namespace`'s int `cursor` becomes opaque (encoded `scan_at`); `total_entries` deprecated alias removed. |
| [`openzim_mcp/zim/structure.py`](../../../openzim_mcp/zim/structure.py) | `extract_article_links_data` requires `kind` (defaults `"internal"`); returns single-category `LinksResponse`; `category_totals: {internal, external, media}` replaces three `total_*_links` fields. `get_table_of_contents_data` and `get_article_structure_data` return their respective TypedDicts. |
| [`openzim_mcp/zim/content.py`](../../../openzim_mcp/zim/content.py) | `get_binary_entry_data`, `get_main_page` (where applicable), and `_data` shapes for entry-fetching tools migrate to TypedDicts. Phase A's `_meta` continues to attach. |
| [`openzim_mcp/tools/*.py`](../../../openzim_mcp/tools/) | Every `@server.mcp.tool()` registration updates its return annotation to the appropriate `Union[<SuccessResponse>, ToolErrorPayload]`. Input signatures gain `cursor: Optional[str] = None` where applicable; existing `offset` parameters remain. |
| [`openzim_mcp/simple_tools.py`](../../../openzim_mcp/simple_tools.py) | Compact-mode footer continues to read `_meta`; the `pagination` nested block reads disappear (footer code becomes simpler). |
| `tests/` | Per-tool tests update for new keys; `tests/test_structured_tool_output.py` extends to cover every migrated tool; new `tests/test_pagination_cursor.py` covers the `Cursor` API. |
| `README.md`, `CHANGELOG.md` | Document the new contract; CHANGELOG entry under `## [2.0.0a2]`. |

### What does **not** change

- No tool name changes. (That's Phase F.)
- No tool removals. (That's Phase F.)
- Phase A's `_meta` envelope shape (`tokens_est`, `chars`, `truncated`, `more_at_offset`, `total_chars`, `suggestions`, `reason`).
- `compact=False` markdown output remains markdown — the structural changes are dict-side only.
- `tool_error()` shape and the `ToolErrorPayload` TypedDict.
- The simple-mode (`zim_query`) external surface.

---

## The `PaginatedResponse` contract

Every list-returning tool returns a TypedDict that includes these five contract keys plus `_meta`:

```python
class PageInfo(TypedDict):
    offset: int                        # the offset this page started at
    limit: int                         # the limit honored
    returned_count: int                # len(results)
    total_is_lower_bound: NotRequired[bool]  # only for sampling-based browse

class MetaEnvelope(TypedDict, total=False):
    tokens_est: int
    chars: int
    truncated: bool
    more_at_offset: int
    total_chars: int
    suggestions: list[dict]
    reason: str

# Per-tool response TypedDicts subclass this conceptually but Python 3.12
# doesn't support generic TypedDict cleanly, so we declare contract keys
# on each per-tool TypedDict directly. Examples below.

class SearchHit(TypedDict):
    path: str
    title: str
    score: float
    snippet: str
    zim_file: str

class SearchResponse(TypedDict):
    # contract keys
    results: list[SearchHit]
    next_cursor: Optional[str]
    total: Optional[int]
    done: bool
    page_info: PageInfo
    _meta: MetaEnvelope
    # tool-specific extras
    query: str
```

### Field semantics

| Field | Type | Always present? | Notes |
|---|---|---|---|
| `results` | `list[T]` | Yes | The page of items. Empty `[]` on zero hits. Never `None`. |
| `next_cursor` | `Optional[str]` | Yes (may be `None`) | Opaque base64 cursor. `None` ⟺ last page. |
| `total` | `Optional[int]` | Yes (may be `None`) | Best-known total across all pages. `None` when not knowable mid-scan (e.g., `walk_namespace`). For sampling-based namespace discovery, the integer is a lower bound — `page_info.total_is_lower_bound: true` flags this. |
| `done` | `bool` | Yes | Redundant with `next_cursor=None` (always co-vary). Provided so a model gets a one-glance boolean. |
| `page_info.offset` | `int` | Yes | Start position of this page in the underlying paging state. For offset-paginated tools (`search_zim_file`, `browse_namespace`, `extract_article_links`, etc.) it's the integer offset. For the streaming scan in `walk_namespace`, it's the entry id (`scan_at`) the page resumed at — `0` on the first page. The interpretation is tool-specific but the field is always populated. |
| `page_info.limit` | `int` | Yes | Limit honored on this page. |
| `page_info.returned_count` | `int` | Yes | `len(results)`. Redundant; included for ergonomics. |
| `page_info.total_is_lower_bound` | `bool` | Only on sampling-based browse | Documents that `total` is a discovered minimum, not the true count. |
| `_meta` | `MetaEnvelope` | Yes (Phase A) | Unchanged from Phase A. Sibling to contract keys. |

### Tools that don't paginate

`find_entry_by_title`, `get_search_suggestions`, `list_zim_files`, `get_related_articles`, the top-level of `search_all`, and `get_zim_entries` (batch fetch) all use the same shape with `next_cursor=None, done=True, total=len(results), page_info.offset=0, page_info.limit=<as_requested>`. **Every list-returning tool has the same five contract keys regardless of whether it paginates.** A model that learns "list tool" learns one shape.

`list_namespaces` is the one exception — it returns a dict-of-summaries keyed by namespace letter, not a list, so the contract doesn't apply (see the next sub-section).

### `list_namespaces` is not a list

`list_namespaces` returns a dict keyed by namespace letter (`{"C": {...}, "M": {...}}`), not a list. It does not get `PaginatedResponse` keys. Its own TypedDict is:

```python
class NamespaceSummary(TypedDict):
    total: int                   # renamed from `entry_count`
    is_authoritative: bool

class ListNamespacesResponse(TypedDict):
    total_entries: int
    sampled_entries: int
    has_new_namespace_scheme: bool
    is_total_authoritative: bool
    discovery_method: str
    namespaces: dict[str, NamespaceSummary]
    _meta: MetaEnvelope
```

This is the only list-shaped result that doesn't fit the `PaginatedResponse` contract; calling it out explicitly so the rule "every list-returning tool has the same shape" holds (`list_namespaces` returns a dict-of-summaries, not a list).

---

## Cursor format

### Wire format

Cursors are URL-safe base64-encoded JSON of the following shape:

```json
{
  "v": 1,
  "t": "browse_namespace",
  "s": {"o": 50, "l": 50, "ns": "C"}
}
```

### Required fields

- `v` (int) — version. Currently `1`. New required fields in future versions bump `v`; new optional fields ride v=1.
- `t` (str) — tool name. Must match the tool decoding the cursor. On mismatch, the server returns `tool_error(operation=..., message="cursor was issued by '<other_tool>', cannot be used here")`.
- `s` (object) — tool-specific state.

### Per-tool state shapes

| Tool | State keys |
|---|---|
| `search_zim_file` | `o` (offset), `l` (limit), `q` (query) |
| `search_with_filters` | `o`, `l`, `q`, plus optional `ns` (namespace), `ct` (content_type) |
| `browse_namespace` | `o`, `l`, `ns` |
| `walk_namespace` | `scan_at` (entry id), `l` |
| `extract_article_links` | `o`, `l`, `ep` (entry path), `k` (kind) |
| `search_all` | per-archive cursors only; same shape as `search_zim_file` with `t="search_zim_file"`. The top-level `search_all` shape doesn't paginate, so it never emits a top-level cursor. |

### Encoding API

```python
from openzim_mcp.pagination import Cursor

next_cursor = Cursor.encode(
    tool="browse_namespace",
    state={"o": 50, "l": 50, "ns": "C"},
)  # -> str (URL-safe base64)

decoded = Cursor.decode(token, expected_tool="browse_namespace")
# decoded is CursorPayload; raises CursorMismatchError on tool mismatch
# or ValueError on malformed token. Tool wrappers catch both and emit tool_error.
```

### Input precedence

When a tool accepts both `cursor` and `offset`:

1. If `cursor` is non-null, decode it; on success, derive offset/limit/query/etc. from `cursor.s`. Ignore the `offset`/`limit` arguments.
2. If `cursor` is null, use the `offset`/`limit` arguments directly (default `offset=0`).
3. If both are supplied and the cursor is invalid, return `tool_error` (don't silently fall through to offset-mode — that would mask client bugs).

This rule is documented in every paged tool's docstring.

### Why tool-bound

A `search_zim_file` cursor carries `{o, l, q}`. Passing it to `browse_namespace` (which expects `ns` instead of `q`) would silently misbehave: namespace decoder sees a missing `ns` and returns the wrong page. The `t` field eliminates this class of bug at near-zero cost (~10 bytes in the encoded token).

### Why versioned

Adding a new optional cursor field later (e.g., a `since` timestamp for live archives) doesn't require a new wire format. Decoder ignores unknown keys at v=1; future v=2 cursors carry whatever new required fields demand.

---

## Per-tool changes

This section enumerates every tool. For each tool, "Today" shows the v1.3.0 response shape; "v2 Phase B" shows the new shape.

### `search_zim_file`

**Inputs.** `zim_file_path`, `query`, `limit?`, `offset?`, `cursor?` — `cursor` newly added; `offset` retained.

**Today (selected keys):**
```json
{
  "query": "berlin",
  "total_results": 42,
  "offset": 0, "limit": 20,
  "results": [...],
  "pagination": {"has_more": true, "showing_start": 1, "showing_end": 20, "next_cursor": "..."}
}
```

**v2 Phase B:**
```json
{
  "query": "berlin",
  "results": [...],
  "next_cursor": "<base64>",
  "total": 42,
  "done": false,
  "page_info": {"offset": 0, "limit": 20, "returned_count": 20},
  "_meta": {...}
}
```

Removed: `pagination` nested block, `total_results`, `pagination.showing_start/showing_end` (the model can derive them from offset+limit+returned_count if needed; they bloat the response).

### `search_all`

**Inputs.** `query`, `limit_per_file?`. No top-level cursor; pagination happens per-archive.

**v2 Phase B:**
```json
{
  "query": "berlin",
  "files_searched": 4,
  "files_with_hits": 2,
  "results": [
    {"zim_file_path": "...", "name": "...", "result": {<SearchResponse>}, "has_hits": true},
    ...
  ],
  "next_cursor": null,
  "total": 4,
  "done": true,
  "page_info": {"offset": 0, "limit": 4, "returned_count": 4},
  "_meta": {...}
}
```

`results[].result` is itself a full `PaginatedResponse` (each archive can be paged independently via its own cursor). The top-level paginates trivially (always `done=true`) so the contract holds at every level.

### `search_with_filters`

Today returns a markdown string. **v2 Phase B:** returns `SearchResponse`-shaped TypedDict (same shape as `search_zim_file`, with `query`, `namespace_filter`, `content_type_filter` as tool-specific extras). Cursor `t="search_with_filters"`.

### `find_entry_by_title`

**Inputs.** `query`, `limit?`. No cursor (no natural pagination — it's a best-N lookup).

**v2 Phase B:**
```json
{
  "query": "Berlin",
  "results": [...],
  "next_cursor": null,
  "total": 3,
  "done": true,
  "page_info": {"offset": 0, "limit": 10, "returned_count": 3},
  "fast_path_hit": true,
  "files_searched": 1,
  "_meta": {...}
}
```

### `get_search_suggestions`

**Inputs.** `partial_query`, `limit?`. No cursor.

**v2 Phase B:**
```json
{
  "partial_query": "berl",
  "results": [
    {"text": "Berlin", "path": "C/Berlin", "type": "title"},
    ...
  ],
  "next_cursor": null,
  "total": 5,
  "done": true,
  "page_info": {"offset": 0, "limit": 10, "returned_count": 5},
  "_meta": {...}
}
```

Renamed: `suggestions` → `results`. (The Phase A `_meta.suggestions[]` recovery candidates are a separate concept — they live inside `_meta` and stay there. The top-level `results` is the paginated list of *autocomplete* suggestions.) `count` is removed; `page_info.returned_count` covers it.

### `browse_namespace`

**Inputs.** `zim_file_path`, `namespace`, `limit?`, `offset?`, `cursor?`.

**v2 Phase B:**
```json
{
  "namespace": "C",
  "results": [
    {"path": "C/Berlin", "title": "Berlin", "content_type": "text/html", "preview": "..."},
    ...
  ],
  "next_cursor": "<base64>",
  "total": 100,
  "done": false,
  "page_info": {"offset": 0, "limit": 50, "returned_count": 50, "total_is_lower_bound": true},
  "discovery_method": "sampled",
  "sampling_based": true,
  "results_may_be_incomplete": false,
  "_meta": {...}
}
```

Renamed: `entries` → `results`, `total_in_namespace` → `total`, `total_in_namespace_is_lower_bound` → `page_info.total_is_lower_bound`. Removed: `has_more` (use `done`); top-level `is_total_authoritative` (covered by `page_info.total_is_lower_bound`'s presence).

### `walk_namespace`

**Inputs.** `zim_file_path`, `namespace`, `limit?`, `cursor?` (was `cursor: int`, now opaque str).

**v2 Phase B:**
```json
{
  "namespace": "C",
  "results": [{"path": "C/Berlin", "title": "Berlin"}, ...],
  "next_cursor": "<base64>",
  "total": null,
  "done": false,
  "page_info": {"offset": 0, "limit": 200, "returned_count": 200},
  "scanned_count": 412,
  "scanned_through_id": 5234,
  "archive_entry_count": 1000000,
  "_meta": {...}
}
```

`total` is `null` because `walk_namespace` doesn't know the per-namespace count until it finishes scanning; `scanned_count` and `archive_entry_count` give the model enough information to estimate progress without misleading it about an authoritative total. Removed: `total_entries` (already-deprecated alias), `cursor` (input/output now lives in `next_cursor` opaque token), `total_in_namespace` (use `total`).

### `extract_article_links`

**Inputs.** `zim_file_path`, `entry_path`, `kind` (now **required**, default `"internal"`), `limit?`, `offset?`, `cursor?`.

**Today:** returns three lists with three pagination flags.

**v2 Phase B:**
```json
{
  "title": "Berlin",
  "path": "C/Berlin",
  "content_type": "text/html",
  "kind": "internal",
  "results": [{"target": "C/Germany", "label": "Germany"}, ...],
  "next_cursor": "<base64>",
  "total": 187,
  "done": false,
  "page_info": {"offset": 0, "limit": 100, "returned_count": 100},
  "category_totals": {"internal": 187, "external": 23, "media": 5},
  "_meta": {...}
}
```

Removed: `internal_links`, `external_links`, `media_links` arrays (now `results` for the requested category); `total_internal_links`/`total_external_links`/`total_media_links` (now `category_totals`); `pagination` nested block (now top-level).

To get all three categories, callers make three calls. This is a clean break — the prior multi-category response was awkward for paginated use anyway (per-category cursors interleaved poorly).

### `list_zim_files`

**Inputs.** `name_filter?`. No cursor.

**v2 Phase B:**
```json
{
  "name_filter": null,
  "directories_count": 1,
  "results": [{"name": "...", "path": "...", "directory": "...", "size": "1.2 GB", "size_bytes": 1234567890, "modified": "..."}, ...],
  "next_cursor": null,
  "total": 4,
  "done": true,
  "page_info": {"offset": 0, "limit": 4, "returned_count": 4},
  "_meta": {...}
}
```

Renamed: `files` → `results`, `count` → `total`.

### `get_related_articles`

**Inputs.** `zim_file_path`, `entry_path`, `limit?`. No cursor.

**v2 Phase B:**
```json
{
  "entry_path": "C/Berlin",
  "results": [{"path": "C/Germany", "title": "Germany", "link_text": "Germany"}, ...],
  "next_cursor": null,
  "total": 7,
  "done": true,
  "page_info": {"offset": 0, "limit": 10, "returned_count": 7},
  "_meta": {...}
}
```

Renamed: `outbound_results` → `results`. (Anticipates the Phase E inbound link-graph feature, where `direction` becomes a parameter and `results` covers either side.)

### `get_zim_entries` (batch fetch)

Returns a list of entry-fetch results. Gets the full contract with `next_cursor=null, done=true, total=len(results)` since batch fetch doesn't paginate (the caller already supplied an explicit list of paths). The TypedDict is `BatchEntryResponse` with `results: list[EntryResponse]` plus the contract keys.

### Non-list tools (TypedDict only, no contract keys)

These tools return non-list payloads and get TypedDict migrations only — no `PaginatedResponse` shape:

| Tool | Response TypedDict | Notes |
|---|---|---|
| `get_zim_metadata` | `ZimMetadataResponse` | Existing keys preserved; just typed. |
| `get_zim_entry` / `get_main_page` | `EntryResponse` | Includes `_meta` with `more_at_offset` for Phase A truncation. |
| `get_entry_summary` | `EntrySummaryResponse` | Existing keys typed. |
| `get_table_of_contents` | `TableOfContentsResponse` | Tree, not list. Existing keys typed. |
| `get_article_structure` | `ArticleStructureResponse` | Existing keys typed. |
| `get_binary_entry` | `BinaryEntryResponse` | Existing keys typed; base64 `data` field annotation `Optional[str]`. |
| `list_namespaces` | `ListNamespacesResponse` | Dict-of-summaries; not a list. |
| `get_server_health` / `get_server_configuration` | typed where they're not already | Mostly already typed via existing TypedDict. |

---

## Removed wire-format keys (clean break)

| Removed key | Tool(s) | Replaced by |
|---|---|---|
| `pagination` nested block | search_zim_file, search_with_filters, browse_namespace, extract_article_links | top-level `next_cursor`, `done`, `total`, `page_info` |
| `pagination.showing_start` / `showing_end` | search_zim_file | derivable from `page_info.offset + page_info.returned_count`; not surfaced |
| `has_more` | browse_namespace, walk_namespace | `done` (polarity flip; `done = !has_more`) |
| `total_results` | search_zim_file | `total` |
| `total_in_namespace` | browse_namespace | `total` |
| `total_in_namespace_is_lower_bound` | browse_namespace | `page_info.total_is_lower_bound` |
| `is_total_authoritative` | browse_namespace top-level | `page_info.total_is_lower_bound` (presence ⟺ non-authoritative) |
| `total_entries` | walk_namespace (already deprecated in v1) | removed |
| `cursor: int` (input + output) | walk_namespace | `cursor: str` opaque |
| `entries` | browse_namespace, walk_namespace | `results` |
| `outbound_results` | get_related_articles | `results` |
| `suggestions` (top-level list) | get_search_suggestions | `results` |
| `files` | list_zim_files | `results` |
| `count` | list_zim_files | `total` |
| `total_internal_links` / `total_external_links` / `total_media_links` | extract_article_links | `category_totals` |
| `internal_links` / `external_links` / `media_links` (parallel lists) | extract_article_links | `results` (single category per call) |
| FastMCP `{"result": ...}` outer wrapper | every dict-returning tool | uniform `{"result": ...}` wrapper around a real-schema TypedDict (FastMCP wraps `Union` returns; we keep the wrapper but the inner shape now has a real schema — see [Note on FastMCP wrapping](#goal)) |

The Phase A `_meta` envelope and all its keys are unchanged.

---

## Error handling

Every tool's return annotation becomes `Union[<SuccessTypedDict>, ToolErrorPayload]`:

```python
async def browse_namespace(...) -> Union[BrowseNamespaceResponse, ToolErrorPayload]: ...
```

FastMCP emits `anyOf` in the schema; clients branch on the presence of `error: True`. Behavior is unchanged from v1: rate limits, validation failures, decode errors, and unexpected exceptions all return error data.

### New error path: cursor decode

When `Cursor.decode` raises:
- `ValueError` (malformed token) → `tool_error(operation="<tool>", message="Invalid pagination cursor: <reason>", context=f"cursor=<truncated>")`
- `CursorMismatchError` (wrong tool) → `tool_error(operation="<tool>", message="Cursor was issued by '<other_tool>'; pass a cursor obtained from <tool>'s previous response.", context=...)`

### Empty list semantics

When zero results match:

```json
{
  "results": [],
  "next_cursor": null,
  "total": 0,
  "done": true,
  "page_info": {"offset": 0, "limit": <as_requested>, "returned_count": 0},
  "_meta": {"reason": "0_hits", "suggestions": [...]}
}
```

The Phase A footer continues to render the suggestions in compact mode.

---

## Configuration

Phase B introduces no new env vars or config knobs. The existing `OPENZIM_MCP_*` surface is unchanged.

---

## Testing

### New test files

- `tests/test_pagination_cursor.py` — `Cursor.encode/decode` round-trips, version handling, tool-binding rejection, malformed-token rejection, base64 padding tolerance.
- `tests/test_response_contract.py` — golden-shape assertions: every list-returning tool returns the five contract keys with the right types; non-paged tools have `done=true, next_cursor=null`; `page_info` shape conforms.

### Extended test files

- `tests/test_structured_tool_output.py` — extend to every dict-returning tool (today covers two pilots). Each tool asserts (a) `convert_result=True` returns a tuple (TypedDict path), (b) the structured payload is at `structuredContent.result` and conforms to its declared TypedDict (FastMCP wraps `Union[<SuccessResponse>, ToolErrorPayload]` returns in a single uniform envelope — see [Note on FastMCP wrapping](#goal)), (c) the inner payload exposes the contract keys for paged tools.
- `tests/test_search_tools.py`, `tests/test_navigation_tools.py`, `tests/test_metadata_tools.py`, `tests/test_structure_tools.py`, `tests/test_walk_namespace.py`, `tests/test_extract_article_links_pagination.py`, `tests/test_search_all.py` — update key assertions to new contract; remove assertions on removed keys.
- `tests/test_simple_tools.py` — verify compact-mode footer reads from the new shape (no `pagination` nested lookups).

### Migrated test surface

The test files above will need ~150 small key-rename updates (`pagination.next_cursor` → `next_cursor`, etc.). Mechanical work; flagged in the implementation plan.

### Golden-file regression

Phase A introduced `tests/test_golden_v2_phase_a.py` with 5-archive snapshots. Phase B adds `tests/test_golden_v2_phase_b.py` capturing the **new** contract shape for the same 5 fixture archives across the same prompt set. (The Phase A goldens stop matching after Phase B by design — they're a v1.x-compat anchor that's allowed to break here.)

### Performance budget

| Operation | Budget |
|---|---|
| `Cursor.encode` | ≤ 0.05 ms |
| `Cursor.decode` | ≤ 0.1 ms (includes JSON parse + tool-name check) |
| Per-tool TypedDict construction overhead | ≤ 0.1 ms per response |

All under existing tool latency by 2-3 orders of magnitude. No measurable regression expected; budget exists to catch surprises.

---

## Acceptance criteria

Phase B is shippable as `v2.0.0a2` when:

1. Every list-returning tool returns the five contract keys (`results`, `next_cursor`, `total`, `done`, `page_info`) with semantics matching this spec.
2. Every dict-returning tool's MCP registration uses a `Union[<SuccessTypedDict>, ToolErrorPayload]` return annotation; `tests/test_structured_tool_output.py` asserts the structured payload conforms to its declared TypedDict (whether or not FastMCP applies a `{"result": ...}` wrapper around `Union` returns — with the chosen `Union` annotation, the wrapper is present and uniform across all migrated tools; see [Note on FastMCP wrapping](#goal)).
3. Every paged tool accepts both `cursor` and `offset` as input; `cursor` wins on conflict; invalid cursors produce `tool_error`.
4. Cursor tool-binding works: passing a wrong-tool cursor produces a clear error.
5. `extract_article_links` requires `kind` (default `"internal"`) and emits `category_totals`.
6. `walk_namespace`'s integer cursor is gone from both input and output; `next_cursor` is opaque.
7. All removed keys (per the [Removed keys](#removed-wire-format-keys-clean-break) table) are absent from responses.
8. Phase A's `_meta` envelope is unchanged in shape and continues to populate.
9. Full unit + integration test suite passing on Python 3.12 and 3.13.
10. README updated with the new contract; CHANGELOG entry under `## [2.0.0a2]`.
11. No `tiktoken`/libzim/dependency changes.
12. Phase B golden file regression captured and passing.

---

## Release plan

- Branch: `v2-phase-b` off `main`.
- **Single bundled PR** targeting `v2-phase-b`. Logical commits within the PR (for reviewer ergonomics, not separate merges):
  1. `pagination`: introduce `openzim_mcp/pagination.py`; move `PaginationCursor`; add tool-binding + version field.
  2. `tool_schemas`: introduce `openzim_mcp/tool_schemas.py` with all per-tool TypedDicts and `PageInfo`.
  3. `search`: migrate `search_zim_file`, `search_all`, `search_with_filters`, `find_entry_by_title`, `get_search_suggestions`.
  4. `namespace`: migrate `browse_namespace`, `walk_namespace`, `list_namespaces`.
  5. `structure`: migrate `extract_article_links` (with `kind` requirement), `get_table_of_contents`, `get_article_structure`, `get_binary_entry`, `get_related_articles`.
  6. `entries`: migrate `get_zim_entry`, `get_zim_entries`, `get_entry_summary`, `get_main_page`, `get_zim_metadata`.
  7. `tests`: extend `test_structured_tool_output.py`; add `test_pagination_cursor.py` and `test_response_contract.py`; update existing tests; capture Phase B goldens.
  8. `docs`: README + CHANGELOG.
- After the PR merges into `v2-phase-b`, a single `v2-phase-b` → `main` PR for final review and tag.
- Tag: `v2.0.0a2`. Pre-release on PyPI; not promoted to "latest."
- v1.x branches receive no Phase B backports.

---

## Forward references

- **Phase C #11** (precomputed section index) will introduce `get_section` and may add tool-specific cursor state for section-level paging — handled cleanly by the versioned cursor format.
- **Phase D #15** (semantic embedding sidecar) hybrid retrieval will produce a fused result list paginated under the same `PaginatedResponse` contract.
- **Phase E #16** (inbound link-graph) will extend `get_related_articles` with a `direction` parameter; the existing `results` field already covers either direction.
- **Phase F #9** (tool collapse, 21 → 8) consolidates the many list-returning tools into `zim_search`, `zim_browse`, etc. — the unified contract makes that consolidation a name-mapping exercise rather than a shape exercise.
- **Future cursor v=2** will be needed if a tool requires a new mandatory state field. Until then, additive-only changes ride v=1.

---

## Open issues / accepted risks

- **TypedDict generic limitations.** Python 3.12 doesn't support generic TypedDict cleanly. Per-tool TypedDicts redeclare contract keys. Drift is prevented by `tests/test_response_contract.py`'s structural assertions, not by the type system. (Generic TypedDict in PEP 705 lands fully in 3.13+; revisitable then.)
- **Bulk test churn.** ~150 small assertion updates across test files. Mechanical; the implementation plan will sequence them after the production-code migration.
- **Documentation churn.** Every paginated tool's docstring needs rewriting. Counted into the PR's effort estimate.
