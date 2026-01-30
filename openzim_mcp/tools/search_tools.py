"""Search tools for OpenZIM MCP server."""

import logging
from typing import TYPE_CHECKING, Optional

from ..constants import INPUT_LIMIT_FILE_PATH, INPUT_LIMIT_QUERY
from ..exceptions import OpenZimMcpRateLimitError
from ..security import sanitize_input

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


def register_search_tools(server: "OpenZimMcpServer") -> None:
    """
    Register search-related tools.

    Args:
        server: The OpenZimMcpServer instance to register tools on
    """

    @server.mcp.tool()
    async def search_zim_file(
        zim_file_path: str,
        query: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> str:
        """Search within ZIM file content.

        Args:
            zim_file_path: Path to the ZIM file
            query: Search query term
            limit: Maximum number of results to return (default from config)
            offset: Result starting offset (for pagination)

        Returns:
            Search result text
        """
        try:
            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("search")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="search ZIM file",
                    error=e,
                    context=f"Query: '{query}'",
                )

            # Sanitize inputs
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            query = sanitize_input(query, INPUT_LIMIT_QUERY)

            # Validate parameters
            if limit is not None and (limit < 1 or limit > 100):
                return (
                    "**Parameter Validation Error**\n\n"
                    f"**Issue**: Search limit must be between 1 and 100 "
                    f"(provided: {limit})\n\n"
                    "**Troubleshooting**: Adjust the limit parameter to be "
                    "within the valid range.\n"
                    "**Example**: Use `limit=10` for 10 results or "
                    "`limit=50` for more results."
                )

            if offset < 0:
                return (
                    "**Parameter Validation Error**\n\n"
                    f"**Issue**: Offset must be non-negative (provided: {offset})\n\n"
                    "**Troubleshooting**: Use `offset=0` to start from the "
                    "beginning, or a positive number to skip results.\n"
                    "**Example**: Use `offset=0` for first page, "
                    "`offset=10` for second page with limit=10."
                )

            # Perform the search using async operations
            search_result = await server.async_zim_operations.search_zim_file(
                zim_file_path, query, limit, offset
            )

            # Add proactive conflict detection for search operations
            return server._check_and_append_conflict_warnings(search_result)

        except Exception as e:
            logger.error(f"Error searching ZIM file: {e}")
            return server._create_enhanced_error_message(
                operation="search ZIM file",
                error=e,
                context=f"File: {zim_file_path}, Query: '{query}'",
            )
