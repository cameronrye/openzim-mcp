"""Content retrieval tools for OpenZIM MCP server."""

import logging
from typing import TYPE_CHECKING, Optional

from ..constants import INPUT_LIMIT_ENTRY_PATH, INPUT_LIMIT_FILE_PATH
from ..exceptions import OpenZimMcpRateLimitError
from ..security import sanitize_input

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


def register_content_tools(server: "OpenZimMcpServer") -> None:
    """Register content retrieval tools.

    Args:
        server: The OpenZimMcpServer instance to register tools on
    """

    @server.mcp.tool()
    async def get_zim_entry(
        zim_file_path: str,
        entry_path: str,
        max_content_length: Optional[int] = None,
    ) -> str:
        """Get detailed content of a specific entry in a ZIM file.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'A/Some_Article'
            max_content_length: Maximum length of content to return

        Returns:
            Entry content text
        """
        try:
            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("get_entry")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="get ZIM entry",
                    error=e,
                    context=f"Entry: {entry_path}",
                )

            # Sanitize inputs
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)

            # Validate parameters
            if max_content_length is not None and max_content_length < 1000:
                return (
                    "**Parameter Validation Error**\n\n"
                    f"**Issue**: max_content_length must be at least 1000 characters "
                    f"(provided: {max_content_length})\n\n"
                    "**Troubleshooting**: Increase the max_content_length parameter "
                    "or omit it to use the default.\n"
                    "**Example**: Use `max_content_length=5000` for longer content "
                    "or omit the parameter for default length."
                )

            # Use async operations to avoid blocking
            return await server.async_zim_operations.get_zim_entry(
                zim_file_path, entry_path, max_content_length
            )

        except Exception as e:
            logger.error(f"Error getting ZIM entry: {e}")
            return server._create_enhanced_error_message(
                operation="get ZIM entry",
                error=e,
                context=f"File: {zim_file_path}, Entry: {entry_path}",
            )
