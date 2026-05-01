"""
Extended tests for file_tools module to increase test coverage.

These tests focus on the untested paths in file_tools.py:
- Rate limit error handling
- Empty result handling
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpRateLimitError
from openzim_mcp.server import OpenZimMcpServer


class TestListZimFilesToolInvocation:
    """Test list_zim_files tool by invoking the actual registered handler."""

    @pytest.fixture
    def advanced_server(self, temp_dir):
        """Create a server in advanced mode."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        return OpenZimMcpServer(config)

    @pytest.mark.asyncio
    async def test_list_zim_files_success(self, advanced_server):
        """Test successful ZIM file listing through tool handler."""
        advanced_server.async_zim_operations.list_zim_files = AsyncMock(
            return_value='[{"path": "/test/file.zim", "size": 1024}]'
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "list_zim_files" in tools:
            tool_handler = tools["list_zim_files"].fn
            result = await tool_handler()
            assert "file.zim" in result

    @pytest.mark.asyncio
    async def test_list_zim_files_rate_limit_error(self, advanced_server):
        """Test rate limit error handling in list_zim_files."""
        # Configure rate limiter to raise error
        advanced_server.rate_limiter.check_rate_limit = MagicMock(
            side_effect=OpenZimMcpRateLimitError("Rate limit exceeded")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "list_zim_files" in tools:
            tool_handler = tools["list_zim_files"].fn
            result = await tool_handler()
            # Should return error message, not raise exception
            assert "Error" in result or "Rate" in result

    @pytest.mark.asyncio
    async def test_list_zim_files_generic_exception(self, advanced_server):
        """Test generic exception handling in list_zim_files."""
        advanced_server.async_zim_operations.list_zim_files = AsyncMock(
            side_effect=RuntimeError("File system error")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "list_zim_files" in tools:
            tool_handler = tools["list_zim_files"].fn
            result = await tool_handler()
            # Should return error message, not raise exception
            assert "Error" in result or "error" in result.lower()


class TestEmptyZimFilesList:
    """Test list_zim_files with empty results."""

    @pytest.fixture
    def advanced_server(self, temp_dir):
        """Create a server in advanced mode."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        return OpenZimMcpServer(config)

    @pytest.mark.asyncio
    async def test_list_zim_files_empty_result(self, advanced_server):
        """Test list_zim_files when no ZIM files are found."""
        advanced_server.async_zim_operations.list_zim_files = AsyncMock(
            return_value="[]"
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "list_zim_files" in tools:
            tool_handler = tools["list_zim_files"].fn
            result = await tool_handler()
            assert result == "[]"
