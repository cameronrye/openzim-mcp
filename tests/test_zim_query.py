"""Tests for the Phase F ``zim_query`` tool registration (Task D3).

The tool module hoists the b13 ``zim_query`` from
``server._register_simple_tools`` into its own per-tool module. These
tests verify:
  1. The module registers a tool named ``zim_query`` on the MCP server.
  2. The tool's description is the committed-file content (not the
     empty docstring) — proves the ``@server.mcp.tool(description=...)``
     wiring works end-to-end.
  3. The handler delegates to ``SimpleToolsHandler.handle_zim_query``
     with the parameter shape and options the b13 surface used.
  4. Parameter validation (negative offsets, non-positive limit) is
     preserved from b13.

The data-layer behavior of ``handle_zim_query`` itself is exercised
by the existing ``test_simple_tools`` suite; this module only covers
the registration / delegation layer.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from openzim_mcp.tools.zim_query import register as register_zim_query


@pytest.fixture
def server() -> MagicMock:
    """A ``OpenZimMcpServer`` shaped well enough for tool registration."""
    srv = MagicMock()
    # The @mcp.tool() decorator path needs an mcp attr whose `.tool(...)` is
    # itself a decorator factory returning the wrapped function unchanged.
    tools_store: dict[str, Any] = {}

    def _tool(*, description: str = ""):
        def decorate(fn: Any) -> Any:
            tools_store[fn.__name__] = (fn, description)
            return fn

        return decorate

    srv.mcp.tool = _tool
    srv._tools_store = tools_store  # so tests can introspect
    srv.simple_tools_handler.handle_zim_query.return_value = "fake-result"
    return srv


def test_zim_query_registers_under_phase_f_module(server: MagicMock) -> None:
    register_zim_query(server)
    assert "zim_query" in server._tools_store


def test_zim_query_description_attached_to_tool(server: MagicMock) -> None:
    """Verify the committed-file description (not an empty docstring)
    actually lands on the registered tool. Without this, the wire
    description would be empty even though the file is on disk."""
    register_zim_query(server)
    _fn, description = server._tools_store["zim_query"]
    assert len(description) > 1000
    assert "Query ZIM archives" in description


@pytest.mark.asyncio
async def test_zim_query_dispatches_to_simple_tools_handler(
    server: MagicMock,
) -> None:
    """Verify the tool body delegates to handle_zim_query via to_thread."""
    register_zim_query(server)
    fn, _ = server._tools_store["zim_query"]
    result = await fn(query="hello", zim_file_path=None)
    assert result == "fake-result"
    # handle_zim_query was called with the b13 positional shape
    # (query, zim_file_path, options).
    args, _kwargs = server.simple_tools_handler.handle_zim_query.call_args
    assert args[0] == "hello"
    assert args[1] is None
    options = args[2]
    # M14: ``limit`` is no longer force-injected — it is omitted when the
    # caller doesn't pass one, so each intent's per-intent default applies.
    assert "limit" not in options
    assert options["max_content_length"] == 4000
    assert options["compact"] is True
    assert options["synthesize"] is False


@pytest.mark.asyncio
async def test_zim_query_forwards_explicit_limit(server: MagicMock) -> None:
    """An explicitly-passed limit IS threaded into options (M14)."""
    register_zim_query(server)
    fn, _ = server._tools_store["zim_query"]
    await fn(query="hello", limit=25)
    args, _kwargs = server.simple_tools_handler.handle_zim_query.call_args
    assert args[2]["limit"] == 25


@pytest.mark.asyncio
async def test_zim_query_rejects_negative_content_offset(
    server: MagicMock,
) -> None:
    register_zim_query(server)
    fn, _ = server._tools_store["zim_query"]
    result = await fn(query="x", content_offset=-1)
    assert result["error"] is True
    assert result["operation"] == "invalid_content_offset"


@pytest.mark.asyncio
async def test_zim_query_rejects_non_positive_limit(server: MagicMock) -> None:
    register_zim_query(server)
    fn, _ = server._tools_store["zim_query"]
    result = await fn(query="x", limit=0)
    assert result["error"] is True
    assert result["operation"] == "invalid_limit"


@pytest.mark.asyncio
async def test_zim_query_rejects_negative_offset(server: MagicMock) -> None:
    register_zim_query(server)
    fn, _ = server._tools_store["zim_query"]
    result = await fn(query="x", offset=-3)
    assert result["error"] is True
    assert result["operation"] == "invalid_offset"


@pytest.mark.asyncio
async def test_zim_query_handles_missing_handler(server: MagicMock) -> None:
    """The b13 code returned a static error string when the simple_tools
    handler hadn't been initialized — preserve that envelope."""
    server.simple_tools_handler = None
    register_zim_query(server)
    fn, _ = server._tools_store["zim_query"]
    result = await fn(query="x")
    assert "not initialized" in result
