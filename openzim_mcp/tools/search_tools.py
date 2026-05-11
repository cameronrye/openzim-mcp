"""Search tools for OpenZIM MCP server."""

import logging
from typing import TYPE_CHECKING, Optional, Union

from ..constants import INPUT_LIMIT_FILE_PATH, INPUT_LIMIT_QUERY
from ..exceptions import OpenZimMcpRateLimitError
from ..responses import ToolErrorPayload, tool_error
from ..security import sanitize_input
from ..tool_schemas import FindEntryResponse, SearchAllResponse, SearchResponse

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


def register_search_tools(server: "OpenZimMcpServer") -> None:
    """Register search-related tools."""
    _register_search_zim_file(server)
    _register_search_all(server)
    _register_find_entry_by_title(server)


def _register_search_zim_file(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def search_zim_file(
        zim_file_path: str,
        query: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        cursor: Optional[str] = None,
    ) -> Union[SearchResponse, ToolErrorPayload]:
        """Search within ZIM file content.

        Args:
            zim_file_path: Path to the ZIM file
            query: Search query term. Required unless ``cursor`` is provided,
                in which case the query encoded in the cursor is reused.
            limit: Maximum number of results to return (default from config)
            offset: Result starting offset (for pagination)
            cursor: Opaque pagination token from a previous result's
                ``next_cursor`` field. When provided, overrides ``offset``,
                ``limit``, and ``query`` with the values encoded in the
                token (cursor wins on conflict per response-contract spec).

        Returns:
            ``SearchResponse``-shaped dict on success (Phase B contract:
            top-level ``results`` / ``next_cursor`` / ``total`` / ``done`` /
            ``page_info``); ``ToolErrorPayload`` envelope on failure.
        """
        cursor_ai: Optional[str] = None
        try:
            # Phase B: cursor wins on conflict per response-contract spec.
            if cursor is not None:
                from ..pagination import Cursor, CursorMismatchError

                try:
                    decoded = Cursor.decode(cursor, expected_tool="search_zim_file")
                except CursorMismatchError as e:
                    return tool_error(
                        operation="search ZIM file",
                        message=str(e),
                        context="Tool: search_zim_file, cursor=<truncated>",
                    )
                except ValueError as e:
                    return tool_error(
                        operation="search ZIM file",
                        message=f"Invalid pagination cursor: {e}",
                        context="Tool: search_zim_file",
                    )
                offset = decoded["s"]["o"]
                if "l" in decoded["s"]:
                    limit = decoded["s"]["l"]
                # Cursor's q overrides the query argument so the cursor
                # round-trips cleanly even if a caller forgets to pass query
                # alongside.
                if "q" in decoded["s"]:
                    query = decoded["s"]["q"]
                cursor_ai = decoded["s"].get("ai")

            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("search")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="search ZIM file",
                    message=server._create_enhanced_error_message(
                        operation="search ZIM file",
                        error=e,
                        context=f"Query: '{query}'",
                    ),
                    context=f"Query: '{query}'",
                )

            # Sanitize file path eagerly; query is sanitized once resolved.
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)

            if not query:
                return tool_error(
                    operation="search ZIM file",
                    message=(
                        "`query` is required when `cursor` is not provided. "
                        "Pass a search term as `query`, or pass a `cursor` "
                        "from a prior search response to resume pagination."
                    ),
                    context="Tool: search_zim_file",
                )

            query = sanitize_input(query, INPUT_LIMIT_QUERY)

            # Validate parameters
            if limit is not None and (limit < 1 or limit > 100):
                return tool_error(
                    operation="search ZIM file",
                    message=(
                        f"Search limit must be between 1 and 100 "
                        f"(provided: {limit}). Use `limit=10` for 10 results "
                        f"or `limit=50` for more results."
                    ),
                    context=f"Query: '{query}'",
                )

            if offset < 0:
                return tool_error(
                    operation="search ZIM file",
                    message=(
                        f"Offset must be non-negative (provided: {offset}). "
                        "Use `offset=0` to start from the beginning, or a "
                        "positive number to skip results."
                    ),
                    context=f"Query: '{query}'",
                )

            # Perform the search using async operations (structured payload).
            return await server.async_zim_operations.search_zim_file_data(
                zim_file_path,
                query,
                limit,
                offset,
                cursor_archive_identity=cursor_ai,
            )

        except Exception as e:
            logger.error(f"Error searching ZIM file: {e}")
            return tool_error(
                operation="search ZIM file",
                message=server._create_enhanced_error_message(
                    operation="search ZIM file",
                    error=e,
                    context=f"File: {zim_file_path}, Query: '{query}'",
                ),
                context=f"File: {zim_file_path}, Query: '{query}'",
            )


