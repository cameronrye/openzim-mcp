# v2 Phase F — Tool Surface Consolidation (Design Spec)

**Status:** Revised — review-driven (2026-05-24)
**Phase:** F of 6 ([tracking doc](../../v2/README.md)) — final v2 phase
**Items in scope:** #9 — collapse 22-tool advanced surface to 8
**Targets:** Gate 0 (`oneOf` transport + small-model parsing) → `v2.0.0rc0` (pure refactor) → Gate 0b (dispatch eval against prototype) → `v2.0.0rc1` (surface change) → `v2.0.0`

---

## Goal

Reshape the MCP tool surface from **22 advanced-mode tools + 1 simple-mode tool (mutually exclusive via `tool_mode` config)** to an **8-tool advanced surface + 1-tool simple surface that share one code path, filtered at registration time by `tool_mode`**. The driver is the [MCP Tax](https://www.mmntm.net/articles/mcp-context-tax) finding that Haiku-class and 7-8B open-weights models show ~49% failure rate against schema sets in the 25–50KB range. The current advanced surface measures **36KB / ~9,000 schema tokens** — squarely inside the pain band. The v2.0.0rc1 advanced-mode surface lands at **~17.4KB** (wired-`oneOf`) or **~17.0KB** (flat-schema fallback if Gate 0 forces it). Both sit well below the 25KB lower threshold. The headline is "out of the pain band by collapsing 22 tools to 8."

**Release sequencing — three merging PRs + one non-merging prototype branch.** (1) **Gate 0 PR** on `v2-phase-f-gate-0` lands the `oneOf` transport-verification artifacts (Gate 0.1 emission + Gate 0.2 transport round-trip — and a spec amendment to flat schemas if either fails) — merges to main before rc0 branches. **Gate 0.3 (small-model `oneOf`-parsing benchmark) is NOT in this PR**; it moved to Stage B so it can run against the actual prototype skeleton schemas rather than synthetic stand-ins. (2) **`v2.0.0rc0` PR** ships the promotion-extraction refactor alone (diff-tested against the b1 → b13 cumulative probe set), held for manual sign-off after Cameron's ad-hoc probing. (3) **`v2-phase-f-prototype` branch (non-merging)** hosts both the Gate 0.3 ablation AND the Gate 0b dispatch eval against an in-progress 8-tool surface — used solely to produce `gate_0b_decision.json` and is never merged. (4) **`v2.0.0rc1` PR** ships the 8-tool surface change on top of the proven-clean refactor. Splitting these gives clean blame domain: a defect in rc1's sweep cannot be attributed to transport (Gate 0) or refactor (rc0) code.

This is the final v2 work item. When Phase F ships, v2.0.0 cuts and v1.x branches enter **maintenance mode** — see [v1.x maintenance commitment](#v1x-maintenance-commitment-rollback-runway) below.

## Non-goals

- **No new retrieval primitives.** Phase C's primitives (`get_section`, `synthesize` mode) are the ones we have. Phase F only renames `get_section` → `zim_get_section`.
- **No new ML accelerators or ML deps.** Phase D's reranker and Tier 1 query rewriting ship as-is. Phase F's wiring of NL preprocessing + promotion into `zim_search` is **conditional on Gate 0b's Criterion C outcome** — see [Criterion C circuit-breaker](#criterion-c-circuit-breaker-pre-decided-fallback).
- **No response-contract redesign.** Phase B's `_meta` envelope, cursor pagination, and `Union[<Response>, ToolErrorPayload]` return-shape pattern survive untouched.
- **No inbound-link runtime.** Phase E's link-graph sidecar moved to v2.5. At v2.0, `zim_links` ships with `direction: Literal["outbound","related"]` only. v2.5 #16 adds `inbound` as a non-breaking enum addition alongside the link-graph sidecar.
- **No new dependencies.**
- **No archive-format change.** The data layer below the tool registrations is largely untouched.
- **No two-mode coexistence.** The current `tool_mode = 'simple' | 'advanced'` split (completely different tool registrations per mode) collapses into a single code path with `tool_mode` as a registration-time filter.
- **No deprecation period.** v2 is a major release; old tool names disappear at `v2.0.0` per the foundational decisions in the v2 tracking doc.
- **No `compact=True` default flip on `zim_get`.** Earlier drafts uniformly defaulted `compact=True` across `zim_query`, `zim_get`, and `zim_get_section`. Phase F preserves `compact=True` on `zim_query` and `zim_get_section` (both already shipped that way at b13 — no break) but **defers the `zim_get` compact-default flip to v2.5**. Rationale: v2.0.0 stacks two independent risks on `zim_get` already (rename from `get_zim_entry` + new 4-branch `oneOf`); adding a default-behavior break on top makes post-release debugging harder. v2.5 will revisit the `zim_get` compact default with telemetry from real adoption. The `compact` *parameter* exists on `zim_get` at v2.0 (uniform surface) but defaults to `False`.
- **No `simple-extended` mode.** Earlier drafts considered a third `tool_mode` value (`zim_query` + `zim_search` + `zim_get`) gated by a 4-criterion Gate 0b adoption rule. Dropped: the opt-in path requires operators to read CHANGELOG to discover, and operators who want a 3-tool subset can wrap the advanced surface today. v2.0 ships binary `simple` / `advanced`. v2.5 may revisit if real demand emerges.

## Foundational decisions inherited from the v2 tracking doc

1. **Clean breaks allowed.** Tool renames and signature changes land in the v2.0.0 release line (which includes pre-release tags `v2.0.0rc0`, `v2.0.0rc1`, and the final `v2.0.0`); no aliases, no shims spanning v1.x → v2.0.0.
2. **ML accelerators opt-in via extras.** Phase F ships zero new ML deps.
3. **Offline-first.** No network code paths.
4. **Markdown for prose, JSON for navigation, no XML.** Already-shipped from Phase B.
5. **Phase A `_meta` envelope is canonical.** All Phase F tools carry `_meta`, populated via the existing `attach_meta()` helper.

## Design decisions

| Decision | Choice |
| --- | --- |
| Mode split | **Collapse to one code path.** Both `tool_mode` values run through the same `register_phase_f_tools(server)` orchestrator. `tool_mode = Literal["simple", "advanced"]` — binary, no third value. `simple` registers only `zim_query`; `advanced` registers all 8. `simple` is the v2.0.0 default (unchanged from v2.0.0b13). There is no longer a separate `_register_simple_tools` codebase to maintain. |
| Tool naming convention | **`zim_*` prefix on every tool.** Matches the v2 README sketch; gives the schema clear namespacing when clients connect to multiple MCP servers. |
| `get_binary_entry`, `find_entry_by_title`, `get_search_suggestions` | **Fold into the 8** via `mode=` / `binary=` parameters on `zim_search` and `zim_get`. |
| `get_entry_summary`, `get_table_of_contents`, `get_article_structure` | **Fold into `zim_get` via `view=`.** All three are slicers over the Phase-C EntryBundle; the bundle is built once and the response shape varies by `view`. |
| `list_zim_files` | **Fold into `zim_health`.** Server inventory belongs with server health and config. |
| `zim_links` v2.0 scope | **Outbound + related only.** `inbound` is **not in the v2.0 enum** — adding it in v2.5 alongside the link-graph sidecar is a non-breaking JSON-Schema-additive change. Reserving an unusable enum value at v2.0 creates a small-model failure mode (model attempts it, eats an error, gives up). |
| `zim_get_section` boundary | **Stays as its own tool.** Phase C shipped it as a separate tool; folding into `zim_get` now would be unnecessary churn. |
| `synthesize` mode | **Stays as `zim_query(synthesize=True)`.** Phase C already made this decision. |
| Cross-archive parameter shape | **`zim_file_path` is `Optional[str] = None` on query-style tools (`zim_search`, `zim_query`) and `str` (required) on entry-targeted tools.** Query-style tools auto-select when omitted. Entry-targeted tools require the archive to be explicit. `cross_file: bool = False` unlocks all-archive fan-out on `zim_search` (modes `fulltext` and `title`) and on `zim_query`. `mode="suggest"` rejects `cross_file=True` because libzim's `SuggestionSearcher` is per-archive. |
| `cross_file=True` + `mode="title"` promotion | **Promotion is disabled when `cross_file=True`.** The Z3/Z4/OPP-1 promotion layer is per-archive (it probes the title index of a specific archive). With `cross_file=True`, results merge across archives where the probe cannot run safely — applying promotion against one archive while returning others' results unfiltered would be inconsistent. The response includes `_meta.promotion_applied: false` and a `hint` documenting that pinning a specific archive enables promotion. Behaviorally matches v1.x `find_entry_by_title(cross_file=True)`. |
| Batch fetch shape on `zim_get` | **Single mutually-exclusive choice:** `entry_path: str` for one-shot OR `entry_paths: list[str]` for batch. Passing both is a validation error. |
| `compact` default on `zim_get` | **`False` at v2.0** (matches legacy `get_zim_entry`). The `compact` parameter exists on every body-returning tool for surface uniformity, but on `zim_get` the default preserves the pre-Phase-F behavior. `zim_query` and `zim_get_section` keep `compact=True` defaults — they already shipped that way at b13. The mixed defaults are documented in the migration table and the CHANGELOG. v2.5 revisits the `zim_get` default with telemetry. |
| Module organization | **One file per tool** under `openzim_mcp/tools/`. Eight files. Replaces the current domain-grouped files. |
| Schema-conditional parameters | **Use JSON Schema `oneOf` to gate mode-dependent parameters at the wire-schema level** when Gate 0 confirms transport + small-model parsing. `zim_search` exposes `namespace`/`content_type` only in the `mode="fulltext"` branch; exposes `cross_file` only in the `mode∈{"fulltext","title"}` branches. `zim_get` exposes `view` choices conditional on `binary` and on the path-shape (single/batch/main-page). Rationale: small models cannot reliably reason "this parameter is only valid when an earlier enum has value X" from prose. Schema-level conditional surfacing makes invalid combinations unrepresentable rather than detected-and-rejected. The handler still validates as defense-in-depth for clients that flatten `oneOf`. **If Gate 0.2 (transport) or Gate 0.3 (small-model parsing) reports STOP, the spec falls back to flat schemas + prose conditionals + handler validation.** |
| Release shape | **Three merging PRs to main + one non-merging prototype branch.** See [Release plan](#release-plan). |
| `zim_metadata` main-page hint | **No `main_page_path` field in the response.** Exposing it would create two paths to fetch the main page (`zim_get(main_page=True)` vs `zim_get(entry_path=metadata.main_page_path)` needing a null-check). Small models would construct the null-check path unnecessarily. The canonical fetch is `zim_get(main_page=True)`. |

---

## Architecture

### The 8-tool surface

#### 1. `zim_query`

**Signature:** unchanged from v2.0.0b13. NL entry point, intent classification, optional `synthesize=True` for Phase C's pipeline. The current ~6,300-byte description ships unchanged. Earlier drafts proposed a trimmed V1 variant gated by Gate 0b; dropped — the simpler ship-V0-everywhere design loses ~1.8KB of byte savings well below the noise floor on user-perceptible dispatch quality.

```python
async def zim_query(
    query: str,
    zim_file_path: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    content_offset: int = 0,
    cursor: Optional[str] = None,
    max_content_length: Optional[int] = None,
    compact: bool = True,
    compact_budget: Optional[Union[str, int]] = None,
    synthesize: bool = False,
) -> Union[str, SynthesizeResponse, ToolErrorPayload]: ...
```

#### 2. `zim_search`

**Signature:**

```python
async def zim_search(
    query: str,
    mode: Literal["fulltext", "title", "suggest"] = "fulltext",
    zim_file_path: Optional[str] = None,
    cross_file: bool = False,
    namespace: Optional[str] = None,
    content_type: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    cursor: Optional[str] = None,
) -> Union[SearchResponse, ToolErrorPayload]: ...
```

**Mode semantics.**

| `mode` | Behavior | Internally calls | Preprocessing / promotion |
| --- | --- | --- | --- |
| `"fulltext"` (default) | Xapian BM25 search with optional namespace / content-type filters. | `zim_operations.search_zim_file` or `search_all` | Tier 1 query rewriting + filler-prose stripping unconditionally. |
| `"title"` | Exact / typo-tolerant title lookup (case ladder + `SuggestionSearcher` + Levenshtein-1 expansion from Phase A #14). | `zim_operations.find_entry_by_title` | **Conditional on Gate 0b's `criterion_c_path`:** if `"wired"` (default), applies Tier 1 + filler-prose preprocessing AND Z3/Z4/OPP-1 promotion via the extracted `promote_topic_via_title_index` **only when `cross_file=False`**; if `"fallback"`, ships as explicit-string-only — see [Criterion C circuit-breaker](#criterion-c-circuit-breaker-pre-decided-fallback). |
| `"suggest"` | Prefix autocomplete via libzim `SuggestionSearcher`. Returns title candidates only (no snippets). | `zim_operations.get_search_suggestions` | None (autocomplete is by definition a prefix; preprocessing would defeat the use case). |

**Filter parameters.** `namespace` and `content_type` apply only to `mode="fulltext"`. At the schema level, the `inputSchema` is generated as a JSON Schema `oneOf` over the three modes; `namespace` and `content_type` only appear in the `mode="fulltext"` branch. Defense in depth: the handler still validates if a client flattens `oneOf` and sends an invalid combination.

**Cross-archive.** `cross_file=True` requires `zim_file_path` to be omitted; together they are mutually exclusive. `mode="fulltext"` and `mode="title"` support cross-archive; `mode="suggest"` does not (libzim `SuggestionSearcher` is per-archive).

**Promotion + cross-archive interaction.** Promotion (Z3/Z4/OPP-1) is per-archive — it probes a specific archive's title index. When `cross_file=True` AND `mode="title"`, promotion is disabled and the response includes `_meta.promotion_applied: false` plus a `hint` field documenting that pinning a specific archive enables promotion. This matches v1.x `find_entry_by_title(cross_file=True)` behavior and preserves Z4 protection only on the single-archive case where it can run consistently.

**Promotion + single-archive title mode — conditional on Gate 0b's Criterion C outcome.** In the **wired** path (default), `mode="title"` runs `find_entry_by_title` results through the same promotion filter that `zim_query`'s tell-me-about flow uses today, so a small model that routes `"Tesla electricity"` to `zim_search(mode="title")` instead of `zim_query` does not silently get `Tesla's_Wireless_Electricity`. Phase F extracts the promotion code to a module-level pure function in `openzim_mcp/topic_preprocessing.py` (the current code is an instance method on `SimpleToolsHandler` with a closure over `zim_file_path`, not callable as a simple cross-module import). The extracted form takes `zim_operations` and `zim_file_path` as explicit arguments. `SimpleToolsHandler._promote_topic_via_title_index` becomes a thin delegating wrapper; every existing call site continues to work unchanged.

The extraction is gated by a diff-test against the b1 → b13 cumulative probe set ([Gate 0a](#gate-0a--rc0-pure-refactor)) — byte-identical resolved-entry paths.

Sub-pattern C disambig handling stays bound to `_handle_tell_me_about`'s render-time flow regardless of path (it requires body fetch and is not reachable from `zim_search`).

**Collapses:** `search_zim_file` + `search_all` + `search_with_filters` + `find_entry_by_title` + `get_search_suggestions` (5 → 1).

#### 3. `zim_get`

**Signature:**

```python
async def zim_get(
    zim_file_path: str,
    entry_path: Optional[str] = None,
    entry_paths: Optional[list[str]] = None,
    view: Literal["full", "summary", "toc", "structure"] = "full",
    binary: bool = False,
    main_page: bool = False,
    max_content_length: Optional[int] = None,
    content_offset: int = 0,
    compact: bool = False,
    compact_budget: Optional[Union[str, int]] = None,
) -> Union[
    EntryResponse,
    BatchEntryResponse,
    EntrySummaryResponse,
    TableOfContentsResponse,
    ArticleStructureResponse,
    BinaryEntryResponse,
    ToolErrorPayload,
]: ...
```

**`compact` default is `False` at v2.0** — matches legacy `get_zim_entry` raw-markdown behavior, so the v1.x → v2.0 migration is rename-only on this axis. Callers who want the compacted shape opt in with `compact=True`. v2.5 revisits the default with adoption telemetry.

**`main_page` is a separate boolean flag, not a view value.** Earlier drafts overloaded `view="main_page"` as a fifth view enum, but that gave the type signature five view choices a small model would have to remember `entry_path` is forbidden for. Schema-flattening clients would parse the `view` enum literally and construct `zim_get(zim_file_path=X, entry_path=Y, view="main_page")` — a representable-looking but invalid combination. Promoting main-page to its own flag keeps the `view` enum focused on bundle slicers (full/summary/toc/structure) and makes the main-page dispatch a single-purpose boolean.

**Path semantics — schema-conditional, not runtime-validated.** The `inputSchema` is generated as a JSON Schema `oneOf` over four branches:

| Branch | Required | Optional | Forbidden in this branch |
| --- | --- | --- | --- |
| Single-entry, body view | `entry_path`, `view∈{"full","summary","toc","structure"}` | `binary` (only `False` allowed), `main_page` (only `False` allowed) | `entry_paths` |
| Single-entry, binary | `entry_path`, `binary=True` | (none — `view` locked to `"full"`) | `entry_paths`, `view∈{"summary","toc","structure"}`, `main_page=True` |
| Batch | `entry_paths`, `view∈{"full","summary","toc","structure"}` | (none) | `entry_path`, `binary=True`, `main_page=True` |
| Main page | `main_page=True` | (none — `view` ignored; defaults to `"full"`-shaped response) | `entry_path`, `entry_paths`, `binary=True`, `view∈{"summary","toc","structure"}` |

Defense in depth: the handler still returns structured `tool_error("invalid_path_combination", hint=...)` if a client flattens `oneOf` and sends an invalid combination anyway.

**View semantics.** Four bundle-view values; main-page is a separate flag (see above), not a view. The bundle views are slicers over the Phase-C EntryBundle; the bundle is built once per `(validated_path, entry_path)` and cached.

| `view` | Returns | Internally |
| --- | --- | --- |
| `"full"` (default) | `EntryResponse` — full rendered markdown body | bundle's `rendered_markdown`, optionally sliced by `content_offset` / `max_content_length` |
| `"summary"` | `EntrySummaryResponse` — short summary (first-section snippet or infobox if available) | bundle slice via `_extract_entry_summary_data` |
| `"toc"` | `TableOfContentsResponse` — nested `TocHeading` tree (Phase C tightened shape) | bundle's `sections` reassembled via `_extract_table_of_contents_data` |
| `"structure"` | `ArticleStructureResponse` — flat section list with char ranges and metadata | bundle's `sections` |

**Main-page fetch.** `main_page=True` is the dedicated path-free main-page fetch. Returns `EntryResponse` shaped like `view="full"`. Internally calls `zim_operations.get_main_page`. `view`, `entry_path`, `entry_paths`, and `binary` are all forbidden in this branch.

**Binary mode.** `binary=True` returns `BinaryEntryResponse`. Per the `oneOf` branch table, binary mode lives in its own branch where `view` is locked to `"full"` and `main_page` is forbidden. v2.0 keeps binary single-entry only (no batch binary fetch).

**Collapses:** `get_zim_entry` + `get_zim_entries` + `get_main_page` + `get_binary_entry` + `get_entry_summary` + `get_table_of_contents` + `get_article_structure` (7 → 1).

#### 4. `zim_get_section`

**Signature:** renamed from `get_section`, with `compact` and `compact_budget` added. The data layer (`_get_section_data`), response shape (`GetSectionResponse`), and error semantics stay identical from Phase C. `compact=True` is the default; callers preserving the legacy raw shape pass `compact=False`. This is a behavior break called out in the migration table.

```python
async def zim_get_section(
    zim_file_path: str,
    entry_path: str,
    section_id: str,
    max_chars: Optional[int] = None,
    compact: bool = True,
    compact_budget: Optional[Union[str, int]] = None,
) -> Union[GetSectionResponse, ToolErrorPayload]: ...
```

**Collapses:** rename of `get_section` (1 → 1).

#### 5. `zim_browse`

```python
async def zim_browse(
    zim_file_path: str,
    namespace: str,
    mode: Literal["page", "walk"] = "page",
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> Union[BrowseNamespaceResponse, WalkNamespaceResponse, ToolErrorPayload]: ...
```

- `"page"` (default) — page through namespace entries with cursor pagination (current `browse_namespace`).
- `"walk"` — enumerate the namespace with current `walk_namespace` semantics.

**Collapses:** `browse_namespace` + `walk_namespace` (2 → 1).

#### 6. `zim_metadata`

```python
async def zim_metadata(
    zim_file_path: str,
) -> Union[ArchiveMetadataResponse, ToolErrorPayload]: ...
```

**Returns** a combined response:

```python
class ArchiveMetadataResponse(TypedDict):
    metadata: dict[str, str]         # M-namespace fields: Name, Title, Creator, Date, …
    namespaces: list[NamespaceInfo]  # current list_namespaces shape
    _meta: MetaEnvelope
```

No `main_page_path` field. Main-page fetch is `zim_get(main_page=True)`.

**Collapses:** `get_zim_metadata` + `list_namespaces` (2 → 1; `get_main_page` moves to `zim_get`).

#### 7. `zim_links`

```python
async def zim_links(
    zim_file_path: str,
    entry_path: str,
    direction: Literal["outbound", "related"] = "outbound",
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> Union[ArticleLinksResponse, RelatedArticlesResponse, ToolErrorPayload]: ...
```

| `direction` | Behavior |
| --- | --- |
| `"outbound"` (default) | Current `extract_article_links` semantics — internal / external / media link buckets, paginated. |
| `"related"` | Current `get_related_articles` semantics — articles connected to this one (outbound-link overlap). |

v2.5 #16 adds `"inbound"` to the enum as a non-breaking additive change.

**Collapses:** `extract_article_links` + `get_related_articles` (2 → 1).

#### 8. `zim_health`

```python
async def zim_health() -> Union[ServerHealthResponse, ToolErrorPayload]: ...
```

**Returns** a combined response:

```python
class ServerHealthResponse(TypedDict):
    health: HealthStatus           # current get_server_health shape
    configuration: ServerConfig    # current get_server_configuration shape
    loaded_archives: list[ArchiveInfo]  # current list_zim_files shape
    _meta: MetaEnvelope
```

Single tool that answers "what is this server, what does it have, and is it OK."

**Collapses:** `get_server_health` + `get_server_configuration` + `list_zim_files` (3 → 1).

### Mode-as-filter (replacing the simple/advanced split)

The current `tool_mode` config has two values, with `'simple'` as the default. After Phase F, the 8 tools are registered through a single `register_phase_f_tools(server)` orchestrator. The `tool_mode` config key keeps the same spelling and only the registered tool *set* changes:

| `tool_mode` value | Behavior |
| --- | --- |
| `'simple'` (v2.0.0 default) | Only `zim_query` registered; the other 7 are skipped at registration time. |
| `'advanced'` | All 8 tools registered. The set is smaller (8 vs 22) but the config key keeps the name operators already use. |

No rename, no alias, no deprecation cycle.

**Default-install impact: unchanged tool count.** Default-install operators see exactly the same tool count at v2.0.0 as at v2.0.0b13 — one tool, `zim_query`, with the same description. The `simple` mode default has been hardened through 17 b-series sweeps; Phase F does not change it.

Operators who explicitly opted into the 22-tool surface (`tool_mode='advanced'`) see the surface shrink to 8 tools but make no config change.

The mode is a registration-time filter, not a separate code path — the same per-tool `register(server)` functions fire either way.

### Module reorganization

**Today** (`openzim_mcp/tools/`):

```
content_tools.py      get_zim_entry, get_zim_entries          (2 tools)
file_tools.py         list_zim_files                          (1)
metadata_tools.py     get_zim_metadata, get_main_page, list_namespaces  (3)
navigation_tools.py   browse_namespace, walk_namespace, search_with_filters, get_search_suggestions  (4)
search_tools.py       search_zim_file, search_all, find_entry_by_title  (3)
server_tools.py       get_server_health, get_server_configuration  (2)
structure_tools.py    get_article_structure, extract_article_links, get_entry_summary,
                      get_table_of_contents, get_binary_entry, get_related_articles, get_section  (7)
```

The domain grouping made sense at 22 tools but per-file complexity grew unevenly — `structure_tools.py` is 629 lines and conflates seven unrelated tools.

**After** (`openzim_mcp/tools/`):

```
zim_query.py           # always registered; the one tool every tool_mode value includes
zim_search.py          # advanced only
zim_get.py             # advanced only
zim_get_section.py     # advanced only
zim_browse.py          # advanced only
zim_metadata.py        # advanced only
zim_links.py           # advanced only
zim_health.py          # advanced only
__init__.py            # exposes register_phase_f_tools(server)
prompts.py             # untouched
resource_tools.py      # untouched
```

A sibling helper module is added at the package root (not under `tools/`):

```
openzim_mcp/topic_preprocessing.py   # NEW — narrow extraction host:
                                     #   promote_topic_via_title_index(zim_operations, zim_file_path, topic)
                                     #     extracted from SimpleToolsHandler._promote_topic_via_title_index.
                                     #   auto_select_zim_file(zim_operations)
                                     #     extracted from SimpleToolsHandler._auto_select_zim_file
                                     #     (verbatim port preserving try/except + 4-arm log emits).
                                     # Both are module-level pure functions.
                                     # Tier 1 / filler-prose / possessive helpers stay in intent_parser.py
                                     # and title_promotion.py (already cross-module-callable).
                                     # Called by zim_query (via simple_tools.py thin wrappers) and by
                                     # zim_search.py directly: auto_select_zim_file always,
                                     # promote_topic_via_title_index IFF Gate 0b takes the wired path.
```

`__init__.py` becomes:

```python
def register_phase_f_tools(server: "OpenZimMcpServer") -> None:
    """Register the v2 Phase F tool surface. Honors server.config.tool_mode."""
    from . import zim_query
    zim_query.register(server)

    if server.config.tool_mode == "simple":
        return  # 1-tool surface (default)

    # advanced — all 8
    from . import zim_search, zim_get, zim_get_section, zim_browse, zim_metadata, zim_links, zim_health
    for module in (zim_search, zim_get, zim_get_section, zim_browse, zim_metadata, zim_links, zim_health):
        module.register(server)
```

Each per-tool module exposes a single `register(server)` function. The current domain files are deleted.

### Internal layer untouched

| Layer | Status |
| --- | --- |
| `zim_operations.py` | **Unchanged.** |
| `async_operations.py` | **Mostly unchanged.** New wrappers added for `zim_health` (health + config + loaded-archives) and `zim_metadata` (metadata + namespaces). |
| `content_processor.py`, `bundle.py`, `synthesize.py` | **Unchanged.** |
| `pagination.py`, `cache.py`, `intent_parser.py` | **Unchanged.** |
| `simple_tools.py` | **Mostly unchanged.** Still backs `zim_query`; registered from `zim_query.py` instead of `server._register_simple_tools`. `SimpleToolsHandler._promote_topic_via_title_index` becomes a thin delegating wrapper around the extracted module-level `promote_topic_via_title_index`. |
| `topic_preprocessing.py` | **New file.** Hosts the extracted promotion orchestrator. Pure function taking `zim_operations` as an explicit argument. |
| `tool_schemas.py` | **Adds the new combined response types** (`ArchiveMetadataResponse`, `ServerHealthResponse` enriched with `loaded_archives`). |

The Phase F change is **almost entirely at the MCP-tool-registration boundary**.

---

## Schema budget validation

### Measurement methodology

Each tool's wire footprint = `len(json.dumps({"name": ..., "description": ..., "inputSchema": ...}).encode('utf-8'))`. This matches what an MCP client sees in its `tools/list` response.

### Today (v2.0.0b13)

| Mode | Tools | Bytes | Est. tokens (~4 chars/token) |
| --- | --- | --- | --- |
| Advanced | 22 | **36,131** | ~9,032 |
| Simple | 1 (`zim_query`) | ~6,300 | ~1,575 |

The advanced surface sits **inside the MCP Tax pain band** (25–50KB).

### Target (Gate 0 outcome)

| Mode | Tools | Wired `oneOf` (default) | Flat-schema fallback |
| --- | --- | --- | --- |
| `advanced` | 8 | **~17,400** | **~17,000** |
| `simple` | 1 (`zim_query`) | ~6,300 | ~6,300 |

Both cells sit well below the 25–50KB MCP Tax pain band. The tool-count reduction alone clears the pain band regardless of which Gate 0 outcome ships.

### Tool-by-tool budget allocation

| Tool | Wired `oneOf` (default) | Flat-schema fallback | Notes |
| --- | --- | --- | --- |
| `zim_query` | 6,300 | 6,300 | b13 description unchanged. No `oneOf` either way. |
| `zim_search` | 2,400 | 2,200 | Wired: 3-mode `oneOf` (+200 bytes). Flat: parameters listed flat + handler-level runtime validation. |
| `zim_get` | 3,200 | 3,000 | Wired: 4-branch `oneOf` (+200 bytes). |
| `zim_get_section` | 1,300 | 1,300 | Trim from current 2,243; absorbs `compact`/`compact_budget`. |
| `zim_browse` | 1,500 | 1,500 | Two-mode dispatch. |
| `zim_metadata` | 850 | 850 | Single-parameter tool with combined response. No `main_page_path` field. |
| `zim_links` | 1,250 | 1,250 | Two-direction enum; brief forward-compatibility note about v2.5 `inbound` addition. |
| `zim_health` | 600 | 600 | No parameters. |
| **Total** | **17,400** | **17,000** | Both well below the MCP Tax pain band. |

These are initial allocations, not hard caps. **Draft descriptions for all 8 tools MUST be committed to the prototype branch before Gate 0b runs**, so the gate measures realistic schemas — not estimated ones. If any tool exceeds its allocation by >20%, the spec authors EITHER (a) trim before Gate 0b, OR (b) **redistribute the per-tool `ALLOCATION` dict** so the overflowing tool gets more bytes from a tool that's under-using its allocation — as long as the TOTAL stays under `TOTAL_CAP` and no individual tool drops below what its description needs for dispatch quality. Option (b) is the right path when Gate 0b's F2 traces a per-class regression to too-tight description on a specific tool (likely candidates: the most-compressed tools, `zim_health` at 600B or `zim_metadata` at 850B). Redistribution is a deliberate edit to `ALLOCATION` in `tests/test_phase_f_schema_budget.py`, committed alongside the spec amendment justifying the new distribution. The total budget is the only hard cap; the per-tool allocations are a distribution decision the gate can revise.

### Gate 0b — surface-change non-regression (PRE-implementation eval)

This section defines the Gate 0b eval that runs against the prototype branch (`v2-phase-f-prototype`) after `v2.0.0rc0` ships and before `v2.0.0rc1` opens its implementation PR.

**The question Gate 0b answers:** does the 8-tool surface itself regress dispatch vs the b13 22-tool surface? The earlier draft deferred this to rc1 stabilization, which left the architecture committed before validation could influence it. Gate 0b pulls validation forward.

#### Procedure

1. **Build a dispatch probe set.** **n = 300 probes total**, NL queries that exercise every intent the current `zim_query` description's operations list mentions (search, entry fetch, summary, ToC, namespace browse, link extraction, etc.). Composition:

   - **~130 probes** sampled from `tests/dispatch_eval/data/b1_b13_probes.jsonl` (the b-series cumulative set). Selection biased toward at least 2× coverage of each b-series defect class (Z1–Z4, OPP-1, Sub-pattern-C, filler-prose, possessive) so per-class F1 minimums hold. If the cumulative set lacks ≥20 candidates for a class, the gap is filled by hand-authoring new probes in that class shape, flagged with `"source": "b-series-author-extended"` for traceability.
   - **~120 probes** authored fresh against a representative-query distribution.
   - **~50 probes** specifically targeting Phase F operation classes (toc, summary, structure, binary, main-page, batch, browse-page/walk, metadata, links-outbound/related, health).

   **Acknowledged sourcing bias.** The 130 b-series probes are NOT representative of real user query distribution — they're the failure shapes the project paid hardening for. Aggregate accuracy numbers will read higher than real-world. Per-class numbers in Criterion F1 are the load-bearing signal; aggregate numbers in A/B/D are interpreted as "non-inferiority against a known baseline."

   Probes are gold-labeled with four fields:
   - (a) the correct *operation*;
   - (b) the *expected parameter shape* for the correct tool (partial labels pinning only load-bearing fields);
   - (c) a *tool-eligibility tag* — `zim_query_preferred`, `zim_search_title_preferred`, or `either_acceptable`;
   - (d) an *operational-class tag list* (`operational_classes`, list-valued) — b-series defect classes (`Z1`, `Z2`, `Z3`, `Z4`, `OPP-1`, `Sub-pattern-C`, `filler-prose`, `possessive`) plus Phase F operation classes (`zim_get-toc`, `zim_get-summary`, etc.). **Each class must have ≥20 probes.**

   The probe set is committed under `tests/dispatch_eval/probes.jsonl`.

2. **Run the probe set against three surface variants × two modes.** Matrix:
   - **b13 × {simple, advanced}** — 2 cells. Baseline.
   - **phase-f × {simple, advanced}** — 2 cells. The 8-tool surface.

   Four cells total.

   **Primary model: Qwen-2.5-7B-Instruct** (local, vLLM with `--tool-call-parser hermes`), 100% of cells. Rationale: the MCP Tax pain band research targets open-weights 7-8B models — that's the population whose dispatch the surface change is supposed to help. Running Qwen at 100% gives 5pp non-inferiority resolution against the actual target population.

   **Secondary cross-validation (Anthropic-family): Haiku-4.5** (`claude-haiku-4-5-20251001`), 50% of cells. Rationale: Anthropic-family clients (Claude Code, Claude Desktop) are a major deployment population. Haiku at 50% confirms the primary's findings don't reflect a Qwen-specific quirk and validates that the surface change works for the Anthropic-family user base.

   **Tertiary cross-validation (architecturally-distinct small model, ~8B band): Llama-3.1-8B-Instruct** (local, vLLM with `--tool-call-parser llama3_json`), 50% of cells. Rationale: Qwen-2.5 is a single open-weights family. Real small-model deployments span Llama 3.x, Mistral, Phi, Gemma, Qwen 2.x/3.x. If Phase F passes on Qwen but regresses on Llama, the gate has overfit to one model family. Llama-3.1-8B at 50% coverage gives a second open-weights architecture point with a different tool-call parser path, catching family-specific failures that wouldn't surface on Qwen alone.

   **Quaternary cross-validation (sub-7B size class): Phi-3.5-mini-instruct (3.8B)** (local, vLLM with `--tool-call-parser pythonic`), 50% of cells. Rationale: 7-8B is the *upper* end of "small model" — real-world deployments routinely run sub-4B models (Phi-3.5 mini, Llama-3.2-3B, Qwen-2.5-3B, Gemma-2-2B). Schema-handling quality drops noticeably below 7B, so a "small models" claim that holds only at 7-8B understates the surface's real failure boundary. Phi-3.5-mini is the strongest tool-using sub-4B open-weights model in the deployment population, ships under MIT license (no HuggingFace gating friction), and represents a third architecturally-distinct family (Microsoft) so it doubles as an architecture-diversity probe at a smaller size. **Documented fallback if vLLM's `pythonic` parser is flaky for Phi in the deployer's vLLM version: substitute Qwen-2.5-3B-Instruct (`--tool-call-parser hermes`, same parser as Qwen primary) and note the substitution in `gate_0b_decision.json` under `quaternary_model_substituted`.** The substitution costs the architecture-diversity-at-small-size signal but preserves the size axis.

   **Why these four.** Qwen-7B is the load-bearing primary (matches MCP Tax research population). Haiku covers Anthropic-API consumers. Llama-8B covers the "other open-weights family" axis at the same size class. Phi-3.5-mini covers the sub-4B size class — the actual deployment boundary where small-model schema-handling falls off. Two open-weights families × two size classes + the Anthropic API path is materially better than one model — and the cost is bounded by the three secondaries each running 50% of cells.

   **Disagreement decision rule.** All four models have gating power on a defined subset of criteria. Sample-size-aware margins:

   - **Primary (Qwen-7B) at 100% coverage (n=300 per cell)**: 5pp non-inferiority margin on Criteria A, B, D.
   - **Secondary (Haiku) at 50% coverage (n=150 per cell)**: 10pp non-inferiority margin on the same criteria (matched to sample-size resolution).
   - **Tertiary (Llama-8B) at 50% coverage (n=150 per cell)**: 10pp non-inferiority margin on the same criteria.
   - **Quaternary (Phi-3.5-mini, ~3.8B) at 50% coverage (n=150 per cell)**: **10pp non-inferiority margin on the same criteria** — matched to the tertiary's margin. Phi represents the deployment population most likely to be hurt by the surface change (sub-4B is the actual deployment boundary where small-model schema-handling falls off); a 12pp ceiling on this population would permit a real 11pp regression to slip the gate, and "12pp drop from 90% baseline" = 22% wrong dispatches on the population the design claims to protect. Size-induced variance is addressed by **increased rep count rather than wider margin**: Phi runs at reps=5 (matched to primary/Gate 0b) at both Gate 0b and Stage E, giving 750 effective observations per cell. Reps are cheap on a 3.8B model — variance reduction without sacrificing detection power.
   - **Haiku OR Llama OR Phi failure on Criteria A, B, D at their respective margins BLOCKS rc1**, even if Qwen passes. A Qwen-pass / secondary-or-tertiary-or-quaternary-fail signals that the surface change doesn't generalize beyond Qwen; resolution: root-cause the divergence (write-up committed to `tests/dispatch_eval/qwen_<other>_divergence.md`) and either fix the prototype to pass on all four, or amend the spec acknowledging the surface targets a narrower population than claimed.
   - **Haiku OR Llama OR Phi failure on Criteria C1 (>5%), C2 (>30%, ≥10 events), C3 BLOCKS rc1.** C-criteria are rate ceilings, not non-inferiority comparisons. Z4 silent-wrong-answer risk is family-agnostic AND size-agnostic — if any small-model architecture or size produces the harm, the surface ships the harm.
   - **Haiku OR Llama OR Phi failure on Criteria F1, F2 in any mode is OBSERVATIONAL** — these are per-class metrics where the secondaries' per-class n (~15 per class) is below any statistical floor. Logged under `secondary_observational_failures` (Haiku), `tertiary_observational_failures` (Llama), `quaternary_observational_failures` (Phi) in the gate decision; investigated but not blocking.
   - **Haiku UNAVAILABLE** (API budget exhausted) **DOES NOT block Gate 0b.** Documented in `gate_0b_decision.json` under `secondary_status: "unavailable"`.
   - **Llama UNAVAILABLE** (no GPU capacity for a second local model) **DOES NOT block Gate 0b** but DOES require a documented decision (`tertiary_status: "unavailable"` with brief justification). This is weaker than Haiku-unavailable because Llama coverage is the explicit response to the architecture-overfit risk.
   - **Phi UNAVAILABLE** (no GPU capacity for a third local model, OR `pythonic` parser broken in deployer's vLLM AND Qwen-3B substitution refused) **DOES NOT block Gate 0b** but DOES require a documented decision (`quaternary_status: "unavailable"` with brief justification). Same reasoning as Llama: this is weaker than Haiku-unavailable because Phi coverage is the explicit response to the sub-7B-size blind spot.

   Each cell runs **5 reps** at temperature=0.2.

3. **Architecture preconditions already cleared at [Gate 0](#gate-0-pre-rc0--oneof-transport-verification).** By the time Gate 0b runs, either `oneOf` round-trips (proceed as designed) or the spec was already amended to a flat-schema design.

4. **Measure four per-cell metrics** (Criterion D is derived from comparing A/B between cells):
   - **(M1) Dispatch accuracy** — did the model call the right tool for the probe's operation? Feeds Criterion A.
   - **(M2) Parameter validity** — did the model construct a call whose parameters (a) pass the wire-schema AND (b) match the probe's expected parameter shape on load-bearing fields? Feeds Criterion B.
   - **(M3) Spurious-routing rate** — on `zim_query_preferred` probes only: how often does the model pick `zim_search(mode="title")` instead of `zim_query`? A spurious-route event that *still resolves the correct entry* is rescued; a spurious-route event that *resolves a different or worse entry* counts toward Criterion C. Broken out by `operational_classes` tag — Criterion C3 measures Z4 specifically.
   - **(M4) Per-class dispatch accuracy** — same as M1 but broken down by `operational_classes` tag. Feeds Criterion F.

   **Pass criteria:**

   - **Criterion A (dispatch non-inferiority).** Non-inferiority test on dispatch accuracy: 5pp margin on the primary, 10pp on the secondary, one-sided two-proportion z-test at α=0.05.
   - **Criterion B (parameter-validity non-inferiority).** Same form as A, applied to parameter-validity rate.
   - **Criterion C (dispatch-confusion ceiling — three sub-criteria).** Measured on `zim_query_preferred` probes in `advanced` mode. Phase F passes Criterion C only if ALL THREE sub-criteria hold:
     - **C1 (user-facing harm rate).** Answer-degrading spurious-routing rate (spurious route AND resolved entry differs from `zim_query`'s resolution), denominator = all `zim_query_preferred` probes, must be **≤ 5%**.
     - **C2 (conditional-harm-when-confused).** Of probes that actually misroute, the fraction whose resolved entry differs from `zim_query`'s resolution must be **≤ 30%**. Computed only when the confusion-conditional subset has ≥10 events; below that floor, C2 is reported as "underpowered" without blocking.
     - **C3 (per-class confusion — Z4 floor).** On `zim_query_preferred` probes tagged `Z4`, the answer-degrading rate must be ≤5% (absolute, not non-inferiority — Z4 is the freshest hardening per b13 and the most likely casualty of a routing change). Computed when the Z4 subset has ≥20 events; below that floor, C3 is underpowered but the gate authors must explicitly hand-audit Z4 outcomes before signing off.

     **Pre-decided fallback if any of C1/C2/C3 fails — see [Criterion C circuit-breaker](#criterion-c-circuit-breaker-pre-decided-fallback).**

   - **Criterion D (surface-change non-regression).** **phase-f must be non-inferior to b13** at the 5pp margin (primary) / 10pp (secondary) on Criteria A and B in **advanced mode**. This is the load-bearing gate: if the 8-tool surface itself regresses against the 22-tool surface, Phase F has an architectural problem and rc1 does not open.
   - **Criterion F (per-class non-regression — tiered).**
     - **F1 (b-series hardened classes, ≤8pp).** Classes `Z1`, `Z2`, `Z3`, `Z4`, `OPP-1`, `Sub-pattern-C`, `filler-prose`, `possessive` have accumulated 17 sweeps of targeted hardening. Per-class dispatch accuracy on `phase-f` (advanced mode, primary model) must hold **≥ b13 accuracy − 8 points absolute** at 5 reps × ≥20 probes = ≥100 effective n per class.
     - **F2 (Phase F operation classes, ≤10pp).** New dispatch shapes (`zim_get-toc`, `zim_get-summary`, etc.) get a slightly looser tolerance than F1 because there's no hardened baseline to defend — but **not 15pp**. The b13 baseline for these classes uses dedicated tools (`get_table_of_contents`, `get_entry_summary`, etc.) whose names match the operation 1:1, while Phase F collapses them under `zim_get(view="...")`. A 15pp ceiling would permit a small model to lose ~15% accuracy on, say, ToC fetches while the gate still passed — a real-world quality drop a small-model operator would notice. 10pp keeps a meaningful per-class signal without making the gate impossibly tight on a re-shaped surface. Classes with n=20 probes × 5 reps = 100 effective observations support the 10pp margin at α=0.05 / β=0.20 against ~90% baselines.

     **F1/F2 promotion criterion (forward compat).** Classes promote from F2 to F1 once actively hardened by sweep methodology. The trigger: the class appears in two or more b-series-style sweep fix lists with a documented baseline. Promotion is a deliberate edit to the analyzer's `F1_CLASSES` set, accompanied by a spec amendment.

5. **Schema budget.** Advanced total is ~17,400 (wired) or ~17,000 (flat). Both remain well below the MCP Tax pain band.

#### Criterion C circuit-breaker (pre-decided fallback)

If any of C1/C2/C3 fails on the prototype's wired path, the fallback ships `zim_search(mode="title")` as **explicit-string-only**. This is a deliberate framing choice: when small models conflate `zim_search(mode="title")` with `zim_query`, the fix is not to silently patch up title-mode results (the wired path tries that and Criterion C measures the cost). The fix is to make title mode legibly explicit — its description amends to say "for callers who already know the entity name; for natural-language questions, use `zim_query`" — and let models adjust their routing.

**Fallback design (chosen in advance, applied automatically if Criterion C fails).**

1. **`zim_search(mode="title")` runs no Tier 1 / filler-prose preprocessing.** The query string is passed to `find_entry_by_title_data` byte-identical.
2. **`zim_search(mode="title")` runs no Z3/Z4/OPP-1 promotion.** Results come back as raw `find_entry_by_title` hits, ranked by libzim's native title-similarity score.
3. **Description amended (~80 bytes net)** to make the explicit-name-required framing stark, with an explicit pointer to `zim_query` for NL questions.
4. **rc0's extraction is preserved as-is.** The module-level `promote_topic_via_title_index` in `topic_preprocessing.py` continues to back `SimpleToolsHandler._promote_topic_via_title_index` via the thin wrapper. v2.5 may still wire it into other surfaces. **rc0 is not wasted work in the fallback scenario.**
5. **Re-run scope.** The `phase-f-fallback` cell runs in advanced mode to confirm the fallback architecture passes Criteria A, B, D, F **AND Criterion C3 (Z4 floor)**. C1 and C2 are measured incidentally on the fallback run for the record, but they are not re-checked as ship gates — the fallback's premise is that title mode is no longer wired into the harmful path C1/C2 measured. C3 IS re-checked because it asks the model-routing question directly: even with title mode stripped of preprocessing, does a small model still route Z4 queries to title mode and silently get a worse answer than `zim_query` would have produced? If yes, the legibility-fix premise has failed — the model's routing instinct is broken, not just title mode's behavior. **In that scenario rc1 still does not open; the gate authors choose between amending the spec to drop title mode from advanced entirely OR returning to design. Shipping a known Z4 harm is not an option** — the b-series spent 17 sweeps eliminating exactly this regression class, and the surface change must not reintroduce it.

**Fallback C3 pass criterion.** Same threshold as the wired path: answer-degrading rate on Z4-tagged `zim_query_preferred` probes ≤5% absolute, computed against the model's resolved entries when it (still) misroutes to title mode. Underpowered if <20 events; gate authors hand-audit.

**Fallback C1 + C2 pass criteria.** Also re-checked on the fallback cell at the same thresholds as the wired path (C1 ≤5%, C2 ≤30% with ≥10 events floor). The earlier draft re-checked only C3 on the fallback under the premise that the legibility fix's only failure mode is "Z4 still gets misrouted." That premise is single-axis — the fix could plausibly produce new dispatch confusion (e.g., a model that previously routed all NL queries to `zim_query` starts splitting routing between `zim_query` and the explicit-only `zim_search(mode="title")` because the amended description's stark framing surprises it). C1 catches answer-degrading routes across all `zim_query_preferred` probes (not just Z4); C2 catches the conditional harm-when-confused rate. Both are computed by the same `--fallback-c3-check` analyzer pass (now broadened to also write `fallback_c1_pass` and `fallback_c2_pass`).

The fallback ships only if **all three** of `fallback_c1_pass`, `fallback_c2_pass`, `fallback_c3_pass` are true. If C2 is underpowered (<10 events on the fallback cell), it is reported as `null` and the gate authors hand-audit the misroute events before signing off — same treatment as the wired-path C2 underpowered case.

**Why "remove protection" is the right fallback.** The wired path tries to fix mistakes inside title mode. If the mistake rate is still >5% even with the fix in place, that signals the dispatch confusion is fundamental — the model is picking the wrong tool, not making a recoverable mistake within the right tool. The legibility fix attacks the dispatch confusion at its source: a stark, explicit-only description gives the model better signal to NOT pick title mode for NL queries. The hope is that the *rate of routing into title mode* drops below the confusion threshold. The fallback is a routing-incentive change, not a result-quality patch.

**Decision flow:**

| Criterion C outcome | Action | rc0 still valuable? |
| --- | --- | --- |
| All of C1/C2/C3 pass | Ship as designed: preprocessing + promotion wired into title mode. | Yes — used by rc1. |
| Any of C1/C2/C3 fails | Apply the pre-decided fallback above; re-run the fallback cell; if it passes Criteria A/B/D/F **AND fallback-C1 AND fallback-C2 AND fallback-C3**, rc1 opens with the fallback. | Yes — module persists, used by `SimpleToolsHandler`, available for future surfaces. |
| Wired Criterion C fails AND any of fallback-C1/C2/C3 also fails | rc1 does NOT open. Gate authors choose between (a) amending the spec to drop title mode from advanced entirely, or (b) returning to design with the dispatch-routing problem as the central question. **Shipping a known Z4 silent-wrong-answer harm is NOT an option** — the b-series invested 17 sweeps eliminating exactly this regression class, and the surface change must not reintroduce it. | Yes — module persists regardless of which path is taken. |

This pre-decision means the Stage A refactor proceeds without taking on Gate-0b-outcome risk.

#### Per-class minimum sample sizes

Aggregate non-inferiority at n = 300 cannot detect a narrow but devastating regression in a single operational class.

**Constraints layered on top of the 300-probe total:**

- **Each value in any probe's `operational_classes` list gets ≥20 probes** — including each b-series defect class AND each Phase F operation class.
- **Per-class non-regression check (Criterion F).** For each class, dispatch accuracy on `phase-f` (advanced mode, primary model) must be **≥ b13 accuracy − ceiling** at 5 reps × ≥20 probes = ≥100 effective n per class.
- **Class budgeting.** The 300-probe total accommodates 32 classes × 20 = 640 probe-slots overcommitted, so each probe can carry multiple operational-class tags as a list (e.g., a Z4 + filler-prose probe counts toward both).
- **Class-failure remediation.** If Criterion F fails on any class, root-cause the regression class-by-class. Likely fixes are localized. rc1 does not open until every class passes.

#### Sample-size justification

Comparing two binomial proportions p₁ and p₂ with a one-sided non-inferiority test at α = 0.05, β = 0.20 (power 0.80), and non-inferiority margin δ = 0.05:

```
n ≈ (z_{α} + z_{β})² × [p₁(1-p₁) + p₂(1-p₂)] / δ²
  ≈ (1.645 + 0.842)² × [0.90(0.10) + 0.90(0.10)] / 0.05²
  ≈ 6.19 × 0.18 / 0.0025
  ≈ 446 per cell at p = 0.90
```

At p = 0.95, required n drops to ~235. At p = 0.85, it rises to ~635. **n = 300 per cell** with 5 reps sits in the upper-power band across the realistic accuracy range.

**Criterion C uses the `zim_query_preferred` subset (~120 probes per variant × 5 reps = 600 effective n) for spurious-routing measurement.** At a 5% C1 ceiling and expected ~3% baseline rate, n = 600 gives high power.

The schema-budget validation test asserts the empirically derived numbers, not the table above.

### Validation gate

A new test `tests/test_phase_f_schema_budget.py` boots the server, dumps the registered tool schemas, and cross-references the Gate 0b decision artifact to assert invariants:

```python
# Per-tool allocations and TOTAL_CAP are baked into the rc1 commit as Python constants,
# selected at PR time from the (build-time-only) gate_0b_decision.json. Production
# code does NOT read the JSON at runtime. This test enforces drift detection between
# the committed constants and the gate outcome they were derived from.
decision = json.loads(GATE_DECISION_PATH.read_text())

# (1) Total + per-tool budget caps.
assert total_schema_bytes <= TOTAL_CAP, f"Phase F schema budget exceeded: {total_schema_bytes}"
assert all(per_tool_bytes[name] <= ALLOCATION[name] * 1.2 for name in ALLOCATION)

# (2) Criterion D held in the gate decision record. Each criterion records
#     a primary verdict (Qwen-7B, 5pp margin), a secondary verdict (Haiku,
#     10pp margin), a tertiary verdict (Llama-8B, 10pp margin), and a
#     quaternary verdict (Phi-3.5-mini, 10pp margin, reps=5 for matched power). All available
#     verdicts must pass per the disagreement rule.
assert decision["gate_passed"] is True
assert decision["criteria"]["D"]["primary"]["pass"] is True
if decision["secondary_status"] == "available":
    assert decision["criteria"]["D"]["secondary"]["pass"] is True
if decision["tertiary_status"] == "available":
    assert decision["criteria"]["D"]["tertiary"]["pass"] is True
if decision["quaternary_status"] == "available":
    assert decision["criteria"]["D"]["quaternary"]["pass"] is True

# (3) rc1 commit matches the gate's Criterion C path.
assert decision["criterion_c_path"] in {"wired", "fallback"}

# (4) Default mode is always "simple" at v2.0.0.
assert decision["default_tool_mode"] == "simple"
```

`TOTAL_CAP` and the per-tool `ALLOCATION` dict are hard-coded Python constants in the rc1 commit. Cap values: **~17,400 wired / ~17,000 flat**. The 20% slack on per-tool allocation tolerates small description wobble; the hard cap is the total.

**Three gate-decision fields are load-bearing for the rc1 commit. Each is baked into production source as a Python constant or attribute; the gate-decision JSON is read only by the test below at test time, NOT by production code at runtime.**

| Gate decision field | rc1 commit's corresponding artifact |
| --- | --- |
| `default_tool_mode` (must be `'simple'`) | `openzim_mcp/config.py` `tool_mode` Field's `default=` value |
| `criterion_c_path` ∈ {wired, fallback} | `_CRITERION_C_PATH: Literal["wired","fallback"] = "..."` constant at module level in `openzim_mcp/tools/zim_search.py`. Production code branches on this constant; in `"fallback"`, the title-mode handler short-circuits to `find_entry_by_title_data` and the promotion-layer import is never reached. |
| `gate_0_schema_shape` ∈ {wired_oneof, flat} | The `inputSchema` shape `openzim_mcp/tools/zim_search.py` and `zim_get.py` emit (contains `"oneOf"` iff wired). |

A separate `tests/test_phase_f_gate_decision_consistency.py` walks these three fields and asserts the corresponding rc1 commit artifacts match. Drift between any constant and the gate decision file blocks merge — this is the build-time enforcement that lets production code legibly NOT depend on the gate JSON.

---

## Migration story

v2 allows clean breaks; there are no aliases on the wire. Callers updating from v1.x or from v2 beta need a single-pass rewrite. The mapping is mechanical.

### Full call-site map

| v1 / v2-beta call | v2.0 equivalent |
| --- | --- |
| `list_zim_files()` | `zim_health()` → `.loaded_archives` |
| `get_server_health()` | `zim_health()` → `.health` |
| `get_server_configuration()` | `zim_health()` → `.configuration` |
| `get_zim_metadata(path)` | `zim_metadata(path)` → `.metadata` |
| `list_namespaces(path)` | `zim_metadata(path)` → `.namespaces` |
| `get_main_page(path)` | `zim_get(path, main_page=True)` |
| `search_zim_file(path, q)` | `zim_search(q, zim_file_path=path)` |
| `search_all(q)` | `zim_search(q, cross_file=True)` |
| `search_with_filters(path, q, ns=, ct=)` | `zim_search(q, zim_file_path=path, namespace=ns, content_type=ct)` |
| `find_entry_by_title(path, title)` | `zim_search(title, zim_file_path=path, mode="title")` |
| `find_entry_by_title(cross_file=True)` | `zim_search(title, cross_file=True, mode="title")` — promotion disabled in cross-archive case (see [zim_search → Promotion + cross-archive](#2-zim_search)) |
| `get_search_suggestions(path, prefix)` | `zim_search(prefix, zim_file_path=path, mode="suggest")` |
| `get_zim_entry(path, entry_path)` | `zim_get(path, entry_path=entry_path)` — rename only; `compact` defaults to `False` (legacy behavior preserved) |
| `get_zim_entries(path, entry_paths)` | `zim_get(path, entry_paths=entry_paths)` — rename only; `compact` defaults to `False` |
| `get_binary_entry(path, entry_path)` | `zim_get(path, entry_path=entry_path, binary=True)` |
| `get_entry_summary(path, entry_path)` | `zim_get(path, entry_path=entry_path, view="summary")` |
| `get_table_of_contents(path, entry_path)` | `zim_get(path, entry_path=entry_path, view="toc")` |
| `get_article_structure(path, entry_path)` | `zim_get(path, entry_path=entry_path, view="structure")` |
| `get_section(path, entry_path, section_id)` | `zim_get_section(path, entry_path, section_id)` — **note:** `compact` parameter is **new** and defaults to `True`; pass `compact=False` to preserve the pre-Phase-F raw-text response shape |
| `browse_namespace(path, namespace)` | `zim_browse(path, namespace)` |
| `walk_namespace(path, namespace)` | `zim_browse(path, namespace, mode="walk")` |
| `extract_article_links(path, entry_path)` | `zim_links(path, entry_path)` |
| `get_related_articles(path, entry_path)` | `zim_links(path, entry_path, direction="related")` |
| inbound-link lookup (no v1 tool) | not available at v2.0 — `zim_links(..., direction="related")` is the closest approximation; `direction="inbound"` arrives in v2.5 #16 |
| `zim_query(...)` | unchanged |

### CHANGELOG entry shape

The v2.0.0rc1 CHANGELOG includes a dedicated **"Migrating from v1.x / v2 beta"** section that reproduces this table verbatim.

The same CHANGELOG carries a **"Default behavior changes"** sub-section calling out:

- **`zim_get_section` adds `compact=True` default.** New parameter; the legacy `get_section` returned raw text. Pass `compact=False` to preserve the pre-Phase-F shape.
- **`zim_metadata` no longer exposes `main_page_path`.** Callers who used it to construct an explicit `entry_path` round-trip to `zim_get` should switch to `zim_get(path, main_page=True)`.

The `zim_get` rename is **behavior-preserving** on the `compact` axis (default is `False`, matching legacy). v2.5 may revisit the `zim_get` default once telemetry shows adoption.

### MCP client integrations

Known integrators get coordinated PRs from the rc1 author. No external client library currently pins to v1.x tool names that we know of; if one surfaces during rc1 stabilization, we publish a one-line `sed` command rather than reinstating aliases.

---

## Parameter shape consolidation

Phase F unifies parameter naming across the new surface.

### Standard parameter vocabulary

| Parameter | Type | Semantics | Default |
| --- | --- | --- | --- |
| `zim_file_path` | `Optional[str]` on `zim_search` / `zim_query`; `str` (required) on entry-targeted tools | Archive identifier. | `None` / required |
| `cross_file` | `bool` | Multi-archive fan-out. Only present on `zim_search` and `zim_query`. Mutually exclusive with `zim_file_path`. | `False` |
| `entry_path` | `Optional[str]` | Single-entry identifier. | `None` |
| `entry_paths` | `Optional[list[str]]` | Batch-entry identifiers. Mutually exclusive with `entry_path`. | `None` |
| `query` | `str` | Search / NL query text. | — |
| `mode` | `Literal[...]` | Within-tool dispatch. | per-tool default |
| `view` | `Literal["full","summary","toc","structure"]` | View selector on `zim_get`. Bundle slicers only; main-page is a separate flag. | `"full"` |
| `binary` | `bool` | Switch `zim_get` to base64 return shape. Mutually exclusive with `view≠"full"` and with `main_page=True`. | `False` |
| `main_page` | `bool` | `zim_get`-only: fetch the archive's main page. Mutually exclusive with `entry_path`, `entry_paths`, `binary=True`, and `view≠"full"`. | `False` |
| `direction` | `Literal["outbound","related"]` | `zim_links` direction selector. v2.5 #16 adds `"inbound"`. | `"outbound"` |
| `namespace` | `Optional[str]` | Single-character namespace filter. Only on `zim_search` fulltext mode. | `None` |
| `content_type` | `Optional[str]` | MIME-type filter. Only on `zim_search` fulltext mode. | `None` |
| `limit` | `Optional[int]` | Max results to return. | `None` |
| `offset` | `int` | Pagination offset. Cursor preferred. | `0` |
| `cursor` | `Optional[str]` | Phase B opaque pagination cursor. Overrides `offset` when supplied. | `None` |
| `max_content_length` | `Optional[int]` | Body truncation cap on `zim_get` (`view="full"` body view OR `main_page=True`) and `zim_query`. | `None` |
| `content_offset` | `int` | Resume reading a long article from this character offset. | `0` |
| `compact` | `bool` | Apply small-model response trimming. | `True` on `zim_query`, `zim_get_section`; `False` on `zim_get` (preserves legacy `get_zim_entry` behavior; revisited in v2.5). |
| `compact_budget` | `Optional[str \| int]` | Hard char-cap on compact responses. Present on every tool that has `compact`. | `None` |
| `synthesize` | `bool` | `zim_query`-only: switch to the synthesize pipeline. | `False` |
| `max_chars` | `Optional[int]` | `zim_get_section`-only: section-body truncation cap. | `None` |

**Removed inconsistencies:**

- `term` and `q` aliases → just `query`.
- `path` → always `zim_file_path`.
- `prefix` (used by `get_search_suggestions`) → folded into `query` since `zim_search(mode="suggest")` semantically treats `query` as a prefix.
- `limit_per_file` (used by `search_all`) → derived internally from `limit` when `cross_file=True`.

### Cursor / pagination consistency

Every list-returning tool returns `{results, next_cursor, total, done, page_info}` per Phase B.

---

## Test impact

### Measurement methodology

Counted lines and files in `tests/` that reference each soon-to-be-renamed tool name:

- Lines that look up the MCP-registered tool name → must be renamed.
- Lines that call internal `zim_operations.search_zim_file()` or similar → stay the same (data layer unchanged).
- Lines that mention old names in assertions, error messages, comments → audited case by case.

### Headline numbers

| Bucket | Files | Lines |
| --- | --- | --- |
| Total test files mentioning a soon-renamed name (`grep -w`) | 133 | ~1,809 |
| Test files looking up tools by MCP-registered name | **3** | **8** |
| Test files importing data-layer methods directly | 23 | (unaffected) |
| Golden-snapshot files mentioning tool names | TBD during implementation | likely <10 |

The bulk of the 1,809 lines are data-layer calls and string-literal mentions — they survive the rename.

### Rewrite scope

- **MCP-registration lookups** (the 3 files): straightforward mechanical rename.
- **Per-tool test modules**: existing files like `tests/test_search_zim_file.py` get renamed and updated — imports change and registered-tool-name lookups change, but underlying assertions about response shape stay the same.
- **Golden snapshots**: re-record after the rename lands.
- **New schema-budget test** (`test_phase_f_schema_budget.py`): asserts total + per-tool byte cap, reads gate decision at test time.
- **Schema-shape tests** (`test_phase_f_schema_shapes.py`): assert `oneOf` branch structure on `zim_get` and `zim_search` (or absence thereof if Gate 0 selected flat).
- **Gate-decision-consistency test** (`test_phase_f_gate_decision_consistency.py`): asserts the baked Python constants in production code (`_CRITERION_C_PATH` in `zim_search.py`, `tool_mode` default in `config.py`, schema shape in `zim_search.py` / `zim_get.py`) match the values recorded in the committed `gate_0b_decision.json`. Drift between them blocks merge.
- **Packaging regression test** (`test_phase_f_packaging.py`): confirms `zim_query_description.md` is shipped in the installed wheel via `importlib.resources` — catches `pyproject.toml` package-data regressions that would `FileNotFoundError` at import on the installed package.
- **Schema-bypass defense-in-depth tests** (`test_phase_f_schema_bypass.py`): hand-construct wire-level invalid payloads that bypass `oneOf` and assert structured validation errors.
- **rc0 refactor diff-test harnesses (PRE-rc0).** Two diff-tests replay the b1 → b13 cumulative probe set (~150 distinct probes) to assert byte-identical behavior across the refactor.
  - `tests/dispatch_eval/test_promotion_extraction_parity.py` — replays each probe through both the old `SimpleToolsHandler._promote_topic_via_title_index` and the new module-level `topic_preprocessing.promote_topic_via_title_index`, asserts byte-identical resolved entry paths.
  - `tests/dispatch_eval/test_preprocessing_extraction_parity.py` — pins the orchestration order of the existing `IntentParser` classmethod calls in `simple_tools.py` by replaying each probe and asserting the chain is idempotent.
- **Gate 0b dispatch-eval infrastructure (PRE-rc1).** A 300-probe gold-labeled probe set, a runner that boots the MCP server with each variant × mode cell and drives the model, a non-inferiority analyzer that emits the criterion verdicts and renders the decision rule including the Criterion C circuit-breaker.

---

## Operations

- **Configuration.** `tool_mode` config key keeps the existing spelling (`'simple'` and `'advanced'`); the Literal is binary. Default value is `'simple'`. Only the registered tool *set* changes per mode (22 → 8 in `'advanced'`; 1 → 1 in default-install). No deprecation cycle, no alias logic. **Default-install operators see zero tool-count change at v2.0.0 vs v2.0.0b13.**
- **CHANGELOG.** Add a dedicated "Migrating from v1.x / v2 beta" section that includes the full call-site map.
- **Telemetry.** No new telemetry. Existing logging at debug level continues; tool-name strings change to the new names.
- **Schema budget regression guard.** `tests/test_phase_f_schema_budget.py` enforces the cap. Subsequent feature work that wants to expand a tool's description will trip this test and force a tradeoff discussion.

---

## Phase boundaries

### Inherited from Phase A

- `_meta` envelope on every response — continues.
- Phase A #14 typo-tolerant title lookup — now reached via `zim_search(mode="title")`.
- `compact` / `compact_budget` parameters — preserved on `zim_query` (default `True`); added uniformly to `zim_get` (default `False`, deferred to v2.5 for revisit) and `zim_get_section` (default `True`).

### Inherited from Phase B

- Cursor pagination contract — every list-returning Phase F tool follows it.
- `Union[<Response>, ToolErrorPayload]` return-type pattern — preserved.
- FastMCP `{"result": ...}` wrapper — preserved.
- Batch response envelope on `zim_get(entry_paths=...)` — same as current `get_zim_entries`.

### Inherited from Phase C

- `zim_get_section` is the renamed `get_section`; data layer and response shape identical.
- `zim_get(view="summary"|"toc"|"structure")` slices the Phase-C EntryBundle; first call builds the bundle, subsequent calls hit the cache.
- `zim_query(synthesize=True)` continues to dispatch to the Phase-C synthesize pipeline.

### Inherited from Phase D

- `zim_search(mode="fulltext")` and `zim_query(synthesize=True)` benefit from the cross-encoder reranker when `[reranker]` extra is installed.
- **Phase D Tier 1 query rewriting + lightweight NL preprocessing — already shareable.** The b-series investment in NL-topic handling already lives at module level in `intent_parser.py` and `title_promotion.py` and is cross-module-callable. rc0's preprocessing diff-test pins the orchestration order of these existing classmethod calls; the helpers themselves don't change.
- **NL-topic promotion layer extracted to `topic_preprocessing.py` (rc0); rc1 wiring into `zim_search(mode="title")` is conditional on Gate 0b.** The extraction is necessary because the current code is an instance method with closures over caller state. `SimpleToolsHandler._promote_topic_via_title_index` becomes a thin delegating wrapper. rc1's `zim_search.py` then conditionally calls the extracted module-level function: **wired** in the default Gate 0b path (single-archive title mode), **NOT imported** in the Criterion C fallback path. Either way, the extracted module persists.

### Hooks for v2.5

- `zim_links` v2.5 will add `"inbound"` to the `direction` enum as a non-breaking JSON-Schema-additive change.
- `zim_metadata` is the natural surface to extend with v2.5 archive-type-preset awareness (#17).
- Hybrid intent parser / Tier 2 decomposition (deferred Phase D items) plug into `zim_query` without changing its signature.
- **`zim_get` compact-default revisit.** v2.5 examines telemetry on `zim_get` usage and decides whether to flip the default to `True`. The parameter and surface stay stable; only the default value is in play.
- **NL-topic promotion code relocation is consumed by Phase F.** The previously-tracked `v2.5-promotion-lift` item is closed.

---

## Out of scope (explicit deferrals)

| Item | Where it lands |
| --- | --- |
| Inbound link runtime | v2.5 #16 (link-graph sidecar) |
| Archive-type presets | v2.5 #17 |
| Hybrid intent parser, Tier 2 decomposition, embeddings sidecar | v2.5 sub-D-3, sub-D-4 |
| Tool-name aliases / deprecation shims | Out — v2 allows clean breaks |
| Semantic versioning hooks for tool-list compat | Out — clients pin to v2 via standard MCP version negotiation |
| Tool-list filtering / role-based scoping | Out — the `tool_mode` Literal is the only filter mechanism |
| `simple-extended` mode | Out — v2.5 may revisit if real demand emerges |
| Trimmed `zim_query` description (V1) | Out — V0 ships unconditionally |
| `compact=True` default on `zim_get` | v2.5 — revisited with telemetry |
| Synthesize as a top-level tool | Out — stays as `zim_query(synthesize=True)` per Phase C |
| Binary batch fetch | Out — `zim_get(binary=True)` is single-entry only at v2.0 |
| Inbound-direction `zim_links` at v2.0 | Out — `"inbound"` not in the v2.0 enum |

---

## Release plan

The plan ships in four stages: **Gate 0** (architecture precondition) → **`v2.0.0rc0`** (pure refactor) → **Gate 0b** (dispatch eval against prototype) → **`v2.0.0rc1`** (surface change) → **`v2.0.0`** (final tag). Each stage's gates are hard preconditions for the next; failures roll back to the previous stable point rather than degrade forward.

### Gate 0 (PRE-rc0) — `oneOf` transport verification

If FastMCP does not emit / does not preserve `oneOf` in `inputSchema`, the schema-conditional architecture is structurally infeasible. Two sub-gates land in this stage (cheapest-first). **Gate 0.3 (small-model `oneOf`-parsing benchmark) moved to Stage B** (Task B2a in the plan) because it must measure the actual production schemas rc1 will ship, not synthetic stand-ins authored before the schemas exist:

#### Gate 0.1: `oneOf` emission spike

**Goal:** prove that FastMCP can emit `oneOf` *at all* from one of the available patterns. Cheapest possible check.

**Procedure.** In a throwaway script, try three registration patterns and dump `tool.parameters` for each:

- **Pattern A:** type-signature only — `Literal["a","b","c"]`-gated parameter.
- **Pattern B:** explicit `inputSchema=<oneOf-dict>` override on `@tool()` (if the decorator accepts it).
- **Pattern C:** Pydantic `discriminator` field in a parameter model class.

**Decision:**

- ≥1 pattern produces `oneOf` in-memory → proceed to Gate 0.2. Record which patterns work.
- 0 patterns produce `oneOf` in-memory → STOP. Open the spec-amendment PR (flat-schema design) immediately. Skip Gate 0.2 and 0.3.

#### Gate 0.2 — transport round-trip verification

**Procedure.** Runs only if Gate 0.1 confirmed at least one pattern emits `oneOf`.

1. Take the winning pattern. Write a minimal `@server.mcp.tool()` registration. Boot the server and dump `server.mcp._tool_manager._tools[name].parameters`.
2. Walk the dumped dict for any `"oneOf"` key at any depth. Record whether the structure round-trips JSON encoding.
3. Inspect what the FastMCP HTTP and stdio transports actually send over the wire by snooping the `tools/list` response.

**Decision rule.**

| Outcome | Action |
| --- | --- |
| `oneOf` round-trips on both transports | Proceed to Gate 0.3. |
| `oneOf` requires explicit override pattern (B or C) that DOES round-trip | Proceed to Gate 0.3. Plan amended to use the winning override pattern. |
| `oneOf` does not round-trip on the target transport | **STOP.** Amend the spec to flat schemas + prose conditionals + handler validation. Re-budget: `zim_search` ~2,200, `zim_get` ~3,000, total ~17,000. Skip Gate 0.3. |

**Result committed** as `tests/dispatch_eval/transport_oneof_verification.md`.

#### Gate 0.3: small-model `oneOf`-parsing benchmark

**Goal:** the spec's entire `oneOf` rationale rests on the claim that small models parse `oneOf` schemas better than flat-schema-plus-prose. Gate 0.2 verified the schema TRANSPORTS; Gate 0.3 verifies the model on the other end can USE it.

**Procedure.** Runs only if Gate 0.2 produced a wired-`oneOf` verdict.

1. Author a **100-probe `oneOf` ablation set** in `tests/dispatch_eval/oneof_parse_benchmark.jsonl`. Each probe is an NL query targeting one of the actual Phase F production tools (`zim_get`'s 4-branch shape and `zim_search`'s 3-branch shape, as drafted in the Gate 0b prototype skeletons under [Task B2 of the plan](../plans/2026-05-24-v2-phase-f-tool-surface.md#task-b2-draft-all-8-tool-descriptions-in-skeleton-modules)). **Probes use the actual rc1 schemas, not synthetic stand-ins** — the earlier "modeled on" framing decoupled Gate 0.3 from the production schemas it was meant to validate. Each probe has a gold-labeled expected branch and parameter shape. The ablation set is curated against `zim_get` + `zim_search` only (the two tools that actually use `oneOf`); the other 6 tools have flat schemas regardless of Gate 0 outcome.
2. Build two registrations of the same target tools:
   - **`oneof_variant`** — `zim_get` and `zim_search` with the `oneOf` schemas the winning Gate 0.2 pattern produces (byte-identical to what the prototype skeletons emit, and to what rc1 will ship).
   - **`flat_variant`** — `zim_get` and `zim_search` with flat parameter schemas where the conditionals are described in prose only.
3. Run both variants against **Qwen-2.5-7B-Instruct** (local, vLLM with `--tool-call-parser hermes`) at temperature=0.2, 5 reps per probe.
4. Measure branch-selection accuracy and parameter-validity rate.

**Production-schema invariant.** Because the prototype skeletons ([plan Task B2](../plans/2026-05-24-v2-phase-f-tool-surface.md#task-b2-draft-all-8-tool-descriptions-in-skeleton-modules)) must be authored before Gate 0.3 runs (the ablation set imports their schema bytes), the rc0→prototype dependency means Gate 0.3 cannot run until rc0 is published. Sequencing: Gate 0.1 + Gate 0.2 land on `v2-phase-f-gate-0` and merge to main → rc0 ships → prototype branch authors the 8 skeletons → Gate 0.3 runs against the prototype skeletons → Gate 0b runs. The Gate 0.3 verdict and the prototype skeletons commit on the same prototype branch; rc1 then cherry-picks the verdict alongside the Gate 0b decision artifact, AND a schema-parity test (see [prototype-rc1 schema parity](#prototype-rc1-schema-parity-required-before-rc1-merge)) enforces that the rc1 schemas haven't drifted from what Gate 0.3 measured.

**Decision rule.**

| Outcome | Action |
| --- | --- |
| `oneof_variant` accuracy beats `flat_variant` by a statistically significant ≥7pp on either metric | **`oneOf` validated.** Proceed to rc0 with the wired-`oneOf` design. |
| `oneof_variant` is statistically indistinguishable from flat | **`oneOf` neither helps nor hurts at large-effect resolution.** Proceed to rc0 with wired-`oneOf` but note that the design's claimed small-model benefit is unmeasured at small effect size. |
| `oneof_variant` is significantly WORSE than `flat_variant` by ≥7pp | **`oneOf` invalidated.** Gate 0 verdict downgrades to STOP-AMEND-SPEC even though the schema transports. Open the spec amendment to flat schemas. |

**Result committed** as `tests/dispatch_eval/oneof_parse_benchmark.md`.

#### Prototype-uses-Literal-signatures requirement

The Gate 0b prototype skeleton is the only artifact the dispatch eval measures models against. If the prototype uses flat parameter signatures with the conditional structure in prose ONLY, the eval measures models against flat schemas — but rc1 ships `oneOf`. The eval does not validate the production surface.

**Fix:** the prototype skeleton MUST use the exact type-signature pattern selected by Gate 0.1's winning variant, so the schema Gate 0b measures is byte-identical to the schema rc1 ships. For the STOP-AMEND-SPEC path, the prototype uses the flat signatures matching the amended spec — same identity property.

#### Prototype-rc1 schema parity (required before rc1 merge)

The prototype is throwaway scaffolding. rc1 writes the real per-tool implementations from scratch ([plan Task D0 Step 2](../plans/2026-05-24-v2-phase-f-tool-surface.md#task-d0-create-v2-phase-f-rc1-branch--cherry-pick-decision)). This creates a divergence risk: a rc1 author who edits a description for clarity, reorders parameters, or trims prose to fit the per-tool byte cap can produce a tool surface that LOOKS like the prototype but is materially different from what Gate 0.3 and Gate 0b measured.

The byte-cap test ([Task D13](../plans/2026-05-24-v2-phase-f-tool-surface.md#task-d13-schema-budget-enforcement-test)) catches gross divergence (rc1 exceeds the allocation) but does NOT catch description-quality drift inside the cap.

**Parity requirement.** Before rc1 merges, a `tests/test_phase_f_prototype_parity.py` test asserts THREE invariants on every tool: (a) wire footprint (`name + description + inputSchema` as MCP would serialize it) stays within **±5% bytes** of the prototype's recorded footprint; (b) the `inputSchema` shape (oneOf branches, parameter names, parameter types, enum values) is structurally identical to the prototype; (c) the description prose has **Levenshtein edit distance ≤30%** of the prototype's recorded description. The edit-distance check (c) catches the case where an rc1 author rewrites a description significantly while preserving its byte count — pure prose rewrites within the byte budget can materially change the dispatch signal a small model reads. The prototype's per-tool snapshot (`bytes` + `description` + `inputSchema`) is committed at `tests/dispatch_eval/prototype_schema_snapshot.json` alongside `gate_0b_decision.json` and cherry-picked into rc1.

- A pure-description prose edit inside the cap is allowed (±5% byte slack absorbs minor rewording for grammar/clarity).
- A schema-shape change (adding a oneOf branch, renaming a parameter, changing a Literal's enum values) BLOCKS the merge and forces a Gate 0b re-run — the measurement is invalidated.

This makes the cherry-pick contract precise: rc1 inherits Gate 0b's verdict only as long as the rc1 surface is what Gate 0b measured. Description rewrites that meaningfully change the surface require re-validation.

### Gate 0a / rc0 (pure refactor)

`v2.0.0rc0` ships the promotion + preprocessing extraction from `simple_tools.py` to `openzim_mcp/topic_preprocessing.py`, with no tool-surface changes. The wire surface is bit-identical to b13. The release exists solely to scope refactor risk away from the rc1 surface change.

**Scope (rc0 PR).** The actual extraction surface is narrower than earlier drafts implied — most of the b-series investment in NL handling already lives in module-level/classmethod form:

- `IntentParser._apply_misspelling_map`, `IntentParser._detect_stopword_phrase`, etc. are already `@classmethod` on `IntentParser` and reachable from any caller.
- `title_promotion.find_title_match`, `accept_possessive_promotion`, etc. are already module-level pure functions.

What actually needs extraction in rc0:

- **`_promote_topic_via_title_index`** (simple_tools.py:3896): the orchestrator that chains `IntentParser` rewriting → `find_title_match` → `_probe` (which calls `self.zim_operations.find_entry_by_title_data`) → per-pass acceptance. This is the only instance method that ties the pieces together. Extract to a module-level function `promote_topic_via_title_index(zim_operations, zim_file_path, topic, ...)` in `openzim_mcp/topic_preprocessing.py`.
- **`_auto_select_zim_file`** (simple_tools.py:5784): the single-archive auto-selection helper with its try/except + 4-arm log envelope (0-files info / 1-file debug / N-files info / exception warning). Extract to module-level `auto_select_zim_file(zim_operations)` in the same `topic_preprocessing.py`. Necessary because `zim_search(mode="title")` at rc1 needs auto-select in the no-`zim_file_path` case AND the diagnostic surface (the four log emits) is operator-visible — reimplementing inline in `zim_search.py` would silently drop the log envelope.
- **Inner closure `_probe`**: becomes an explicit-argument function (or kept as a local closure inside the extracted orchestrator — equivalent at the byte-output level).
- **Wrappers:** `SimpleToolsHandler._promote_topic_via_title_index` becomes a one-line `return promote_topic_via_title_index(self.zim_operations, zim_file_path, topic, ...)`. `SimpleToolsHandler._auto_select_zim_file` becomes a one-line `return auto_select_zim_file(self.zim_operations)`.

What does NOT need extraction (already shareable):

- The Tier 1 rewriting chain — classmethods on `IntentParser`.
- The possessive shape primitives — module-level in `title_promotion.py`.
- Conversational-filler detection — stays on `SimpleToolsHandler`; `zim_search` is not an NL-routing surface.

**Preprocessing diff-test in rc0** validates that the orchestrating glue in `simple_tools.py` produces byte-identical post-rewrite strings before/after — not that the IntentParser methods themselves change (they don't).

**Gate 0a — three diff-tests (hard merge gate on rc0).**

1. **`tests/dispatch_eval/test_promotion_extraction_parity.py`.** Replay the b1 → b13 cumulative probe set through both the old method and the new module-level function. Assert byte-identical resolved entry paths. Failure blocks rc0.
2. **`tests/dispatch_eval/test_auto_select_extraction_parity.py`.** For each of four archive-count scenarios (0 / 1 / N files; `list_zim_files_data` raises), call BOTH the old `SimpleToolsHandler._auto_select_zim_file` and the new module-level `auto_select_zim_file`. Assert byte-identical return value AND identical log records (captured via pytest `caplog`). Pins the diagnostic-surface preservation that the inline-reimplementation path would have silently lost. Failure blocks rc0.
3. **`tests/dispatch_eval/test_preprocessing_extraction_parity.py`.** Replay each probe's raw query through the canonical Tier 1 chain in `simple_tools.py` and assert the chain is idempotent. Failure blocks rc0.

All three diff-tests run in seconds (no model calls) — they're pure-data comparisons.

**rc0 stabilization — manual sign-off.**

rc0 is a pure refactor diff-tested against the b1 → b13 cumulative set (~150 probes) AND `caplog`-record-equality on the four auto-select archive-count scenarios. The diff-tests cover the load-bearing risks; manual sign-off catches edge cases the diff-test missed (telemetry shapes, caching behavior, error-message wording).

**Sign-off process:**

- Cameron runs rc0 against a representative ZIM (e.g., Wikipedia) for a short ad-hoc probing session — a few hours, not days. Drawn from b13's known-good shapes. If clean, sign off on the rc0 PR.
- Website demo integration upgrade is **non-blocking** — it happens whenever convenient; any regression discovered post-tag is handled as `v2.0.0rc0.post1`.
- Any divergence Cameron finds during ad-hoc probing blocks rc1 (the divergence-handling path: fix → `v2.0.0rc0.post1` → re-probe → sign off).

There is no calendar-soak timer. The rationale for the earlier 14-day timer (bound the wait for external integration coordination) does not apply: the website demo upgrade is decoupled, and ad-hoc probing on a single-maintainer project is hours not days. Stage B opens once Cameron signs off.

### Gate 0b (PRE-rc1) — dispatch eval against prototype branch

After rc0 signs off, the **Phase F prototype branch** (`v2-phase-f-prototype`) is built on top of rc0 — it wires the 8-tool surface using the now-extracted preprocessing/promotion modules. The prototype is *not* merged; it exists to host the Gate 0b eval.

**Gate 0b runs the 2-variant × 2-mode × 5-rep × n=300 dispatch eval with criteria** (A, B, C1, C2, C3, D, F1, F2). In summary:

- **Architecture precondition (already cleared at Gate 0):** `oneOf` round-trip verified + small-model parsing benchmarked, or spec amended to flat-schema design.
- **b13 baseline cell** runs against the current b13 advanced surface (committed at `tests/dispatch_eval/baselines/b13.json`).
- **phase-f cell** runs against the prototype.
- Each variant runs against `simple` and `advanced` modes.
- **Primary model: Qwen-2.5-7B-Instruct** (local), 100% of cells. **Secondary cross-validation: Haiku-4.5**, 50% of cells.

**Decision rules:**

- If **Criterion D fails** (`phase-f` regresses against `b13`): Phase F has an architectural problem; rc1 does not open.
- If **Criterion D passes**: rc1 opens (modulo the other criteria below).
- If **any of C1/C2/C3 fails**: apply the pre-decided [Criterion C circuit-breaker](#criterion-c-circuit-breaker-pre-decided-fallback). Re-run the fallback cell only, confirm Criteria A/B/D/F still pass, then open rc1 with the fallback.
- If **Criterion F fails** on any class: investigate the class root cause. Localized fix; rc1 does not open until all classes pass.

**Gate 0b decision is committed** as `tests/dispatch_eval/gate_0b_decision.json` recording all criterion outcomes per cell, the Criterion C path taken (wired vs fallback), the final `TOTAL_CAP` value, AND a `scope_limitations` field enumerating known bounds on what the gate measured. The chosen behaviors are **baked into the rc1 commit as Python constants** — production code does NOT read `gate_0b_decision.json` at runtime.

**Gate 0b reproducibility — annotated tag pin.** The prototype branch HEAD used for Gate 0b is preserved as the annotated tag `v2.0.0-gate-0b-prototype` (pushed at the end of Stage C alongside the decision-artifact commit — see plan Task C3 Step 5). The tag carries the audit trail in its message so a future operator re-running Gate 0b under matched conditions can `git checkout v2.0.0-gate-0b-prototype` directly without resurrecting the prototype branch from reflogs. The pin is necessary because the prototype branch is never merged and may be pruned by branch-cleanup automation; without the pin, post-v2.0 Gate 0b re-runs would require rebuilding the prototype from scratch.

**`scope_limitations` field.** A list of strings making the gate's known measurement bounds machine-readable, not just inferable from the spec prose. A downstream auditor reading just the JSON should know the gate's scope without re-reading 1,000 lines of spec. Required entries at v2.0:

- `"probe-distribution: wikipedia-dominant"` — the 130 b-series + 120 representative probes are sampled from Wikipedia-shaped queries. Deployments on non-Wikipedia ZIM (Gutenberg, Wikiquote, internal docs) get unmeasured dispatch behavior.
- `"model-coverage: qwen-7b + llama-8b + phi-3.5-mini + haiku-4.5"` — open-weights coverage is two families at 7-8B and one family at sub-4B. Deployments on Mistral, Gemma, Yi, DeepSeek-Coder, or sub-2B models get unmeasured behavior. Future Gate 0b re-runs that add models extend this list.
- `"size-range: 3.8B–8B (open-weights)"` — Phi-3.5-mini at 3.8B is the smallest model measured. Sub-3B deployments (Gemma-2B, Qwen-1.5B, Llama-3.2-1B) get unmeasured behavior. Note: schema-handling quality is known to fall off sharply below ~3B.
- `"probe-language: english-only"` — all probes are English. Multilingual ZIM deployments get unmeasured behavior.
- (Optional) `"substitution: phi-3.5-mini → qwen-2.5-3b"` if the deployer fell back to Qwen-3B per the documented Phi substitution rule. Surfaces that the architecture-diversity-at-small-size signal was traded for the size signal.

The `scope_limitations` field is asserted non-empty by `tests/test_phase_f_gate_decision_consistency.py` — a maintainer who re-runs Gate 0b under different conditions and forgets to update this field trips the test.

### `v2.0.0rc1` — surface change

rc1 lands after Gate 0b's decision file commits. It implements the 8-tool surface, the per-tool module split, and the schema-conditional `oneOf` schemas (or flat-schema fallback per Gate 0 outcome).

**rc1 stabilization plan:**

1. **Multi-pass live sweep — full b-series set.** Run the established b2 → b13 beta-testing methodology against the new surface using the **full b1 → b13 cumulative probe set (~150 probes)**. n=150 × 5 reps = 750 effective observations CAN detect a 5pp regression at α=0.05 / β=0.20 against a high-baseline (~90%) accuracy bar — commensurate with Gate 0b's 5pp margin. Run via the **primary Qwen-2.5-7B** with secondary Haiku-4.5 (10pp veto), tertiary Llama-3.1-8B (10pp veto), AND quaternary Phi-3.5-mini (10pp veto) cross-validation. **Haiku and Llama run at reps=3** (n=150×3=450 effective) — matched power for their 10pp VETO. **Phi runs at reps=5** (n=150×5=750 effective) — matched to the primary so the 10pp veto on the sub-4B size class isn't strictly weaker than the same margin on the 8B-class secondaries (reps are cheap on a 3.8B model). The 25-probe subset is a smoke-test tool for fast defect triage between sweep iterations, not the stabilization-gate signal.
2. **`zim_get` dispatch sweep — new for Phase F.** The b-series set drives `zim_query`; it does not stress the `zim_get` dispatch surface (4 `oneOf` branches). With schema-conditional `oneOf` enforcement, *most* invalid combinations are unrepresentable at the schema level, so the sweep splits into two parts:
   - **Schema-representable coverage (legal probes).** At least 24 probes spanning every branch combination (single-entry-body × 4 views, single-entry-binary, batch, main-page, pagination edge cases).
   - **Schema-bypass coverage (defense-in-depth invalid probes).** **At least one probe per distinct oneOf-forbidden combination** (currently 13: mutex paths, binary single-only, binary view-locks ×3, binary/main_page conflict, main_page path-free ×2, main_page view-locks ×3, at-least-one-path ×2 — full enumeration in plan Task D15). The count grows in lockstep with any future API change that adds a forbidden combination. **Pass criterion:** each surfaces a structured `tool_error("invalid_path_combination", hint=...)` with the expected hint substring.

   **Pass criteria:** ≥95% schema-representable probes succeed end-to-end AND 100% schema-bypass probes surface a structured validation error.
3. **A/B confirmation sweep — Gate 0b decision held under live conditions, F1 + F2 + secondary/tertiary/quaternary VETO enforced.** Re-run the full b1 → b13 probe set against rc1 with all four models AND re-run the 300-probe Gate 0b probe set against rc1 with the primary Qwen + each available secondary/tertiary/quaternary. The Gate 0b run is what F2 enforcement requires (the b1→b13 cumulative set is dominated by `zim_query` NL queries — it doesn't exercise the Phase F operation classes that F2 covers). **Pass criteria:**
   - `rc1_correct ≥ b13_correct - 5 points` on the b1→b13 set with the primary (one-sided non-inferiority at α=0.05).
   - **F1 holds at 8pp ceiling per b-series class** on the b1→b13 set.
   - **F2 holds at 10pp ceiling per Phase F operation class** on the 300-probe Gate 0b set. F2 enforcement at Stage E (not just Gate 0b) catches the case where a fix between Gate 0b and rc1 patches one defect at the cost of another per-class regression — the prototype-to-rc1 rewrite is the riskiest moment in the timeline for this kind of localized regression to land unnoticed.
   - Secondary (Haiku), tertiary (Llama), quaternary (Phi) do NOT flag A/B/D regressions at their respective veto margins.
4. **Schema-budget regression.** Enforce the `test_phase_f_schema_budget.py` cap on every PR through rc1.
5. **Migration-story validation — broader than the website demo.** Update the website demo integration to v2.0.0rc1 AND run an automated conformance test that exercises every row in the migration table against a synthetic client.

### `v2.0.0` — final tag

When rc1's live sweep returns clean AND step 3's A/B confirmation passes AND the Gate 0b decision file is present and marks Criterion D as passed, `v2.0.0` cuts.

### v1.x maintenance commitment (rollback runway)

**The v1.x branch (specifically the most recent v1.x tag at the time v2.0.0 cuts) is retained as a parallel maintenance branch until the next v2.x release ships (`v2.5.0`) or 6 months after `v2.0.0`, whichever comes first.**

Rationale: Phase F is the largest surface change in the project's history (22 tools → 8, plus schema-conditional `oneOf`). The pre-release gates catch known regression classes but cannot rule out tail-risk regressions discovered after `v2.0.0` ships to real users. If a post-release regression surfaces and the fix isn't trivial, a v1.x patch release is a faster recovery path than a v2.0.1 backport.

**Maintenance scope:**

- **Accepted backports to v1.x:** security fixes (always), data-corruption fixes (always), and crash bugs introduced before v2.0.0 cut. Phase F's surface change itself is NOT backported.
- **Rejected backports to v1.x:** new features, new tools, performance work, refactors.
- **End-of-life trigger:** the FIRST of {`v2.5.0` ships, 6 calendar months after v2.0.0}. EOL is announced in the v1.x branch README at v2.0.0 cut.
- **Tag stability:** v1.x and v2 alpha/beta/rc tags remain pullable from PyPI — they are not yanked.

### Post-final

Phase F is the last v2 phase. Subsequent work (v2.5) is additive per [docs/v2.5/README.md](../v2.5/README.md) and does not change the tool surface.

---

## Housekeeping

Items split between the rc0 and rc1 PRs:

**rc0 housekeeping (lead-in commits before the extraction):**

1. **Add GitHub label.** `gh label create v2-phase-f --description "v2 phase F: tool surface consolidation" --color C5DEF5`. Used on both rc0 and rc1 PRs.
2. **Update v2 README Phase F row** with the spec link and `In Design` status.
3. **Mypy / ruff config for `tests/dispatch_eval/`.** The new `tests/dispatch_eval/` directory is intentionally excluded from the default test collection (Gate 0b runner makes paid API calls and is intended to be invoked manually, not in CI).

**rc1 housekeeping (lead-in commits before the surface code):**

1. **Fix `config.py` stale docstring.** `openzim_mcp/config.py:293` describes the `tool_mode='advanced'` value as registering "21 tools"; actual count is 22. rc1 updates the docstring to describe the new behavior — 8 tools when `'advanced'`, 1 when `'simple'`.
2. **Update v2 README Phase F row** to `In Implementation` when rc1 opens, then to `Shipped` when v2.0.0 cuts.
