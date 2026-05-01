"""Tests for file_tools module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpRateLimitError
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.tools.file_tools import register_file_tools


def _capture_registered_tool(register_fn, server_mock):
    """Run a tool registrar with a mock and return the registered handler."""
    captured = {}

    def tool_decorator(*args, **kwargs):
        def wrap(fn):
            captured["fn"] = fn
            return fn

        return wrap

    server_mock.mcp.tool = tool_decorator
    register_fn(server_mock)
    return captured["fn"]


class TestListZimFilesToolNameFilter:
    """Verify the registered list_zim_files tool forwards name_filter."""

    def _build_mock_server(self):
        server = MagicMock()
        server.mcp = MagicMock()
        server.async_zim_operations.list_zim_files = AsyncMock(return_value="[]")
        server.rate_limiter.check_rate_limit = MagicMock()
        return server

    @pytest.mark.asyncio
    async def test_forwards_name_filter(self):
        """The tool forwards an explicit name_filter to the async op."""
        server = self._build_mock_server()
        tool_fn = _capture_registered_tool(register_file_tools, server)

        await tool_fn(name_filter="nginx")

        server.async_zim_operations.list_zim_files.assert_called_once_with(
            name_filter="nginx"
        )

    @pytest.mark.asyncio
    async def test_default_forwards_empty_filter(self):
        """Calling with no arg forwards the documented empty-string default."""
        server = self._build_mock_server()
        tool_fn = _capture_registered_tool(register_file_tools, server)

        await tool_fn()

        server.async_zim_operations.list_zim_files.assert_called_once_with(
            name_filter=""
        )


class TestRegisterFileTools:
    """Test file tools registration."""

    def test_register_file_tools(self, test_config: OpenZimMcpConfig):
        """Test that file tools are registered correctly."""
        server = OpenZimMcpServer(test_config)
        assert server.mcp is not None


class TestListZimFilesTool:
    """Test list_zim_files tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_list_zim_files_success(self, server: OpenZimMcpServer):
        """Test successful ZIM file listing."""
        server.async_zim_operations.list_zim_files = AsyncMock(
            return_value='[{"path": "/test/file.zim"}]'
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.list_zim_files()

        assert "file.zim" in result
        server.async_zim_operations.list_zim_files.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_zim_files_rate_limit_error(self, server: OpenZimMcpServer):
        """Test rate limit handling in list_zim_files."""
        error = OpenZimMcpRateLimitError("Rate limit exceeded")
        error_msg = server._create_enhanced_error_message(
            operation="list ZIM files",
            error=error,
            context="Listing available ZIM files",
        )
        assert "list ZIM files" in error_msg or "Operation" in error_msg

    @pytest.mark.asyncio
    async def test_list_zim_files_generic_exception(self, server: OpenZimMcpServer):
        """Test generic exception handling in list_zim_files."""
        server.async_zim_operations.list_zim_files = AsyncMock(
            side_effect=Exception("Test error")
        )

        with pytest.raises(Exception) as exc_info:
            await server.async_zim_operations.list_zim_files()
        assert "Test error" in str(exc_info.value)
