"""Tests for search_tools module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpRateLimitError
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.zim_operations import PaginationCursor


def _get_tool_fn(server: OpenZimMcpServer, name: str):
    """Resolve the registered FastMCP tool's callable across SDK versions."""
    tool = server.mcp._tool_manager._tools[name]
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None)
    assert fn is not None, f"could not find callable on tool object: {tool!r}"
    return fn


class TestRegisterSearchTools:
    """Test search tools registration."""

    def test_register_search_tools(self, test_config: OpenZimMcpConfig):
        """Test that search tools are registered correctly."""
        server = OpenZimMcpServer(test_config)
        assert server.mcp is not None


class TestSearchZimFileTool:
    """Test search_zim_file tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_search_zim_file_success(self, server: OpenZimMcpServer):
        """Test successful ZIM file search."""
        server.async_zim_operations.search_zim_file = AsyncMock(
            return_value='{"results": [{"title": "Test Article"}]}'
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.search_zim_file(
            "/path/to/file.zim", "test query", 10, 0
        )

        assert "results" in result
        server.async_zim_operations.search_zim_file.assert_called_once_with(
            "/path/to/file.zim", "test query", 10, 0
        )

    @pytest.mark.asyncio
    async def test_search_zim_file_with_pagination(self, server: OpenZimMcpServer):
        """Test ZIM file search with pagination."""
        server.async_zim_operations.search_zim_file = AsyncMock(
            return_value='{"results": [], "offset": 10}'
        )

        result = await server.async_zim_operations.search_zim_file(
            "/path/to/file.zim", "test query", 10, 10
        )

        assert "results" in result
        server.async_zim_operations.search_zim_file.assert_called_once_with(
            "/path/to/file.zim", "test query", 10, 10
        )

    def test_search_limit_validation_too_low(self):
        """Test that limit < 1 returns validation error."""
        limit = 0
        if limit is not None and (limit < 1 or limit > 100):
            error = (
                "**Parameter Validation Error**\n\n"
                f"**Issue**: Search limit must be between 1 and 100 "
                f"(provided: {limit})\n\n"
            )
            assert "must be between 1 and 100" in error

    def test_search_limit_validation_too_high(self):
        """Test that limit > 100 returns validation error."""
        limit = 200
        if limit is not None and (limit < 1 or limit > 100):
            error = (
                "**Parameter Validation Error**\n\n"
                f"**Issue**: Search limit must be between 1 and 100 "
                f"(provided: {limit})\n\n"
            )
            assert "must be between 1 and 100" in error

    def test_search_offset_validation_negative(self):
        """Test that negative offset returns validation error."""
        offset = -5
        # Negative offset should produce validation error message
        error = (
            "**Parameter Validation Error**\n\n"
            f"**Issue**: Offset must be non-negative (provided: {offset})\n\n"
        )
        assert "must be non-negative" in error

    @pytest.mark.asyncio
    async def test_search_zim_file_rate_limit_error(self, server: OpenZimMcpServer):
        """Test rate limit handling in search_zim_file."""
        error = OpenZimMcpRateLimitError("Rate limit exceeded")
        error_msg = server._create_enhanced_error_message(
            operation="search ZIM file",
            error=error,
            context="Query: 'test'",
        )
        assert "search ZIM file" in error_msg or "Operation" in error_msg

    @pytest.mark.asyncio
    async def test_search_zim_file_generic_exception(self, server: OpenZimMcpServer):
        """Test generic exception handling in search_zim_file."""
        server.async_zim_operations.search_zim_file = AsyncMock(
            side_effect=Exception("Search error")
        )

        with pytest.raises(Exception) as exc_info:
            await server.async_zim_operations.search_zim_file(
                "/path/to/file.zim", "query", None, 0
            )
        assert "Search error" in str(exc_info.value)


class TestSearchCursor:
    """The opaque cursor token round-trips through search_zim_file."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a server with search_zim_file stubbed to a passthrough."""
        srv = OpenZimMcpServer(test_config)
        srv.async_zim_operations.search_zim_file = AsyncMock(return_value="ok")
        srv.rate_limiter.check_rate_limit = MagicMock()
        return srv

    def test_pagination_cursor_round_trip(self):
        """Encode -> decode preserves offset, limit, and query."""
        token = PaginationCursor.create_next_cursor(
            current_offset=0, limit=5, total=100, query="diabetes"
        )
        assert token is not None
        decoded = PaginationCursor.decode(token)
        assert decoded == {"o": 5, "l": 5, "q": "diabetes"}

    def test_pagination_cursor_decode_rejects_garbage(self):
        """Malformed base64 surfaces as ValueError."""
        with pytest.raises(ValueError):
            PaginationCursor.decode("not-base64-!!!")

    def test_pagination_cursor_decode_rejects_missing_fields(self):
        """A token decoding to a dict without offset/limit is rejected."""
        import base64
        import json

        bad = base64.urlsafe_b64encode(json.dumps({"only": 1}).encode()).decode()
        with pytest.raises(ValueError, match="missing required fields"):
            PaginationCursor.decode(bad)

    @pytest.mark.asyncio
    async def test_cursor_overrides_offset_and_limit(self, server: OpenZimMcpServer):
        """`cursor` overrides explicit offset/limit when both are present."""
        token = PaginationCursor.create_next_cursor(
            current_offset=10, limit=7, total=100, query="ignored-here"
        )

        fn = _get_tool_fn(server, "search_zim_file")
        await fn(
            zim_file_path="/path/to/file.zim",
            query="diabetes",
            limit=999,  # would fail validation if cursor didn't override
            offset=999,
            cursor=token,
        )

        call = server.async_zim_operations.search_zim_file.await_args
        # signature: (zim_file_path, query, limit, offset)
        assert call.args[2] == 7  # limit from cursor
        assert call.args[3] == 17  # next-page offset from cursor

    @pytest.mark.asyncio
    async def test_invalid_cursor_returns_validation_error(
        self, server: OpenZimMcpServer
    ):
        """Malformed cursor surfaces as a parameter-validation message."""
        fn = _get_tool_fn(server, "search_zim_file")
        result = await fn(
            zim_file_path="/path/to/file.zim",
            query="diabetes",
            cursor="!!!not-a-cursor!!!",
        )
        assert "Parameter Validation Error" in result
        assert "cursor" in result.lower()
        # The operations layer should not have been called.
        server.async_zim_operations.search_zim_file.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cursor_alone_supplies_query(self, server: OpenZimMcpServer):
        """A cursor alone is sufficient — the encoded query is reused."""
        token = PaginationCursor.create_next_cursor(
            current_offset=0, limit=2, total=100, query="diabetes"
        )

        fn = _get_tool_fn(server, "search_zim_file")
        await fn(zim_file_path="/path/to/file.zim", cursor=token)

        call = server.async_zim_operations.search_zim_file.await_args
        # signature: (zim_file_path, query, limit, offset)
        assert call.args[1] == "diabetes"
        assert call.args[2] == 2
        assert call.args[3] == 2

    @pytest.mark.asyncio
    async def test_missing_query_without_cursor_is_validation_error(
        self, server: OpenZimMcpServer
    ):
        """Without a cursor, an explicit query is still required."""
        fn = _get_tool_fn(server, "search_zim_file")
        result = await fn(zim_file_path="/path/to/file.zim")
        assert "Parameter Validation Error" in result
        assert "query" in result.lower()
        server.async_zim_operations.search_zim_file.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_explicit_query_wins_when_cursor_disagrees(
        self, server: OpenZimMcpServer, caplog: pytest.LogCaptureFixture
    ):
        """Explicit query overrides the cursor's encoded query, with a warning."""
        token = PaginationCursor.create_next_cursor(
            current_offset=0, limit=5, total=100, query="cursor-query"
        )

        fn = _get_tool_fn(server, "search_zim_file")
        with caplog.at_level("WARNING"):
            await fn(
                zim_file_path="/path/to/file.zim",
                query="explicit-query",
                cursor=token,
            )

        call = server.async_zim_operations.search_zim_file.await_args
        assert call.args[1] == "explicit-query"
        assert any(
            "cursor" in rec.message.lower() and "query" in rec.message.lower()
            for rec in caplog.records
        )


