"""Per-tool response TypedDicts for v2 Phase B.

Every dict-returning tool's ``_data`` method returns one of these
TypedDicts (or ``ToolErrorPayload`` from openzim_mcp.responses on
failure). FastMCP reads the function's return annotation to generate
the output schema and emits the payload at the top level of
``structuredContent`` — no ``{"result": ...}`` wrapper.

Every list-returning tool's TypedDict carries the five contract keys
(``results``, ``next_cursor``, ``total``, ``done``, ``page_info``)
plus ``_meta``. See the design spec for shape details:
docs/superpowers/specs/2026-05-08-v2-phase-b-response-contract-design.md
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, Optional, TypedDict, Union

from openzim_mcp.responses import ToolErrorPayload

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


class _SearchAllPerFile(TypedDict):
    zim_file_path: str
    name: str
    has_hits: bool
    # ``result`` is a ``SearchResponse`` when the per-file search succeeded.
    # When the per-archive search raised (e.g. ZIM lacks a full-text Xapian
    # index), it's a ``ToolErrorPayload`` envelope so the wire shape stays
    # uniform — every entry has ``result``, callers branch on ``error: True``.
    result: Union[SearchResponse, ToolErrorPayload]


class SearchAllResponse(TypedDict):
    results: list[_SearchAllPerFile]
    next_cursor: Optional[str]
    total: Optional[int]
    done: bool
    page_info: PageInfo
    _meta: MetaEnvelope
    # Tool-specific extras
    query: str
    files_searched: int
    files_with_hits: int
    files_searched_successfully: int
    files_failed: int


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
    metadata_entries: NotRequired[dict[str, Any]]
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
    """

    section_id: str
    text: str
    level: int
    id_source: Literal["id", "descendant_anchor", "preceding_anchor", "slug"]
    children: list[TocHeading]


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

    Section IDs come from openzim_mcp.content_processor.resolve_heading_id.
    char_start / char_end are offsets into EntryBundle.rendered_markdown.
    """

    id: str
    title: str
    level: int
    char_start: int
    char_end: int
    parent_id: NotRequired[Optional[str]]


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


class Citation(TypedDict):
    cite_id: str
    archive: str
    entry_path: str
    title: str
    section_id: Optional[str]
    section_title: Optional[str]


class SynthesizePassage(TypedDict):
    cite_id: str
    text_markdown: str
    rank: int
    score: float


class SynthesizeResponse(TypedDict):
    query: str
    answer_markdown: str
    passages: list[SynthesizePassage]
    citations: list[Citation]
    archives_searched: list[str]
    fallback_used: Literal["xapian_score", "rrf_fusion", "reranker"]
    total_chars: int
    total_words: int
    _meta: MetaEnvelope
