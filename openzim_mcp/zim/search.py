"""Search-related methods for ``ZimOperations``.

This mixin holds the search/suggestion/title-resolution surface — the
methods that read the ZIM archive's full-text and title indexes. Methods
here run as instance methods of ``ZimOperations`` via the mixin pattern,
so ``self`` exposes the full ``ZimOperations`` API (cache, validator,
content processor, plus other mixins' methods).

The only subtle point is ``zim_archive`` access: tests monkey-patch
``openzim_mcp.zim_operations.zim_archive``, so call sites resolve it via
the ``zim_operations`` module at call time rather than capturing a
reference at import time.
"""

import logging
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, cast

from libzim.reader import Archive  # type: ignore[import-untyped]

import openzim_mcp.zim_operations as _zim_ops_mod
from openzim_mcp.defaults import CONTENT as _CONTENT_DEFAULTS
from openzim_mcp.exceptions import (
    OpenZimMcpArchiveError,
    OpenZimMcpValidationError,
)
from openzim_mcp.meta import attach_meta
from openzim_mcp.text_utils import tokenize_for_relevance
from openzim_mcp.title_promotion import find_title_match
from openzim_mcp.zim._ops_base import _json

# Mirror ``openzim_mcp.zim.archive.MAX_REDIRECT_DEPTH`` without importing
# it directly — archive.py imports this module, so the reverse-import
# would be circular at module-init time.
MAX_REDIRECT_DEPTH = _CONTENT_DEFAULTS.MAX_REDIRECT_DEPTH

if TYPE_CHECKING:
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.content_processor import ContentProcessor
    from openzim_mcp.security import PathValidator
    from openzim_mcp.tool_schemas import (
        FindEntryResponse,
        SearchAllResponse,
        SearchResponse,
        SearchSuggestionsResponse,
        SearchWithFiltersResponse,
    )

logger = logging.getLogger(__name__)


# Streaming knobs for ``_perform_filtered_search``: bound memory and CPU
# for pathological queries while keeping the page-fill loop predictable.
_FILTERED_BATCH_SIZE = 500
_FILTERED_MAX_SCAN = 10000


def canonical_result_path(path: str) -> str:
    """Strip the query string and fragment from a result path.

    warc2zim stores query-string URL variants as distinct entries, so a
    full-text search surfaces e.g. ``ency/quiz/001214_3.htm`` and
    ``ency/quiz/001214_3.htm?quiz=1`` as two hits for the same page.
    Collapsing on the canonical (query/fragment-free) path lets the
    filtered-search scanner emit each page once.
    """
    return path.split("?", 1)[0].split("#", 1)[0]


def _no_fulltext_index_payload(
    query: str,
    *,
    offset: int,
    limit: int,
    namespace: Optional[str] = None,
    content_type: Optional[str] = None,
    filtered: bool = False,
) -> Dict[str, Any]:
    """Build the empty search payload for an archive with no fulltext index.

    Shared by ``search_zim_file_data`` and ``search_with_filters_data`` so
    both degrade to the same ``reason="no_xapian_index"`` contract instead
    of diverging (the filtered path previously raised a hard error).
    """
    payload: Dict[str, Any] = {
        "query": query,
        "results": [],
        "next_cursor": None,
        "total": 0,
        "done": True,
        "page_info": {
            "offset": offset,
            "limit": limit,
            "returned_count": 0,
        },
    }
    if filtered:
        payload["namespace_filter"] = namespace
        payload["content_type_filter"] = content_type
    return payload


@dataclass(frozen=True)
class _FilteredScanState:
    """Aggregate state captured during one filtered-search scan pass."""

    filtered_count: int
    scanned: int
    scan_cap_hit: bool
    total_filtered_is_lower_bound: bool
    unfiltered_total: int = 0  # pre-filter Xapian hit count, for reason classification


def _format_filter_text(namespace: Optional[str], content_type: Optional[str]) -> str:
    """Render the ``(filters: ...)`` annotation used in result headers."""
    parts: List[str] = []
    if namespace:
        parts.append(f"namespace={namespace}")
    if content_type:
        parts.append(f"content_type={content_type}")
    return f" (filters: {', '.join(parts)})" if parts else ""


# Wikipedia / MediaWiki pseudo-namespaces excluded from suggestion + title
# probe results. These live in the C namespace (not separate ZIM
# namespaces) but use a colon-prefixed title convention to mark
# administrative/templating content. Used in three places — Strategy 1,
# Strategy 2, and the canonical-prefix probe — kept here so the lists
# stay in sync.
_PSEUDO_NAMESPACE_PATH_PREFIXES = ("M/", "X/", "-/")
_PSEUDO_NAMESPACE_TITLE_PREFIXES_STRICT = (
    "File:",
    "Category:",
    "Template:",
)
_PSEUDO_NAMESPACE_TITLE_PREFIXES_EXTENDED = (
    *_PSEUDO_NAMESPACE_TITLE_PREFIXES_STRICT,
    "User:",
    "Wikipedia:",
    "Help:",
)


def _is_pseudo_namespace_entry(
    path: str, title: str, *, extended: bool = False
) -> bool:
    """Return True iff ``path``/``title`` looks like a pseudo-namespace
    entry that should be excluded from suggestion / canonical-probe
    output.

    ``extended=True`` adds ``User:`` / ``Wikipedia:`` / ``Help:`` to the
    excluded-title-prefix set; the canonical-probe path uses the
    extended set, the suggest-from-search path uses the strict set.
    """
    if any(path.startswith(p) for p in _PSEUDO_NAMESPACE_PATH_PREFIXES):
        return True
    prefixes = (
        _PSEUDO_NAMESPACE_TITLE_PREFIXES_EXTENDED
        if extended
        else _PSEUDO_NAMESPACE_TITLE_PREFIXES_STRICT
    )
    return any(title.startswith(p) for p in prefixes)


def _all_results_weakly_match(results: List[Dict[str, Any]], query: str) -> bool:
    """Return True iff NONE of the search results carry any query token.

    libzim's Python binding doesn't expose per-result BM25 scores, so we
    use a cheap proxy: when no result's path or title shares a meaningful
    token with the query, every hit is contextually weak even though
    Xapian found *something*. The signal feeds ``reason=low_relevance``
    on the response so the model can pivot (try alt spellings, broaden
    the query) rather than treat noisy results as authoritative.

    Returns False when ``results`` is empty (callers gate on
    ``total_results > 0`` so empty lists never reach this path; defensive).
    """
    if not results:
        return False
    query_tokens = tokenize_for_relevance(query)
    if not query_tokens:
        return False
    for r in results:
        haystack = f"{r.get('path', '')} {r.get('title', '')}"
        r_tokens = tokenize_for_relevance(haystack)
        if query_tokens & r_tokens:
            return False
    return True


def _format_filtered_response(
    query: str,
    filter_text: str,
    results: List[Dict[str, Any]],
    scan: _FilteredScanState,
    total_results: int,
    offset: int,
    limit: int,
    *,
    display_query: Optional[str] = None,
) -> str:
    """Render the human-readable response body, header, and pagination footer.

    Post-b1 P3-D1: ``display_query`` overrides ``query`` in the user-
    facing echo string. ``query`` is the matched form (lowercased by
    Sub-D-2 Rule 1); ``display_query`` is the original-case form so
    the caller sees the casing they typed.
    """
    capped_note = (
        f" (filtered from first {scan.scanned} of " f"~{total_results} unfiltered hits)"
        if scan.scan_cap_hit
        else ""
    )
    # When ``filtered_count`` is a lower bound, surface that with a ``+``
    # suffix so callers don't mistake it for the final count.
    total_filtered_text = (
        f"{scan.filtered_count}+"
        if scan.total_filtered_is_lower_bound
        else str(scan.filtered_count)
    )
    echo_query = display_query if display_query else query

    parts: List[str] = [
        f'Found {total_filtered_text} filtered matches for "{echo_query}"'
        f"{filter_text}, "
        f"showing {offset + 1}-{offset + len(results)}{capped_note}:\n\n",
    ]
    # P3-D1 contract defence: callers may pass an active namespace /
    # content_type filter so per-result rows without those keys still
    # render meaningful labels. The data builder now populates these
    # fields (P3-D1 fix), but defensive .get() guards historical /
    # synthetic paths that surface namespace-less rows.
    filter_namespace_fallback = ""
    filter_content_type_fallback = ""
    if "namespace=" in filter_text:
        # ``filter_text`` is " (filters: namespace=C, content_type=text/html)"
        # — extract the namespace token for the fallback label.
        ns_seg = filter_text.split("namespace=", 1)[1]
        filter_namespace_fallback = ns_seg.split(",", 1)[0].rstrip(")").strip()
    if "content_type=" in filter_text:
        ct_seg = filter_text.split("content_type=", 1)[1]
        filter_content_type_fallback = ct_seg.split(",", 1)[0].rstrip(")").strip()
    for i, result in enumerate(results):
        parts.append(f"## {offset + i + 1}. {result['title']}\n")
        parts.append(f"Path: {result['path']}\n")
        ns_label = result.get("namespace") or filter_namespace_fallback or "?"
        ct_label = result.get("content_type") or filter_content_type_fallback or "?"
        parts.append(f"Namespace: {ns_label}\n")
        parts.append(f"Content Type: {ct_label}\n")
        # A11 post-a11 L3: same canonical-title-match badge handling as
        # ``_format_search_text`` so filtered-search results that pick
        # up the splice (post-a11 H2) use the same shape as plain search.
        snippet = result.get("snippet", "")
        if snippet == "(canonical title match)":
            parts.append("Match type: canonical title match\n\n")
        else:
            parts.append(f"Snippet: {snippet}\n\n")

    parts.append("---\n")
    has_more = scan.total_filtered_is_lower_bound or (
        offset + len(results) < scan.filtered_count
    )
    # Compact one-liner footer (v1.2.0+). The previous 3-4 line block (with a
    # base64 cursor blob spelled out alongside the offset hint) added ~50
    # tokens to every search response that the agentic loop then re-prompt-
    # eval'd on every subsequent turn. The cursor parameter is still an
    # accepted input — it's just no longer advertised in the response, since
    # an LLM keeping the conversation context can pass ``offset`` and re-
    # supply the original query without losing any information.
    if has_more:
        parts.append(
            f"Showing {offset + 1}-{offset + len(results)} "
            f"of {total_filtered_text} — "
            f"pass `offset={offset + limit}` for the next page\n"
        )
        # A14: when the result set is much larger than a small model can
        # productively page through, nudge toward refining the query
        # instead. Pre-A14, a "notable people from X" search returning
        # 4000 hits would lead an 8B model to either give up or mechanically
        # page until its context budget died. The O2 saturation warning at
        # ≥1M hits caught only stop-word collisions; mid-tier hit counts
        # had no equivalent guidance.
        if _is_large_result_set(scan.filtered_count, len(results)):
            parts.append(_refinement_nudge() + "\n")
    else:
        parts.append(
            f"Showing {offset + 1}-{offset + len(results)} "
            f"of {total_filtered_text} (end of results)\n"
        )
    return "".join(parts)


# A14: threshold above which the response surfaces a refinement nudge
# alongside the next-page hint. Picked so that a 3-result page facing
# >65× more results triggers the nudge — well below the 1M stop-word
# saturation O2 threshold but high enough to avoid nagging on normal
# topical searches (10-100 hits).
_REFINEMENT_NUDGE_TOTAL_THRESHOLD = 200
_REFINEMENT_NUDGE_PAGE_RATIO = 20  # total ≥ page_size × ratio


def _is_large_result_set(total: int, page_size: int) -> bool:
    """Return True when the unpaged total is large enough that mechanical
    paging is unlikely to be productive for a small model. Used to decide
    whether to attach the refinement nudge to the pagination footer.
    """
    if page_size <= 0:
        return False
    return (
        total >= _REFINEMENT_NUDGE_TOTAL_THRESHOLD
        and total >= page_size * _REFINEMENT_NUDGE_PAGE_RATIO
    )


def _refinement_nudge() -> str:
    """One-line nudge appended to large-result-set pagination footers.

    Keep this terse — every byte costs the agentic loop on each turn.
    """
    return (
        "Tip: result set is large — try refining with a quoted phrase or a "
        "more specific term instead of paging through all hits."
    )


