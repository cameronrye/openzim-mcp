"""Per-tool response TypedDicts for v2 Phase B.

Every dict-returning tool's ``_data`` method returns one of these
TypedDicts (or ``ToolErrorPayload`` from openzim_mcp.responses on
failure). FastMCP reads the function's return annotation to generate
the output schema and emits the payload at the top level of
``structuredContent`` — no ``{"result": ...}`` wrapper.

Every list-returning tool's TypedDict carries the five contract keys
(``results``, ``next_cursor``, ``total``, ``done``, ``page_info``)
plus ``_meta``. Cursors are opaque base64-encoded JSON; ``total`` may
carry ``total_is_lower_bound=True`` in ``PageInfo`` when an exact count
would be expensive; ``done=True`` signals end-of-stream for the current
filter set (in sampling browses, end-of-sample rather than
end-of-namespace).
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, Optional, TypedDict

# ---------- shared sub-shapes ----------


class PageInfo(TypedDict):
    offset: int
    limit: int
    returned_count: int
    total_is_lower_bound: NotRequired[bool]


class MetaEnvelope(TypedDict, total=False):
    tokens_est: int
    chars: int
    truncated: bool
    more_at_offset: int
    total_chars: int
    suggestions: list[dict[str, str]]
    reason: str


# ---------- per-item shapes ----------


class SearchHit(TypedDict):
    path: str
    title: str
    snippet: str
    # search_all carries archive identity per-hit; per-archive search omits it.
    zim_file: NotRequired[str]


class FindEntryHit(TypedDict):
    path: str
    title: str
    score: float
    zim_file: NotRequired[str]
    match_type: NotRequired[str]
    # Post-b6 Z1: the path emitted by libzim's suggestion search /
    # fast-path lookup BEFORE ``_follow_redirect_chain`` resolved it
    # to the canonical. Equals ``path`` when no redirect was walked;
    # differs when ``match_type == "redirect"``. Callers using the
    # 0.95 gate check whether the user's query tokens (especially
    # possessor tokens) appear in this pre-redirect path to filter
    # associative-not-semantic redirects.
    pre_redirect_path: NotRequired[str]


class SuggestionItem(TypedDict):
    text: str
    path: str
    type: str


class NamespaceEntry(TypedDict):
    path: str
    title: str
    content_type: NotRequired[str]
    preview: NotRequired[str]


class WalkEntry(TypedDict):
    path: str
    title: str


class LinkItem(TypedDict):
    """One extracted link record. Shape varies slightly per category:

    Internal/external entries carry ``url``, ``text``, ``title``, ``type``,
    and (for external links) ``domain``. Media entries carry ``url``,
    ``type``, ``alt``, and ``title``. All fields except ``url`` and ``type``
    are ``NotRequired`` because they're absent on at least one category.
    """

    url: str
    type: NotRequired[str]
    text: NotRequired[str]
    title: NotRequired[str]
    domain: NotRequired[str]
    alt: NotRequired[str]


class FileSummary(TypedDict):
    name: str
    path: str
    directory: str
    size: str
    size_bytes: int
    modified: str


class RelatedArticle(TypedDict):
    path: str
    title: str
    link_text: NotRequired[str]


class NamespaceSummary(TypedDict):
    # Per-namespace count. ``total`` replaces the legacy ``count`` field
    # so this aligns with the Phase B canonical naming used elsewhere
    # (PaginatedResponse.total, etc.). For full-iteration buckets it is
    # exact; for sampled buckets it is the projected estimate
    # (``estimated_total``).
    total: int
    # True when the bucket was discovered exhaustively (full iteration,
    # or a deterministic source like ``archive.metadata_keys`` /
    # canonical-probes-only). False when the bucket's ``total`` was
    # extrapolated from random sampling.
    is_authoritative: bool
    # Diagnostic fields surfaced for callers that want to reason about
    # the discovery method. ``description`` and ``sample_entries`` come
    # from every namespace; ``sampled_count`` / ``probed_count`` /
    # ``estimated_total`` are populated whether discovery was full or
    # sampled (sampled-only namespaces just zero the unused half).
    description: NotRequired[str]
    sample_entries: NotRequired[list[dict[str, str]]]
    sampled_count: NotRequired[int]
    probed_count: NotRequired[int]
    estimated_total: NotRequired[int]


# ---------- list-returning tool responses ----------


class SearchResponse(TypedDict):
    # Contract keys
    results: list[SearchHit]
    next_cursor: Optional[str]
    total: Optional[int]
    done: bool
    page_info: PageInfo
    _meta: MetaEnvelope
    # Tool-specific extras
    query: str


class _SearchAllPerFile(TypedDict, total=False):
    """Per-file row inside ``SearchAllResponse.results``.

    H14: ``result`` was previously a ``Union[SearchResponse, ToolErrorPayload]``
    so callers had to type-sniff its shape. Phase B's contract wants
    ``results[].result`` to be a single shape; errors now ride a sibling
    ``error`` flag plus ``error_message`` / ``error_operation`` so the wire
    contract is uniform.
    """

    zim_file_path: str
    name: str
    has_hits: bool
    # Always present. ``None`` when ``error=True``; a ``SearchResponse`` otherwise.
    result: Optional[SearchResponse]
    # Always present. ``True`` on per-file failure, ``False`` on success.
    error: bool
    # Populated only when ``error=True``.
    error_operation: str
    error_message: str


class SearchAllResponse(TypedDict, total=False):
    results: list[_SearchAllPerFile]
    next_cursor: Optional[str]
    total: Optional[int]
    done: bool
    page_info: PageInfo
    _meta: MetaEnvelope
    # Tool-specific extras
    query: str
    files_searched: int
    # H22: ``files_available`` is the total ZIM count the server could see;
    # ``files_searched`` is the count actually probed (may be smaller when
    # the aggregate timeout fired).
    files_available: int
    files_with_hits: int
    files_searched_successfully: int
    files_failed: int
    # H22: True when the aggregate timeout cut iteration short. ``done`` is
    # set to False in this case so callers know more archives remain.
    budget_exceeded: bool


class SearchWithFiltersResponse(TypedDict):
    results: list[SearchHit]
    next_cursor: Optional[str]
    total: Optional[int]
    done: bool
    page_info: PageInfo
    _meta: MetaEnvelope
    query: str
    namespace_filter: Optional[str]
    content_type_filter: Optional[str]


class FindEntryResponse(TypedDict):
    results: list[FindEntryHit]
    next_cursor: Optional[str]
    total: Optional[int]
    done: bool
    page_info: PageInfo
    _meta: MetaEnvelope
    query: str
    fast_path_hit: bool
    fuzzy_path_hit: bool
    files_searched: int


class SearchSuggestionsResponse(TypedDict):
    results: list[SuggestionItem]
    next_cursor: Optional[str]
    total: Optional[int]
    done: bool
    page_info: PageInfo
    _meta: MetaEnvelope
    partial_query: str


class BrowseNamespaceResponse(TypedDict):
    results: list[NamespaceEntry]
    next_cursor: Optional[str]
    total: Optional[int]
    done: bool
    page_info: PageInfo
    _meta: MetaEnvelope
    namespace: str
    discovery_method: str
    sampling_based: bool
    results_may_be_incomplete: bool


class WalkNamespaceResponse(TypedDict):
    results: list[WalkEntry]
    next_cursor: Optional[str]
    total: Optional[int]
    done: bool
    page_info: PageInfo
    _meta: MetaEnvelope
    namespace: str
    scanned_count: int
    # ``None`` when the loop never advanced past ``scan_at`` (e.g. the cursor
    # was already at/past the archive end so no entries were examined).
    scanned_through_id: Optional[int]
    archive_entry_count: int


class LinksResponse(TypedDict):
    results: list[LinkItem]
    next_cursor: Optional[str]
    total: Optional[int]
    done: bool
    page_info: PageInfo
    _meta: MetaEnvelope
    title: str
    path: str
    content_type: str
    kind: str
    category_totals: dict[str, int]
    # Set when content_type is non-HTML; explains why results is empty.
    message: NotRequired[str]


class ListZimFilesResponse(TypedDict):
    results: list[FileSummary]
    next_cursor: Optional[str]
    total: Optional[int]
    done: bool
    page_info: PageInfo
    _meta: MetaEnvelope
    name_filter: Optional[str]
    directories_count: int


class RelatedArticlesResponse(TypedDict):
    results: list[RelatedArticle]
    next_cursor: Optional[str]
    total: Optional[int]
    done: bool
    page_info: PageInfo
    _meta: MetaEnvelope
    entry_path: str
    # Set on partial-success when archive- or extraction-level failure
    # downgrades the response to an empty list with a textual reason.
    outbound_error: NotRequired[str]
    # Set when frequency rank was computed over a truncated link sample
    # (the underlying link scan capped at ``scan_limit`` and there are
    # more internal links in the source article). Callers should treat
    # the ranking as document-head-biased on hub articles when this is
    # True. ``_meta.reason`` carries ``"scan_truncated"`` to surface
    # the same signal to compact-mode renderers.
    scan_truncated: NotRequired[bool]
    scan_total_internal: NotRequired[int]
    scan_limit: NotRequired[int]


class _BatchEntryItem(TypedDict):
    index: int
    zim_file_path: str
    entry_path: str
    success: bool
    content: NotRequired[str]
    error: NotRequired[str]


class BatchEntryResponse(TypedDict):
    results: list[_BatchEntryItem]
    next_cursor: Optional[str]
    total: Optional[int]
    done: bool
    page_info: PageInfo
    _meta: MetaEnvelope
    succeeded: int
    failed: int


# ---------- non-list tool responses ----------


class ZimMetadataResponse(TypedDict):
    entry_count: int
    all_entry_count: int
    article_count: int
    media_count: int
    # Native libzim identity + index-capability fields.
    uuid: str
    is_multipart: bool
    has_fulltext_index: bool
    has_title_index: bool
    metadata_entries: NotRequired[dict[str, Any]]
    # Parsed ``M/Counter`` — {mimetype: count}. Omitted when absent.
    counter_breakdown: NotRequired[dict[str, int]]
    _meta: MetaEnvelope


class ListNamespacesResponse(TypedDict):
    total_entries: int
    sampled_entries: int
    has_new_namespace_scheme: bool
    is_total_authoritative: bool
    discovery_method: str
    namespaces: dict[str, NamespaceSummary]
    _meta: MetaEnvelope


class EntryResponse(TypedDict):
    path: str
    title: str
    content: str
    content_type: NotRequired[str]
    # ``requested_path`` is set when the resolved entry differs from the
    # requested path (redirect or fallback search); callers can use it to
    # confirm what they asked for vs. what they got.
    requested_path: NotRequired[str]
    # ``content_offset`` and ``total_chars`` are populated when the caller
    # passed a non-zero offset, so they can page through long articles
    # without re-fetching the prefix.
    content_offset: NotRequired[int]
    total_chars: NotRequired[int]
    _meta: MetaEnvelope


class EntrySummaryResponse(TypedDict):
    path: str
    title: str
    summary: str
    word_count: NotRequired[int]
    # ``content_type`` and ``is_truncated`` are always emitted by the
    # current implementation; declared NotRequired so future code paths
    # that omit them (e.g. errors short-circuited before extraction)
    # remain schema-conformant.
    content_type: NotRequired[str]
    is_truncated: NotRequired[bool]
    _meta: MetaEnvelope


# ---------------------------------------------------------------------------
# Phase C — TOC heading (replaces list[dict[str, Any]] in TableOfContentsResponse)
# ---------------------------------------------------------------------------


class TocHeading(TypedDict):
    """One heading in get_table_of_contents output.

    `section_id` is the value to pass to get_section(section_id=...).
    Renamed from the old `id` field for clarity.

    `id_source` documents how the section identifier was derived (``"id"``
    when libzim/raw HTML carried an explicit anchor, ``"descendant_anchor"``
    / ``"preceding_anchor"`` when we resolved it from a nearby anchor in
    the soup, or ``"slug"`` when we generated a slug from the heading
    text). Preserved per the Phase C spec so callers can tell which IDs
    are stable across re-rendering vs. derived heuristically.
    """

    section_id: str
    text: str
    level: int
    children: list[TocHeading]
    id_source: NotRequired[
        Literal["id", "descendant_anchor", "preceding_anchor", "slug"]
    ]


class TableOfContentsResponse(TypedDict):
    title: str
    path: str
    content_type: NotRequired[str]
    toc: list[TocHeading]
    heading_count: int
    max_depth: int
    # Set when content_type is non-HTML; explains why toc is empty.
    message: NotRequired[str]
    _meta: MetaEnvelope


class ArticleStructureResponse(TypedDict):
    title: str
    path: str
    content_type: str
    headings: list[dict[str, Any]]
    sections: list[dict[str, Any]]
    metadata: dict[str, Any]
    word_count: int
    character_count: int
    _meta: MetaEnvelope


class BinaryEntryResponse(TypedDict):
    path: str
    title: str
    mime_type: str
    size: int
    size_human: str
    encoding: Optional[str]
    truncated: bool
    data: NotRequired[Optional[str]]
    message: NotRequired[str]
    _meta: MetaEnvelope


# ---------------------------------------------------------------------------
# Phase C — bundle internals
# ---------------------------------------------------------------------------


class SectionMeta(TypedDict):
    """One section's metadata in an EntryBundle.

    Section IDs come from openzim_mcp.content_processor.resolve_heading_id;
    ``id_source`` records which arm of that resolver produced the ID
    (preserved through the TOC response so callers can tell stable
    anchors from generated slugs).
    char_start / char_end are offsets into EntryBundle.rendered_markdown.
    """

    id: str
    title: str
    level: int
    char_start: int
    char_end: int
    parent_id: NotRequired[Optional[str]]
    id_source: NotRequired[
        Literal["id", "descendant_anchor", "preceding_anchor", "slug"]
    ]


class InfoboxField(TypedDict):
    label: str
    value: str


class InfoboxData(TypedDict):
    title: NotRequired[str]
    fields: list[InfoboxField]


class LinkBuckets(TypedDict):
    internal: list[LinkItem]
    external: list[LinkItem]
    media: list[LinkItem]


class EntryBundle(TypedDict):
    """Single-parse intermediate for content-shape tools.

    First touch of an entry produces this bundle; subsequent calls to
    get_entry_summary, get_table_of_contents, get_article_structure,
    extract_article_links, and get_section all slice into it without
    re-parsing the HTML. Stored under cache key
    'bundle:v2c:{validated_path}:{entry_path}'.
    """

    entry_path: str
    title: str
    content_type: str
    word_count: int
    char_count: int
    rendered_markdown: str
    sections: list[SectionMeta]
    links: LinkBuckets
    infobox: Optional[InfoboxData]


# ---------------------------------------------------------------------------
# Phase C — get_section response
# ---------------------------------------------------------------------------


class GetSectionResponse(TypedDict):
    entry_path: str
    title: str
    section_id: str
    section_title: str
    level: int
    parent_id: Optional[str]
    content_markdown: str
    char_count: int
    word_count: int
    truncated: bool
    _meta: MetaEnvelope


# ---------------------------------------------------------------------------
# Phase C — synthesize response
# ---------------------------------------------------------------------------


class Citation(TypedDict, total=False):
    """A citation in a SynthesizeResponse.

    ``total=False`` lets D8 (v2.0.0a9) attach ``rank`` and ``score``
    in compact-mode synthesize responses — fields the verbose path
    keeps on ``SynthesizePassage`` but compact mode drops the
    passages array entirely to save tokens. Compact callers correlate
    rank/score with the citation directly.
    """

    cite_id: str
    archive: str
    entry_path: str
    title: str
    section_id: Optional[str]
    section_title: Optional[str]
    rank: int
    score: float


class SynthesizePassage(TypedDict):
    cite_id: str
    text_markdown: str
    rank: int
    score: float


class ConsideredArticle(TypedDict, total=False):
    """A14: an article hit not selected as the featured citation, surfaced
    so the caller can pivot in a follow-up turn without re-running search.

    ``archive`` + ``entry_path`` form the handle the caller passes to
    ``get_zim_entries`` (or composes into a ``cite_id``). ``score`` is the
    underlying ranking score at the point of selection — informational,
    not part of the handle.
    """

    archive: str
    entry_path: str
    title: str
    score: float


class ConsideredSection(TypedDict, total=False):
    """A14: a section of the featured article not selected as the featured
    passage. ``section_id`` is the handle the caller passes to
    ``get_section`` (or composes into a ``cite_id`` suffix).
    """

    section_id: str
    title: str


class SynthesizeResponse(TypedDict, total=False):
    query: str
    answer_markdown: str
    passages: list[SynthesizePassage]
    citations: list[Citation]
    archives_searched: list[str]
    fallback_used: Literal["xapian_score", "rrf_fusion", "reranker"]
    total_chars: int
    total_words: int
    _meta: MetaEnvelope
    # A14: multi-round handles. Empty lists when no candidate space
    # exists (zero-hit response, or no resolved entity article).
    considered_articles: list[ConsideredArticle]
    considered_sections: list[ConsideredSection]


# ---------------------------------------------------------------------------
# Phase B — server-tools responses
# ---------------------------------------------------------------------------


class UptimeInfo(TypedDict):
    """Uptime block of ``HealthStatus``."""

    process_id: str
    started_at: str
    uptime_seconds: Optional[float]


class HealthChecks(TypedDict):
    """Per-check booleans/counters of ``HealthStatus``."""

    directories_accessible: int
    zim_files_found: int
    permissions_ok: bool


class HealthConfiguration(TypedDict):
    """Configuration summary embedded in the health report."""

    allowed_directories: int
    cache_enabled: bool
    config_hash: str


class HealthStatus(TypedDict, total=False):
    """Health block of ``ServerHealthResponse`` — the shape the legacy
    ``get_server_health`` tool returned at v2.0.0rc0.

    Renamed from ``ServerHealthResponse`` at Phase F rc1 because that
    name now belongs to the combined-shape ``zim_health`` response (see
    below). Legacy ``server_tools.py`` callers were updated to import
    ``HealthStatus`` directly.

    ``cache_performance`` and ``simple_tools_telemetry`` carry free-form
    dicts whose shape is owned by the cache / simple-tools modules; the
    server-tools surface intentionally doesn't pin them here so additions
    in those modules don't ripple back into the response schema.
    """

    timestamp: str
    status: str
    server_name: str
    uptime_info: UptimeInfo
    configuration: HealthConfiguration
    cache_performance: dict[str, Any]
    simple_tools_telemetry: dict[str, Any]
    health_checks: HealthChecks
    recommendations: list[str]
    warnings: list[str]


class ServerConfigDetails(TypedDict):
    """Configuration block inside ``ServerConfigurationResponse``."""

    server_name: str
    allowed_directories: list[str]
    allowed_directories_count: int
    cache_enabled: bool
    cache_max_size: int
    cache_ttl_seconds: int
    content_max_length: int
    content_snippet_length: int
    search_default_limit: int
    config_hash: str
    server_pid: str


class ServerConfigDiagnostics(TypedDict):
    """Diagnostics block inside ``ServerConfigurationResponse``."""

    validation_status: str
    warnings: list[str]
    recommendations: list[str]


class ServerConfigurationResponse(TypedDict):
    """``get_server_configuration`` success payload."""

    configuration: ServerConfigDetails
    diagnostics: ServerConfigDiagnostics
    timestamp: str


# Phase F rc1 alias: the spec calls this ``ServerConfig`` when used as a
# building block of ``ServerHealthResponse``. Keeping both names lets
# legacy ``server_tools.py`` continue to import the long name while the
# new combined response references the spec-matching short one.
ServerConfig = ServerConfigurationResponse


# Phase F rc1 alias: spec name ``ArchiveInfo`` for ``FileSummary`` when
# carried as an element of ``ServerHealthResponse.loaded_archives``.
ArchiveInfo = FileSummary


class NamespaceInfo(TypedDict):
    """List-form variant of a single namespace entry, used inside
    ``ArchiveMetadataResponse.namespaces``.

    The legacy ``list_namespaces`` data returns a ``dict[str, NamespaceSummary]``
    keyed by namespace letter. The combined ``zim_metadata`` response
    converts that dict to a list so small models can iterate naturally
    over namespaces without flattening a single-character-keyed mapping.
    """

    letter: str
    total: int
    is_authoritative: bool
    description: NotRequired[str]
    sample_entries: NotRequired[list[dict[str, str]]]
    sampled_count: NotRequired[int]
    probed_count: NotRequired[int]
    estimated_total: NotRequired[int]


class ArchiveMetadataResponse(TypedDict):
    """Phase F ``zim_metadata`` success payload.

    Combines the per-archive M-namespace fields (current
    ``get_zim_metadata`` shape) with the namespace inventory (current
    ``list_namespaces`` shape, converted to list-form). The combined
    tool collapses ``get_zim_metadata`` + ``list_namespaces`` into one.

    Per the design spec, this response does **not** expose
    ``main_page_path``. The canonical main-page fetch is
    ``zim_get(main_page=True)``; surfacing the path here would create
    two routes that small models would null-check unnecessarily.
    """

    metadata: dict[str, str]
    namespaces: list[NamespaceInfo]
    # Native libzim archive identity ({uuid, is_multipart}) and index
    # capabilities ({has_fulltext_index, has_title_index}). Always emitted by
    # get_archive_metadata_data, so they are required (not NotRequired).
    archive_identity: dict[str, Any]
    index_capabilities: dict[str, bool]
    # Parsed ``M/Counter`` breakdown ({mimetype: count}); omitted when the
    # archive carries no Counter metadata.
    counter_breakdown: NotRequired[dict[str, int]]
    _meta: MetaEnvelope


class ArchiveValidationResponse(TypedDict):
    """Per-archive validation payload from ``zim_health(zim_file_path=...)``.

    Reports the native ``Archive.check()`` integrity result, checksum
    availability, index presence, and archive identity. Distinct from the
    server-state ``ServerHealthResponse`` returned by ``zim_health()``.
    """

    path: str
    name: str
    is_valid: bool  # Archive.check() — internal checksum verification
    has_checksum: bool
    checksum: Optional[str]  # hex digest when has_checksum, else None
    has_fulltext_index: bool
    has_title_index: bool
    uuid: str
    is_multipart: bool
    _meta: MetaEnvelope


class ServerHealthResponse(TypedDict):
    """Phase F ``zim_health`` success payload — combined server state.

    Replaces the legacy single-purpose shape (now ``HealthStatus``) by
    folding three tools into one: ``get_server_health`` +
    ``get_server_configuration`` + ``list_zim_files``. Single tool that
    answers "what is this server, what does it have, and is it OK".
    """

    health: HealthStatus
    configuration: ServerConfig
    loaded_archives: list[ArchiveInfo]
    _meta: MetaEnvelope
