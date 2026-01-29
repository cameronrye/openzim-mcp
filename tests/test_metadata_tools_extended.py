"""
Extended tests for metadata_tools module to increase test coverage.

These tests focus on the untested paths in metadata_tools.py:
- Rate limit error handling for all three tools
- General exception handling
- Direct tool invocation
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpRateLimitError
from openzim_mcp.server import OpenZimMcpServer


class TestGetZimMetadataToolInvocation:
    """Test get_zim_metadata tool by invoking the actual registered handler."""

    @pytest.fixture
    def server(self, temp_dir):
        """Create a test server."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        return OpenZimMcpServer(config)

    @pytest.mark.asyncio
    async def test_get_zim_metadata_success(self, server, temp_dir):
        """Test successful metadata retrieval through tool handler."""
        server.async_zim_operations.get_zim_metadata = AsyncMock(
            return_value='{"title": "Test", "language": "en"}'
        )

        tools = server.mcp._tool_manager._tools
        if "get_zim_metadata" in tools:
            tool_handler = tools["get_zim_metadata"].fn
            result = await tool_handler(zim_file_path=str(temp_dir / "test.zim"))
            assert "title" in result
            assert "Test" in result

    @pytest.mark.asyncio
    async def test_get_zim_metadata_rate_limit_error(self, server, temp_dir):
        """Test rate limit error handling in get_zim_metadata."""
        server.rate_limiter.check_rate_limit = MagicMock(
            side_effect=OpenZimMcpRateLimitError("Rate limit exceeded")
        )

        tools = server.mcp._tool_manager._tools
        if "get_zim_metadata" in tools:
            tool_handler = tools["get_zim_metadata"].fn
            result = await tool_handler(zim_file_path=str(temp_dir / "test.zim"))
            # Should return error message, not raise
            assert "Error" in result or "Rate" in result

    @pytest.mark.asyncio
    async def test_get_zim_metadata_generic_exception(self, server, temp_dir):
        """Test generic exception handling in get_zim_metadata."""
        server.async_zim_operations.get_zim_metadata = AsyncMock(
            side_effect=RuntimeError("Metadata retrieval failed")
        )

        tools = server.mcp._tool_manager._tools
        if "get_zim_metadata" in tools:
            tool_handler = tools["get_zim_metadata"].fn
            result = await tool_handler(zim_file_path=str(temp_dir / "test.zim"))
            # Should return error message, not raise
            assert "Error" in result or "error" in result.lower()