def _register_search_all(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def search_all(
        query: str,
        limit_per_file: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Union[SearchAllResponse, ToolErrorPayload]:
        """Search across every ZIM file in the allowed directories.

        Returns merged per-file results so the caller doesn't need to know
        which file holds the information they want. Files that can't be
        searched (corrupt, no full-text index) are skipped without aborting
        the rest.

        Args:
            query: Search query term (required)
            limit_per_file: Max hits per ZIM file (1-50, default: 5)
            limit: Alias for ``limit_per_file`` for symmetry with
                ``search_zim_file``. If both are provided, ``limit_per_file``
                wins.

        Returns:
            ``SearchAllResponse``-shaped dict on success (Phase B contract:
            top-level ``results`` / ``next_cursor`` / ``total`` / ``done`` /
            ``page_info``, with each ``results[].result`` itself a
            ``SearchResponse``); ``ToolErrorPayload`` envelope on failure.
            ``search_all`` does not paginate at the top level — fan-out
            across archives happens in one shot, so ``done`` is always
            ``True`` and ``next_cursor`` is always ``None``.
        """
        try:
            try:
                server.rate_limiter.check_rate_limit("search")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="search across ZIM files",
                    message=server._create_enhanced_error_message(
                        operation="search across ZIM files",
                        error=e,
                        context=f"Query: '{query}'",
                    ),
                    context=f"Query: '{query}'",
                )

            query = sanitize_input(query, INPUT_LIMIT_QUERY)

            effective_limit = limit_per_file if limit_per_file is not None else limit
            if effective_limit is None:
                effective_limit = 5

            if effective_limit < 1 or effective_limit > 50:
                return tool_error(
                    operation="search across ZIM files",
                    message=(
                        f"limit_per_file must be between 1 and 50 "
                        f"(provided: {effective_limit})"
                    ),
                    context=f"Query: '{query}'",
                )

            return await server.async_zim_operations.search_all_data(
                query, effective_limit
            )

        except Exception as e:
            logger.error(f"Error in search_all: {e}")
            return tool_error(
                operation="search across ZIM files",
                message=server._create_enhanced_error_message(
                    operation="search across ZIM files",
                    error=e,
                    context=f"Query: '{query}'",
                ),
                context=f"Query: '{query}'",
            )


def _register_find_entry_by_title(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def find_entry_by_title(
        zim_file_path: str,
        title: str,
        cross_file: bool = False,
        limit: int = 10,
    ) -> Union[FindEntryResponse, ToolErrorPayload]:
        """Resolve a title to one or more entry paths.

        Cheaper than full-text search when the caller knows the article title.
        Tries an exact normalized C/<Title> match first (fast path), then
        falls back to libzim's title-indexed suggestion search. Set
        cross_file=True to query every ZIM file in allowed directories.

        Args:
            zim_file_path: Path to the ZIM file (used unless cross_file=True)
            title: Title or partial title to resolve (case-insensitive)
            cross_file: If True, search across all allowed ZIM files
            limit: Max results to return (1-50, default: 10)

        Returns:
            ``FindEntryResponse``-shaped dict on success (Phase B contract:
            top-level ``results`` / ``next_cursor`` / ``total`` / ``done`` /
            ``page_info`` plus ``query`` / ``fast_path_hit`` /
            ``fuzzy_path_hit`` / ``files_searched`` extras);
            ``ToolErrorPayload`` envelope on failure. ``find_entry_by_title``
            is non-paginated: ``done`` is always ``True`` and
            ``next_cursor`` is always ``None``.
        """
        try:
            try:
                server.rate_limiter.check_rate_limit("find_entry_by_title")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="find entry by title",
                    message=server._create_enhanced_error_message(
                        operation="find entry by title",
                        error=e,
                        context=f"Title: '{title}'",
                    ),
                    context=f"Title: '{title}'",
                )

            title = sanitize_input(title, INPUT_LIMIT_QUERY)
            # Always sanitize the path: even with cross_file=True the value
            # is forwarded to backend operations and must not carry control
            # characters (e.g. NUL bytes) into libzim.
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)

            return await server.async_zim_operations.find_entry_by_title_data(
                zim_file_path, title, cross_file, limit
            )

        except Exception as e:
            logger.error(f"Error in find_entry_by_title: {e}")
            return tool_error(
                operation="find entry by title",
                message=server._create_enhanced_error_message(
                    operation="find entry by title",
                    error=e,
                    context=f"File: {zim_file_path}, Title: '{title}'",
                ),
                context=f"File: {zim_file_path}, Title: '{title}'",
            )
