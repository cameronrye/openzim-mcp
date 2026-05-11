"""Navigation and browsing tools for OpenZIM MCP server."""

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

from ..constants import (
    INPUT_LIMIT_CONTENT_TYPE,
    INPUT_LIMIT_FILE_PATH,
    INPUT_LIMIT_NAMESPACE,
    INPUT_LIMIT_PARTIAL_QUERY,
    INPUT_LIMIT_QUERY,
)
from ..exceptions import OpenZimMcpRateLimitError
from ..responses import ToolErrorPayload, tool_error
from ..security import sanitize_input
from ..tool_schemas import (
    BrowseNamespaceResponse,
    SearchSuggestionsResponse,
    SearchWithFiltersResponse,
    WalkNamespaceResponse,
)

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


def register_navigation_tools(server: "OpenZimMcpServer") -> None:
    """Register navigation and browsing tools."""
    _register_browse_namespace(server)
    _register_walk_namespace(server)
    _register_search_with_filters(server)
    _register_get_search_suggestions(server)


def _register_browse_namespace(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def browse_namespace(
        zim_file_path: str,
        namespace: str,
        limit: int = 50,
        offset: int = 0,
        cursor: Optional[str] = None,
    ) -> Union[BrowseNamespaceResponse, ToolErrorPayload]:
        """Browse entries in a specific namespace with pagination.

        **Sampling caveat (Op3).** On large archives where libzim's
        per-namespace index isn't authoritative, ``browse_namespace``
        returns a sampled view rather than the full namespace listing.
        Two response fields flag this:

        - ``sampling_based: true`` — the discovery method walked a
          bounded sample rather than enumerating every entry.
        - ``page_info.total_is_lower_bound: true`` — ``total`` is the
          sampled count, not the true namespace size.

        When sampling is in play, this tool's ``done=True`` means "end
        of the sample" — NOT "end of the namespace." For exhaustive
        iteration over a sampled namespace, switch to ``walk_namespace``,
        which streams every entry without sampling. The compact-mode
        ``_meta.reason="sample_only"`` footer surfaces this hint
        automatically.

        Args:
            zim_file_path: Path to the ZIM file
            namespace: Namespace to browse (C, M, W, X, A, I for old; domains for new)
            limit: Maximum number of entries to return (1-200, default: 50)
            offset: Starting offset for pagination (default: 0)
            cursor: Opaque pagination token from a previous result's
                ``next_cursor`` field. When provided, overrides ``offset``,
                ``limit``, and ``namespace`` with the values encoded in the
                token (cursor wins on conflict per response-contract spec).

        Returns:
            ``BrowseNamespaceResponse``-shaped dict on success (Phase B
            contract: top-level ``results`` / ``next_cursor`` / ``total`` /
            ``done`` / ``page_info`` plus ``namespace`` / ``discovery_method``
            / ``sampling_based`` / ``results_may_be_incomplete`` extras);
            ``ToolErrorPayload`` envelope on failure.
        """
        cursor_ai: Optional[str] = None
        try:
            # Phase B: cursor wins on conflict per response-contract spec.
            if cursor is not None:
                from ..pagination import Cursor, CursorMismatchError

                try:
                    decoded = Cursor.decode(cursor, expected_tool="browse_namespace")
                except CursorMismatchError as e:
                    return tool_error(
                        operation="browse namespace",
                        message=str(e),
                        context="Tool: browse_namespace, cursor=<truncated>",
                    )
                except ValueError as e:
                    return tool_error(
                        operation="browse namespace",
                        message=f"Invalid pagination cursor: {e}",
                        context="Tool: browse_namespace",
                    )
                offset = decoded["s"]["o"]
                if "l" in decoded["s"]:
                    limit = decoded["s"]["l"]
                if "ns" in decoded["s"]:
                    namespace = decoded["s"]["ns"]
                cursor_ai = decoded["s"].get("ai")

            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("browse_namespace")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="browse namespace",
                    message=server._create_enhanced_error_message(
                        operation="browse namespace",
                        error=e,
                        context=f"Namespace: {namespace}",
                    ),
                    context=f"Namespace: {namespace}",
                )

            # Sanitize inputs
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            namespace = sanitize_input(
                namespace, INPUT_LIMIT_NAMESPACE
            )  # Increased to support new namespace scheme

            # Validate parameters
            if limit < 1 or limit > 200:
                return tool_error(
                    operation="browse namespace",
                    message=(
                        "**Parameter Validation Error**\n\n"
                        f"**Issue**: limit must be between 1 and 200 "
                        f"(provided: {limit})\n\n"
                        "**Troubleshooting**: Adjust the limit parameter to a "
                        "value within the valid range.\n"
                        "**Example**: Use `limit=50` for reasonable pagination."
                    ),
                    context=f"Namespace: {namespace}, Limit: {limit}",
                )
            if offset < 0:
                return tool_error(
                    operation="browse namespace",
                    message=(
                        "**Parameter Validation Error**\n\n"
                        f"**Issue**: offset must be non-negative "
                        f"(provided: {offset})\n\n"
                        "**Troubleshooting**: Use offset=0 to start from the "
                        "beginning, or a positive number to skip entries.\n"
                        "**Example**: Use `offset=50` to skip the first 50 entries."
                    ),
                    context=f"Namespace: {namespace}, Offset: {offset}",
                )

            # Use async operations
            return await server.async_zim_operations.browse_namespace_data(
                zim_file_path,
                namespace,
                limit,
                offset,
                cursor_archive_identity=cursor_ai,
            )

        except Exception as e:
            logger.error(f"Error browsing namespace: {e}")
            return tool_error(
                operation="browse namespace",
                message=server._create_enhanced_error_message(
                    operation="browse namespace",
                    error=e,
                    context=(
                        f"File: {zim_file_path}, Namespace: {namespace}, "
                        f"Limit: {limit}, Offset: {offset}"
                    ),
                ),
                context=(
                    f"File: {zim_file_path}, Namespace: {namespace}, "
                    f"Limit: {limit}, Offset: {offset}"
                ),
            )