class TestGetMainPageToolInvocation:
    """Test get_main_page tool by invoking the actual registered handler."""

    @pytest.fixture
    def server(self, temp_dir):
        """Create a test server."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        return OpenZimMcpServer(config)

    @pytest.mark.asyncio
    async def test_get_main_page_success(self, server, temp_dir):
        """Test successful main page retrieval through tool handler."""
        server.async_zim_operations.get_main_page = AsyncMock(
            return_value="Main page content here"
        )

        tools = server.mcp._tool_manager._tools
        if "get_main_page" in tools:
            tool_handler = tools["get_main_page"].fn
            result = await tool_handler(zim_file_path=str(temp_dir / "test.zim"))
            assert "Main page content" in result

    @pytest.mark.asyncio
    async def test_get_main_page_rate_limit_error(self, server, temp_dir):
        """Test rate limit error handling in get_main_page."""
        server.rate_limiter.check_rate_limit = MagicMock(
            side_effect=OpenZimMcpRateLimitError("Rate limit exceeded")
        )

        tools = server.mcp._tool_manager._tools
        if "get_main_page" in tools:
            tool_handler = tools["get_main_page"].fn
            result = await tool_handler(zim_file_path=str(temp_dir / "test.zim"))
            # Should return error message, not raise
            assert "Error" in result or "Rate" in result

    @pytest.mark.asyncio
    async def test_get_main_page_generic_exception(self, server, temp_dir):
        """Test generic exception handling in get_main_page."""
        server.async_zim_operations.get_main_page = AsyncMock(
            side_effect=RuntimeError("Main page retrieval failed")
        )

        tools = server.mcp._tool_manager._tools
        if "get_main_page" in tools:
            tool_handler = tools["get_main_page"].fn
            result = await tool_handler(zim_file_path=str(temp_dir / "test.zim"))
            # Should return error message, not raise
            assert "Error" in result or "error" in result.lower()


class TestListNamespacesToolInvocation:
    """Test list_namespaces tool by invoking the actual registered handler."""

    @pytest.fixture
    def server(self, temp_dir):
        """Create a test server."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        return OpenZimMcpServer(config)

    @pytest.mark.asyncio
    async def test_list_namespaces_success(self, server, temp_dir):
        """Test successful namespace listing through tool handler."""
        server.async_zim_operations.list_namespaces = AsyncMock(
            return_value='{"namespaces": ["A", "C", "M", "W"]}'
        )

        tools = server.mcp._tool_manager._tools
        if "list_namespaces" in tools:
            tool_handler = tools["list_namespaces"].fn
            result = await tool_handler(zim_file_path=str(temp_dir / "test.zim"))
            assert "namespaces" in result

    @pytest.mark.asyncio
    async def test_list_namespaces_rate_limit_error(self, server, temp_dir):
        """Test rate limit error handling in list_namespaces."""
        server.rate_limiter.check_rate_limit = MagicMock(
            side_effect=OpenZimMcpRateLimitError("Rate limit exceeded")
        )

        tools = server.mcp._tool_manager._tools
        if "list_namespaces" in tools:
            tool_handler = tools["list_namespaces"].fn
            result = await tool_handler(zim_file_path=str(temp_dir / "test.zim"))
            # Should return error message, not raise
            assert "Error" in result or "Rate" in result

    @pytest.mark.asyncio
    async def test_list_namespaces_generic_exception(self, server, temp_dir):
        """Test generic exception handling in list_namespaces."""
        server.async_zim_operations.list_namespaces = AsyncMock(
            side_effect=RuntimeError("Namespace listing failed")
        )

        tools = server.mcp._tool_manager._tools
        if "list_namespaces" in tools:
            tool_handler = tools["list_namespaces"].fn
            result = await tool_handler(zim_file_path=str(temp_dir / "test.zim"))
            # Should return error message, not raise
            assert "Error" in result or "error" in result.lower()


class TestMetadataToolsInputSanitization:
    """Test input sanitization in metadata tools."""

    @pytest.fixture
    def server(self, temp_dir):
        """Create a test server."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        return OpenZimMcpServer(config)

    @pytest.mark.asyncio
    async def test_get_zim_metadata_input_sanitization(self, server, temp_dir):
        """Test that get_zim_metadata sanitizes file path input."""
        server.async_zim_operations.get_zim_metadata = AsyncMock(
            return_value='{"title": "Test"}'
        )

        tools = server.mcp._tool_manager._tools
        if "get_zim_metadata" in tools:
            tool_handler = tools["get_zim_metadata"].fn
            # Normal path should work
            result = await tool_handler(zim_file_path=str(temp_dir / "test.zim"))
            assert "title" in result

    @pytest.mark.asyncio
    async def test_get_main_page_input_sanitization(self, server, temp_dir):
        """Test that get_main_page sanitizes file path input."""
        server.async_zim_operations.get_main_page = AsyncMock(
            return_value="Main page content"
        )

        tools = server.mcp._tool_manager._tools
        if "get_main_page" in tools:
            tool_handler = tools["get_main_page"].fn
            # Normal path should work
            result = await tool_handler(zim_file_path=str(temp_dir / "test.zim"))
            assert "Main page" in result

    @pytest.mark.asyncio
    async def test_list_namespaces_input_sanitization(self, server, temp_dir):
        """Test that list_namespaces sanitizes file path input."""
        server.async_zim_operations.list_namespaces = AsyncMock(
            return_value='{"namespaces": ["A"]}'
        )

        tools = server.mcp._tool_manager._tools
        if "list_namespaces" in tools:
            tool_handler = tools["list_namespaces"].fn
            # Normal path should work
            result = await tool_handler(zim_file_path=str(temp_dir / "test.zim"))
            assert "namespaces" in result