class _SearchMixin:
    """Search, suggestion, and title-resolution methods for ZimOperations.

    Attributes below are provided by the concrete ``ZimOperations`` class
    that mixes this in; they're declared at the type-checker level so the
    mixin's method bodies type-check against the same surface.
    """

    # Attributes contributed by ZimOperations.__init__.
    if TYPE_CHECKING:
        config: "OpenZimMcpConfig"
        path_validator: "PathValidator"
        cache: "OpenZimMcpCache"
        content_processor: "ContentProcessor"

        def _validate_zim_path(self, zim_file_path: str) -> Path:
            """Resolve via ``_ArchiveAccessMixin`` on the concrete coordinator."""

        def list_zim_files_data(
            self, name_filter: Optional[str] = None
        ) -> List[Dict[str, Any]]:
            """Resolve via ``ZimOperations`` on the concrete coordinator."""

        # Resolve via the content mixin; declared here for type checking.
        def _get_entry_snippet(self, entry: Any, query: Optional[str] = None) -> str:
            """Resolve via ``_ContentMixin`` on the concrete coordinator."""

        # Resolve via the namespace mixin; declared here for type checking.
        def _canonicalise_namespace(self, namespace: str) -> str:
            """Resolve via ``_NamespaceMixin`` on the concrete coordinator."""

    def search_zim_file(
        self,
        zim_file_path: str,
        query: str,
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        display_query: Optional[str] = None,
    ) -> str:
        """Markdown-rendered search result (legacy surface).

        See ``search_zim_file_data`` for the structured variant. This wrapper
        is retained so existing callers (and tests) that consume the rendered
        text keep working unchanged.

        Args:
            zim_file_path: Path to the ZIM file
            query: Search query term (lowercased upstream by Sub-D-2 Rule 1)
            limit: Maximum number of results to return
            offset: Result starting offset (for pagination)
            display_query: Optional original-case form of ``query`` for
                user-facing echo strings (post-b1 P3-D1). The search
                backend matches case-insensitively, so this only
                affects the rendered ``Found N matches for "X"`` /
                ``No results found for "X"`` strings.

        Returns:
            Search result text

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If search operation fails
        """
        payload = self.search_zim_file_data(zim_file_path, query, limit, offset)
        return self._format_search_text(payload, display_query=display_query)

    def search_zim_file_data(
        self,
        zim_file_path: str,
        query: str,
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        cursor_archive_identity: Optional[str] = None,
    ) -> "SearchResponse":
        """Structured variant of ``search_zim_file``.

        Returns the raw search payload as a Python dict so MCP tool functions
        and aggregators (``search_all``) can hand it straight to FastMCP's
        structured-output path without the json.dumps + re-parse round trip
        the legacy string variant required.

        ``cursor_archive_identity`` is the ``s.ai`` value decoded from a
        resumed cursor. When supplied, it must match the current archive's
        identity or the call is rejected — same anti-cross-archive guard
        as ``walk_namespace`` / ``extract_article_links``.

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If search operation fails
            OpenZimMcpValidationError: If a cursor was issued for a different archive
        """
        if limit is None:
            limit = self.config.content.default_search_limit

        # Validate and resolve file path
        validated_path = self._validate_zim_path(zim_file_path)

        # Cursor integrity: reject cursors issued against a different archive
        # (cf. pagination.py module docstring — search_zim_file is in the list
        # of tools that must verify ``s.ai`` on resume).
        if cursor_archive_identity is not None:
            from openzim_mcp.pagination import Cursor as _CursorClass
            from openzim_mcp.pagination import (
                CursorMismatchError,
                archive_identity,
            )

            try:
                _CursorClass.verify_archive_identity(
                    cast("Any", {"ai": cursor_archive_identity}),
                    expected=archive_identity(validated_path),
                    tool="search_zim_file",
                )
            except CursorMismatchError as e:
                raise OpenZimMcpValidationError(str(e)) from e

        # Empty / whitespace-only query: surface a structured reason so the
        # model can self-correct without parsing an error envelope.
        if not query or not query.strip():
            empty_payload: Dict[str, Any] = {
                "query": query,
                "results": [],
                "next_cursor": None,
                "total": 0,
                "done": True,
                "page_info": {
                    "offset": offset,
                    "limit": limit,
                    "returned_count": 0,
                },
            }
            return cast(
                "SearchResponse", attach_meta(empty_payload, reason="bad_query")
            )

        # Cache key bumped to v2b (Phase B) so v1.x cached responses (old shape)
        # don't leak through after the upgrade.
        cache_key = f"search_v2b:{validated_path}:{query}:{limit}:{offset}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached search dict for query: {query}")
            return cast("SearchResponse", cached_result)

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                # Explicit precheck: an archive with no full-text (Xapian)
                # index can't be searched — surface the structured reason
                # rather than constructing a Searcher just to catch the
                # resulting RuntimeError. Authoritative and message-format
                # independent (the old string-match on the exception text
                # didn't even match libzim's current wording).
                if not archive.has_fulltext_index:
                    return cast(
                        "SearchResponse",
                        attach_meta(
                            _no_fulltext_index_payload(
                                query, offset=offset, limit=limit
                            ),
                            reason="no_xapian_index",
                        ),
                    )
                payload, total_results = self._perform_search(
                    archive, query, limit, offset, validated_path=validated_path
                )
            logger.debug(f"Search completed: query='{query}', results found")
            reason: Optional[str] = "0_hits" if total_results == 0 else None

            # H9: when Xapian returned hits but NONE of them carry the
            # query terms in title or path, flag the response as
            # ``low_relevance`` so callers can act (the snippet was
            # built from the lead paragraph and the user almost
            # certainly wanted something else). libzim's Python binding
            # doesn't surface per-result BM25 scores, so we use a
            # cheap proxy: if no result token-matches the query, all
            # hits are weak. The same alt_spelling / alt_archive
            # suggestion pool that powers ``0_hits`` is surfaced.
            if reason is None and total_results > 0:
                if _all_results_weakly_match(payload.get("results", []), query):
                    reason = "low_relevance"

            # Zero-hit and low-relevance suggestions (Phase A item #4).
            # Sourced in priority order:
            # 1. ``alt_spelling`` from SuggestionSearcher partial matches —
            #    typo correction on the query against the title index.
            # 2. ``alt_archive`` — other open ZIM files whose basename matches a
            #    query token. Last-resort hint when the term itself is correct
            #    but the article lives in a different archive.
            suggestions: List[Dict[str, str]] = []
            if reason in ("0_hits", "low_relevance"):
                limit_n = self.config.search.structured_suggestions_limit
                # alt_spelling first (priority 1 per spec). Gate the
                # archive re-open to ``0_hits`` only — when the user
                # already has some hits (low_relevance), an extra
                # archive open per query doubles the cost for an
                # informational signal. low_relevance still gets the
                # cheap alt_archive path below.
                if reason == "0_hits":
                    try:
                        with _zim_ops_mod.zim_archive(validated_path) as archive:
                            sugg_searcher = _zim_ops_mod.SuggestionSearcher(archive)
                            sugg = sugg_searcher.suggest(query)
                            # Cap at 2x the structured limit to give room for de-dup
                            # against the query itself; SuggestionSearcher results
                            # include exact matches that we don't want to surface.
                            candidates = list(sugg.getResults(0, max(limit_n * 2, 5)))
                        q_lower = query.lower()
                        seen: set[str] = set()
                        for cand_path in candidates:
                            # SuggestionSearcher returns paths (e.g. "C/Berlin");
                            # extract the title segment.
                            title = cand_path.rsplit("/", 1)[-1]
                            # M32: paths preserve title underscores
                            # (``Photosynthesis_(biology)``); humanize back
                            # to spaces so the rendered footer
                            # (`` `suggestions for Photosynthesis (biology)` ``)
                            # is something a model can reuse verbatim as a
                            # query. The lowercase de-dup key uses the
                            # humanized form so ``Foo_Bar`` and ``Foo Bar``
                            # collapse.
                            title = title.replace("_", " ")
                            title_lower = title.lower()
                            if title_lower == q_lower or title_lower in seen:
                                continue
                            seen.add(title_lower)
                            suggestions.append({"type": "alt_spelling", "value": title})
                            if len(suggestions) >= limit_n:
                                break
                    except Exception as e:
                        logger.debug(f"alt_spelling suggestion build failed: {e}")

                # alt_archive (priority 3) — fill remaining slots.
                if len(suggestions) < limit_n:
                    try:
                        files = self.list_zim_files_data()
                        q_lower = query.lower()
                        # Tokens of length >= 4 only (avoids matching "in", "the").
                        q_tokens = [tok for tok in q_lower.split() if len(tok) >= 4]
                        for f in files:
                            file_path_str = str(f.get("path", ""))
                            if file_path_str == str(validated_path):
                                continue  # skip current archive
                            stem = Path(file_path_str).stem
                            if any(tok in stem.lower() for tok in q_tokens):
                                suggestions.append(
                                    {"type": "alt_archive", "value": stem}
                                )
                                if len(suggestions) >= limit_n:
                                    break
                    except Exception as e:
                        logger.debug(f"alt_archive suggestion build failed: {e}")

            with_meta = attach_meta(
                payload,
                reason=reason,
                suggestions=suggestions if suggestions else None,
            )
            # Cache the meta-attached payload so cold vs warm reads are
            # bit-identical. Skip the cache for zero-hit responses
            # because libzim's lazy index warm-up can return 0 matches
            # transiently — TTL-caching "no results" would mask the
            # index becoming ready (also, the suggestions block depends
            # on freshly-enumerated alt_archive candidates).
            if total_results > 0:
                self.cache.set(cache_key, with_meta)
            return cast("SearchResponse", with_meta)

        except OpenZimMcpArchiveError:
            # Missing-fulltext-index is now handled by the explicit precheck
            # above; any OpenZimMcpArchiveError here is a genuine failure.
            # Inner helper already raised a typed archive error with full
            # context — don't re-wrap and double the message prefix.
            raise
        except Exception as e:
            logger.error(f"Search failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(f"Search operation failed: {e}") from e

    def _perform_search(
        self,
        archive: Archive,
        query: str,
        limit: int,
        offset: int,
        *,
        validated_path: Optional[Path] = None,
    ) -> Tuple[Dict[str, Any], int]:
        """Perform the actual search operation.

        ``validated_path`` is the resolved archive path used to derive the
        cursor's ``s.ai`` archive identity. Optional for test-only callers
        that don't paginate; production callers always supply it.

        Returns:
            (structured_payload, total_results) — caller uses total_results
            to decide whether the response is safe to cache. The payload
            shape is documented on ``search_zim_file_data``.
        """
        from openzim_mcp.pagination import Cursor, archive_identity

        query_obj = _zim_ops_mod.Query().set_query(query)
        searcher = _zim_ops_mod.Searcher(archive)
        search = searcher.search(query_obj)

        total_results = search.getEstimatedMatches()

        if total_results == 0:
            return (
                {
                    "query": query,
                    "results": [],
                    "next_cursor": None,
                    "total": 0,
                    "done": True,
                    "page_info": {
                        "offset": offset,
                        "limit": limit,
                        "returned_count": 0,
                    },
                },
                0,
            )

        if offset >= total_results:
            return (
                {
                    "query": query,
                    "results": [],
                    "next_cursor": None,
                    "total": total_results,
                    "done": True,
                    "page_info": {
                        "offset": offset,
                        "limit": limit,
                        "returned_count": 0,
                    },
                },
                total_results,
            )

        result_count = min(limit, total_results - offset)
        result_entries = list(search.getResults(offset, result_count))

        results: List[Dict[str, Any]] = []
        for i, entry_id in enumerate(result_entries):
            try:
                entry = archive.get_entry_by_path(entry_id)
                title = entry.title or "Untitled"
                snippet = self._get_entry_snippet(entry, query=query)
                results.append({"path": entry_id, "title": title, "snippet": snippet})
            except Exception as e:
                logger.warning(f"Error processing search result {entry_id}: {e}")
                results.append(
                    {
                        "path": entry_id,
                        "title": f"Entry {offset + i + 1}",
                        "snippet": f"(Error getting entry details: {e})",
                    }
                )

        returned_count = len(results)
        last_index = offset + returned_count
        done = last_index >= total_results
        next_cursor: Optional[str] = None
        if not done:
            # Post-a20 P1-D1 / post-a21 P1-D5 contract: any tool whose
            # cursor state carries ``"q"`` must also appear in
            # ``simple_tools.SimpleToolsHandler._Q_EMITTING_CURSOR_TOOLS``
            # so the dispatcher's q-overlap guard knows to run for
            # legitimate pagination AND to skip when a cursor's ``t``
            # claims a non-q-emitting tool. Add a new ``Cursor.encode``
            # callsite here? Update that set in lockstep — the post-a21
            # ``TestP1D5QEmittingCursorToolsDrift`` regression pins the
            # contract via a parametric scan of these encode sites.
            cursor_state: Dict[str, Any] = {
                "o": last_index,
                "l": limit,
                "q": query,
            }
            if validated_path is not None:
                cursor_state["ai"] = archive_identity(validated_path)
            next_cursor = Cursor.encode(
                tool="search_zim_file",
                state=cast("Any", cursor_state),
            )

        return (
            {
                "query": query,
                "results": results,
                "next_cursor": next_cursor,
                "total": total_results,
                "done": done,
                "page_info": {
                    "offset": offset,
                    "limit": limit,
                    "returned_count": returned_count,
                },
            },
            total_results,
        )

    def _format_search_text(
        self,
        payload: "SearchResponse",
        *,
        display_query: Optional[str] = None,
        filter_text: Optional[str] = None,
    ) -> str:
        """Render a structured search payload as the legacy markdown text.

        Mirrors the original ``_perform_search`` output exactly so callers
        (and tests) that consume the rendered text keep working unchanged.

        Post-b1 P3-D1: ``display_query`` (optional) overrides
        ``payload["query"]`` in the user-facing echo strings (``Found N
        matches for "X"``, ``No search results found for "X"``, recovery
        hints). The search backend itself is case-insensitive (Xapian),
        so ``payload["query"]`` stays as the matched form for cache
        keys / cursor encoding; only the rendered echoes change.
        Pre-fix, ``search for Biology`` (after Rule 1 lowercase) showed
        ``Found N matches for "biology"`` — sibling of the post-b1
        P1-D2 / P2-D1 / P2-D2 lowercase-leak family.

        Post-b2 D4: ``filter_text`` (optional) marks the rendered echo
        as a FILTERED search. When provided, the count line reads
        ``Found N filtered matches for "X"<filter_text>`` instead of
        ``Found N matches for "X"`` — matching the wording the
        non-compact filtered path emits via ``_format_filtered_response``
        (``zim/search.py:199-203``). Pre-fix, the compact filtered
        path silently dropped the ``filtered`` qualifier because both
        compact and unfiltered paths share this formatter. Callers
        pass a leading-space-prefixed filter description (e.g.
        ``" in namespace C"``) produced by ``_format_filter_text``.
        """
        query = payload["query"]
        echo_query = display_query if display_query else query
        total_results = payload["total"] or 0
        page_info = payload["page_info"]
        offset = page_info["offset"]
        limit = page_info["limit"]
        results = payload["results"]
        done = payload["done"]
        next_cursor = payload.get("next_cursor")
        # Post-b2 D4: render the filtered-search wording when the caller
        # tagged this as a filtered echo. The qualifier word lands
        # between the count and the ``for "<query>"`` echo so the
        # filtered and unfiltered forms read symmetrically.
        is_filtered = filter_text is not None
        match_qualifier = " filtered" if is_filtered else ""
        filter_suffix = filter_text if is_filtered else ""

        if total_results == 0:
            # Append actionable next-step hints so an LLM caller knows
            # the recovery options instead of just seeing "no results"
            # and giving up. Two common rescues:
            #   * suggestions/autocomplete catches typos and partial
            #     names ("Photosynthsis" → "Photosynthesis").
            #   * tell_me_about runs a structured search + auto-fetch
            #     for any reasonably-named topic.
            if is_filtered:
                # Mirror the non-compact filtered path's terse no-results
                # echo (``zim/search.py:1510``) — recovery hints don't
                # apply to a filter mismatch (the typo path doesn't help
                # when the filter excluded the hits).
                return f'No filtered matches for "{echo_query}"{filter_suffix}'
            return (
                f'No search results found for "{echo_query}".\n\n'
                f"**Try one of these:**\n"
                f"- `suggestions for {echo_query[:30]}` — autocomplete to "
                f"catch typos or partial names\n"
                f"- `tell me about {echo_query[:30]}` — structured topic "
                f"lookup with auto article fetch\n"
                f"- A shorter or differently-cased query"
            )

        # Phase B: ``offset_exceeds_total`` is no longer surfaced as a flag —
        # detect via ``total < offset`` plus an empty results list.
        if not results and offset >= total_results:
            return (
                f"Found {total_results}{match_qualifier} matches for "
                f'"{echo_query}"{filter_suffix}, '
                f"but offset {offset} exceeds total results."
            )

        result_text = (
            f"Found {total_results}{match_qualifier} matches for "
            f'"{echo_query}"{filter_suffix}, '
            f"showing {offset + 1}-{offset + len(results)}:\n\n"
        )

        for i, result in enumerate(results):
            result_text += f"## {offset + i + 1}. {result['title']}\n"
            result_text += f"Path: {result['path']}\n"
            # A11 post-a11 L3: the canonical-title-match splice (D6 /
            # _splice_title_match_into_search) injects a synthetic row
            # whose ``snippet`` is the literal sentinel ``(canonical
            # title match)``. Rendering that as a snippet line was
            # confusing — the row looked like Xapian had snippeted the
            # body to that string. Surface it as a distinct match-type
            # badge instead so callers don't pipe the sentinel into
            # downstream snippet processing.
            snippet = result.get("snippet", "")
            if snippet == "(canonical title match)":
                result_text += "Match type: canonical title match\n\n"
            else:
                result_text += f"Snippet: {snippet}\n\n"

        # O2 (beta): warn when the match count is implausibly high. The
        # canonical example: ``search for the and a is in to`` returns a
        # saturated 5,000,000 — the search index treats stopword runs as
        # OR-matches across millions of articles, and the top hits are
        # whichever entries are highest-cited rather than topically
        # relevant. Surface that to the model so it doesn't trust the
        # "Found N matches" line as a meaningful signal.
        if total_results >= 1_000_000:
            result_text += (
                "_Note: this query matched an unusually large set "
                "(likely stop-word dominated). The top results are "
                "ranked by general document importance, not topic "
                "relevance. Re-run with more specific terms for a "
                "narrower, topically-ranked result set._\n\n"
            )

        # Compact one-liner footer — see the matching comment in the simple
        # search renderer above for rationale.
        result_text += "---\n"
        if not done:
            next_offset = offset + limit
            if next_cursor is None:
                # Filtered/limited path that doesn't know the next-page
                # boundary precisely; advance by what we actually returned.
                next_offset = offset + len(results)
            result_text += (
                f"Showing {offset + 1}-{offset + len(results)} "
                f"of {total_results} — "
                f"pass `offset={next_offset}` for the next page\n"
            )
            # A14: see ``_format_filtered_response`` for the rationale —
            # nudge toward query refinement when the total is much
            # larger than a small model can productively page through.
            # The ≥1M O2 saturation note above handles stop-word
            # collisions; this fills the mid-tier gap (200-1M).
            if total_results < 1_000_000 and _is_large_result_set(
                total_results, len(results)
            ):
                result_text += _refinement_nudge() + "\n"
        else:
            result_text += (
                f"Showing {offset + 1}-{offset + len(results)} "
                f"of {total_results} (end of results)\n"
            )

        return result_text

    def search_with_filters_with_canonical_splice(
        self,
        zim_file_path: str,
        query: str,
        namespace: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        display_query: Optional[str] = None,
    ) -> str:
        """A11 post-a11 H2: ``search_with_filters`` plus the canonical-
        title-match splice that plain ``search`` already gets through
        ``_handle_search`` → ``_splice_title_match_into_search``.

        Pre-fix, ``search for berlin in namespace C`` would return
        ``List of songs about Berlin`` / ``Berlin (disambiguation)`` /
        ``Timeline of Berlin`` and silently drop the canonical
        ``Berlin`` article — even though ``Berlin`` lives in namespace
        C and is the obvious top hit. The splice was wired into
        ``_handle_search`` only; ``_handle_filtered_search`` delegated
        directly to the legacy text path with no promotion. This
        method runs the same probe + prepend the structured-search
        path uses, gated to ``offset == 0`` (paged results stay
        stable) and to canonical hits whose path actually lives in
        the requested namespace.
        """

        # Collapse the five identical legacy-path bail-outs into one
        # closure so the guard chain below reads as a sequence of bail
        # conditions. The closure reads ``limit`` at CALL time, so the
        # ``offset != 0`` bail (which runs BEFORE the ``limit`` default)
        # sees the original ``limit`` while every later bail sees the
        # defaulted value — exactly matching the prior inline behavior.
        def _delegate() -> str:
            return self.search_with_filters(
                zim_file_path,
                query,
                namespace,
                content_type,
                limit,
                offset,
                display_query=display_query,
            )

        if offset != 0:
            return _delegate()
        if limit is None:
            limit = self.config.content.default_search_limit

        # Probe for the canonical title match BEFORE the filtered
        # scan; if the canonical isn't reachable in the requested
        # namespace, just return the legacy result unchanged.
        # a13: imports hoisted from function-local to module-level
        # (see top of file) so unit tests can patch
        # ``openzim_mcp.zim.search.find_title_match`` directly. The
        # ``is_strong_title_match`` reference is retained for
        # historical callers but the splice gate (post-a13 D5) uses
        # exact path comparison rather than the strong-match predicate.
        try:
            canonical = find_title_match(self, zim_file_path, query)
        except Exception:  # pragma: no cover — defensive
            canonical = None

        if canonical is None:
            return _delegate()

        canonical_path = canonical["path"]
        # Namespace gate: when a namespace filter is in play, only
        # splice the canonical if its path lives in that namespace.
        # New-scheme C has no path prefix; legacy / metadata namespaces
        # use the ``X/`` prefix convention.
        if namespace:
            ns_letter = namespace.strip().upper()
            path_prefix = (
                canonical_path.split("/", 1)[0] if "/" in canonical_path else "C"
            )
            if path_prefix != ns_letter:
                return _delegate()
        # Same content-type gate when applicable; the title-index probe
        # doesn't carry mimetype info, so skip the splice rather than
        # mis-attribute one when the caller filtered by content-type.
        if content_type:
            return _delegate()

        return self._splice_canonical_into_filtered(
            zim_file_path=zim_file_path,
            query=query,
            namespace=namespace,
            content_type=content_type,
            limit=limit,
            offset=offset,
            display_query=display_query,
            canonical=canonical,
        )

    def _splice_canonical_into_filtered(
        self,
        *,
        zim_file_path: str,
        query: str,
        namespace: Optional[str],
        content_type: Optional[str],
        limit: int,
        offset: int,
        display_query: Optional[str],
        canonical: Dict[str, Any],
    ) -> str:
        """Splice the canonical title match into the filtered-search render.

        (Extracted verbatim from
        ``search_with_filters_with_canonical_splice``.) The guards in the
        caller guarantee: ``offset == 0``, ``limit`` is defaulted, a
        canonical exists and lives in the requested namespace, and no
        ``content_type`` filter is in play.
        """
        canonical_path = canonical["path"]

        # Get the structured payload, splice, then render via the same
        # ``_format_filtered_response`` the legacy path uses. The
        # post-splice ``_FilteredScanState`` is synthesised from the
        # structured payload's metadata (we know filtered_count, scan
        # cap state from the page_info hint).
        payload = self.search_with_filters_data(
            zim_file_path,
            query,
            namespace,
            content_type,
            limit,
            offset,
        )
        # A11 post-a11 H3: stable-demote catalog-shape hits below
        # narrative articles before the splice, mirroring the basic-
        # search path. ``search for cats in namespace C`` was
        # surfacing ``Rephlex Records discography`` at rank 1 — same
        # bug the synthesize layer fixed via Opp2 / _demote_list_articles
        # but never applied to the filtered-search surface. Cast to
        # plain ``list[dict[str, Any]]`` so the partition / mutation /
        # synthetic-row prepend below isn't constrained by the
        # ``SearchHit`` TypedDict's narrower wire shape (the renderer
        # only reads the keys we already pass through).
        from openzim_mcp.synthesize import _is_list_article

        results: List[Dict[str, Any]] = [
            cast(Dict[str, Any], r) for r in (payload.get("results", []) or [])
        ]
        non_list = [r for r in results if not _is_list_article(r)]
        list_hits = [r for r in results if _is_list_article(r)]
        results = non_list + list_hits
        # A11 post-a11 H2 third-pass: build the synthetic canonical row
        # once so the empty-results path (Xapian filtered to zero) and
        # the populated-results path (canonical missing or out-of-order)
        # share the same prepend logic. Pre-fix, the empty-results
        # branch fell through unchanged — a ``search for X in
        # namespace C`` that returned zero hits but had a canonical X
        # in C would still report "0 filtered matches" even though
        # the canonical existed. Now the canonical lands as a single-
        # result page with the badge, mirroring how the unfiltered
        # search surface treats it.
        synthetic_canonical: Dict[str, Any] = {
            "path": canonical_path,
            "title": canonical["title"],
            "snippet": "(canonical title match)",
            # The renderer needs ``namespace`` / ``content_type`` so
            # derive them from the requested filter and the canonical
            # path's prefix. Defaults match the plain-search shape for
            # archives without explicit filters.
            "namespace": namespace
            or (canonical_path.split("/", 1)[0] if "/" in canonical_path else "C"),
            "content_type": content_type or "text/html",
        }
        if not results:
            results = [synthetic_canonical]
        else:
            # a13 D5: only short-circuit when BM25's top hit IS the
            # canonical (exact path match) — otherwise we should still
            # splice/reorder. Pre-fix, ``is_strong_title_match`` returned
            # True for any candidate that token-prefixed the topic
            # (``Berlin`` → ``Berlin_(disambiguation)`` qualifies via
            # candidate-extends-topic), and the early-return fell back
            # to the legacy ``search_with_filters`` markdown path that
            # neither spliced the canonical nor demoted list articles.
            # Result: ``search for Berlin in namespace C`` rendered
            # ``[List_of_songs_about_Berlin, Berlin_(disambiguation),
            # Timeline_of_Berlin]`` with the actual ``Berlin`` canonical
            # absent. Tightening to exact-path match preserves the
            # "don't duplicate when canonical is already at top"
            # invariant while letting the splice/reorder logic do its
            # job for every other shape.
            top = results[0]
            top_path = str(top.get("path") or "") if isinstance(top, dict) else ""
            if top_path == canonical_path:
                return self.search_with_filters(
                    zim_file_path,
                    query,
                    namespace,
                    content_type,
                    limit,
                    offset,
                )
            existing_paths = {
                str(r.get("path", "")) for r in results if isinstance(r, dict)
            }
            if canonical_path in existing_paths:
                # Reorder: move the canonical to position 0 without dup.
                reordered = [
                    r
                    for r in results
                    if not (
                        isinstance(r, dict) and str(r.get("path", "")) == canonical_path
                    )
                ]
                promoted_existing = next(
                    r
                    for r in results
                    if isinstance(r, dict) and str(r.get("path", "")) == canonical_path
                )
                results = [promoted_existing, *reordered][:limit]
            else:
                results = [synthetic_canonical, *results][:limit]

        # Synthesise a ``_FilteredScanState`` from the structured
        # payload so the render path stays unchanged. Honor the
        # lower-bound flag from page_info.
        page_info = payload.get("page_info") or {}
        total_lower_bound = bool(page_info.get("total_is_lower_bound"))
        # ``filtered_count`` for the renderer: bump by 1 when we
        # synthesised a fresh canonical row that wasn't in the
        # original result set.
        original_total = int(payload.get("total") or len(results))
        filtered_count = max(original_total, len(results))
        synthetic_scan = _FilteredScanState(
            filtered_count=filtered_count,
            scanned=0,
            scan_cap_hit=False,
            total_filtered_is_lower_bound=total_lower_bound,
        )
        filter_text = _format_filter_text(namespace, content_type)
        return _format_filtered_response(
            query=query,
            filter_text=filter_text,
            results=results,
            scan=synthetic_scan,
            total_results=filtered_count,
            offset=offset,
            limit=limit,
            display_query=display_query,
        )

    def search_with_filters(
        self,
        zim_file_path: str,
        query: str,
        namespace: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        display_query: Optional[str] = None,
    ) -> str:
        """Markdown-rendered filtered search (legacy surface).

        See ``search_with_filters_data`` for the structured variant. This
        wrapper renders the structured payload to the legacy markdown text
        block so existing callers (and tests) that consume the rendered
        text keep working unchanged.

        Args:
            zim_file_path: Path to the ZIM file
            query: Search query term
            namespace: Optional namespace filter (C, M, W, X, etc.)
            content_type: Optional content type filter (text/html, text/plain, etc.)
            limit: Maximum number of results to return
            offset: Result starting offset (for pagination)

        Returns:
            Search result text

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpValidationError: If parameter validation fails
                (limit out of range, negative offset, malformed namespace).
            OpenZimMcpArchiveError: If search operation fails
        """
        if limit is None:
            limit = self.config.content.default_search_limit

        # Caller-input validation surfaces as OpenZimMcpValidationError so
        # the tool layer can render a targeted "bad parameter" message
        # instead of formatting it as an archive failure.
        if limit < 1 or limit > 100:
            raise OpenZimMcpValidationError("Limit must be between 1 and 100")
        if offset < 0:
            raise OpenZimMcpValidationError("Offset must be non-negative")
        # Validate namespace - single chars (old) or longer names (new format)
        if namespace and (len(namespace) > 50 or not namespace.strip()):
            raise OpenZimMcpValidationError(
                "Namespace must be a non-empty string (max 50 characters)"
            )

        # Validate and resolve file path
        validated_path = self._validate_zim_path(zim_file_path)

        # Check cache (legacy markdown cache, separate from the v2b dict cache).
        # Post-b1 P3-D1: include display_query in the cache key. Two calls
        # with the same matched query but different display forms must
        # render different text; a stale cache would echo the wrong
        # casing back to the second caller.
        cache_key = (
            f"search_filtered:{validated_path}:{query}:{namespace}:"
            f"{content_type}:{limit}:{offset}:dq={display_query or ''}"
        )
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached filtered search results for query: {query}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                # Mirror search_with_filters_data: degrade gracefully when the
                # archive has no full-text index rather than letting the
                # Searcher raise (which this wrapper would re-wrap as a hard
                # OpenZimMcpArchiveError). Not cached — same rationale as the
                # zero-result path below.
                if not archive.has_fulltext_index:
                    echo_query = display_query or query
                    return (
                        f"No full-text index in this archive; filtered search "
                        f'for "{echo_query}" is unavailable.'
                    )
                result, total_filtered = self._perform_filtered_search(
                    archive,
                    query,
                    namespace,
                    content_type,
                    limit,
                    offset,
                    display_query=display_query,
                )

            # Don't cache zero-result responses: libzim's lazy index warm-up
            # can return 0 matches transiently, and a TTL-cached "no results"
            # would mask the index becoming ready.
            if total_filtered > 0:
                self.cache.set(cache_key, result)
            logger.info(
                f"Filtered search completed: query='{query}', "
                f"namespace={namespace}, type={content_type}"
            )
            return result

        except OpenZimMcpValidationError:
            # Caller-input validation may also surface from inside the
            # archive block (e.g. namespace canonicalisation in future
            # paths). Surface it as-is so the tool layer can render a
            # targeted "bad parameter" message.
            raise
        except OpenZimMcpArchiveError:
            # Inner helper already raised a typed archive error with full
            # context. Don't re-wrap and double the message prefix.
            raise
        except Exception as e:
            logger.error(f"Filtered search failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(
                f"Filtered search operation failed: {e}"
            ) from e

    def search_with_filters_data(
        self,
        zim_file_path: str,
        query: str,
        namespace: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        cursor_archive_identity: Optional[str] = None,
    ) -> "SearchWithFiltersResponse":
        """Structured filtered-search response. v2 Phase B contract.

        Same shape as ``search_zim_file_data`` (top-level ``results`` /
        ``next_cursor`` / ``total`` / ``done`` / ``page_info``) plus
        tool-specific extras ``query`` / ``namespace_filter`` /
        ``content_type_filter``. Cursor ``t="search_with_filters"``.

        The libzim-level filtering pipeline (``_scan_filtered_search`` →
        ``_materialise_filtered_entry``) is preserved verbatim — only the
        response shape is changing. That pipeline streams search hits in
        bounded batches and applies cheap path-prefix namespace filtering
        before the per-entry archive lookups required for content_type
        filtering, which would otherwise multiply ``offset + limit`` entry
        materialisations across every candidate.

        ``cursor_archive_identity`` is the ``s.ai`` value decoded from a
        resumed cursor; mismatched archives are rejected per the cursor
        contract.

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpValidationError: If parameter validation fails
                (limit out of range, negative offset, malformed namespace,
                cursor archive mismatch).
            OpenZimMcpArchiveError: If search operation fails
        """
        from openzim_mcp.pagination import (
            Cursor,
            CursorMismatchError,
            archive_identity,
        )

        if limit is None:
            limit = self.config.content.default_search_limit

        # Caller-input validation surfaces as OpenZimMcpValidationError so
        # the tool layer can render a targeted "bad parameter" message
        # instead of formatting it as an archive failure.
        if limit < 1 or limit > 100:
            raise OpenZimMcpValidationError("Limit must be between 1 and 100")
        if offset < 0:
            raise OpenZimMcpValidationError("Offset must be non-negative")
        if namespace and (len(namespace) > 50 or not namespace.strip()):
            raise OpenZimMcpValidationError(
                "Namespace must be a non-empty string (max 50 characters)"
            )

        # Validate and resolve file path
        validated_path = self._validate_zim_path(zim_file_path)

        # Cursor integrity: reject cursors issued against a different archive.
        if cursor_archive_identity is not None:
            try:
                Cursor.verify_archive_identity(
                    cast("Any", {"ai": cursor_archive_identity}),
                    expected=archive_identity(validated_path),
                    tool="search_with_filters",
                )
            except CursorMismatchError as e:
                raise OpenZimMcpValidationError(str(e)) from e

        # Cache key bumped to v2b (Phase B) so v1.x cached responses (markdown
        # strings under the legacy ``search_filtered:`` prefix) don't leak
        # through after the upgrade — different prefix, different cache slot.
        cache_key = (
            f"search_filtered_v2b:{validated_path}:{query}:{namespace}:"
            f"{content_type}:{limit}:{offset}"
        )
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached filtered search dict for query: {query}")
            return cast("SearchWithFiltersResponse", cached_result)

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                # Same explicit precheck as search_zim_file_data: degrade
                # gracefully to reason="no_xapian_index" when the archive has
                # no full-text index, instead of raising a hard archive error.
                if not archive.has_fulltext_index:
                    return cast(
                        "SearchWithFiltersResponse",
                        attach_meta(
                            _no_fulltext_index_payload(
                                query,
                                offset=offset,
                                limit=limit,
                                namespace=namespace,
                                content_type=content_type,
                                filtered=True,
                            ),
                            reason="no_xapian_index",
                        ),
                    )
                results, scan = self._perform_filtered_search_data(
                    archive, query, namespace, content_type, limit, offset
                )
        except OpenZimMcpValidationError:
            raise
        except OpenZimMcpArchiveError:
            raise
        except Exception as e:
            logger.error(f"Filtered search failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(
                f"Filtered search operation failed: {e}"
            ) from e

        # Build the contract envelope. ``done`` / ``next_cursor`` mirror
        # the search_zim_file_data semantics: when the scan filled a full
        # page short of exhausting the unfiltered hit list, more pages may
        # exist; emit a cursor so callers can resume.
        returned_count = len(results)
        last_index = offset + returned_count
        # ``filtered_count`` is the number of post-filter hits the scanner
        # tallied through ``last_index``. It can be a lower bound when the
        # scan filled the page short of exhausting the unfiltered list.
        total_filtered: Optional[int] = scan.filtered_count
        # When the scan capped (10k) without exhausting the result list,
        # ``filtered_count`` is a lower bound — we don't know the true total.
        # Surface that via ``page_info.total_is_lower_bound`` so the contract
        # ``total`` stays honest.
        done = (
            last_index >= scan.filtered_count and not scan.total_filtered_is_lower_bound
        )
        next_cursor: Optional[str] = None
        if not done:
            cursor_state: Dict[str, Any] = {
                "o": last_index,
                "l": limit,
                "q": query,
                "ai": archive_identity(validated_path),
            }
            if namespace:
                cursor_state["ns"] = namespace
            if content_type:
                cursor_state["ct"] = content_type
            next_cursor = Cursor.encode(
                tool="search_with_filters",
                state=cast(Any, cursor_state),
            )

        page_info: Dict[str, Any] = {
            "offset": offset,
            "limit": limit,
            "returned_count": returned_count,
        }
        if scan.total_filtered_is_lower_bound:
            page_info["total_is_lower_bound"] = True

        payload: Dict[str, Any] = {
            "query": query,
            "namespace_filter": namespace,
            "content_type_filter": content_type,
            "results": results,
            "next_cursor": next_cursor,
            "total": total_filtered,
            "done": done,
            "page_info": page_info,
        }

        logger.info(
            f"Filtered search completed: query='{query}', "
            f"namespace={namespace}, type={content_type}, "
            f"results={returned_count}"
        )
        # Classify the zero-result case: if a namespace/content_type filter
        # was supplied AND the unfiltered search returned hits, the filter
        # is what killed them — surface that as ``bad_namespace`` so the
        # model can self-correct (drop or change the filter) instead of
        # treating the whole query as a miss.
        if scan.filtered_count == 0:
            if (namespace or content_type) and scan.unfiltered_total > 0:
                reason: Optional[str] = "bad_namespace"
            else:
                reason = "0_hits"
        else:
            reason = None
        with_meta = attach_meta(payload, reason=reason)
        # Cache the post-attach payload so cold/warm reads are bit-identical
        # (Phase B #12). Skip zero-hit results — see search_zim_file_data
        # for rationale (libzim lazy index, fresh suggestions).
        if scan.filtered_count > 0:
            self.cache.set(cache_key, with_meta)
        return cast("SearchWithFiltersResponse", with_meta)

    def _perform_filtered_search_data(
        self,
        archive: Archive,
        query: str,
        namespace: Optional[str],
        content_type: Optional[str],
        limit: int,
        offset: int,
    ) -> Tuple[List[Dict[str, Any]], "_FilteredScanState"]:
        """Run the libzim-level filtered scan and return structured hits.

        Mirrors ``_perform_filtered_search`` but returns
        ``(results_list, scan_state)`` instead of a rendered markdown
        string. The same streaming-with-skip-counter scan applies — see
        ``_scan_filtered_search`` for the bounded-batch rationale.

        Returns:
            (results, scan) — ``results`` is a list of hit dicts shaped
            like ``SearchHit`` (path/title/snippet); ``scan`` carries the
            ``_FilteredScanState`` aggregate (filtered_count,
            total_filtered_is_lower_bound, etc.) that the caller uses to
            decide pagination semantics.
        """
        # Canonicalise user-supplied namespace ("c" -> "C", "content" -> "C")
        # so the comparison against namespace prefixes derived from libzim
        # paths (which always surface in canonical form) does not silently
        # filter every result when callers pass lowercase or long-form names.
        if namespace:
            namespace = self._canonicalise_namespace(namespace.strip())

        query_obj = _zim_ops_mod.Query().set_query(query)
        searcher = _zim_ops_mod.Searcher(archive)
        search = searcher.search(query_obj)
        total_results = search.getEstimatedMatches()
        if total_results == 0:
            return [], _FilteredScanState(
                filtered_count=0,
                scanned=0,
                scan_cap_hit=False,
                total_filtered_is_lower_bound=False,
                unfiltered_total=0,
            )

        page, scan = self._scan_filtered_search(
            archive, search, total_results, namespace, content_type, limit, offset
        )

        # Propagate the pre-filter total so the caller can distinguish
        # "query matched nothing" (0_hits) from "filter killed every match"
        # (bad_namespace) when emitting structured reason codes.
        scan = _FilteredScanState(
            filtered_count=scan.filtered_count,
            scanned=scan.scanned,
            scan_cap_hit=scan.scan_cap_hit,
            total_filtered_is_lower_bound=scan.total_filtered_is_lower_bound,
            unfiltered_total=total_results,
        )

        if scan.filtered_count == 0:
            return [], scan
        if offset >= scan.filtered_count:
            return [], scan

        # Project (entry_id, entry, namespace, content_mime) tuples onto
        # SearchHit-shaped dicts. P3-D1 (live-MCP sweep): per-hit
        # ``namespace`` / ``content_type`` MUST be populated. The legacy
        # ``_build_filtered_results`` always did so; this _data sibling
        # previously dropped them with the rationale that filters were
        # echoed once at the top level. But the renderer
        # ``_format_filtered_response`` does direct-key access on each
        # row, and the canonical-IS-top short-circuit at
        # ``search_with_filters_with_canonical_splice`` falls through to
        # that renderer with these rows — causing
        # ``KeyError: 'namespace'`` on every ``search Berlin in namespace
        # C`` / ``search Tokyo in namespace C`` / ``search Paris in
        # namespace C`` query. Restore the contract so both callers
        # (renderer + structured consumers) see the same shape.
        results: List[Dict[str, Any]] = []
        for i, (entry_id, entry, entry_namespace, content_mime) in enumerate(page):
            try:
                title = entry.title or "Untitled"
                snippet = self._get_entry_snippet(entry, query=query)
                if not content_type:
                    try:
                        content_mime = entry.get_item().mimetype or content_mime
                    except Exception as e:
                        logger.debug(
                            f"Could not get mimetype for entry {entry_id}: {e}"
                        )
                results.append(
                    {
                        "path": entry_id,
                        "title": title,
                        "snippet": snippet,
                        "namespace": entry_namespace,
                        "content_type": content_mime,
                    }
                )
            except Exception as e:
                logger.warning(
                    f"Error processing filtered search result {entry_id}: {e}"
                )
                results.append(
                    {
                        "path": entry_id,
                        "title": f"Entry {offset + i + 1}",
                        "snippet": f"(Error getting entry details: {e})",
                        "namespace": entry_namespace or "unknown",
                        "content_type": content_mime or "unknown",
                    }
                )
        return results, scan

    def _perform_filtered_search(
        self,
        archive: Archive,
        query: str,
        namespace: Optional[str],
        content_type: Optional[str],
        limit: int,
        offset: int,
        *,
        display_query: Optional[str] = None,
    ) -> Tuple[str, int]:
        """Perform filtered search operation.

        Returns:
            (result_text, total_filtered) — caller uses total_filtered to decide
            whether the response is safe to cache. ``total_filtered`` is 0 for
            both the unfiltered no-results and the post-filter no-matches cases.

        Post-b1 P3-D1: ``display_query`` (when set) replaces ``query``
        in user-facing echo strings (``No search results found for "X"``,
        ``No filtered matches for "X"``, ``Found N filtered matches for
        "X"``). Matching uses ``query`` unchanged; only the rendered
        echo changes.
        """
        echo_query = display_query if display_query else query
        # Canonicalise user-supplied namespace ("c" -> "C", "content" -> "C")
        # so the comparison against namespace prefixes derived from libzim
        # paths (which always surface in canonical form) does not silently
        # filter every result when callers pass lowercase or long-form names.
        if namespace:
            namespace = self._canonicalise_namespace(namespace.strip())

        query_obj = _zim_ops_mod.Query().set_query(query)
        searcher = _zim_ops_mod.Searcher(archive)
        search = searcher.search(query_obj)
        total_results = search.getEstimatedMatches()
        if total_results == 0:
            return f'No search results found for "{echo_query}"', 0

        page, scan = self._scan_filtered_search(
            archive, search, total_results, namespace, content_type, limit, offset
        )

        filter_text = _format_filter_text(namespace, content_type)
        if scan.filtered_count == 0:
            return f'No filtered matches for "{echo_query}"{filter_text}', 0
        if offset >= scan.filtered_count:
            return (
                f'Found {scan.filtered_count} filtered matches for "{echo_query}"'
                f"{filter_text}, but offset {offset} exceeds total results."
            ), scan.filtered_count

        results = self._build_filtered_results(page, content_type, offset, query=query)
        result_text = _format_filtered_response(
            query,
            filter_text,
            results,
            scan,
            total_results,
            offset,
            limit,
            display_query=display_query,
        )
        return result_text, scan.filtered_count

    def _scan_filtered_search(
        self,
        archive: Archive,
        search: Any,
        total_results: int,
        namespace: Optional[str],
        content_type: Optional[str],
        limit: int,
        offset: int,
    ) -> Tuple[List[Tuple[str, Any, str, str]], "_FilteredScanState"]:
        """Stream search results in batches, applying filters and skip counter.

        Streaming with a skip counter avoids the old pattern that materialised
        ``offset + limit`` Entry objects via ``get_entry_by_path`` for every
        candidate in that window — pathological for high offsets (e.g.
        ``offset=9900, limit=100`` materialised ~10k entries to return 100).
        We only materialise entries we will actually emit.
        """
        page: List[Tuple[str, Any, str, str]] = []
        filtered_count = 0
        scanned = 0
        scan_cap_hit = False
        # Canonical paths already placed on this page, so warc2zim query-string
        # variants (foo.htm and foo.htm?x=1) don't each consume a result slot.
        # Scoped to the emitted page; a duplicate is skipped without filling a
        # slot, and scanning continues so the page still fills to ``limit``.
        seen_canonical: set[str] = set()
        has_new_scheme = getattr(archive, "has_new_namespace_scheme", False)
        # When namespace-only filtering is active (no content_type), the
        # entry namespace is derivable from the path string without an
        # archive lookup, so skipped entries cost nothing.
        need_entry_for_filter = bool(content_type)

        # New-scheme search hits are always C (the only iterable surface).
        # If the caller asked for any other namespace we'd otherwise scan the
        # full result set and find nothing — short-circuit to empty.
        if has_new_scheme and namespace and namespace != "C":
            return page, _FilteredScanState(
                filtered_count=0,
                scanned=0,
                scan_cap_hit=False,
                total_filtered_is_lower_bound=False,
            )

        while scanned < total_results and len(page) < limit:
            if scanned >= _FILTERED_MAX_SCAN:
                scan_cap_hit = True
                break
            batch_end = min(
                scanned + _FILTERED_BATCH_SIZE, total_results, _FILTERED_MAX_SCAN
            )
            batch = list(search.getResults(scanned, batch_end - scanned))
            scanned = batch_end
            if not batch:
                break

            for entry_id in batch:
                if namespace and not self._matches_cheap_namespace(
                    entry_id, namespace, has_new_scheme=has_new_scheme
                ):
                    continue
                # Cheap-skip semantics: when no content_type filter is
                # active, ``filtered_count`` counts namespace-matching
                # candidates (not just successfully materialised ones).
                # When a content_type filter IS active, ``filtered_count``
                # counts entries that passed both filters. The two
                # semantics differ slightly — entries that fail
                # post-redirect namespace re-check would count toward
                # the namespace-only offset but not the combined one —
                # but pagination is internally consistent within each
                # path (`> offset` emit gate, monotonic counter).
                if not need_entry_for_filter and filtered_count < offset:
                    filtered_count += 1
                    continue

                materialised = self._materialise_filtered_entry(
                    archive,
                    entry_id,
                    namespace,
                    content_type,
                    has_new_scheme=has_new_scheme,
                )
                if materialised is None:
                    continue

                filtered_count += 1
                if filtered_count > offset and len(page) < limit:
                    canonical = canonical_result_path(materialised[0])
                    if canonical in seen_canonical:
                        # A query-string variant of an entry already on this
                        # page — skip it and keep scanning so the dropped slot
                        # is backfilled with the next distinct result.
                        continue
                    seen_canonical.add(canonical)
                    page.append(materialised)
                    if len(page) >= limit:
                        break

        # ``total_filtered_is_lower_bound`` is True when we stopped scanning
        # before exhausting the result set — either because the page filled
        # short of the scan tail, OR because the scan cap fired. The cap
        # case was previously masked, which made ``done`` flip to True at
        # the cap (clients thought iteration was complete when filtered
        # entries remained past the cap). Both stopping conditions imply
        # the filtered count is a lower bound.
        page_filled_short_of_scan = len(page) >= limit and scanned < total_results
        return page, _FilteredScanState(
            filtered_count=filtered_count,
            scanned=scanned,
            scan_cap_hit=scan_cap_hit,
            total_filtered_is_lower_bound=page_filled_short_of_scan or scan_cap_hit,
        )

    def _matches_cheap_namespace(
        self, entry_id: str, namespace: str, has_new_scheme: bool = False
    ) -> bool:
        """Cheap namespace filter from the path string (no archive lookup).

        In new-scheme archives every iterable / search-indexed entry is in C,
        so the only valid match is ``namespace == 'C'``. Path-prefix parsing
        on a new-scheme path like ``Evolution`` would falsely admit it as
        namespace ``E``.

        For old-scheme: ``entry_id`` is the path libzim returned; resolved
        ``entry.path`` may differ across redirects, but namespace agreement
        holds in practice (redirects within the same namespace are the
        common case; for cross-namespace redirects we accept the resolved
        entry's namespace when we materialise).
        """
        if has_new_scheme:
            return namespace == "C"

        if "/" in entry_id:
            cheap_namespace = entry_id.split("/", 1)[0]
        elif entry_id:
            cheap_namespace = entry_id[0]
        else:
            cheap_namespace = ""
        return self._canonicalise_namespace(cheap_namespace) == namespace

    def _materialise_filtered_entry(
        self,
        archive: Archive,
        entry_id: str,
        namespace: Optional[str],
        content_type: Optional[str],
        has_new_scheme: bool = False,
    ) -> Optional[Tuple[str, Any, str, str]]:
        """Resolve an entry and apply the post-redirect namespace + mime filters."""
        try:
            entry = archive.get_entry_by_path(entry_id)
        except Exception as e:
            logger.warning(f"Error filtering search result {entry_id}: {e}")
            return None

        # Use the resolved entry's namespace for the response so the value
        # shown matches what libzim actually surfaces (handles
        # cross-namespace redirects). New-scheme archives only surface C
        # via this path so we set it directly; old-scheme paths still carry
        # the namespace as a single-character prefix.
        if has_new_scheme:
            entry_namespace = "C"
        else:
            entry_namespace = ""
            if "/" in entry.path:
                entry_namespace = entry.path.split("/", 1)[0]
            elif entry.path:
                entry_namespace = entry.path[0]
        if namespace and (self._canonicalise_namespace(entry_namespace) != namespace):
            return None

        content_mime = ""
        if content_type:
            try:
                content_mime = entry.get_item().mimetype or ""
            except Exception:  # nosec B112 - intentional filter skip
                return None
            if not content_mime.startswith(content_type):
                return None

        return entry_id, entry, entry_namespace, content_mime

    def _build_filtered_results(
        self,
        page: List[Tuple[str, Any, str, str]],
        content_type: Optional[str],
        offset: int,
        query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Format each materialised entry into the response result dict."""
        results: List[Dict[str, Any]] = []
        for i, (entry_id, entry, entry_namespace, content_mime) in enumerate(page):
            try:
                title = entry.title or "Untitled"
                snippet = self._get_entry_snippet(entry, query=query)
                if not content_type:
                    try:
                        content_mime = entry.get_item().mimetype or ""
                    except Exception as e:
                        logger.debug(
                            f"Could not get mimetype for entry {entry_id}: {e}"
                        )
                results.append(
                    {
                        "path": entry_id,
                        "title": title,
                        "snippet": snippet,
                        "namespace": entry_namespace,
                        "content_type": content_mime,
                    }
                )
            except Exception as e:
                logger.warning(
                    f"Error processing filtered search result {entry_id}: {e}"
                )
                results.append(
                    {
                        "path": entry_id,
                        "title": f"Entry {offset + i + 1}",
                        "snippet": f"(Error getting entry details: {e})",
                        "namespace": "unknown",
                        "content_type": "unknown",
                    }
                )
        return results

    def get_search_suggestions_data(
        self, zim_file_path: str, partial_query: str, limit: int = 10
    ) -> "SearchSuggestionsResponse":
        """Structured variant of ``get_search_suggestions``.

        Returns the result dict directly (not a JSON string) so MCP tools
        can hand it straight to FastMCP's structured-content path.

        ``get_search_suggestions`` is non-paginated (no cursor input,
        no offset), but the v2 Phase B contract still applies for
        uniformity: ``next_cursor=None``, ``done=True``,
        ``total=len(results)``, ``page_info.offset=0``.

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpValidationError: If ``limit`` is outside ``1..50``.
            OpenZimMcpArchiveError: If suggestion generation fails
        """
        # Validate parameters
        if limit < 1 or limit > 50:
            raise OpenZimMcpValidationError("Limit must be between 1 and 50")
        if not partial_query or len(partial_query.strip()) < 2:
            empty_payload: Dict[str, Any] = {
                "partial_query": partial_query,
                "results": [],
                "next_cursor": None,
                "total": 0,
                "done": True,
                "page_info": {"offset": 0, "limit": limit, "returned_count": 0},
            }
            return cast("SearchSuggestionsResponse", attach_meta(empty_payload))

        # Validate and resolve file path
        validated_path = self._validate_zim_path(zim_file_path)

        # Cache key bumped to v2b (Phase B) so v1.x cached responses (old
        # shape: suggestions/count keys) don't leak through after the upgrade.
        cache_key = f"suggestions_data:v2b:{validated_path}:{partial_query}:{limit}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached suggestions dict for: {partial_query}")
            return cast("SearchSuggestionsResponse", cached_result)

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                raw = self._generate_search_suggestions(archive, partial_query, limit)

            # ``_generate_search_suggestions`` returns the legacy
            # {partial_query, suggestions, count} shape. Adapt to the
            # contract here: rename ``suggestions`` → ``results`` at the
            # top level (the Phase A ``_meta.suggestions[]`` recovery
            # candidates are unrelated and live inside ``_meta``).
            suggestions = raw.get("suggestions", [])
            actual_count = len(suggestions)

            payload: Dict[str, Any] = {
                "partial_query": partial_query,
                "results": suggestions,
                "next_cursor": None,
                "total": actual_count,
                "done": True,
                "page_info": {
                    "offset": 0,
                    "limit": limit,
                    "returned_count": actual_count,
                },
            }

            with_meta = attach_meta(payload)
            # Cache the post-attach payload (Phase B #12). A cold-cache
            # request that hits before the libzim title index has warmed
            # up can return zero suggestions for a query that will
            # produce results moments later — caching that empty payload
            # locks the query into "no suggestions" for the full TTL.
            # Only cache non-empty results.
            if actual_count > 0:
                self.cache.set(cache_key, with_meta)
            logger.info(f"Generated {actual_count} suggestions for: {partial_query}")
            return cast("SearchSuggestionsResponse", with_meta)

        except OpenZimMcpArchiveError:
            # Inner helper already raised a typed archive error with full
            # context. Don't re-wrap and double the message prefix.
            raise
        except Exception as e:
            logger.error(f"Suggestion generation failed for {partial_query}: {e}")
            raise OpenZimMcpArchiveError(f"Suggestion generation failed: {e}") from e

    def get_search_suggestions(
        self, zim_file_path: str, partial_query: str, limit: int = 10
    ) -> str:
        """Legacy JSON-string variant of ``get_search_suggestions_data``.

        Get search suggestions and auto-complete for partial queries.

        Args:
            zim_file_path: Path to the ZIM file
            partial_query: Partial search query
            limit: Maximum number of suggestions to return

        Returns:
            JSON string containing search suggestions

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpValidationError: If ``limit`` is outside ``1..50``.
            OpenZimMcpArchiveError: If suggestion generation fails
        """
        return _json(
            self.get_search_suggestions_data(zim_file_path, partial_query, limit)
        )

    def _generate_search_suggestions(  # NOSONAR(python:S3776)
        self, archive: Archive, partial_query: str, limit: int
    ) -> Dict[str, Any]:
        """Generate search suggestions based on partial query.

        Errors during iteration of individual entries are logged and skipped
        (per-entry isolation). Errors that escape the per-entry try/except
        propagate so callers can avoid caching a sentinel response — a
        transient libzim failure in this path was previously locked into the
        suggestions cache for the full TTL.
        """
        logger.info(
            f"Starting suggestion generation for query: '{partial_query}', "
            f"limit: {limit}"
        )
        suggestions = []
        partial_lower = partial_query.lower().strip()

        # Strategy 1: Use search functionality as fallback since direct entry
        # iteration may not work reliably with all ZIM file structures.
        suggestions = self._get_suggestions_from_search(archive, partial_query, limit)

        # D6 (beta): the libzim suggest index / Xapian search both miss
        # the canonical bare-title article for common prefixes.
        # ``suggestions for Photosyn`` returns 15 results — ``PhotoSynth``,
        # ``Photosyntesis`` (typo), ``Photosynthetic_efficiency``,
        # ``Photosynthesis_(song)`` etc. — but NOT bare ``Photosynthesis``,
        # which has score 1.0 in the title index. The Xapian search
        # ranks broader articles (mentioning photosynt-* many times)
        # above the canonical short-title article. Probe the title-index
        # fast-path for the partial query directly and prepend the
        # canonical entry when it's a clean prefix match and not
        # already in the result list. Strategy 1 takes priority for
        # cases where the prefix lands across many same-prefix titles;
        # this prepend just fills the canonical gap.
        #
        # D6 (beta, second pass): only run the canonical probe when
        # Strategy 1 returned something. The probe's purpose is to fill
        # a gap in a populated list; when Strategy 1 is empty, Strategy 2
        # below runs SuggestionSearcher with its own canonical-promotion
        # logic (sorted by score+length), so running the canonical probe
        # here would just be a duplicate SuggestionSearcher call against
        # the same archive on the cold path.
        if suggestions:
            canonical = self._find_canonical_prefix_match(
                archive, partial_query, suggestions
            )
            if canonical is not None:
                suggestions = [canonical] + suggestions
                # Trim back to limit so the canonical doesn't push the
                # original last suggestion off the cliff unaccounted.
                suggestions = suggestions[:limit]

            logger.info(f"Found {len(suggestions)} suggestions using search fallback")
            return {
                "partial_query": partial_query,
                "suggestions": suggestions,
                "count": len(suggestions),
            }

        # Strategy 2: Use the libzim title-index suggestion API. Replaces the
        # previous strided ``_get_entry_by_id`` scan, which only inspected
        # ~entry_count/step entries and missed almost everything on large
        # archives. ``SuggestionSearcher`` works against the title/redirect
        # index and is independent of the full-text index used by Strategy 1,
        # so it remains a legitimate fallback when full-text returns zero.
        title_matches: List[Dict[str, Any]] = []

        try:
            suggestion_search = _zim_ops_mod.SuggestionSearcher(archive).suggest(
                partial_query
            )
            total = suggestion_search.getEstimatedMatches()
            logger.info(
                f"SuggestionSearcher matched {total} candidates for "
                f"'{partial_query}'"
            )
            # Pull a few extra so we can re-rank by start vs contains.
            max_results = min(total, max(limit * 5, 25)) if total else 0
            result_paths = (
                list(suggestion_search.getResults(0, max_results))
                if max_results
                else []
            )
        except Exception as e:
            logger.debug(f"SuggestionSearcher failed for '{partial_query}': {e}")
            result_paths = []

        for result_path in result_paths:
            try:
                entry = archive.get_entry_by_path(str(result_path))
                title = entry.title or ""
                path = entry.path or str(result_path)

                # Skip entries without meaningful titles
                if not title.strip() or len(title.strip()) < 2:
                    continue

                # Skip system/metadata entries (common patterns)
                if _is_pseudo_namespace_entry(path, title):
                    continue

                title_lower = title.lower()

                # Prioritize titles that start with the query
                if title_lower.startswith(partial_lower):
                    title_matches.append(
                        {
                            "suggestion": title,
                            "path": path,
                            "type": "title_start_match",
                            "score": 100,
                        }
                    )
                # Then titles that contain the query
                elif partial_lower in title_lower:
                    title_matches.append(
                        {
                            "suggestion": title,
                            "path": path,
                            "type": "title_contains_match",
                            "score": 50,
                        }
                    )
                else:
                    # Suggestion API may return fuzzy matches that don't
                    # textually contain the query — keep them but rank lower.
                    title_matches.append(
                        {
                            "suggestion": title,
                            "path": path,
                            "type": "title_suggest_match",
                            "score": 25,
                        }
                    )

                # Stop if we have enough matches
                if len(title_matches) >= limit * 2:
                    break

            except Exception as e:
                logger.warning(f"Error processing suggestion result {result_path}: {e}")
                continue

        logger.info(
            f"Suggestion processing complete: "
            f"candidates={len(result_paths)}, matches={len(title_matches)}"
        )

        # Sort by score and title length (prefer shorter, more relevant titles)
        title_matches.sort(key=lambda x: (-x["score"], len(x["suggestion"])))

        # Take the best matches
        for match in title_matches[:limit]:
            suggestions.append(
                {
                    "text": match["suggestion"],
                    "path": match["path"],
                    "type": match["type"],
                }
            )

        # D6 (beta, third pass): also probe for the canonical bare-title
        # article on the Strategy 2 path. The earlier "skip probe when
        # Strategy 1 is empty" optimisation regressed the empty-Strategy-1
        # case (``Photosynt`` returns 0 hits via Xapian on cold Strategy 1
        # locally; Strategy 2 then surfaces ``PhotoSynth`` but misses
        # bare ``Photosynthesis``). Reuse the same ``result_paths``
        # the loop above already pulled so we don't pay a second
        # ``SuggestionSearcher.suggest()`` round trip — the helper
        # accepts pre-fetched paths via its ``result_paths=`` arg.
        if result_paths and suggestions:
            canonical = self._find_canonical_prefix_match(
                archive,
                partial_query,
                suggestions,
                result_paths=[str(p) for p in result_paths],
            )
            if canonical is not None:
                suggestions = [canonical] + suggestions
                suggestions = suggestions[:limit]

        return {
            "partial_query": partial_query,
            "suggestions": suggestions[:limit],
            "count": len(suggestions[:limit]),
        }

    def _get_suggestions_from_search(  # NOSONAR(python:S3776)
        self, archive: Archive, partial_query: str, limit: int
    ) -> List[Dict[str, Any]]:
        """Get suggestions by using the search functionality as fallback."""
        suggestions: list[dict[str, str]] = []

        try:
            # Create a search query - try both exact and wildcard approaches.
            # ``Query``/``Searcher`` resolve via ``zim_operations`` so tests can
            # patch them at the original module path.
            query_obj = _zim_ops_mod.Query().set_query(partial_query)
            searcher = _zim_ops_mod.Searcher(archive)
            search = searcher.search(query_obj)

            total_results = search.getEstimatedMatches()
            logger.debug(f"Search found {total_results} matches for '{partial_query}'")

            if total_results == 0:
                return suggestions

            # Get a reasonable number of search results to extract titles from
            # Get more results to filter from
            max_results = min(total_results, limit * 5)
            result_entries = list(search.getResults(0, max_results))

            seen_titles = set()

            for entry_id in result_entries:
                try:
                    entry = archive.get_entry_by_path(entry_id)
                    title = entry.title or ""
                    path = entry.path or ""

                    if not title.strip() or title in seen_titles:
                        continue

                    # Skip system/metadata entries
                    if _is_pseudo_namespace_entry(path, title, extended=True):
                        continue

                    seen_titles.add(title)
                    title_lower = title.lower()
                    partial_lower = partial_query.lower()

                    # Prioritize titles that start with the query
                    if title_lower.startswith(partial_lower):
                        suggestions.append(
                            {"text": title, "path": path, "type": "search_start_match"}
                        )
                    # Then titles that contain the query
                    elif partial_lower in title_lower:
                        suggestions.append(
                            {
                                "text": title,
                                "path": path,
                                "type": "search_contains_match",
                            }
                        )

                    # Stop when we have enough suggestions
                    if len(suggestions) >= limit:
                        break

                except Exception as e:
                    logger.warning(f"Error processing search result {entry_id}: {e}")
                    continue

            # Sort suggestions to prioritize better matches
            suggestions.sort(
                key=lambda x: (
                    (
                        0 if x["type"] == "search_start_match" else 1
                    ),  # Start matches first
                    len(x["text"]),  # Shorter titles first
                )
            )

            return suggestions[:limit]

        except Exception as e:
            logger.error(f"Error in search-based suggestions: {e}")
            return []

    def _find_canonical_prefix_match(
        self,
        archive: Archive,
        partial_query: str,
        existing: List[Dict[str, str]],
        *,
        result_paths: Optional[List[str]] = None,
    ) -> Optional[Dict[str, str]]:
        """D6 (beta): probe for the canonical title with this exact prefix.

        Wikipedia files ``Photosynthesis`` at path ``Photosynthesis`` with
        title ``Photosynthesis``; both libzim's SuggestionSearcher and
        Xapian search routinely miss the bare canonical article in favor
        of disambiguator-bearing variants (``Photosynthesis (song)``,
        ``Photosynthetic_efficiency``). Strategy 1 (search-based) returns
        15 hits, none of which is ``Photosynthesis`` because longer
        titles like ``Photosynthetic_efficiency`` rank higher on Xapian
        relevance. We re-probe via SuggestionSearcher and pick the
        SHORTEST title that starts with the partial — typically the bare
        canonical article — and prepend it when missing.

        Two strategies, tried in order:
          A. Disambiguator-strip: scan ``foo_(suffix)`` results and
             check if the un-suffixed root exists.
          B. Shortest-prefix-title: scan all results and pick the
             shortest title that starts with the partial.

        Returns ``None`` when neither resolves.
        """
        partial_clean = (partial_query or "").strip()
        if not partial_clean or len(partial_clean) < 2:
            return None
        if result_paths is None:
            result_paths = self._probe_suggestion_paths(archive, partial_clean)
        if not result_paths:
            return None

        partial_lower = partial_clean.lower()
        existing_paths = {
            e.get("path") for e in existing if isinstance(e.get("path"), str)
        }
        existing_titles = {
            e.get("text", "").lower()
            for e in existing
            if isinstance(e.get("text"), str)
        }

        canonical = self._canonical_via_disambiguator_strip(
            archive,
            result_paths,
            partial_lower,
            existing_paths,
            existing_titles,
        )
        if canonical is not None:
            return canonical
        return self._canonical_via_shortest_title(
            archive,
            result_paths,
            partial_lower,
            existing_paths,
            existing_titles,
        )

    @staticmethod
    def _probe_suggestion_paths(archive: Archive, partial_clean: str) -> List[str]:
        """Run a SuggestionSearcher probe and return result paths.

        Returns an empty list on any error or zero matches; the canonical
        probe degrades gracefully without surfacing the failure.
        """
        try:
            suggestion_search = _zim_ops_mod.SuggestionSearcher(archive).suggest(
                partial_clean
            )
            total = suggestion_search.getEstimatedMatches()
            if not total:
                return []
            max_results = min(total, 25)
            return [str(p) for p in suggestion_search.getResults(0, max_results)]
        except Exception as e:
            logger.debug(f"D6 SuggestionSearcher probe failed: {e}")
            return []

    def _canonical_via_disambiguator_strip(
        self,
        archive: Archive,
        result_paths: List[str],
        partial_lower: str,
        existing_paths: set,
        existing_titles: set,
    ) -> Optional[Dict[str, str]]:
        """Strategy A: derive a canonical root from ``foo_(suffix)`` hits.

        Wikipedia's pattern is unambiguous: any title with ``_(suffix)``
        has a corresponding base article (or disambiguation page) at the
        un-suffixed path. Verify via ``has_entry_by_path`` so we only
        promote articles that actually exist.
        """
        roots_seen: set[str] = set()
        for path_str in result_paths:
            root = self._extract_disambiguator_root(path_str, partial_lower)
            if root is None or root in roots_seen:
                continue
            roots_seen.add(root)
            if root in existing_paths:
                continue
            entry_info = self._resolve_entry(archive, root)
            if entry_info is None:
                continue
            title, path = entry_info
            if not title.lower().startswith(partial_lower):
                continue
            if title.lower() in existing_titles or path in existing_paths:
                continue
            return {"text": title, "path": path, "type": "title_start_match"}
        return None

    @staticmethod
    def _extract_disambiguator_root(path_str: str, partial_lower: str) -> Optional[str]:
        """Return the pre-``_(`` portion of ``path_str`` if it starts
        with ``partial_lower``, else None."""
        paren_idx = path_str.find("_(")
        if paren_idx <= 0:
            return None
        root = path_str[:paren_idx]
        if not root or not root.lower().startswith(partial_lower):
            return None
        return root

    @staticmethod
    def _resolve_entry(archive: Archive, path: str) -> Optional[Tuple[str, str]]:
        """Resolve ``path`` to ``(title, path)`` or None if absent / mocked."""
        try:
            if not archive.has_entry_by_path(path):
                return None
            entry = archive.get_entry_by_path(path)
            title = entry.title or path
            actual = entry.path or path
        except Exception:  # pragma: no cover — defensive
            return None
        if not isinstance(title, str) or not isinstance(actual, str):
            return None
        return title, actual

    @staticmethod
    def _is_shortest_title_candidate(
        title: str,
        path: str,
        partial_lower: str,
        existing_paths: set,
        existing_titles: set,
    ) -> bool:
        """Per-row predicate for the shortest-title Strategy B scan."""
        if not title or not path:
            return False
        if _is_pseudo_namespace_entry(path, title, extended=True):
            return False
        if not title.lower().startswith(partial_lower):
            return False
        if path in existing_paths or title.lower() in existing_titles:
            return False
        return True

    def _canonical_via_shortest_title(
        self,
        archive: Archive,
        result_paths: List[str],
        partial_lower: str,
        existing_paths: set,
        existing_titles: set,
    ) -> Optional[Dict[str, str]]:
        """Strategy B: pick the shortest prefix-matching title.

        Catches archives where the canonical bare entry didn't appear
        alongside any parenthesised siblings.
        """
        best: Optional[Tuple[str, str]] = None
        best_len = float("inf")
        for result_path in result_paths:
            entry_info = self._resolve_entry(archive, result_path)
            if entry_info is None:
                continue
            title, path = entry_info
            if not self._is_shortest_title_candidate(
                title, path, partial_lower, existing_paths, existing_titles
            ):
                continue
            if len(title) < best_len:
                best = (title, path)
                best_len = len(title)
        if best is None:
            return None
        return {"text": best[0], "path": best[1], "type": "title_start_match"}

    @staticmethod
    def _find_entry_fast_path(archive: Any, title: str) -> Optional[Any]:
        """Try a small set of case variants to resolve ``title`` by path.

        libzim's ``has_entry_by_path`` is case-sensitive, so a user who
        types ``"climate change"`` against an archive that filed the entry
        as ``A/Climate_change`` would otherwise fall straight through to
        suggestion search (and miss the fast-path 1.0 score). Try the
        common natural variants in priority order: as-typed, capitalize-
        first-letter, title-case, lowercase, uppercase. Stop at the first
        hit. ``C/`` is tried before ``A/`` so new-scheme aliases win on
        modern archives; old-scheme A-namespace entries are still reached.

        Returns the resolved Entry on first match, or None on miss.
        """
        # Strongest signal first: an exact match against libzim's native
        # title index. This resolves titles whose on-disk path differs from
        # the title (e.g. title "Climate Change" filed at path "A/CC") that
        # the case-variant path probe below can never reach. ``has_entry_by_
        # title`` avoids the KeyError ``get_entry_by_title`` raises on a miss.
        try:
            if archive.has_entry_by_title(title):
                return archive.get_entry_by_title(title)
        except Exception as e:  # pragma: no cover — defensive
            logger.debug(f"_find_entry_fast_path title probe {title!r} failed: {e}")

        normalized = title.replace(" ", "_")
        # Order matters: most specific / common first. ``capitalize`` only
        # uppercases the first character; ``title`` upper-cases each word.
        variants: List[str] = []
        for candidate in (
            normalized,
            normalized.capitalize(),
            normalized.title(),
            normalized.lower(),
            normalized.upper(),
        ):
            if candidate not in variants:
                variants.append(candidate)
        for prefix in ("C/", "A/"):
            for variant in variants:
                full = f"{prefix}{variant}"
                try:
                    if archive.has_entry_by_path(full):
                        return archive.get_entry_by_path(full)
                except Exception as e:  # pragma: no cover — defensive
                    logger.debug(f"_find_entry_fast_path probe {full!r} failed: {e}")
        return None

    # Alphabet used for insertion + substitution edits. ASCII a-z + a few
    # common diacritics covers ~99% of Wikipedia titles in English-class
    # archives. Trying the full unicode letter set would inflate the
    # variant count by ~50× without proportional recall improvement.
    _TYPO_ALPHABET = tuple("abcdefghijklmnopqrstuvwxyz")

    @staticmethod
    def _typo_variants(title: str) -> List[str]:
        """Yield single-edit variants of ``title`` for typo-tolerant lookup.

        Targets the four most common keystroke errors that survive the
        case-variant fast path AND produce no libzim suggestions:

          * Adjacent character transposition — ``"Einstien"`` →
            ``"Einstein"`` (swap of ``i``/``e`` at positions 5-6).
          * Single character deletion — ``"Pythoon"`` → ``"Python"``
            (extra ``o`` removed).
          * Single character insertion — ``"Photosythesis"`` →
            ``"Photosynthesis"`` (missing ``n`` between ``y`` and ``t``).
            This was the named regression target of Phase A #14.
          * Single character substitution — ``"Wikipidia"`` →
            ``"Wikipedia"`` (i → e at position 5).

        Variants are de-duplicated. Whitespace is preserved; the caller
        (the fast path) is responsible for the space→underscore
        normalisation. Insertion/substitution are length-gated more
        strictly than deletion because they each multiply the search
        space by 26.
        """
        seen: set = {title}
        variants: List[str] = []

        # Adjacent character transposition. Skips no-op swaps where
        # the adjacent characters are identical (``"Coffee"`` → ``"Coffee"``).
        for i in range(len(title) - 1):
            if title[i] == title[i + 1]:
                continue
            v = title[:i] + title[i + 1] + title[i] + title[i + 2 :]
            if v not in seen:
                seen.add(v)
                variants.append(v)

        # Single character deletion. Capped to titles >= 5 chars on the
        # *result* (i.e. >= 6 on the input) — below that, deletions match
        # too many spurious short articles ("test" -> "tes" -> any 3-char
        # title is a false positive).
        if len(title) >= 6:
            for i in range(len(title)):
                v = title[:i] + title[i + 1 :]
                if v and v not in seen:
                    seen.add(v)
                    variants.append(v)

        # Single character insertion (Phase A #14 named regression
        # target: "Photosythesis" → "Photosynthesis"). Length-gated at
        # 5+ chars to suppress 3-char query false positives ("cat" →
        # "cats", "cart", etc.). We try the full ASCII a-z alphabet
        # because the most common case — a missing letter — is by
        # definition a letter NOT in the input ("Photosythesis" is
        # missing 'n', which doesn't appear in the user's keystrokes).
        # Variant count is bounded at ``26 × (n+1)`` for an n-char
        # title; each variant is a B-tree lookup against the libzim
        # path index, so even ~400 variants finish in <100ms.
        if len(title) >= 5:
            for i in range(len(title) + 1):
                for c in _SearchMixin._TYPO_ALPHABET:
                    v = title[:i] + c + title[i:]
                    if v not in seen:
                        seen.add(v)
                        variants.append(v)

        # Single character substitution — handles the wrong-key case
        # ("Wikipidia" → "Wikipedia", i → e at position 5). Same length
        # gate as insertion; full alphabet because the substituting
        # letter is, by definition, NOT the one typed.
        if len(title) >= 5:
            for i in range(len(title)):
                if not title[i].isalpha():
                    continue
                original = title[i].lower()
                for c in _SearchMixin._TYPO_ALPHABET:
                    if c == original:
                        continue
                    v = title[:i] + c + title[i + 1 :]
                    if v not in seen:
                        seen.add(v)
                        variants.append(v)

        return variants

    # After the first hit, keep probing for at most this many extra
    # variants. Caps the worst-case latency at
    # ``first_hit_position + _TYPO_MAX_EXTRA_PROBES`` fast-path lookups
    # so a typo with a canonical reachable two positions later doesn't
    # explode into a full ~700-variant scan.
    _TYPO_MAX_EXTRA_PROBES = 32

    def _find_entry_typo_fallback_with_suggestions(
        self,
        archive: Any,
        title: str,
        *,
        suggestion_limit: int,
    ) -> Tuple[Optional[Any], List[str]]:
        """Single-sweep typo probe (best entry + verified suggestions).

        Walks the ~700-variant typo set once, calling
        ``_find_entry_fast_path`` per variant, and returns both the best
        entry hit and the verified suggestion titles in one pass. This
        replaced an earlier two-function design that iterated the variant
        set twice — once for the entry, once for the suggestion titles —
        which on a ``find_entry_by_title`` zero-hit cold path doubled the
        archive lookup count and blew through the spec's 30 ms budget.

        Returns ``(best_entry, verified_titles)``:

        - ``best_entry`` is the canonical-preferred hit (``_TYPO_MAX_
          EXTRA_PROBES`` extra probes after first hit, redirect chain
          followed), or ``None``.
        - ``verified_titles`` is the canonical-title list for
          ``_meta.suggestions``, capped at ``suggestion_limit``.
        """
        if len(title) < self.config.search.fuzzy_title_min_query_len:
            return None, []

        best: Optional[Any] = None
        best_is_canonical = False
        extra_probes = 0
        verified: List[str] = []
        seen_titles: set[str] = set()
        for variant in self._typo_variants(title):
            # Early-out once we have a canonical hit AND enough suggestions.
            best_is_done = best is not None and (
                best_is_canonical or extra_probes >= self._TYPO_MAX_EXTRA_PROBES
            )
            if best_is_done and len(verified) >= suggestion_limit:
                break

            try:
                entry = self._find_entry_fast_path(archive, variant)
            except Exception:
                if best is not None and not best_is_done:
                    extra_probes += 1
                continue
            if entry is None:
                if best is not None and not best_is_done:
                    extra_probes += 1
                continue

            source_is_canonical = not bool(getattr(entry, "is_redirect", False))
            resolved = self._follow_redirect_chain(entry)

            # Update the verified-titles pool for _meta.suggestions.
            resolved_title = resolved.title or entry.title or variant
            if resolved_title not in seen_titles and len(verified) < suggestion_limit:
                verified.append(resolved_title)
                seen_titles.add(resolved_title)

            # Update the best-entry candidate.
            if best is None:
                best = resolved
                best_is_canonical = source_is_canonical
            elif source_is_canonical and not best_is_canonical:
                best = resolved
                best_is_canonical = True
            else:
                if not best_is_done:
                    extra_probes += 1
        return best, verified

    @staticmethod
    def _follow_redirect_chain(entry: Any) -> Any:
        """Walk an entry's ``is_redirect`` chain to its canonical target.

        Bounded by ``MAX_REDIRECT_DEPTH``; tolerates cycles by tracking
        seen paths. Returns the last *real* entry on any failure so the
        caller always gets something it can name — never ``None``.

        Post-a14 sweep self-audit: the prior implementation could
        return ``None`` when ``get_redirect_entry()`` returned None
        (observed on archives with broken redirect chains). That
        crashed every downstream ``entry.path`` access. The
        ``last_good`` tracking keeps the most recent non-None Entry so
        the caller can still emit a hit.
        """
        target = entry
        last_good = entry
        seen: set = set()
        first_path = getattr(target, "path", None)
        if first_path is not None:
            seen.add(first_path)
        for _ in range(MAX_REDIRECT_DEPTH):
            if not getattr(target, "is_redirect", False):
                return target
            try:
                target = target.get_redirect_entry()
            except Exception:
                return last_good
            if target is None:
                return last_good
            tp = getattr(target, "path", None)
            if tp is None or tp in seen:
                return last_good
            seen.add(tp)
            last_good = target
        return target

    def _fast_path_row(
        self, archive: Any, title: str, file_path: str
    ) -> Optional[Dict[str, Any]]:
        """Probe the fast path for ``title``; return a result row or None.

        Tries a handful of case variants against ``C/<normalized>`` and
        ``A/<normalized>`` (legacy content namespace). libzim's path
        lookups are case-sensitive, so we expand a small set of natural
        variants — ``Climate change``, ``climate change``, ``Climate
        Change``, etc. — rather than asking callers to know exactly how
        the entry was filed. has_new_scheme archives accept ``C/<path>``
        as an alias for ``<path>``.

        Returns the score-1.0 result row on a hit, or ``None`` on a miss.
        The caller owns the loop control flow (break/continue) and the
        ``fast_path_hit`` flag.
        """
        fast_hit_entry = self._find_entry_fast_path(archive, title)
        if fast_hit_entry is None:
            return None
        # Post-a14 sweep: walk the redirect chain so the
        # reported path is the canonical post-redirect
        # one. ``Big_Rapids_Michigan`` (comma-stripped
        # redirect) → ``Big_Rapids,_Michigan`` keeps the
        # cite_id stable across lookup-variant paths.
        # Post-b4 D1: capture the pre-redirect path so we
        # can annotate ``match_type`` with whether the
        # canonical lookup actually walked a redirect.
        # Post-b6 Z1: propagate the pre-redirect path
        # itself in the result row so the D1 filter can
        # check whether the redirect target is
        # semantically related to the user's query.
        fast_pre_path = getattr(fast_hit_entry, "path", None)
        fast_hit_entry = self._follow_redirect_chain(fast_hit_entry)
        fast_post_path = getattr(fast_hit_entry, "path", None)
        fast_match_type = "redirect" if fast_pre_path != fast_post_path else "direct"
        return {
            "path": fast_hit_entry.path,
            "title": fast_hit_entry.title or title,
            "score": 1.0,
            "zim_file": file_path,
            "match_type": fast_match_type,
            "pre_redirect_path": str(fast_pre_path or ""),
        }

    def _typo_fallback_row(
        self,
        archive: Any,
        title: str,
        file_path: str,
        *,
        suggestion_limit: int,
    ) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        """Run the single-sweep typo probe; return ``(row_or_none, variants)``.

        One pass collects both the typo-corrected best hit AND the
        verified alt-spelling suggestions. The previous code ran two
        separate ~700-variant sweeps on the same archive, doubling the
        worst-case latency on cold-miss queries.

        Returns the ``typo_corrected`` result row (or ``None``) plus the
        fresh verified alt-spelling titles. The caller owns the
        ``fuzzy_path_hit`` flag and the verified-variant accumulation.
        """
        typo_entry, fresh_variants = self._find_entry_typo_fallback_with_suggestions(
            archive, title, suggestion_limit=suggestion_limit
        )
        if typo_entry is None:
            return None, fresh_variants
        # Post-a14 sweep: typo-fallback variants
        # almost always land on a redirect (the
        # canonical title is exactly what they were
        # trying to reach by typo-correcting). Walk
        # the chain so cite_id consumers see the
        # canonical path.
        typo_entry = self._follow_redirect_chain(typo_entry)
        resolved_typo_title = typo_entry.title or title
        row = {
            "path": typo_entry.path,
            "title": resolved_typo_title,
            # Score set from config (default 0.85).
            # Below 0.95 (suggestion-rank top) and
            # well below 1.0 (exact match) so a
            # fuzzy hit never silently outranks a
            # legitimate result from another file.
            "score": self.config.search.fuzzy_title_score_penalty,
            "zim_file": file_path,
            "match_type": "typo_corrected",
        }
        return row, fresh_variants

    def _assemble_find_response(
        self,
        aggregate_results: List[Dict[str, Any]],
        *,
        title: str,
        limit: int,
        files: List[str],
        fast_path_hit: bool,
        fuzzy_path_hit: bool,
        verified_variants: List[str],
    ) -> "FindEntryResponse":
        """Sort, dedupe, and assemble the contract envelope.

        Pure transformation of the per-file accumulated state — no
        archive access, no control flow. Mirrors the legacy post-loop
        block exactly.
        """
        structured_suggestions_limit = self.config.search.structured_suggestions_limit

        # Sort results so exact case-insensitive matches (score=1.0) lead;
        # otherwise preserve per-file rank order.
        aggregate_results.sort(key=lambda r: -r["score"])

        # Post-a14 sweep self-audit: dedupe by (zim_file, path) AFTER
        # sorting so the highest-scored row wins. The F3 redirect-
        # chain canonicalisation collapses ``Bilogy`` and ``Biology``
        # suggestions onto the same canonical path; without this
        # dedup the response would carry two rows for the same
        # article (one from each suggestion that resolved to the
        # canonical). Pre-F3, the rows had distinct paths so no
        # dedup was needed.
        seen: set[tuple[str, str]] = set()
        deduped: List[Dict[str, Any]] = []
        for row in aggregate_results:
            key = (str(row.get("zim_file", "")), str(row.get("path", "")))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        aggregate_results = deduped

        # Build _meta.suggestions[] from archive-verified typo variants.
        # Two cases surface them (spec §14.4):
        #   * No results of any kind — pure recovery hints.
        #   * A fuzzy hit is returned — the variant that matched is shown
        #     so the caller can verify the auto-correction rather than
        #     silently accepting it.
        # When the response carries a non-fuzzy hit, suggestions stay
        # empty so confident matches aren't muddled by alt-spelling noise.
        suggestions: List[Dict[str, str]] = []
        if not aggregate_results or fuzzy_path_hit:
            for resolved in verified_variants[:structured_suggestions_limit]:
                suggestions.append({"type": "alt_spelling", "value": resolved})

        reason = None if aggregate_results else "0_hits"

        # Trim to limit and build the contract envelope. ``find_entry_by_title``
        # is non-paginated (no cursor input, no offset), but the v2 Phase B
        # contract still applies for uniformity: ``next_cursor=None``,
        # ``done=True``, ``total=len(results)``, ``page_info.offset=0``.
        trimmed_results = aggregate_results[:limit]
        payload: Dict[str, Any] = {
            "query": title,
            "results": trimmed_results,
            "next_cursor": None,
            "total": len(trimmed_results),
            "done": True,
            "page_info": {
                "offset": 0,
                "limit": limit,
                "returned_count": len(trimmed_results),
            },
            "fast_path_hit": fast_path_hit,
            "fuzzy_path_hit": fuzzy_path_hit,
            "files_searched": len(files),
        }
        return cast(
            "FindEntryResponse",
            attach_meta(
                payload,
                suggestions=suggestions if suggestions else None,
                reason=reason,
            ),
        )

    def find_entry_by_title_data(
        self,
        zim_file_path: str,
        title: str,
        cross_file: bool = False,
        limit: int = 10,
    ) -> "FindEntryResponse":
        """Structured variant of ``find_entry_by_title``.

        Returns the result dict directly (not a JSON string) so MCP tools
        can hand it straight to FastMCP's structured-content path.

        Implementation order:
          1. Direct path probe in C/ and A/ namespaces against a small set of
             case variants (fast path) — handles the common "user typed
             lowercase" case without paying for a suggestion search.
          2. libzim suggestion search (title-indexed) — primary fallback.
             Results carry rank-derived scores; an exact case-insensitive
             title match is promoted to score 1.0 and flips fast_path_hit.
          3. Return list sorted by score (descending).
        """
        if not title or not title.strip():
            raise OpenZimMcpValidationError(
                "Input is empty or contains only whitespace/control characters"
            )
        if limit < 1 or limit > 50:
            raise OpenZimMcpValidationError(
                f"limit must be between 1 and 50 (provided: {limit})"
            )

        if cross_file:
            files = [f["path"] for f in self.list_zim_files_data() if f.get("path")]
        else:
            validated = self._validate_zim_path(zim_file_path)
            files = [str(validated)]

        aggregate_results: List[Dict[str, Any]] = []
        fast_path_hit = False
        fuzzy_path_hit = False
        title_lower = title.lower()
        # Verified typo-variant titles accumulated during the per-file
        # typo-fallback probe. Used only when *all* archives return
        # zero hits, to populate ``_meta.suggestions`` with values the
        # caller can re-issue as a fresh query (Phase A #6 fix).
        verified_variants: List[str] = []
        verified_variants_seen: set[str] = set()
        structured_suggestions_limit = self.config.search.structured_suggestions_limit

        for file_path in files:
            try:
                with _zim_ops_mod.zim_archive(file_path) as archive:
                    # Fast path: a direct case-variant path/title probe.
                    # The helper returns the score-1.0 row or None; the
                    # loop owns the control flow and the flag update.
                    fast_row = self._fast_path_row(archive, title, file_path)
                    if fast_row is not None:
                        aggregate_results.append(fast_row)
                        fast_path_hit = True
                        if not cross_file:
                            break
                        continue

                    # Fallback: libzim suggestion search (title-indexed).
                    # Note: ``Archive.suggest()`` does not exist; the public
                    # API is ``SuggestionSearcher(archive).suggest(text)``.
                    try:
                        suggestion_search = _zim_ops_mod.SuggestionSearcher(
                            archive
                        ).suggest(title)
                        total = suggestion_search.getEstimatedMatches()
                        if total > 0:
                            paths = list(suggestion_search.getResults(0, limit))
                            # Score by rank — first result is the best
                            # libzim suggestion match. Legacy behaviour was a
                            # hardcoded 0.8 for every hit, which made the
                            # ``score`` field decorative; rank-based scoring
                            # gives callers a real ordering signal. An exact
                            # case-insensitive title match is promoted to
                            # 1.0 (and flips fast_path_hit) so callers can
                            # recognise the strongest possible match.
                            n = max(len(paths), 1)
                            for idx, path in enumerate(paths):
                                try:
                                    entry = archive.get_entry_by_path(path)
                                except Exception as e:
                                    logger.debug(
                                        f"find_entry_by_title suggestion read "
                                        f"failed for {path}: {e}"
                                    )
                                    continue
                                # Post-a14 sweep: report canonical post-
                                # redirect path so cite_id consumers
                                # always see the same key for the same
                                # article regardless of which redirect
                                # the suggestion index emitted.
                                # Post-b4 D1: track whether the
                                # redirect chain actually walked, so
                                # the row's ``match_type`` distinguishes
                                # a true canonical redirect (safe to
                                # auto-fetch at the 0.95 gate) from a
                                # raw fuzzy title-prefix suggestion
                                # (``Darwin's evolution`` → ``Evolution``
                                # at 0.95 — same score, not safe).
                                suggest_pre_path = getattr(entry, "path", None)
                                entry = self._follow_redirect_chain(entry)
                                suggest_post_path = getattr(entry, "path", None)
                                redirect_walked = suggest_pre_path != suggest_post_path
                                resolved_title = entry.title or path
                                exact_ci = resolved_title.lower() == title_lower
                                if exact_ci:
                                    score: float = 1.0
                                    fast_path_hit = True
                                    match_type = "direct"
                                else:
                                    # Linearly decaying rank-score in (0, 0.95].
                                    # Capped below 1.0 so an exact match always
                                    # outranks any prefix/partial.
                                    score = round(0.95 * (1.0 - idx / n), 4)
                                    match_type = (
                                        "redirect"
                                        if redirect_walked
                                        else "fuzzy_suggest"
                                    )
                                aggregate_results.append(
                                    {
                                        "path": entry.path,
                                        "title": resolved_title,
                                        "score": score,
                                        "zim_file": file_path,
                                        "match_type": match_type,
                                        # Post-b6 Z1: propagate the
                                        # pre-redirect path so the D1
                                        # filter on possessive topics
                                        # can detect associative
                                        # redirects (pre-path unrelated
                                        # to the user's possessor
                                        # entity).
                                        "pre_redirect_path": str(
                                            suggest_pre_path or ""
                                        ),
                                    }
                                )
                    except Exception as e:
                        if not cross_file:
                            raise
                        logger.debug(
                            f"find_entry_by_title suggest() failed for "
                            f"{file_path}: {e}"
                        )

                    # Typo-tolerant fallback: when both fast path AND
                    # the libzim suggestion index came up empty, OR when
                    # the suggestions only yielded weak results (score < 0.7),
                    # try a small set of single-edit variants of the input
                    # (transposition / single deletion). Runs only as a
                    # last resort because the false-match rate isn't
                    # zero — we don't want it competing with real hits.
                    already_has_strong = any(
                        r.get("score", 0.0) >= 0.7 for r in aggregate_results
                    )
                    if not fast_path_hit and not already_has_strong:
                        suggestion_room = structured_suggestions_limit - len(
                            verified_variants
                        )
                        typo_row, fresh_variants = self._typo_fallback_row(
                            archive,
                            title,
                            file_path,
                            suggestion_limit=max(suggestion_room, 0),
                        )
                        if typo_row is not None:
                            aggregate_results.append(typo_row)
                            fuzzy_path_hit = True
                        # Whether or not the merged probe found a fuzzy
                        # hit, surface the verified alt-spelling pool so
                        # the response carries actionable suggestions in
                        # both branches (matching the spec §14.4 surfacing
                        # rule the legacy split-pass version implemented
                        # via two code paths).
                        for resolved in fresh_variants:
                            if resolved not in verified_variants_seen:
                                verified_variants.append(resolved)
                                verified_variants_seen.add(resolved)
                            if len(verified_variants) >= structured_suggestions_limit:
                                break
            except Exception as e:
                if not cross_file:
                    raise
                logger.debug(f"find_entry_by_title: skipped {file_path}: {e}")

        return self._assemble_find_response(
            aggregate_results,
            title=title,
            limit=limit,
            files=files,
            fast_path_hit=fast_path_hit,
            fuzzy_path_hit=fuzzy_path_hit,
            verified_variants=verified_variants,
        )

    def find_entry_by_title(
        self,
        zim_file_path: str,
        title: str,
        cross_file: bool = False,
        limit: int = 10,
    ) -> str:
        """Legacy JSON-string variant of ``find_entry_by_title_data``.

        Resolve a title or partial title to one or more entry paths.

        Returns:
            JSON string with query, ranked results, fast_path_hit flag,
            files_searched.
        """
        return _json(
            self.find_entry_by_title_data(zim_file_path, title, cross_file, limit)
        )

    def _find_entry_by_search(self, archive: Archive, entry_path: str) -> Optional[str]:
        """Find the actual entry path by searching for the entry.

        This method attempts to find an entry by searching for various parts
        of the provided path, handling common path encoding issues.

        Args:
            archive: ZIM archive instance
            entry_path: The requested entry path

        Returns:
            The actual entry path if found, None otherwise
        """
        # Re-import to honour test patches against ``libzim.search.Searcher``.
        # Tests for this method historically patched the upstream libzim
        # symbols rather than the ``zim_operations`` re-export, and the
        # original implementation had a function-local import that picked
        # up those patches.
        from libzim.search import (  # type: ignore[import-untyped]
            Query,
            Searcher,
        )

        # Hoist Searcher construction out of the loop. Each ``Searcher(archive)``
        # opens the archive's Xapian DB; building a fresh one per fallback term
        # multiplied that cost by up to 5x.
        try:
            searcher = Searcher(archive)
        except Exception as e:
            logger.debug(f"Searcher initialization failed: {e}")
            return None

        for search_term in self._extract_search_terms_from_path(entry_path):
            if len(search_term) < 2:  # Skip very short terms
                continue
            match = self._search_term_for_path(searcher, Query, search_term, entry_path)
            if match is not None:
                return match
        return None

    def _search_term_for_path(
        self,
        searcher: Any,
        query_factory: Any,
        search_term: str,
        entry_path: str,
    ) -> Optional[str]:
        """Run one search term and return the first result that matches the path.

        Returns ``None`` if the term yields no results, all results miss, or
        the search itself raises (a single bad term shouldn't abort the
        outer loop's other fallbacks).
        """
        try:
            logger.debug(f"Searching for entry with term: '{search_term}'")
            search = searcher.search(query_factory().set_query(search_term))
            total_results = search.getEstimatedMatches()
            if total_results == 0:
                return None
            max_results = min(total_results, 10)
            for result_path in search.getResults(0, max_results):
                result_path_str = str(result_path)
                if self._is_path_match(entry_path, result_path_str):
                    logger.debug(f"Found matching entry: {result_path_str}")
                    return result_path_str
        except Exception as e:
            logger.debug(f"Search failed for term '{search_term}': {e}")
        return None

    def _extract_search_terms_from_path(self, entry_path: str) -> List[str]:
        """Extract potential search terms from an entry path.

        Args:
            entry_path: The entry path to extract terms from

        Returns:
            List of search terms to try
        """
        terms = []

        # Remove namespace prefix if present (e.g., "A/Article" -> "Article")
        if "/" in entry_path:
            path_without_namespace = entry_path.split("/", 1)[1]
            terms.append(path_without_namespace)
        else:
            path_without_namespace = entry_path

        # Add the full path as a search term
        terms.append(entry_path)

        # Replace underscores with spaces (common in Wikipedia-style paths)
        if "_" in path_without_namespace:
            terms.append(path_without_namespace.replace("_", " "))

        # Replace spaces with underscores
        if " " in path_without_namespace:
            terms.append(path_without_namespace.replace(" ", "_"))

        # URL decode if it looks like it might be encoded
        try:
            decoded = urllib.parse.unquote(path_without_namespace)
            if decoded != path_without_namespace:
                terms.append(decoded)
        except Exception as e:
            logger.debug(f"URL decode failed for path '{path_without_namespace}': {e}")

        # Remove duplicates while preserving order
        seen = set()
        unique_terms = []
        for term in terms:
            if term not in seen:
                seen.add(term)
                unique_terms.append(term)

        return unique_terms

    def _is_path_match(self, requested_path: str, actual_path: str) -> bool:
        """Check if an actual path from search results matches the requested path.

        Args:
            requested_path: The originally requested path
            actual_path: A path from search results

        Returns:
            True if the paths are considered a match
        """
        # Exact match
        if requested_path == actual_path:
            return True

        # Extract the path part without namespace
        requested_part = (
            requested_path.split("/", 1)[1] if "/" in requested_path else requested_path
        )
        actual_part = (
            actual_path.split("/", 1)[1] if "/" in actual_path else actual_path
        )

        # Case-insensitive comparison
        if requested_part.lower() == actual_part.lower():
            return True

        # Compare with underscore/space variations
        requested_normalized = requested_part.replace("_", " ").lower()
        actual_normalized = actual_part.replace("_", " ").lower()
        if requested_normalized == actual_normalized:
            return True

        # URL encoding comparison
        try:
            requested_decoded = urllib.parse.unquote(requested_part).lower()
            actual_decoded = urllib.parse.unquote(actual_part).lower()
            if requested_decoded == actual_decoded:
                return True
        except Exception as e:
            logger.debug(f"URL decode comparison failed: {e}")

        return False

    def search_all_data(
        self,
        query: str,
        limit_per_file: int = 5,
    ) -> "SearchAllResponse":
        """Structured variant of ``search_all`` (Phase B contract).

        Top-level shape is a non-paginated ``PaginatedResponse[per_file]``
        — ``done`` is always ``True`` and ``next_cursor`` is always
        ``None`` because fan-out across archives happens in one shot.
        Each ``results[].result`` is itself a Phase B ``SearchResponse``
        carrying its own per-archive cursor.

        Per-file results are real dicts (the structured payload from
        ``search_zim_file_data``) rather than markdown strings — fixing
        the triple-stringification of the legacy ``search_all`` (where
        the per-file ``result`` field was a markdown blob escaped inside
        the outer JSON string).

        Args:
            query: Search query
            limit_per_file: Maximum hits to return per ZIM file (1-50, default 5)

        Returns:
            ``SearchAllResponse``-shaped dict. Each ``results[].result``
            is the structured search payload from ``search_zim_file_data``
            — a dict, not a string. Aggregate counts (``files_searched``,
            ``files_with_hits``, ``files_searched_successfully``,
            ``files_failed``) live at the top level alongside the
            contract keys.
        """
        if not query or not query.strip():
            raise OpenZimMcpValidationError(
                "Input is empty or contains only whitespace/control characters"
            )
        if limit_per_file < 1 or limit_per_file > 50:
            raise OpenZimMcpValidationError(
                f"limit_per_file must be between 1 and 50 "
                f"(provided: {limit_per_file})"
            )

        files = self.list_zim_files_data()
        per_file: List[Dict[str, Any]] = []
        # H22: aggregate wall-clock budget across the fan-out.
        # ``0`` disables.
        import time as _time

        total_timeout = float(
            getattr(
                getattr(self.config, "search", None),
                "search_all_total_timeout_seconds",
                0.0,
            )
            or 0.0
        )
        deadline = _time.monotonic() + total_timeout if total_timeout > 0 else None
        budget_exceeded = False
        for file_info in files:
            path = file_info.get("path")
            if not path:
                continue
            # Stop iterating once the aggregate budget is gone — the threadpool
            # slot frees instead of blocking on another full Xapian search.
            if deadline is not None and _time.monotonic() >= deadline:
                budget_exceeded = True
                break
            try:
                payload = self.search_zim_file_data(path, query, limit_per_file, 0)
                _total = payload.get("total", 0) or 0
                per_file.append(
                    {
                        "zim_file_path": path,
                        "name": file_info.get("name"),
                        "result": payload,
                        "has_hits": _total > 0,
                        # H14: success entries carry ``error=False`` so the
                        # per-file row is shape-stable across success and
                        # failure. The legacy contract stuffed a
                        # ``ToolErrorPayload`` into ``result`` for failures,
                        # making ``results[].result`` heterogeneous —
                        # sometimes a SearchResponse, sometimes an error
                        # envelope. Splitting the error into a sibling key
                        # keeps ``result`` a single TypedDict shape and gives
                        # small models a single boolean to branch on.
                        "error": False,
                    }
                )
            except Exception as e:
                logger.debug(f"search_all: skipped {path}: {e}")
                per_file.append(
                    {
                        "zim_file_path": path,
                        "name": file_info.get("name"),
                        "has_hits": False,
                        # H14: failure entries carry ``error=True`` plus an
                        # ``error_message`` / ``error_operation`` for context.
                        # ``result`` is None so the TypedDict shape stays
                        # uniform; callers branch on ``error`` instead of
                        # type-sniffing ``result``.
                        "result": None,
                        "error": True,
                        "error_operation": "search_zim_file",
                        "error_message": str(e),
                    }
                )

        files_searched = len(files)
        # H22: when the budget cut iteration short, ``done=True`` would
        # be a lie — there are unsearched archives. Flag with
        # ``budget_exceeded`` on the top-level payload and propagate as a
        # ``reason`` so the footer can render the actionable hint
        # ("budget exceeded; raise OPENZIM_MCP_SEARCH__SEARCH_ALL_TOTAL_TIMEOUT_SECONDS
        # or narrow zim_file_filter").
        meta_reason: Optional[str] = (
            "search_all_budget_exceeded" if budget_exceeded else None
        )
        return cast(
            "SearchAllResponse",
            attach_meta(
                {
                    "query": query,
                    "files_searched": len(per_file),
                    "files_available": files_searched,
                    "files_with_hits": sum(1 for r in per_file if r.get("has_hits")),
                    "files_searched_successfully": sum(
                        1 for r in per_file if not r.get("error")
                    ),
                    "files_failed": sum(1 for r in per_file if r.get("error") is True),
                    "budget_exceeded": budget_exceeded,
                    "results": per_file,
                    "next_cursor": None,
                    "total": files_searched,
                    "done": not budget_exceeded,
                    "page_info": {
                        "offset": 0,
                        "limit": files_searched,
                        "returned_count": len(per_file),
                    },
                },
                reason=meta_reason,
            ),
        )

    def search_all(
        self,
        query: str,
        limit_per_file: int = 5,
    ) -> str:
        """Legacy JSON-string variant of ``search_all_data``.

        Useful when the model doesn't know which ZIM file holds the
        information it needs. Skips files that can't be searched (corrupt,
        no full-text index) without aborting the rest.

        New callers should prefer ``search_all_data`` so the per-file
        result payload stays as a structured dict instead of being
        re-stringified inside the outer JSON envelope.

        Args:
            query: Search query
            limit_per_file: Maximum hits to return per ZIM file (1-50, default 5)

        Returns:
            JSON with per-file result groups (each ``result`` is itself a
            structured search payload) and aggregate counts.
        """
        return _json(self.search_all_data(query, limit_per_file))

    def search_top_k(self, archive: "Archive", query: str, *, k: int) -> list[dict]:
        """Top-K Xapian results from an open archive as a flat dict list.

        Used by synthesize.py as the primary stage of the pipeline.  Each hit
        has the shape ``{"path": str, "snippet": str, "score": float}``.

        ``path`` is the entry path string returned directly by
        ``search.getResults()`` (entry_id IS the path in libzim 9+).
        ``snippet`` is produced by ``_get_entry_snippet`` (content-processor
        extract, consistent with the rest of the search surface).
        ``score`` is set to the hit's rank-based inverse (1 / rank) as a
        lightweight proxy — libzim's Xapian binding does not expose raw BM25
        scores through the public Python API.
        """
        query_obj = _zim_ops_mod.Query().set_query(query)
        searcher = _zim_ops_mod.Searcher(archive)
        search = searcher.search(query_obj)
        total_results = search.getEstimatedMatches()
        if total_results == 0:
            return []
        result_count = min(k, total_results)
        entry_ids: List[str] = list(search.getResults(0, result_count))
        hits: list[dict] = []
        for rank, entry_id in enumerate(entry_ids, start=1):
            try:
                entry = archive.get_entry_by_path(entry_id)
                snippet = self._get_entry_snippet(entry, query=query)
            except Exception as exc:
                logger.warning(
                    f"search_top_k: error fetching entry {entry_id!r}: {exc}"
                )
                snippet = ""
            score = 1.0 / rank  # rank-inverse proxy; no raw BM25 in libzim Python API
            hits.append({"path": entry_id, "snippet": snippet, "score": score})
        return hits

    def title_match_hit(
        self, archive: "Archive", title: str
    ) -> Optional[Dict[str, Any]]:
        """Resolve ``title`` against an open archive's title-index fast path
        and return a search-top-k-shaped hit on success, ``None`` on miss.

        D3 / Op1 (v2.0.0a9): synthesize and other ranking-aware paths
        need to promote canonical title hits past BM25 noise without
        re-opening the archive. ``_find_entry_fast_path`` already knows
        the case-variant + namespace-prefix sweep; we wrap its result
        in the ``{path, snippet, score}`` shape that downstream stages
        expect, so the promoted entry plugs into the synthesize pipeline
        as if it had come from ``search_top_k``.

        Post-a14 sweep: walks the redirect chain to the canonical
        target via ``_follow_redirect_chain`` before reporting the
        path. Wikipedia archives carry many comma-stripped /
        case-normalised redirects (``Big_Rapids_Michigan`` →
        ``Big_Rapids,_Michigan``); without this, the synthesize
        ``cite_id`` and the BM25 ``cite_id`` for the same article
        diverge depending on which lookup variant matched, splitting
        multi-round-agent state across two distinct cite_ids.

        ``score`` is fixed at 1.0 — a fast-path title hit is the
        strongest possible signal we can produce, and the caller uses
        the value only to label the promoted entry; subsequent fusion
        respects positional order anyway.
        """
        try:
            entry = self._find_entry_fast_path(archive, title)
        except Exception as e:
            logger.debug(f"title_match_hit fast-path failed for {title!r}: {e}")
            return None
        if entry is None:
            return None
        entry = self._follow_redirect_chain(entry)
        try:
            snippet = self._get_entry_snippet(entry, query=title)
        except Exception as e:
            logger.debug(f"title_match_hit snippet failed for {title!r}: {e}")
            snippet = ""
        return {"path": entry.path, "snippet": snippet, "score": 1.0}