def _register_walk_namespace(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def walk_namespace(
        zim_file_path: str,
        namespace: str,
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> Union[WalkNamespaceResponse, ToolErrorPayload]:
        """Iterate every entry in a namespace via deterministic cursor pagination.

        Unlike browse_namespace (which samples and may cap at 200 entries
        for large archives), walk_namespace scans the archive by entry ID.
        Pair the returned ``next_cursor`` with a follow-up call to walk
        the rest. ``done: true`` indicates iteration is complete.

        Use this when you need exhaustive enumeration of a namespace —
        e.g. to dump every M/* metadata entry, or to find an entry whose
        path doesn't follow common patterns.

        v2 BREAKING: ``cursor`` was previously an ``int`` entry id and is
        now an opaque ``str`` token. Pass ``None`` (or omit) on the first
        call; pass back the ``next_cursor`` value from a prior response
        to resume.

        Args:
            zim_file_path: Path to the ZIM file
            namespace: Namespace to walk (C, M, W, X, A, I, etc.)
            limit: Max entries per page (1-500, default: 200). When a
                ``cursor`` is supplied, the limit encoded in the cursor
                wins per response-contract spec.
            cursor: Opaque pagination token from a previous result's
                ``next_cursor`` field. ``None`` starts from the beginning.

        Returns:
            ``WalkNamespaceResponse``-shaped dict on success (Phase B
            contract: top-level ``results`` / ``next_cursor`` (opaque str)
            / ``total`` (always None — walk doesn't know the per-namespace
            total mid-scan) / ``done`` / ``page_info`` plus ``namespace``
            / ``scanned_count`` / ``scanned_through_id`` /
            ``archive_entry_count`` extras); ``ToolErrorPayload`` envelope
            on failure.
        """
        try:
            # Phase B: cursor wins on conflict per response-contract spec.
            cursor_state: Optional[Dict[str, Any]] = None
            if cursor is not None:
                from ..pagination import Cursor, CursorMismatchError

                try:
                    decoded = Cursor.decode(cursor, expected_tool="walk_namespace")
                except CursorMismatchError as e:
                    return tool_error(
                        operation="walk namespace",
                        message=str(e),
                        context="Tool: walk_namespace, cursor=<truncated>",
                    )
                except ValueError as e:
                    return tool_error(
                        operation="walk namespace",
                        message=f"Invalid pagination cursor: {e}",
                        context="Tool: walk_namespace",
                    )
                cursor_state = dict(decoded["s"])
                if "l" in cursor_state:
                    limit = cursor_state["l"]

            try:
                server.rate_limiter.check_rate_limit("browse_namespace")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="walk namespace",
                    message=server._create_enhanced_error_message(
                        operation="walk namespace",
                        error=e,
                        context=f"Namespace: {namespace}",
                    ),
                    context=f"Namespace: {namespace}",
                )

            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            namespace = sanitize_input(namespace, INPUT_LIMIT_NAMESPACE)

            # Validate parameters before any backend call. The docstring
            # promises ``limit: 1-500``; without this check, callers could
            # open the libzim Archive for arbitrarily oversized requests
            # before being rejected.
            if limit < 1 or limit > 500:
                return tool_error(
                    operation="walk namespace",
                    message=(
                        "**Parameter Validation Error**\n\n"
                        f"**Issue**: limit must be between 1 and 500 "
                        f"(provided: {limit})\n\n"
                        "**Troubleshooting**: Adjust the limit parameter to a "
                        "value within the valid range.\n"
                        "**Example**: Use `limit=200` for the default page size."
                    ),
                    context=f"Namespace: {namespace}, Limit: {limit}",
                )

            return await server.async_zim_operations.walk_namespace_data(
                zim_file_path,
                namespace,
                cursor_state=cursor_state,
                limit=limit,
            )

        except Exception as e:
            logger.error(f"Error in walk_namespace: {e}")
            return tool_error(
                operation="walk namespace",
                message=server._create_enhanced_error_message(
                    operation="walk namespace",
                    error=e,
                    context=(
                        f"File: {zim_file_path}, Namespace: {namespace}, "
                        f"Limit: {limit}"
                    ),
                ),
                context=(
                    f"File: {zim_file_path}, Namespace: {namespace}, " f"Limit: {limit}"
                ),
            )


def _register_search_with_filters(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def search_with_filters(
        zim_file_path: str,
        query: Optional[str] = None,
        namespace: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        cursor: Optional[str] = None,
    ) -> Union[SearchWithFiltersResponse, ToolErrorPayload]:
        """Search within ZIM file content with namespace and content type filters.

        Args:
            zim_file_path: Path to the ZIM file
            query: Search query term. Required unless ``cursor`` is provided,
                in which case the query encoded in the cursor is reused.
            namespace: Optional namespace filter (C, M, W, X, etc.)
            content_type: Optional content type filter (text/html, text/plain, etc.)
            limit: Maximum number of results to return (default from config)
            offset: Result starting offset (for pagination)
            cursor: Opaque pagination token from a previous result's
                ``next_cursor`` field. When provided, overrides ``offset``,
                ``limit``, ``query``, ``namespace``, and ``content_type``
                with the values encoded in the token (cursor wins on
                conflict per response-contract spec).

        Returns:
            ``SearchWithFiltersResponse``-shaped dict on success (Phase B
            contract: top-level ``results`` / ``next_cursor`` / ``total`` /
            ``done`` / ``page_info`` plus ``query`` / ``namespace_filter``
            / ``content_type_filter`` extras); ``ToolErrorPayload``
            envelope on failure.
        """
        cursor_ai: Optional[str] = None
        try:
            # Phase B: cursor wins on conflict per response-contract spec.
            if cursor is not None:
                from ..pagination import Cursor, CursorMismatchError

                try:
                    decoded = Cursor.decode(cursor, expected_tool="search_with_filters")
                except CursorMismatchError as e:
                    return tool_error(
                        operation="search with filters",
                        message=str(e),
                        context="Tool: search_with_filters, cursor=<truncated>",
                    )
                except ValueError as e:
                    return tool_error(
                        operation="search with filters",
                        message=f"Invalid pagination cursor: {e}",
                        context="Tool: search_with_filters",
                    )
                offset = decoded["s"]["o"]
                if "l" in decoded["s"]:
                    limit = decoded["s"]["l"]
                if "q" in decoded["s"]:
                    query = decoded["s"]["q"]
                if "ns" in decoded["s"]:
                    namespace = decoded["s"]["ns"]
                if "ct" in decoded["s"]:
                    content_type = decoded["s"]["ct"]
                cursor_ai = decoded["s"].get("ai")

            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("search_with_filters")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="search with filters",
                    message=server._create_enhanced_error_message(
                        operation="filtered search",
                        error=e,
                        context=f"Query: '{query}'",
                    ),
                    context=f"Query: '{query}'",
                )

            # Sanitize file path eagerly; query is sanitized once resolved.
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)

            if not query:
                return tool_error(
                    operation="search with filters",
                    message=(
                        "`query` is required when `cursor` is not provided. "
                        "Pass a search term as `query`, or pass a `cursor` "
                        "from a prior search response to resume pagination."
                    ),
                    context="Tool: search_with_filters",
                )

            query = sanitize_input(query, INPUT_LIMIT_QUERY)
            if namespace:
                namespace = sanitize_input(
                    namespace, INPUT_LIMIT_NAMESPACE
                )  # Increased to support new namespace scheme
            if content_type:
                content_type = sanitize_input(content_type, INPUT_LIMIT_CONTENT_TYPE)

            # Validate parameters
            if limit is not None and (limit < 1 or limit > 100):
                return tool_error(
                    operation="search with filters",
                    message=(
                        "**Parameter Validation Error**\n\n"
                        f"**Issue**: limit must be between 1 and 100 "
                        f"(provided: {limit})\n\n"
                        "**Troubleshooting**: Adjust the limit parameter or "
                        "omit it to use the default.\n"
                        "**Example**: Use `limit=20` for a reasonable number."
                    ),
                    context=f"Query: '{query}', Limit: {limit}",
                )
            if offset < 0:
                return tool_error(
                    operation="search with filters",
                    message=(
                        "**Parameter Validation Error**\n\n"
                        f"**Issue**: offset must be non-negative "
                        f"(provided: {offset})\n\n"
                        "**Troubleshooting**: Use offset=0 to start from the "
                        "beginning, or a positive number for pagination.\n"
                        "**Example**: Use `offset=20` to get the next page."
                    ),
                    context=f"Query: '{query}', Offset: {offset}",
                )

            # Perform the filtered search using async operations
            # (structured payload).
            return await server.async_zim_operations.search_with_filters_data(
                zim_file_path,
                query,
                namespace,
                content_type,
                limit,
                offset,
                cursor_archive_identity=cursor_ai,
            )

        except Exception as e:
            logger.error(f"Error in filtered search: {e}")
            return tool_error(
                operation="search with filters",
                message=server._create_enhanced_error_message(
                    operation="filtered search",
                    error=e,
                    context=f"File: {zim_file_path}, Query: {query}",
                ),
                context=f"File: {zim_file_path}, Query: '{query}'",
            )


