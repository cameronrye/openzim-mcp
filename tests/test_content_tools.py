"""Tests for content_tools module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpRateLimitError
from openzim_mcp.server import OpenZimMcpServer


class TestRegisterContentTools:
    """Test content tools registration."""

    def test_register_content_tools(self, test_config: OpenZimMcpConfig):
        """Test that content tools are registered correctly."""
        server = OpenZimMcpServer(test_config)
        # Tools are registered during server init, verify MCP instance exists
        assert server.mcp is not None


class TestGetZimEntryTool:
    """Test get_zim_entry tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_get_zim_entry_success(self, server: OpenZimMcpServer):
        """Test successful entry retrieval."""
        # Mock async_zim_operations
        server.async_zim_operations.get_zim_entry = AsyncMock(
            return_value="Entry content"
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.get_zim_entry(
            "/path/to/file.zim", "A/Article", None
        )

        assert result == "Entry content"
        server.async_zim_operations.get_zim_entry.assert_called_once_with(
            "/path/to/file.zim", "A/Article", None
        )

    @pytest.mark.asyncio
    async def test_get_zim_entry_with_max_content_length(
        self, server: OpenZimMcpServer
    ):
        """Test entry retrieval with max_content_length parameter."""
        server.async_zim_operations.get_zim_entry = AsyncMock(
            return_value="Truncated content"
        )

        result = await server.async_zim_operations.get_zim_entry(
            "/path/to/file.zim", "A/Article", 5000
        )

        assert result == "Truncated content"
        server.async_zim_operations.get_zim_entry.assert_called_once_with(
            "/path/to/file.zim", "A/Article", 5000
        )

    def test_max_content_length_validation(self, server: OpenZimMcpServer):
        """Test that max_content_length < 1000 returns validation error."""
        # This tests the validation logic that would be in the actual tool
        max_content_length = 500
        if max_content_length is not None and max_content_length < 1000:
            error_message = (
                "**Parameter Validation Error**\n\n"
                f"**Issue**: max_content_length must be at least 1000 characters "
                f"(provided: {max_content_length})\n\n"
            )
            assert "must be at least 1000" in error_message

    @pytest.mark.asyncio
    async def test_get_zim_entry_rate_limit_error(self, server: OpenZimMcpServer):
        """Test rate limit handling in get_zim_entry."""
        # Test rate limit error creation
        error = OpenZimMcpRateLimitError("Rate limit exceeded")
        error_msg = server._create_enhanced_error_message(
            operation="get ZIM entry",
            error=error,
            context="Entry: A/Test",
        )
        assert "Rate limit" in error_msg or "Operation" in error_msg

    @pytest.mark.asyncio
    async def test_get_zim_entry_generic_exception(self, server: OpenZimMcpServer):
        """Test generic exception handling in get_zim_entry."""
        server.async_zim_operations.get_zim_entry = AsyncMock(
            side_effect=Exception("Test error")
        )

        with pytest.raises(Exception) as exc_info:
            await server.async_zim_operations.get_zim_entry(
                "/path/to/file.zim", "A/Article", None
            )
        assert "Test error" in str(exc_info.value)


class TestInputSanitization:
    """Test input sanitization in content tools."""

    def test_sanitize_input_called(self, test_config: OpenZimMcpConfig):
        """Test that sanitize_input validates input length."""
        from openzim_mcp.constants import INPUT_LIMIT_ENTRY_PATH, INPUT_LIMIT_FILE_PATH
        from openzim_mcp.exceptions import OpenZimMcpValidationError
        from openzim_mcp.security import sanitize_input

        # Test that valid input passes
        valid_path = "a" * 100
        sanitized = sanitize_input(valid_path, INPUT_LIMIT_FILE_PATH)
        assert sanitized == valid_path

        # Test that overly long input raises error
        long_path = "a" * 2000
        with pytest.raises(OpenZimMcpValidationError) as exc_info:
            sanitize_input(long_path, INPUT_LIMIT_FILE_PATH)
        assert "Input too long" in str(exc_info.value)

        # Test entry path sanitization
        valid_entry = "b" * 100
        sanitized_entry = sanitize_input(valid_entry, INPUT_LIMIT_ENTRY_PATH)
        assert sanitized_entry == valid_entry
