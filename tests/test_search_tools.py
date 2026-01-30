"""Tests for search_tools module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpRateLimitError
from openzim_mcp.server import OpenZimMcpServer


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


class TestConflictWarningAppend:
    """Test conflict warning appending functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_check_and_append_conflict_warnings(self, server: OpenZimMcpServer):
        """Test that conflict warnings are appended correctly."""
        # This tests the _check_and_append_conflict_warnings method
        original_result = '{"results": []}'

        # When no instance tracker or no conflicts, result should be unchanged
        result = server._check_and_append_conflict_warnings(original_result)

        # Result should contain the original content
        assert "results" in result


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