def _register_get_search_suggestions(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def get_search_suggestions(
        zim_file_path: str, partial_query: str, limit: int = 10
    ) -> Union[SearchSuggestionsResponse, ToolErrorPayload]:
        """Get search suggestions and auto-complete for partial queries.

        Args:
            zim_file_path: Path to the ZIM file
            partial_query: Partial search query. Must be at least 2 characters
                after stripping whitespace; shorter queries return an empty
                results list with the contract envelope (``done=True``,
                ``total=0``).
            limit: Maximum number of suggestions to return (1-50, default: 10)

        Returns:
            ``SearchSuggestionsResponse``-shaped dict on success (Phase B
            contract: top-level ``results`` / ``next_cursor`` / ``total`` /
            ``done`` / ``page_info`` plus ``partial_query`` extra);
            ``ToolErrorPayload`` envelope on failure. ``get_search_suggestions``
            is non-paginated: ``done`` is always ``True`` and ``next_cursor``
            is always ``None``.
        """
        try:
            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("suggestions")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="get search suggestions",
                    message=server._create_enhanced_error_message(
                        operation="get search suggestions",
                        error=e,
                        context=f"Query: '{partial_query}'",
                    ),
                    context=f"Query: '{partial_query}'",
                )

            # Sanitize inputs
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            partial_query = sanitize_input(partial_query, INPUT_LIMIT_PARTIAL_QUERY)

            # Validate parameters
            if limit < 1 or limit > 50:
                return tool_error(
                    operation="get search suggestions",
                    message=(
                        "**Parameter Validation Error**\n\n"
                        f"**Issue**: limit must be between 1 and 50 "
                        f"(provided: {limit})\n\n"
                        "**Troubleshooting**: Adjust the limit parameter to a "
                        "value within the valid range.\n"
                        "**Example**: Use `limit=10` for reasonable suggestions."
                    ),
                    context=f"Query: '{partial_query}', Limit: {limit}",
                )

            # Use async operations
            return await server.async_zim_operations.get_search_suggestions_data(
                zim_file_path, partial_query, limit
            )

        except Exception as e:
            logger.error(f"Error getting search suggestions: {e}")
            return tool_error(
                operation="get search suggestions",
                message=server._create_enhanced_error_message(
                    operation="get search suggestions",
                    error=e,
                    context=f"File: {zim_file_path}, Query: {partial_query}",
                ),
                context=f"File: {zim_file_path}, Query: {partial_query}",
            )
