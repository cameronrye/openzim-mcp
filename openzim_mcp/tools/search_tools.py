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
    ) -> str:
        """Search within ZIM file content.

        Args:
            zim_file_path: Path to the ZIM file
            query: Search query term. Required unless ``cursor`` is provided,
                in which case the query encoded in the cursor is reused.
            limit: Maximum number of results to return (default from config)
            offset: Result starting offset (for pagination)
            cursor: Opaque pagination token from a previous result's
                ``next_cursor`` field. When provided, overrides ``offset`` and
                ``limit`` with the values encoded in the token, and supplies
                ``query`` if it was not given explicitly.

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

            # Sanitize file path eagerly; query is sanitized once resolved.
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)

            # Resolve cursor before validating offset/limit so cursor-supplied
            # values are subject to the same bounds checks. The cursor also
            # carries the original query, which is used when the caller did
            # not pass `query` explicitly.
            if cursor:
                from ..zim_operations import PaginationCursor

                try:
                    decoded = PaginationCursor.decode(cursor)
                except ValueError as e:
                    return (
                        "**Parameter Validation Error**\n\n"
                        f"**Issue**: {e}\n\n"
                        "**Troubleshooting**: Use the exact `next_cursor` "
                        "value from a prior search response, or fall back to "
                        "explicit `offset`/`limit` parameters."
                    )
                offset = decoded["o"]
                limit = decoded["l"]
                cursor_query = decoded.get("q")
                if query is None:
                    query = cursor_query
                elif cursor_query and cursor_query != query:
                    # Cursors encode the query they were paired with;
                    # honoring a different `query` would silently return the
                    # wrong page of the wrong query. Reject instead.
                    return (
                        "**Parameter Validation Error**\n\n"
                        f"**Issue**: `cursor` was issued for query "
                        f"{cursor_query!r} but the request supplied "
                        f"query {query!r}. Cursors are only valid for "
                        "the query they were issued for.\n\n"
                        "**Troubleshooting**: Either drop `cursor` and "
                        "start a fresh search with the new `query`, or "
                        "omit `query` so the cursor's embedded query is "
                        "reused."
                    )

            if not query:
                return (
                    "**Parameter Validation Error**\n\n"
                    "**Issue**: `query` is required when `cursor` is not "
                    "provided.\n\n"
                    "**Troubleshooting**: Pass a search term as `query`, or "
                    "pass a `cursor` from a prior search response to resume "
                    "pagination."
                )

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
            return await server.async_zim_operations.search_zim_file(
                zim_file_path, query, limit, offset
            )

        except Exception as e:
            logger.error(f"Error searching ZIM file: {e}")
            return server._create_enhanced_error_message(
                operation="search ZIM file",
                error=e,
                context=f"File: {zim_file_path}, Query: '{query}'",
            )


def _register_search_all(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def search_all(
        query: str,
        limit_per_file: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> str:
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
            JSON containing per-file result groups and counts of files
            searched / with-results / failed
        """
        try:
            try:
                server.rate_limiter.check_rate_limit("search")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="search across ZIM files",
                    error=e,
                    context=f"Query: '{query}'",
                )

            query = sanitize_input(query, INPUT_LIMIT_QUERY)

            effective_limit = limit_per_file if limit_per_file is not None else limit
            if effective_limit is None:
                effective_limit = 5

            if effective_limit < 1 or effective_limit > 50:
                return (
                    "**Parameter Validation Error**\n\n"
                    f"**Issue**: limit_per_file must be between 1 and 50 "
                    f"(provided: {effective_limit})\n"
                    "**Example**: Use `limit_per_file=5` for default, "
                    "`limit_per_file=20` for more results per file."
                )

            return await server.async_zim_operations.search_all(query, effective_limit)

        except Exception as e:
            logger.error(f"Error in search_all: {e}")
            return server._create_enhanced_error_message(
                operation="search across ZIM files",
                error=e,
                context=f"Query: '{query}'",
            )


def _register_find_entry_by_title(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def find_entry_by_title(
        zim_file_path: str,
        title: str,
        cross_file: bool = False,
        limit: int = 10,
    ) -> str:
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
            JSON with query, ranked results, fast_path_hit flag, files_searched
        """
        try:
            try:
                server.rate_limiter.check_rate_limit("find_entry_by_title")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="find entry by title",
                    error=e,
                    context=f"Title: '{title}'",
                )

            title = sanitize_input(title, INPUT_LIMIT_QUERY)
            # Always sanitize the path: even with cross_file=True the value
            # is forwarded to backend operations and must not carry control
            # characters (e.g. NUL bytes) into libzim.
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)

            return await server.async_zim_operations.find_entry_by_title(
                zim_file_path, title, cross_file, limit
            )

        except Exception as e:
            logger.error(f"Error in find_entry_by_title: {e}")
            return server._create_enhanced_error_message(
                operation="find entry by title",
                error=e,
                context=f"File: {zim_file_path}, Title: '{title}'",
            )
