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
        ) -> List[Dict[str, Any]]: ...

        # Provided by the content mixin; declared here for type checking.
        def _get_entry_snippet(self, entry: Any) -> str: ...

    def search_zim_file(
        self,
        zim_file_path: str,
        query: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> str:
        """Search within ZIM file content.

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
        if limit is None:
            limit = self.config.content.default_search_limit

        # Validate and resolve file path
        validated_path = self.path_validator.validate_path(zim_file_path)
        validated_path = self.path_validator.validate_zim_file(validated_path)

        # Check cache
        cache_key = f"search:{validated_path}:{query}:{limit}:{offset}"
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            logger.debug(f"Returning cached search results for query: {query}")
            return cached_result  # type: ignore[no-any-return]

        try:
            with _zim_ops_mod.zim_archive(validated_path) as archive:
                result, total_results = self._perform_search(
                    archive, query, limit, offset
                )

            # Don't cache zero-result responses: libzim's lazy index warm-up
            # can return 0 matches transiently, and a TTL-cached "no results"
            # would mask the index becoming ready.
            if total_results > 0:
                self.cache.set(cache_key, result)
            logger.debug(f"Search completed: query='{query}', results found")
            return result

        except Exception as e:
            logger.error(f"Search failed for {validated_path}: {e}")
            raise OpenZimMcpArchiveError(f"Search operation failed: {e}") from e

    def _perform_search(
        self, archive: Archive, query: str, limit: int, offset: int
    ) -> Tuple[str, int]:
        """Perform the actual search operation.

        Returns:
            (result_text, total_results) — caller uses total_results to decide
            whether the response is safe to cache.
        """
        # Create searcher and execute search
        query_obj = _zim_ops_mod.Query().set_query(query)
        searcher = _zim_ops_mod.Searcher(archive)
        search = searcher.search(query_obj)

        # Get total results
        total_results = search.getEstimatedMatches()

        if total_results == 0:
            return f'No search results found for "{query}"', 0

        # Guard against offset exceeding total results (would produce negative count)
        if offset >= total_results:
            return (
                f'Found {total_results} matches for "{query}", '
                f"but offset {offset} exceeds total results."
            ), total_results

        result_count = min(limit, total_results - offset)

        # Get search results
        result_entries = list(search.getResults(offset, result_count))

        # Collect search results
        results = []
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

        # Build result text with pagination info
        result_text = (
            f'Found {total_results} matches for "{query}", '
            f"showing {offset + 1}-{offset + len(results)}:\n\n"
        )

        for i, result in enumerate(results):
            result_text += f"## {offset + i + 1}. {result['title']}\n"
            result_text += f"Path: {result['path']}\n"
            result_text += f"Snippet: {result['snippet']}\n\n"

        # Add pagination information
        has_more = (offset + len(results)) < total_results
        result_text += "---\n"
        result_text += (
            f"**Pagination**: Showing {offset + 1}-{offset + len(results)} "
            f"of {total_results}\n"
        )

        if has_more:
            next_cursor = _zim_ops_mod.PaginationCursor.create_next_cursor(
                offset, limit, total_results, query
            )
            result_text += f"**Next cursor**: `{next_cursor}`\n"
            result_text += (
                f"**Hint**: pass `cursor={next_cursor}` "
                f"or `offset={offset + limit}` to get the next page\n"
            )
        else:
            result_text += "**End of results**\n"

        return result_text, total_results

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
            OpenZimMcpArchiveError: If search operation fails
        """
        if limit is None:
            limit = self.config.content.default_search_limit

        # Validate parameters
        if limit < 1 or limit > 100:
            raise OpenZimMcpArchiveError("Limit must be between 1 and 100")
        if offset < 0:
            raise OpenZimMcpArchiveError("Offset must be non-negative")
        # Validate namespace - single chars (old) or longer names (new format)
        if namespace and (len(namespace) > 50 or not namespace.strip()):
            raise OpenZimMcpArchiveError(
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
        # Create searcher and execute search
        query_obj = _zim_ops_mod.Query().set_query(query)
        searcher = _zim_ops_mod.Searcher(archive)
        search = searcher.search(query_obj)

        # Get total results
        total_results = search.getEstimatedMatches()

        if total_results == 0:
            return f'No search results found for "{query}"', 0

        # Stream raw results in batches and filter as we go, applying a
        # **skip counter** so the offset window is never materialised. The
        # old implementation accumulated ``offset + limit`` Entry objects in
        # memory and called ``get_entry_by_path`` for every candidate in
        # that window before slicing — pathological for high offsets
        # (e.g. ``offset=9900, limit=100`` materialised ~10k entries to
        # return 100). The new pattern only materialises entries we will
        # actually emit (the ``limit``-sized page after ``offset``).
        BATCH_SIZE = 500
        MAX_SCAN = 10000  # bound memory and CPU for pathological queries

        # Running count of entries that pass all filters. Used both to skip
        # the offset window and as the response's reported ``total_filtered``
        # — equivalent to the old ``len(filtered_results)``.
        filtered_count = 0
        # Page entries we will format and return. Capped at ``limit``.
        page: List[Tuple[str, Any, str, str]] = []
        scanned = 0
        scan_cap_hit = False

        # When namespace-only filtering is active (no content_type), we can
        # derive the entry namespace from the search-result path string
        # itself without paying for ``get_entry_by_path``. That eliminates
        # archive lookups for skipped entries entirely.
        need_entry_for_filter = bool(content_type)

        while scanned < total_results and len(page) < limit:
            if scanned >= MAX_SCAN:
                scan_cap_hit = True
                break
            batch_end = min(scanned + BATCH_SIZE, total_results, MAX_SCAN)
            batch = list(search.getResults(scanned, batch_end - scanned))
            scanned = batch_end
            if not batch:
                break

            for entry_id in batch:
                # Cheap namespace filter from the path string. ``entry_id``
                # is the path libzim returned; resolved entry.path may
                # differ across redirects, but namespace agreement holds in
                # practice (redirects within the same namespace are the
                # common case; for cross-namespace redirects we accept the
                # resolved entry's namespace below when we materialise).
                if "/" in entry_id:
                    cheap_namespace = entry_id.split("/", 1)[0]
                elif entry_id:
                    cheap_namespace = entry_id[0]
                else:
                    cheap_namespace = ""

                if namespace and cheap_namespace != namespace:
                    continue

                # If the only filter was namespace and we haven't reached
                # the offset yet, count without materialising the entry.
                if not need_entry_for_filter and filtered_count < offset:
                    filtered_count += 1
                    continue

                # Materialise the entry — needed either for the
                # content_type filter or because we're in the page window.
                try:
                    entry = archive.get_entry_by_path(entry_id)

                    # Use the resolved ``entry.path`` for the response so
                    # the namespace shown matches what libzim actually
                    # surfaces (handles cross-namespace redirects).
                    entry_namespace = ""
                    if "/" in entry.path:
                        entry_namespace = entry.path.split("/", 1)[0]
                    elif entry.path:
                        entry_namespace = entry.path[0]

                    # Re-check namespace after redirect resolution — a
                    # redirect may have crossed namespaces.
                    if namespace and entry_namespace != namespace:
                        continue

                    content_mime = ""
                    if content_type:
                        try:
                            content_mime = entry.get_item().mimetype or ""
                            if not content_mime.startswith(content_type):
                                continue
                        except Exception:  # nosec B112 - intentional filter skip
                            continue

                except Exception as e:
                    logger.warning(f"Error filtering search result {entry_id}: {e}")
                    continue

                # This entry passes all filters — count it and decide
                # whether to keep it on the response page.
                filtered_count += 1
                if filtered_count > offset and len(page) < limit:
                    page.append((entry_id, entry, entry_namespace, content_mime))
                    if len(page) >= limit:
                        # Got the full page; stop scanning.
                        break

        # Preserve the legacy "results_capped" semantics for the message —
        # true if there are more raw results we haven't scanned.
        results_capped = scan_cap_hit or scanned < total_results
        raw_fetch_limit = scanned  # what we actually scanned
        # ``total_filtered`` mirrors the old ``len(filtered_results)`` —
        # the count of filter-passing entries we observed. Callers cache
        # the response only when this is non-zero.
        total_filtered = filtered_count

        filters_applied = []
        if namespace:
            filters_applied.append(f"namespace={namespace}")
        if content_type:
            filters_applied.append(f"content_type={content_type}")
        filter_text = (
            f" (filters: {', '.join(filters_applied)})" if filters_applied else ""
        )

        if total_filtered == 0:
            return f'No filtered matches for "{query}"{filter_text}', 0

        if offset >= total_filtered:
            return (
                f'Found {total_filtered} filtered matches for "{query}"{filter_text}, '
                f"but offset {offset} exceeds total results."
            ), total_filtered

        # Collect detailed results, reusing the entries already fetched above.
        results = []
        for i, (entry_id, entry, entry_namespace, content_mime) in enumerate(page):
            try:
                title = entry.title or "Untitled"
                snippet = self._get_entry_snippet(entry)

                # When content_type wasn't filtered, mimetype hasn't been read yet.
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

        capped_note = (
            f" (filtered from first {raw_fetch_limit} of "
            f"~{total_results} unfiltered hits)"
            if results_capped
            else ""
        )
        result_text = (
            f'Found {total_filtered} filtered matches for "{query}"{filter_text}, '
            f"showing {offset + 1}-{offset + len(results)}{capped_note}:\n\n"
        )

        for i, result in enumerate(results):
            result_text += f"## {offset + i + 1}. {result['title']}\n"
            result_text += f"Path: {result['path']}\n"
            result_text += f"Namespace: {result['namespace']}\n"
            result_text += f"Content Type: {result['content_type']}\n"
            result_text += f"Snippet: {result['snippet']}\n\n"

        # Pagination footer — mirrors _perform_search so callers have a
        # consistent way to detect and navigate additional pages.
        has_more = (offset + len(results)) < total_filtered
        result_text += "---\n"
        result_text += (
            f"**Pagination**: Showing {offset + 1}-{offset + len(results)} "
            f"of {total_filtered}\n"
        )
        if has_more:
            next_cursor = _zim_ops_mod.PaginationCursor.create_next_cursor(
                offset, limit, total_filtered, query
            )
            result_text += f"**Next cursor**: `{next_cursor}`\n"
            result_text += (
                f"**Hint**: Use offset={offset + limit} to get the next page\n"
            )
        else:
            result_text += "**End of results**\n"

        return result_text, total_filtered

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
            OpenZimMcpArchiveError: If suggestion generation fails
        """
        # Validate parameters
        if limit < 1 or limit > 50:
            raise OpenZimMcpArchiveError("Limit must be between 1 and 50")
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

        except Exception as e:
            logger.error(f"Suggestion generation failed for {partial_query}: {e}")
            raise OpenZimMcpArchiveError(f"Suggestion generation failed: {e}") from e

    def _generate_search_suggestions(
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

    def _get_suggestions_from_search(
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
            return (
                "**Parameter Validation Error**\n\n"
                f"**Issue**: limit must be between 1 and 50 (provided: {limit})"
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
        # Extract potential search terms from the path
        search_terms = self._extract_search_terms_from_path(entry_path)

        # Hoist Searcher construction out of the loop. Each ``Searcher(archive)``
        # opens the archive's Xapian DB; building a fresh one per fallback term
        # multiplied that cost by up to 5x.
        # Re-import to honour test patches against ``libzim.search.Searcher``.
        # Tests for this method historically patched the upstream libzim
        # symbols rather than the ``zim_operations`` re-export, and the
        # original implementation had a function-local import that picked
        # up those patches.
        from libzim.search import (  # type: ignore[import-untyped]
            Query,
            Searcher,
        )

        try:
            searcher = Searcher(archive)
        except Exception as e:
            logger.debug(f"Searcher initialization failed: {e}")
            return None

        for search_term in search_terms:
            if len(search_term) < 2:  # Skip very short terms
                continue

            try:
                logger.debug(f"Searching for entry with term: '{search_term}'")
                query_obj = Query().set_query(search_term)
                search = searcher.search(query_obj)

                total_results = search.getEstimatedMatches()
                if total_results == 0:
                    continue

                # Check first few results for exact or close matches
                max_results = min(total_results, 10)  # Limit search for performance
                result_entries = list(search.getResults(0, max_results))

                for result_path in result_entries:
                    # Check if this result is a good match for our requested path
                    result_path_str = str(result_path)
                    if self._is_path_match(entry_path, result_path_str):
                        logger.debug(f"Found matching entry: {result_path_str}")
                        return result_path_str

            except Exception as e:
                logger.debug(f"Search failed for term '{search_term}': {e}")
                continue

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

    def search_all(
        self,
        query: str,
        limit_per_file: int = 5,
    ) -> str:
        """Search every ZIM file in allowed directories and return merged results.

        Useful when the model doesn't know which ZIM file holds the
        information it needs. Skips files that can't be searched (corrupt,
        no full-text index) without aborting the rest.

        Args:
            query: Search query
            limit_per_file: Maximum hits to return per ZIM file (1–50, default 5)

        Returns:
            JSON with per-file result groups and a flat ``hits`` list sorted
            by file then rank
        """
        if not query or not query.strip():
            raise OpenZimMcpValidationError(
                "Input is empty or contains only whitespace/control characters"
            )
        if limit_per_file < 1 or limit_per_file > 50:
            return (
                "**Parameter Validation Error**\n\n"
                f"**Issue**: limit_per_file must be between 1 and 50 "
                f"(provided: {limit_per_file})"
            )

        files = self.list_zim_files_data()
        per_file: List[Dict[str, Any]] = []
        for file_info in files:
            path = file_info.get("path")
            if not path:
                continue
            try:
                result_text = self.search_zim_file(path, query, limit_per_file, 0)
                # Real result text begins with "Found N matches..." while
                # empty results begin with "No search results found...". We
                # can't filter on `**` because real search snippets contain
                # bold markdown for emphasis. Match on the leading prefix.
                stripped = result_text.lstrip()
                has_hits = stripped.startswith("Found ")
                per_file.append(
                    {
                        "zim_file_path": path,
                        "name": file_info.get("name"),
                        "result": result_text,
                        "has_hits": has_hits,
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

        return json.dumps(
            {
                "query": query,
                "files_searched": len(files),
                "files_with_hits": sum(1 for r in per_file if r.get("has_hits")),
                "files_searched_successfully": sum(
                    1 for r in per_file if "result" in r
                ),
                "files_failed": sum(1 for r in per_file if "error" in r),
                "per_file": per_file,
            },
            indent=2,
            ensure_ascii=False,
        )
