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

import json
import logging
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from libzim.reader import Archive  # type: ignore[import-untyped]

import openzim_mcp.zim_operations as _zim_ops_mod
from openzim_mcp.exceptions import (
    OpenZimMcpArchiveError,
    OpenZimMcpValidationError,
)

if TYPE_CHECKING:
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.content_processor import ContentProcessor
    from openzim_mcp.security import PathValidator

logger = logging.getLogger(__name__)


# Streaming knobs for ``_perform_filtered_search``: bound memory and CPU
# for pathological queries while keeping the page-fill loop predictable.
_FILTERED_BATCH_SIZE = 500
_FILTERED_MAX_SCAN = 10000


@dataclass(frozen=True)
class _FilteredScanState:
    """Aggregate state captured during one filtered-search scan pass."""

    filtered_count: int
    scanned: int
    scan_cap_hit: bool
    total_filtered_is_lower_bound: bool


def _format_filter_text(namespace: Optional[str], content_type: Optional[str]) -> str:
    """Render the ``(filters: ...)`` annotation used in result headers."""
    parts: List[str] = []
    if namespace:
        parts.append(f"namespace={namespace}")
    if content_type:
        parts.append(f"content_type={content_type}")
    return f" (filters: {', '.join(parts)})" if parts else ""


def _format_filtered_response(
    query: str,
    filter_text: str,
    results: List[Dict[str, Any]],
    scan: _FilteredScanState,
    total_results: int,
    offset: int,
    limit: int,
) -> str:
    """Render the human-readable response body, header, and pagination footer."""
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

    parts: List[str] = [
        f'Found {total_filtered_text} filtered matches for "{query}"'
        f"{filter_text}, "
        f"showing {offset + 1}-{offset + len(results)}{capped_note}:\n\n",
    ]
    for i, result in enumerate(results):
        parts.append(f"## {offset + i + 1}. {result['title']}\n")
        parts.append(f"Path: {result['path']}\n")
        parts.append(f"Namespace: {result['namespace']}\n")
        parts.append(f"Content Type: {result['content_type']}\n")
        parts.append(f"Snippet: {result['snippet']}\n\n")

    parts.append("---\n")
    parts.append(
        f"**Pagination**: Showing {offset + 1}-{offset + len(results)} "
        f"of {total_filtered_text}\n"
    )

    has_more = scan.total_filtered_is_lower_bound or (
        offset + len(results) < scan.filtered_count
    )
    if has_more:
        # When ``filtered_count`` is a lower bound we know there may be more
        # matches but we don't know the true total — ``create_next_cursor``
        # would return ``None`` (since ``offset+limit >= filtered_count``)
        # and we'd render ``Next cursor: None``. Pad the total so the
        # cursor generator emits a valid token.
        cursor_total = (
            scan.filtered_count + 1
            if scan.total_filtered_is_lower_bound
            else scan.filtered_count
        )
        next_cursor = _zim_ops_mod.PaginationCursor.create_next_cursor(
            offset, limit, cursor_total, query
        )
        # Edge case: the scan-cap path can leave ``offset+limit`` equal to
        # the (true) filtered_count, so create_next_cursor returns None
        # even though has_more was True for the lower-bound path. Don't
        # render a literal "None" cursor — omit the line.
        if next_cursor is not None:
            parts.append(f"**Next cursor**: `{next_cursor}`\n")
        parts.append(f"**Hint**: Use offset={offset + limit} to get the next page\n")
    else:
        parts.append("**End of results**\n")
    return "".join(parts)


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

        def list_zim_files_data(
            self, name_filter: Optional[str] = None
        ) -> List[Dict[str, Any]]:
            """Resolve via ``ZimOperations`` on the concrete coordinator."""

        # Resolve via the content mixin; declared here for type checking.
        def _get_entry_snippet(self, entry: Any) -> str:
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
    ) -> str:
        """Markdown-rendered search result (legacy surface).

        See ``search_zim_file_data`` for the structured variant. This wrapper
        is retained so existing callers (and tests) that consume the rendered
        text keep working unchanged.

        Args:
            zim_file_path: Path to the ZIM file
            query: Search query term
            limit: Maximum number of results to return
            offset: Result starting offset (for pagination)

        Returns:
            Search result text

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If search operation fails
        """
        payload = self.search_zim_file_data(zim_file_path, query, limit, offset)
        return self._format_search_text(payload)

    def search_zim_file_data(
        self,
        zim_file_path: str,
        query: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Structured variant of ``search_zim_file``.

        Returns the raw search payload as a Python dict so MCP tool functions
        and aggregators (``search_all``) can hand it straight to FastMCP's
        structured-output path without the json.dumps + re-parse round trip
        the legacy string variant required.

        Raises:
            OpenZimMcpFileNotFoundError: If ZIM file not found
            OpenZimMcpArchiveError: If search operation fails
        """
        if limit is None:
            limit = self.config.content.default_search_limit

        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Cache key distinct from the legacy string cache so old persisted
        # entries (which hold strings) don't collide with the new dict shape.
        cache_key = f"search_data:{validated_path}:{query}:{limit}:{offset}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached search dict for query: {query}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                payload, total_results = self._perform_search(
                    archive, query, limit, offset
                )

            # Don't cache zero-result responses: libzim's lazy index warm-up
            # can return 0 matches transiently, and a TTL-cached "no results"
            # would mask the index becoming ready.
            if total_results > 0:
                self.cache.set(cache_key, payload)
            logger.debug(f"Search completed: query='{query}', results found")
            return payload

        except OpenZimMcpArchiveError:
            # Inner helper already raised a typed archive error with full
            # context. Don't re-wrap and double the message prefix.
            raise
        except Exception as e:
            logger.error(f"Search failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(f"Search operation failed: {e}") from e

    def _perform_search(
        self, archive: Archive, query: str, limit: int, offset: int
    ) -> Tuple[Dict[str, Any], int]:
        """Perform the actual search operation.

        Returns:
            (structured_payload, total_results) — caller uses total_results
            to decide whether the response is safe to cache. The payload
            shape is documented on ``search_zim_file_data``.
        """
        # Create searcher and execute search
        query_obj = _zim_ops_mod.Query().set_query(query)
        searcher = _zim_ops_mod.Searcher(archive)
        search = searcher.search(query_obj)

        # Get total results
        total_results = search.getEstimatedMatches()

        if total_results == 0:
            return (
                {
                    "query": query,
                    "total_results": 0,
                    "offset": offset,
                    "limit": limit,
                    "results": [],
                    "pagination": {"has_more": False},
                },
                0,
            )

        # Guard against offset exceeding total results (would produce negative count)
        if offset >= total_results:
            return (
                {
                    "query": query,
                    "total_results": total_results,
                    "offset": offset,
                    "limit": limit,
                    "results": [],
                    "pagination": {
                        "has_more": False,
                        "offset_exceeds_total": True,
                    },
                },
                total_results,
            )

        result_count = min(limit, total_results - offset)

        # Get search results
        result_entries = list(search.getResults(offset, result_count))

        # Collect search results
        results: List[Dict[str, Any]] = []
        for i, entry_id in enumerate(result_entries):
            try:
                entry = archive.get_entry_by_path(entry_id)
                title = entry.title or "Untitled"

                # Get content snippet
                snippet = self._get_entry_snippet(entry)

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

        has_more = (offset + len(results)) < total_results
        pagination: Dict[str, Any] = {
            "has_more": has_more,
            "showing_start": offset + 1,
            "showing_end": offset + len(results),
        }
        if has_more:
            next_cursor = _zim_ops_mod.PaginationCursor.create_next_cursor(
                offset, limit, total_results, query
            )
            # Partial-page case: has_more can be True (offset+len(results)
            # < total_results) while offset+limit >= total_results, in which
            # case create_next_cursor returns None. Omit the cursor key in
            # that case — the caller falls back to the offset hint.
            if next_cursor is not None:
                pagination["next_cursor"] = next_cursor

        return (
            {
                "query": query,
                "total_results": total_results,
                "offset": offset,
                "limit": limit,
                "results": results,
                "pagination": pagination,
            },
            total_results,
        )

    def _format_search_text(self, payload: Dict[str, Any]) -> str:
        """Render a structured search payload as the legacy markdown text.

        Mirrors the original ``_perform_search`` output exactly so callers
        (and tests) that consume the rendered text keep working unchanged.
        """
        query = payload["query"]
        total_results = payload["total_results"]
        offset = payload["offset"]
        limit = payload["limit"]
        results = payload["results"]
        pagination = payload.get("pagination", {})

        if total_results == 0:
            return f'No search results found for "{query}"'

        if pagination.get("offset_exceeds_total"):
            return (
                f'Found {total_results} matches for "{query}", '
                f"but offset {offset} exceeds total results."
            )

        result_text = (
            f'Found {total_results} matches for "{query}", '
            f"showing {offset + 1}-{offset + len(results)}:\n\n"
        )

        for i, result in enumerate(results):
            result_text += f"## {offset + i + 1}. {result['title']}\n"
            result_text += f"Path: {result['path']}\n"
            result_text += f"Snippet: {result['snippet']}\n\n"

        result_text += "---\n"
        result_text += (
            f"**Pagination**: Showing {offset + 1}-{offset + len(results)} "
            f"of {total_results}\n"
        )

        has_more = pagination.get("has_more", False)
        if has_more:
            next_cursor = pagination.get("next_cursor")
            if next_cursor is not None:
                result_text += f"**Next cursor**: `{next_cursor}`\n"
                result_text += (
                    f"**Hint**: pass `cursor={next_cursor}` "
                    f"or `offset={offset + limit}` to get the next page\n"
                )
            else:
                result_text += (
                    f"**Hint**: pass `offset={offset + len(results)}` "
                    f"to get the next page\n"
                )
        else:
            result_text += "**End of results**\n"

        return result_text

    def search_with_filters(
        self,
        zim_file_path: str,
        query: str,
        namespace: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> str:
        """Search within ZIM file content with namespace and content type filters.

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
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = (
            f"search_filtered:{validated_path}:{query}:{namespace}:"
            f"{content_type}:{limit}:{offset}"
        )
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached filtered search results for query: {query}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                result, total_filtered = self._perform_filtered_search(
                    archive, query, namespace, content_type, limit, offset
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

    def _perform_filtered_search(
        self,
        archive: Archive,
        query: str,
        namespace: Optional[str],
        content_type: Optional[str],
        limit: int,
        offset: int,
    ) -> Tuple[str, int]:
        """Perform filtered search operation.

        Returns:
            (result_text, total_filtered) — caller uses total_filtered to decide
            whether the response is safe to cache. ``total_filtered`` is 0 for
            both the unfiltered no-results and the post-filter no-matches cases.
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
            return f'No search results found for "{query}"', 0

        page, scan = self._scan_filtered_search(
            archive, search, total_results, namespace, content_type, limit, offset
        )

        filter_text = _format_filter_text(namespace, content_type)
        if scan.filtered_count == 0:
            return f'No filtered matches for "{query}"{filter_text}', 0
        if offset >= scan.filtered_count:
            return (
                f'Found {scan.filtered_count} filtered matches for "{query}"'
                f"{filter_text}, but offset {offset} exceeds total results."
            ), scan.filtered_count

        results = self._build_filtered_results(page, content_type, offset)
        result_text = _format_filtered_response(
            query, filter_text, results, scan, total_results, offset, limit
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
        # When namespace-only filtering is active (no content_type), the
        # entry namespace is derivable from the path string without an
        # archive lookup, so skipped entries cost nothing.
        need_entry_for_filter = bool(content_type)

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
                if namespace and not self._matches_cheap_namespace(entry_id, namespace):
                    continue
                if not need_entry_for_filter and filtered_count < offset:
                    filtered_count += 1
                    continue

                materialised = self._materialise_filtered_entry(
                    archive, entry_id, namespace, content_type
                )
                if materialised is None:
                    continue

                filtered_count += 1
                if filtered_count > offset and len(page) < limit:
                    page.append(materialised)
                    if len(page) >= limit:
                        break

        page_filled_short_of_scan = (
            len(page) >= limit and scanned < total_results and not scan_cap_hit
        )
        return page, _FilteredScanState(
            filtered_count=filtered_count,
            scanned=scanned,
            scan_cap_hit=scan_cap_hit,
            total_filtered_is_lower_bound=page_filled_short_of_scan,
        )

    def _matches_cheap_namespace(self, entry_id: str, namespace: str) -> bool:
        """Cheap namespace filter from the path string (no archive lookup).

        ``entry_id`` is the path libzim returned; resolved ``entry.path`` may
        differ across redirects, but namespace agreement holds in practice
        (redirects within the same namespace are the common case; for
        cross-namespace redirects we accept the resolved entry's namespace
        when we materialise).
        """
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
    ) -> Optional[Tuple[str, Any, str, str]]:
        """Resolve an entry and apply the post-redirect namespace + mime filters."""
        try:
            entry = archive.get_entry_by_path(entry_id)
        except Exception as e:
            logger.warning(f"Error filtering search result {entry_id}: {e}")
            return None

        # Use the resolved ``entry.path`` for the response so the namespace
        # shown matches what libzim actually surfaces (handles
        # cross-namespace redirects).
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
    ) -> List[Dict[str, Any]]:
        """Format each materialised entry into the response result dict."""
        results: List[Dict[str, Any]] = []
        for i, (entry_id, entry, entry_namespace, content_mime) in enumerate(page):
            try:
                title = entry.title or "Untitled"
                snippet = self._get_entry_snippet(entry)
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

    def get_search_suggestions(
        self, zim_file_path: str, partial_query: str, limit: int = 10
    ) -> str:
        """Get search suggestions and auto-complete for partial queries.

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
        # Validate parameters
        if limit < 1 or limit > 50:
            raise OpenZimMcpValidationError("Limit must be between 1 and 50")
        if not partial_query or len(partial_query.strip()) < 2:
            return json.dumps(
                {"suggestions": [], "message": "Query too short for suggestions"}
            )

        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = f"suggestions:{validated_path}:{partial_query}:{limit}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached suggestions for: {partial_query}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                result = self._generate_search_suggestions(
                    archive, partial_query, limit
                )

            # Parse result to get actual count for accurate logging and to
            # decide whether the response is worth caching. A cold-cache
            # request that hits before the libzim title index has warmed up
            # can return zero suggestions for a query that will produce
            # results moments later — caching that empty payload locks the
            # query into "no suggestions" for the full TTL.
            try:
                result_data = json.loads(result)
                actual_count = result_data.get(
                    "count", len(result_data.get("suggestions", []))
                )
            except (json.JSONDecodeError, TypeError):
                actual_count = "unknown"

            count_for_gate = actual_count if isinstance(actual_count, int) else 0
            if count_for_gate > 0:
                self.cache.set(cache_key, result)
            logger.info(f"Generated {actual_count} suggestions for: {partial_query}")
            return result

        except OpenZimMcpArchiveError:
            # Inner helper already raised a typed archive error with full
            # context. Don't re-wrap and double the message prefix.
            raise
        except Exception as e:
            logger.error(f"Suggestion generation failed for {partial_query}: {e}")
            raise OpenZimMcpArchiveError(f"Suggestion generation failed: {e}") from e

    def _generate_search_suggestions(  # NOSONAR(python:S3776)
        self, archive: Archive, partial_query: str, limit: int
    ) -> str:
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

        if suggestions:
            logger.info(f"Found {len(suggestions)} suggestions using search fallback")
            result = {
                "partial_query": partial_query,
                "suggestions": suggestions,
                "count": len(suggestions),
            }
            return json.dumps(result, indent=2, ensure_ascii=False)

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
                if (
                    path.startswith("M/")
                    or path.startswith("X/")
                    or path.startswith("-/")
                    or title.startswith("File:")
                    or title.startswith("Category:")
                    or title.startswith("Template:")
                ):
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

        result = {
            "partial_query": partial_query,
            "suggestions": suggestions[:limit],
            "count": len(suggestions[:limit]),
        }

        return json.dumps(result, indent=2, ensure_ascii=False)

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
                    if (
                        title.startswith("File:")
                        or title.startswith("Category:")
                        or title.startswith("Template:")
                        or title.startswith("User:")
                        or title.startswith("Wikipedia:")
                        or title.startswith("Help:")
                    ):
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

    def find_entry_by_title(
        self,
        zim_file_path: str,
        title: str,
        cross_file: bool = False,
        limit: int = 10,
    ) -> str:
        """Resolve a title or partial title to one or more entry paths.

        Implementation order:
          1. Direct path probe in C/ namespace for normalized title (fast path).
          2. libzim suggestion search (title-indexed) — primary fallback.
          3. Return ranked list with score.
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
            validated = self.path_validator.validate_path(zim_file_path)
            validated = self.path_validator.validate_zim_file(validated)
            files = [str(validated)]

        aggregate_results: List[Dict[str, Any]] = []
        fast_path_hit = False

        for file_path in files:
            try:
                with _zim_ops_mod.zim_archive(file_path) as archive:
                    # Fast path: C/<normalized_title>
                    normalized = title.replace(" ", "_")
                    candidate = f"C/{normalized}"
                    if archive.has_entry_by_path(candidate):
                        try:
                            entry = archive.get_entry_by_path(candidate)
                            aggregate_results.append(
                                {
                                    "path": entry.path,
                                    "title": entry.title or candidate,
                                    "score": 1.0,
                                    "zim_file": file_path,
                                }
                            )
                            fast_path_hit = True
                            if not cross_file:
                                break
                            continue
                        except Exception as e:
                            logger.debug(
                                f"find_entry_by_title fast-path read failed: {e}"
                            )

                    # Fallback: libzim suggestion search (title-indexed).
                    # Note: ``Archive.suggest()`` does not exist; the public
                    # API is ``SuggestionSearcher(archive).suggest(text)``.
                    try:
                        suggestion_search = _zim_ops_mod.SuggestionSearcher(
                            archive
                        ).suggest(title)
                        total = suggestion_search.getEstimatedMatches()
                        if total > 0:
                            for path in suggestion_search.getResults(0, limit):
                                try:
                                    entry = archive.get_entry_by_path(path)
                                    aggregate_results.append(
                                        {
                                            "path": entry.path,
                                            "title": entry.title or path,
                                            "score": 0.8,
                                            "zim_file": file_path,
                                        }
                                    )
                                except Exception as e:
                                    logger.debug(
                                        f"find_entry_by_title suggestion read "
                                        f"failed for {path}: {e}"
                                    )
                    except Exception as e:
                        if not cross_file:
                            raise
                        logger.debug(
                            f"find_entry_by_title suggest() failed for "
                            f"{file_path}: {e}"
                        )
            except Exception as e:
                if not cross_file:
                    raise
                logger.debug(f"find_entry_by_title: skipped {file_path}: {e}")

        return json.dumps(
            {
                "query": title,
                "results": aggregate_results[:limit],
                "fast_path_hit": fast_path_hit,
                "files_searched": len(files),
            },
            indent=2,
            ensure_ascii=False,
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
    ) -> Dict[str, Any]:
        """Structured variant of ``search_all``.

        Per-file results are real dicts (the structured payload from
        ``search_zim_file_data``) rather than markdown strings — fixing
        the triple-stringification of the legacy ``search_all`` (where
        the per-file ``result`` field was a markdown blob escaped inside
        the outer JSON string).

        Args:
            query: Search query
            limit_per_file: Maximum hits to return per ZIM file (1-50, default 5)

        Returns:
            Dict with per-file result groups and aggregate counts. Each
            ``per_file[].result`` is the structured search payload from
            ``search_zim_file_data`` — a dict, not a string.
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
        for file_info in files:
            path = file_info.get("path")
            if not path:
                continue
            try:
                payload = self.search_zim_file_data(path, query, limit_per_file, 0)
                per_file.append(
                    {
                        "zim_file_path": path,
                        "name": file_info.get("name"),
                        "result": payload,
                        "has_hits": payload.get("total_results", 0) > 0,
                    }
                )
            except Exception as e:
                logger.debug(f"search_all: skipped {path}: {e}")
                per_file.append(
                    {
                        "zim_file_path": path,
                        "name": file_info.get("name"),
                        "error": str(e),
                    }
                )

        return {
            "query": query,
            "files_searched": len(files),
            "files_with_hits": sum(1 for r in per_file if r.get("has_hits")),
            "files_searched_successfully": sum(1 for r in per_file if "result" in r),
            "files_failed": sum(1 for r in per_file if "error" in r),
            "per_file": per_file,
        }

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
        return json.dumps(
            self.search_all_data(query, limit_per_file),
            indent=2,
            ensure_ascii=False,
        )
