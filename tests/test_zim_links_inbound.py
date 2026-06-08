"""Tests for the ``zim_links`` inbound direction (link-graph sidecar).

``direction="inbound"`` dispatches to ``get_inbound_links_data`` and turns
a missing/stale sidecar into a structured ``inbound_sidecar_unavailable``
error. Cursor handling mirrors the outbound path: a foreign-tool cursor or
an entry-mismatched cursor is rejected rather than silently restarted.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.linkgraph.reader import LinkGraphUnavailable
from openzim_mcp.pagination import Cursor
from openzim_mcp.tools.zim_links import register as register_zim_links


@pytest.fixture
def server() -> MagicMock:
    """Return a stand-in server whose ``mcp.tool`` decorator stores the fn."""
    srv = MagicMock()
    tools_store: dict[str, Any] = {}

    def _tool(*, description: str = ""):
        def decorate(fn: Any) -> Any:
            tools_store[fn.__name__] = (fn, description)
            return fn

        return decorate

    srv.mcp.tool = _tool
    srv._tools_store = tools_store
    return srv


def _patch_async_ops(
    monkeypatch: pytest.MonkeyPatch, **method_returns: Any
) -> MagicMock:
    """Patch AsyncZimOperations so each named data method is an AsyncMock."""
    mock_ops = MagicMock()
    for name, value in method_returns.items():
        setattr(mock_ops, name, AsyncMock(return_value=value))
    monkeypatch.setattr(
        "openzim_mcp.async_operations.AsyncZimOperations",
        lambda _zim_ops: mock_ops,
    )
    return mock_ops


@pytest.mark.asyncio
async def test_inbound_dispatches_to_data_method(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`direction='inbound'` awaits get_inbound_links_data exactly once."""
    ops = _patch_async_ops(
        monkeypatch, get_inbound_links_data={"results": [], "total": 0}
    )
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat", direction="inbound")
    ops.get_inbound_links_data.assert_awaited_once_with(
        "/x.zim", "A/Cat", limit=10, offset=0, cursor_archive_identity=None
    )


@pytest.mark.asyncio
async def test_inbound_missing_sidecar_is_structured_error(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing/stale sidecar surfaces as inbound_sidecar_unavailable."""
    ops = _patch_async_ops(monkeypatch, get_inbound_links_data=None)
    ops.get_inbound_links_data.side_effect = LinkGraphUnavailable(
        "No sidecar; run `openzim-mcp build link-graph` first."
    )
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    result = await fn(zim_file_path="/x.zim", entry_path="A/Cat", direction="inbound")
    assert result["operation"] == "inbound_sidecar_unavailable"
    assert "build link-graph" in result["message"]


@pytest.mark.asyncio
async def test_inbound_foreign_cursor_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cursor issued by another tool must be rejected on the inbound path."""
    _patch_async_ops(monkeypatch, get_inbound_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    cursor = Cursor.encode(tool="walk_namespace", state={"scan_at": 1})
    result = await fn(
        zim_file_path="/x.zim", entry_path="A/Cat", direction="inbound", cursor=cursor
    )
    assert result["operation"] == "cursor_mismatch"


@pytest.mark.asyncio
async def test_inbound_entry_mismatch_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cursor issued for one entry must not resume against a different one."""
    _patch_async_ops(monkeypatch, get_inbound_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    cursor = Cursor.encode(tool="get_inbound_links", state={"o": 5, "ep": "C/Other"})
    result = await fn(
        zim_file_path="/x.zim", entry_path="C/T", direction="inbound", cursor=cursor
    )
    assert result["operation"] == "cursor_context_mismatch"