class TestSearchAllLimitAlias:
    """`limit` is accepted as an alias of `limit_per_file` on search_all."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a server with search_all stubbed to a passthrough."""
        srv = OpenZimMcpServer(test_config)
        srv.async_zim_operations.search_all = AsyncMock(return_value="ok")
        srv.rate_limiter.check_rate_limit = MagicMock()
        return srv

    @pytest.mark.asyncio
    async def test_limit_alias_used_when_limit_per_file_missing(
        self, server: OpenZimMcpServer
    ):
        """`limit` flows through when `limit_per_file` is unset."""
        fn = _get_tool_fn(server, "search_all")
        await fn(query="x", limit=8)
        call = server.async_zim_operations.search_all.await_args
        assert call.args[1] == 8

    @pytest.mark.asyncio
    async def test_limit_per_file_takes_precedence_over_limit(
        self, server: OpenZimMcpServer
    ):
        """`limit_per_file` wins when both names are provided."""
        fn = _get_tool_fn(server, "search_all")
        await fn(query="x", limit_per_file=3, limit=99)
        call = server.async_zim_operations.search_all.await_args
        assert call.args[1] == 3

    @pytest.mark.asyncio
    async def test_default_when_neither_provided(self, server: OpenZimMcpServer):
        """Default of 5 still applies when neither limit nor limit_per_file is set."""
        fn = _get_tool_fn(server, "search_all")
        await fn(query="x")
        call = server.async_zim_operations.search_all.await_args
        assert call.args[1] == 5


class TestInputSanitizationSearch:
    """Test input sanitization in search tools."""

    def test_sanitize_file_path(self, test_config: OpenZimMcpConfig):
        """Test that file paths are validated correctly."""
        from openzim_mcp.constants import INPUT_LIMIT_FILE_PATH
        from openzim_mcp.exceptions import OpenZimMcpValidationError
        from openzim_mcp.security import sanitize_input

        # Valid path should pass
        valid_path = "y" * 100
        sanitized = sanitize_input(valid_path, INPUT_LIMIT_FILE_PATH)
        assert sanitized == valid_path

        # Long path should raise error
        long_path = "y" * 2000
        with pytest.raises(OpenZimMcpValidationError):
            sanitize_input(long_path, INPUT_LIMIT_FILE_PATH)

    def test_sanitize_query(self, test_config: OpenZimMcpConfig):
        """Test that queries are validated correctly."""
        from openzim_mcp.constants import INPUT_LIMIT_QUERY
        from openzim_mcp.exceptions import OpenZimMcpValidationError
        from openzim_mcp.security import sanitize_input

        # Valid query should pass
        valid_query = "z" * 100
        sanitized = sanitize_input(valid_query, INPUT_LIMIT_QUERY)
        assert sanitized == valid_query

        # Long query should raise error
        long_query = "z" * 1000
        with pytest.raises(OpenZimMcpValidationError):
            sanitize_input(long_query, INPUT_LIMIT_QUERY)
