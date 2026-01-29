"""
Metadata and namespace listing tools for OpenZIM MCP server.
"""

import logging
from typing import TYPE_CHECKING

from ..constants import INPUT_LIMIT_FILE_PATH
from ..exceptions import OpenZimMcpRateLimitError
from ..security import sanitize_input

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


def register_metadata_tools(server: "OpenZimMcpServer") -> None:
    """
    Register metadata and namespace listing tools.

    Args:
        server: The OpenZimMcpServer instance to register tools on
    """

    @server.mcp.tool()
    async def get_zim_metadata(zim_file_path: str) -> str:
        """Get ZIM file metadata from M namespace entries.

        Args:
            zim_file_path: Path to the ZIM file

        Returns:
            JSON string containing ZIM metadata
        """
        try:
            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("get_metadata")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="get ZIM metadata",
                    error=e,
                    context=f"File: {zim_file_path}",
                )

            # Sanitize inputs
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)

            # Use async operations
            return await server.async_zim_operations.get_zim_metadata(zim_file_path)

        except Exception as e:
            logger.error(f"Error getting ZIM metadata: {e}")
            return server._create_enhanced_error_message(
                operation="get ZIM metadata",
                error=e,
                context=f"File: {zim_file_path}",
            )

    @server.mcp.tool()
    async def get_main_page(zim_file_path: str) -> str:
        """Get the main page entry from W namespace.

        Args:
            zim_file_path: Path to the ZIM file

        Returns:
            Main page content or information about main page
        """
        try:
            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("get_entry")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="get main page",
                    error=e,
                    context=f"File: {zim_file_path}",
                )

            # Sanitize inputs
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)

            # Use async operations
            return await server.async_zim_operations.get_main_page(zim_file_path)

        except Exception as e:
            logger.error(f"Error getting main page: {e}")
            return server._create_enhanced_error_message(
                operation="get main page",
                error=e,
                context=f"File: {zim_file_path}",
            )

    @server.mcp.tool()
    async def list_namespaces(zim_file_path: str) -> str:
        """List available namespaces and their entry counts.

        Args:
            zim_file_path: Path to the ZIM file

        Returns:
            JSON string containing namespace information
        """
        try:
            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("get_metadata")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="list namespaces",
                    error=e,
                    context=f"File: {zim_file_path}",
                )

            # Sanitize inputs
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)

            # Use async operations
            return await server.async_zim_operations.list_namespaces(zim_file_path)

        except Exception as e:
            logger.error(f"Error listing namespaces: {e}")
            return server._create_enhanced_error_message(
                operation="list namespaces",
                error=e,
                context=f"File: {zim_file_path}",
            )
