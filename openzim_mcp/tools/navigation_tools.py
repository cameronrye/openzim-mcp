"""Navigation and browsing tools for OpenZIM MCP server."""

import logging
from typing import TYPE_CHECKING, Optional

from ..constants import (
    INPUT_LIMIT_CONTENT_TYPE,
    INPUT_LIMIT_FILE_PATH,
    INPUT_LIMIT_NAMESPACE,
    INPUT_LIMIT_PARTIAL_QUERY,
    INPUT_LIMIT_QUERY,
)
from ..exceptions import OpenZimMcpRateLimitError
from ..security import sanitize_input

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


def register_navigation_tools(server: "OpenZimMcpServer") -> None:
    """
    Register navigation and browsing tools.

    Args:
        server: The OpenZimMcpServer instance to register tools on
    """

    @server.mcp.tool()
    async def browse_namespace(
        zim_file_path: str,
        namespace: str,
        limit: int = 50,
        offset: int = 0,
    ) -> str:
        """Browse entries in a specific namespace with pagination.

        Args:
            zim_file_path: Path to the ZIM file
            namespace: Namespace to browse (C, M, W, X, A, I for old; domains for new)
            limit: Maximum number of entries to return (1-200, default: 50)
            offset: Starting offset for pagination (default: 0)

        Returns:
            JSON string containing namespace entries
        """
        try:
            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("browse_namespace")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="browse namespace",
                    error=e,
                    context=f"Namespace: {namespace}",
                )

            # Sanitize inputs
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            namespace = sanitize_input(
                namespace, INPUT_LIMIT_NAMESPACE
            )  # Increased to support new namespace scheme

            # Validate parameters
            if limit < 1 or limit > 200:
                return (
                    "**Parameter Validation Error**\n\n"
                    f"**Issue**: limit must be between 1 and 200 "
                    f"(provided: {limit})\n\n"
                    "**Troubleshooting**: Adjust the limit parameter to a "
                    "value within the valid range.\n"
                    "**Example**: Use `limit=50` for reasonable pagination."
                )
            if offset < 0:
                return (
                    "**Parameter Validation Error**\n\n"
                    f"**Issue**: offset must be non-negative (provided: {offset})\n\n"
                    "**Troubleshooting**: Use offset=0 to start from the beginning, "
                    "or a positive number to skip entries.\n"
                    "**Example**: Use `offset=50` to skip the first 50 entries."
                )

            # Use async operations
            return await server.async_zim_operations.browse_namespace(
                zim_file_path, namespace, limit, offset
            )

        except Exception as e:
            logger.error(f"Error browsing namespace: {e}")
            return server._create_enhanced_error_message(
                operation="browse namespace",
                error=e,
                context=(
                    f"File: {zim_file_path}, Namespace: {namespace}, "
                    f"Limit: {limit}, Offset: {offset}"
                ),
            )

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
            search_result = await server.async_zim_operations.search_with_filters(
                zim_file_path, query, namespace, content_type, limit, offset
            )

            # Add proactive conflict detection for filtered search operations
            return server._check_and_append_conflict_warnings(search_result)

        except Exception as e:
            logger.error(f"Error in filtered search: {e}")
            return server._create_enhanced_error_message(
                operation="filtered search",
                error=e,
                context=f"File: {zim_file_path}, Query: {query}",
            )

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
