"""File listing tools for OpenZIM MCP server."""

import logging
from typing import TYPE_CHECKING

from ..constants import INPUT_LIMIT_QUERY
from ..exceptions import OpenZimMcpRateLimitError
from ..security import sanitize_input

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


def register_file_tools(server: "OpenZimMcpServer") -> None:
    """
    Register file listing tools.

    Args:
        server: The OpenZimMcpServer instance to register tools on
    """

    @server.mcp.tool()
    async def list_zim_files(name_filter: str = "") -> str:
        """List all ZIM files in allowed directories.

        Args:
            name_filter: Optional case-insensitive substring; only files whose
                filename contains it are returned. Use this to narrow large
                listings (e.g. "wikipedia", "nginx"). Empty string lists all.

        Returns:
            JSON string containing the list of ZIM files.
        """
        try:
            try:
                server.rate_limiter.check_rate_limit("default")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="list ZIM files",
                    error=e,
                    context="Listing available ZIM files",
                )

            # Strip control characters and cap length, matching the
            # input-validation pattern every other tool applies. The
            # backend uses ``name_filter`` as a substring match; an
            # un-sanitized value carrying control characters would land
            # in logs verbatim and bypass the consistency every other
            # tool input enjoys.
            name_filter = sanitize_input(
                name_filter, INPUT_LIMIT_QUERY, allow_empty=True
            )

            return await server.async_zim_operations.list_zim_files(
                name_filter=name_filter
            )

        except Exception as e:
            logger.error(f"Error listing ZIM files: {e}")
            return server._create_enhanced_error_message(
                operation="list ZIM files",
                error=e,
                context="Scanning allowed directories for ZIM files",
            )
