"""Navigation and browsing tools for OpenZIM MCP server."""

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, cast

from ..constants import (
    INPUT_LIMIT_CONTENT_TYPE,
    INPUT_LIMIT_FILE_PATH,
    INPUT_LIMIT_NAMESPACE,
    INPUT_LIMIT_PARTIAL_QUERY,
    INPUT_LIMIT_QUERY,
)
from ..exceptions import OpenZimMcpRateLimitError
from ..responses import tool_error
from ..security import sanitize_input

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
    ) -> Dict[str, Any]:
        """Browse entries in a specific namespace with pagination.

        Args:
            zim_file_path: Path to the ZIM file
            namespace: Namespace to browse (C, M, W, X, A, I for old; domains for new)
            limit: Maximum number of entries to return (1-200, default: 50)
            offset: Starting offset for pagination (default: 0)

        Returns:
            Dict with keys: namespace, total_in_namespace, offset, limit,
            returned_count, has_more, next_cursor, entries, sampling_based,
            discovery_method, is_total_authoritative, results_may_be_incomplete.
            On failure, returns a ``{"error": True, ...}`` envelope (see
            ``responses.tool_error``).
        """
        try:
            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("browse_namespace")
            except OpenZimMcpRateLimitError as e:
                return cast(
                    Dict[str, Any],
                    tool_error(
                        operation="browse namespace",
                        message=server._create_enhanced_error_message(
                            operation="browse namespace",
                            error=e,
                            context=f"Namespace: {namespace}",
                        ),
                        context=f"Namespace: {namespace}",
                    ),
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
                zim_file_path, namespace, limit, offset
            )

        except Exception as e:
            logger.error(f"Error browsing namespace: {e}")
            return cast(
                Dict[str, Any],
                tool_error(
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
                ),
            )


