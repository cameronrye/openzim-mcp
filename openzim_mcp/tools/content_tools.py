"""Content retrieval tools for OpenZIM MCP server."""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

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
    async def get_zim_entries(
        entries: List[Dict[str, Any]],
        max_content_length: Optional[int] = None,
    ) -> str:
        """Fetch multiple ZIM entries in one call.

        Pairs naturally with HTTP transport, where round-trip cost matters.
        Up to 50 entries per batch. Each entry resolves independently —
        per-entry failures do not abort the batch. Different ``zim_file_path``
        values within one batch are allowed (multi-archive workflow).

        Args:
            entries: list of ``{"zim_file_path": "...", "entry_path": "..."}``
                dicts. Limit: 50 per batch.
            max_content_length: per-entry max content length.

        Returns:
            JSON string ``{"results": [...], "succeeded": N, "failed": N}``.
            Each result includes ``index``, ``success``, and either ``content``
            or ``error``.

        Notes:
            Rate limit is charged per entry, not per batch (anti-bypass).
        """
        batch_size = len(entries) if entries else 0
        try:
            # Charge rate-limit per entry to prevent batch bypass.
            try:
                for _ in entries or []:
                    server.rate_limiter.check_rate_limit("get_zim_entries")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="batch get entries",
                    error=e,
                    context=f"Batch size: {batch_size}",
                )

            # Sanitize per-entry inputs before delegating. Each entry's paths
            # go through the same input-limit checks as the singular tool.
            sanitized: List[Dict[str, Any]] = []
            for entry in entries or []:
                if not isinstance(entry, dict):
                    sanitized.append({"zim_file_path": "", "entry_path": ""})
                    continue
                sanitized.append(
                    {
                        "zim_file_path": sanitize_input(
                            str(entry.get("zim_file_path", "")),
                            INPUT_LIMIT_FILE_PATH,
                        ),
                        "entry_path": sanitize_input(
                            str(entry.get("entry_path", "")),
                            INPUT_LIMIT_ENTRY_PATH,
                        ),
                    }
                )

            return await server.async_zim_operations.get_entries(
                sanitized, max_content_length
            )

        except Exception as e:
            logger.error(f"Error in get_zim_entries: {e}")
            return server._create_enhanced_error_message(
                operation="batch get entries",
                error=e,
                context=f"Batch size: {batch_size}",
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
