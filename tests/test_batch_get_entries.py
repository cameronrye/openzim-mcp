"""Tests for the get_zim_entries MCP tool registration and async wrapper."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.async_operations import AsyncZimOperations
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


@pytest.mark.asyncio
async def test_async_get_entries_wraps_sync():
    """The async wrapper delegates to the sync ZimOperations.get_entries."""
    sync_ops = MagicMock()
    sync_ops.get_entries.return_value = '{"results": [], "succeeded": 0, "failed": 0}'
    async_ops = AsyncZimOperations(sync_ops)

    result = await async_ops.get_entries(
        [{"zim_file_path": "/x", "entry_path": "y"}], None
    )

    sync_ops.get_entries.assert_called_once()
    assert json.loads(result)["succeeded"] == 0


def test_get_zim_entries_tool_is_registered(test_config: OpenZimMcpConfig):
    """The get_zim_entries tool appears in the registered FastMCP tool set."""
    server = OpenZimMcpServer(test_config)
    # FastMCP exposes _tool_manager / list_tools across SDK versions; we look
    # via the public tool listing if available, else fall back to the manager.
    tools = (
        server.mcp._tool_manager._tools if hasattr(server.mcp, "_tool_manager") else {}
    )
    assert (
        "get_zim_entries" in tools
    ), f"expected get_zim_entries in registered tools, got {list(tools)}"


@pytest.mark.asyncio
async def test_get_zim_entries_tool_passes_through(
    test_config: OpenZimMcpConfig,
):
    """Calling the registered tool function delegates to async_zim_operations."""
    server = OpenZimMcpServer(test_config)
    server.async_zim_operations.get_entries = AsyncMock(
        return_value='{"results": [], "succeeded": 0, "failed": 0}'
    )
    server.rate_limiter.check_rate_limit = MagicMock()

    tool = server.mcp._tool_manager._tools["get_zim_entries"]
    # FastMCP wraps the registered function; ToolDefinition.fn / .func varies.
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None)
    assert fn is not None, f"could not find callable on tool object: {tool!r}"

    result = await fn(
        entries=[{"zim_file_path": "/x", "entry_path": "y"}],
    )
    assert json.loads(result)["succeeded"] == 0
    server.async_zim_operations.get_entries.assert_awaited_once()
