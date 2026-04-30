"""Content retrieval tools for OpenZIM MCP server."""

import logging
from typing import TYPE_CHECKING, Optional

from ..constants import (
    INPUT_LIMIT_ENTRY_PATH,
    INPUT_LIMIT_FILE_PATH,
    INPUT_LIMIT_NAMESPACE,
)
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
        content_offset: int = 0,
    ) -> str:
        """Get detailed content of a specific entry in a ZIM file.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'A/Some_Article'
            max_content_length: Maximum length of content to return
            content_offset: Character offset to start reading from (default 0).
                Combine with max_content_length to page through long articles
                without re-fetching the prefix each time.

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
            if max_content_length is not None and max_content_length < 100:
                return (
                    "**Parameter Validation Error**\n\n"
                    f"**Issue**: max_content_length must be at least 100 characters "
                    f"(provided: {max_content_length})\n\n"
                    "**Troubleshooting**: Increase the max_content_length parameter "
                    "or omit it to use the default.\n"
                    "**Example**: Use `max_content_length=500` for a short preview, "
                    "`5000` for longer content, or omit for default."
                )

            if content_offset < 0:
                return (
                    "**Parameter Validation Error**\n\n"
                    f"**Issue**: content_offset must be non-negative "
                    f"(provided: {content_offset})\n\n"
                    "**Troubleshooting**: Use 0 to read from the start, or a "
                    "positive integer to skip that many leading characters."
                )

            # Use async operations to avoid blocking
            return await server.async_zim_operations.get_zim_entry(
                zim_file_path, entry_path, max_content_length, content_offset
            )

        except Exception as e:
            logger.error(f"Error getting ZIM entry: {e}")
            return server._create_enhanced_error_message(
                operation="get ZIM entry",
                error=e,
                context=f"File: {zim_file_path}, Entry: {entry_path}",
            )

    @server.mcp.tool()
    async def get_random_entry(zim_file_path: str, namespace: str = "C") -> str:
        """Return one random entry from a ZIM file.

        Useful for exploration — pair with /explore prompt or call directly
        when sampling content. Default namespace 'C' returns articles. Pass
        namespace='' to accept any namespace.

        Args:
            zim_file_path: Path to the ZIM file
            namespace: Constrain to this namespace (default 'C' for articles)

        Returns:
            JSON with path, title, namespace, preview (200-char snippet)
        """
        try:
            try:
                server.rate_limiter.check_rate_limit("get_random_entry")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="get random entry",
                    error=e,
                    context=f"Namespace: {namespace}",
                )

            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            namespace = sanitize_input(namespace, INPUT_LIMIT_NAMESPACE)

            return await server.async_zim_operations.get_random_entry(
                zim_file_path, namespace
            )

        except Exception as e:
            logger.error(f"Error in get_random_entry: {e}")
            return server._create_enhanced_error_message(
                operation="get random entry",
                error=e,
                context=f"File: {zim_file_path}, Namespace: {namespace}",
            )
