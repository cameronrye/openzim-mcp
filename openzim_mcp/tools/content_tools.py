"""Content retrieval tools for OpenZIM MCP server."""

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..constants import (
    INPUT_LIMIT_ENTRY_PATH,
    INPUT_LIMIT_FILE_PATH,
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
        entries: List[Any],
        zim_file_path: Optional[str] = None,
        max_content_length: Optional[int] = None,
    ) -> str:
        """Fetch multiple ZIM entries in one call.

        Pairs naturally with HTTP transport, where round-trip cost matters.
        Up to 50 entries per batch. Each entry resolves independently —
        per-entry failures do not abort the batch.

        Two accepted shapes for ``entries``:

        1. **List of strings** — entry paths in ``zim_file_path`` (required).
           Example: ``entries=["A/Foo", "A/Bar"], zim_file_path="/path/x.zim"``
        2. **List of dicts** — ``{"zim_file_path": "...", "entry_path": "..."}``
           per entry. Use this when batching across archives. ``zim_file_path``
           kwarg becomes the default for any dict that omits its own.

        Args:
            entries: list of entry paths (strings) or
                ``{zim_file_path, entry_path}`` dicts. Limit: 50 per batch.
            zim_file_path: default archive path; required if ``entries`` are
                bare strings, optional when each dict carries its own.
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
            # Validate batch size BEFORE charging the per-entry rate limit:
            # otherwise a 50_000-entry oversized batch would burn 50_000
            # rate-limit slots before being rejected, effectively flooding
            # the rate counter for the rejecting client.
            from ..constants import MAX_BATCH_SIZE
            from ..exceptions import OpenZimMcpValidationError

            if batch_size == 0:
                raise OpenZimMcpValidationError("entries list cannot be empty")
            if batch_size > MAX_BATCH_SIZE:
                raise OpenZimMcpValidationError(
                    f"batch size {batch_size} exceeds limit {MAX_BATCH_SIZE}; "
                    "split into multiple batches"
                )

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

            # Normalise each entry into a {zim_file_path, entry_path} dict,
            # accepting either bare strings or dicts. The kwarg-level
            # `zim_file_path` is the default for string entries and dicts that
            # omit `zim_file_path`. Empty/invalid entries pass through as
            # blank pairs so per-entry failures don't abort the batch — the
            # underlying op records them as failures with a useful error.
            default_zfp = (zim_file_path or "").strip()
            sanitized: List[Dict[str, Any]] = []
            for entry in entries or []:
                if isinstance(entry, str):
                    raw_zfp, raw_path = default_zfp, entry
                elif isinstance(entry, dict):
                    raw_zfp = str(entry.get("zim_file_path") or default_zfp)
                    raw_path = str(entry.get("entry_path") or "")
                else:
                    raw_zfp, raw_path = "", ""
                sanitized.append(
                    {
                        "zim_file_path": sanitize_input(
                            raw_zfp, INPUT_LIMIT_FILE_PATH, allow_empty=True
                        ),
                        "entry_path": sanitize_input(
                            raw_path, INPUT_LIMIT_ENTRY_PATH, allow_empty=True
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