def _register_walk_namespace(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def walk_namespace(
        zim_file_path: str,
        namespace: str,
        cursor: int = 0,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Iterate every entry in a namespace via deterministic cursor pagination.

        Unlike browse_namespace (which samples and may cap at 200 entries
        for large archives), walk_namespace scans the archive by entry ID
        from `cursor` onward. Pair the returned `next_cursor` with a
        follow-up call to walk the rest. `done: true` indicates iteration
        is complete.

        Use this when you need exhaustive enumeration of a namespace —
        e.g. to dump every M/* metadata entry, or to find an entry whose
        path doesn't follow common patterns.

        Args:
            zim_file_path: Path to the ZIM file
            namespace: Namespace to walk (C, M, W, X, A, I, etc.)
            cursor: Entry ID to resume from (default: 0)
            limit: Max entries per page (1-500, default: 200)

        Returns:
            Dict with keys: namespace, cursor, limit, returned_count,
            scanned_count, next_cursor, done, scanned_through_id,
            total_entries, entries. On failure, returns a
            ``{"error": True, ...}`` envelope (see ``responses.tool_error``).
        """
        try:
            try:
                server.rate_limiter.check_rate_limit("browse_namespace")
            except OpenZimMcpRateLimitError as e:
                return cast(
                    Dict[str, Any],
                    tool_error(
                        operation="walk namespace",
                        message=server._create_enhanced_error_message(
                            operation="walk namespace",
                            error=e,
                            context=f"Namespace: {namespace}",
                        ),
                        context=f"Namespace: {namespace}",
                    ),
                )

            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            namespace = sanitize_input(namespace, INPUT_LIMIT_NAMESPACE)

            # Validate parameters before any backend call. The docstring
            # promises ``limit: 1-500`` and a non-negative ``cursor``;
            # without this check, callers could open the libzim Archive
            # for arbitrarily oversized requests before being rejected.
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
            if cursor < 0:
                return tool_error(
                    operation="walk namespace",
                    message=(
                        "**Parameter Validation Error**\n\n"
                        f"**Issue**: cursor must be non-negative "
                        f"(provided: {cursor})\n\n"
                        "**Troubleshooting**: Use cursor=0 to start, or pass the "
                        "`next_cursor` value returned by a previous call.\n"
                        "**Example**: `cursor=0` on the first call."
                    ),
                    context=f"Namespace: {namespace}, Cursor: {cursor}",
                )

            return await server.async_zim_operations.walk_namespace_data(
                zim_file_path, namespace, cursor, limit
            )

        except Exception as e:
            logger.error(f"Error in walk_namespace: {e}")
            return cast(
                Dict[str, Any],
                tool_error(
                    operation="walk namespace",
                    message=server._create_enhanced_error_message(
                        operation="walk namespace",
                        error=e,
                        context=(
                            f"File: {zim_file_path}, Namespace: {namespace}, "
                            f"Cursor: {cursor}, Limit: {limit}"
                        ),
                    ),
                    context=(
                        f"File: {zim_file_path}, Namespace: {namespace}, "
                        f"Cursor: {cursor}, Limit: {limit}"
                    ),
                ),
            )


def _register_search_with_filters(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def search_with_filters(
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
            limit: Maximum number of results to return (default from config)
            offset: Result starting offset (for pagination)

        Returns:
            Search result text
        """
        try:
            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("search_with_filters")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="filtered search",
                    error=e,
                    context=f"Query: '{query}'",
                )

            # Sanitize inputs
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            query = sanitize_input(query, INPUT_LIMIT_QUERY)
            if namespace:
                namespace = sanitize_input(
                    namespace, INPUT_LIMIT_NAMESPACE
                )  # Increased to support new namespace scheme
            if content_type:
                content_type = sanitize_input(content_type, INPUT_LIMIT_CONTENT_TYPE)

            # Validate parameters
            if limit is not None and (limit < 1 or limit > 100):
                return (
                    "**Parameter Validation Error**\n\n"
                    f"**Issue**: limit must be between 1 and 100 "
                    f"(provided: {limit})\n\n"
                    "**Troubleshooting**: Adjust the limit parameter or "
                    "omit it to use the default.\n"
                    "**Example**: Use `limit=20` for a reasonable number."
                )
            if offset < 0:
                return (
                    "**Parameter Validation Error**\n\n"
                    f"**Issue**: offset must be non-negative (provided: {offset})\n\n"
                    "**Troubleshooting**: Use offset=0 to start from the beginning, "
                    "or a positive number for pagination.\n"
                    "**Example**: Use `offset=20` to get the next page of results."
                )

            # Perform the filtered search using async operations
            return await server.async_zim_operations.search_with_filters(
                zim_file_path, query, namespace, content_type, limit, offset
            )

        except Exception as e:
            logger.error(f"Error in filtered search: {e}")
            return server._create_enhanced_error_message(
                operation="filtered search",
                error=e,
                context=f"File: {zim_file_path}, Query: {query}",
            )


def _register_get_search_suggestions(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def get_search_suggestions(
        zim_file_path: str, partial_query: str, limit: int = 10
    ) -> str:
        """Get search suggestions and auto-complete for partial queries.

        Args:
            zim_file_path: Path to the ZIM file
            partial_query: Partial search query
            limit: Maximum number of suggestions to return (1-50, default: 10)

        Returns:
            JSON string containing search suggestions
        """
        try:
            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("suggestions")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="get search suggestions",
                    error=e,
                    context=f"Query: '{partial_query}'",
                )

            # Sanitize inputs
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            partial_query = sanitize_input(partial_query, INPUT_LIMIT_PARTIAL_QUERY)

            # Validate parameters
            if limit < 1 or limit > 50:
                return (
                    "**Parameter Validation Error**\n\n"
                    f"**Issue**: limit must be between 1 and 50 "
                    f"(provided: {limit})\n\n"
                    "**Troubleshooting**: Adjust the limit parameter to a "
                    "value within the valid range.\n"
                    "**Example**: Use `limit=10` for reasonable suggestions."
                )

            # Use async operations
            return await server.async_zim_operations.get_search_suggestions(
                zim_file_path, partial_query, limit
            )

        except Exception as e:
            logger.error(f"Error getting search suggestions: {e}")
            return server._create_enhanced_error_message(
                operation="get search suggestions",
                error=e,
                context=f"File: {zim_file_path}, Query: {partial_query}",
            )
