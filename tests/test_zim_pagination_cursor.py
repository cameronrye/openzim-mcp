"""Cursor-pagination wiring for the advanced ``zim_browse`` / ``zim_links`` tools.

These tools historically accepted a ``cursor`` argument the handler never read,
so a documented resume contract was a silent no-op. The tests below pin the
wiring: an encoded cursor resumes at the right offset / walk state, forwards the
archive identity, and a cursor that was issued by another tool, for another
namespace/entry, or is undecodable is rejected with a structured error rather
than silently restarting at page 1.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.pagination import Cursor
from openzim_mcp.tools.zim_browse import register as register_zim_browse
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


# --------------------------------------------------------------------------
# zim_browse
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_page_mode_resumes_from_cursor(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A browse cursor resumes at its offset and forwards the archive identity."""
    ops = _patch_async_ops(monkeypatch, browse_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    cursor = Cursor.encode(
        tool="browse_namespace", state={"o": 20, "l": 50, "ns": "C", "ai": "abc"}
    )
    await fn(
        zim_file_path="/x.zim", namespace="C", mode="page", cursor=cursor, limit=50
    )
    ops.browse_namespace_data.assert_awaited_once_with(
        "/x.zim", namespace="C", limit=50, offset=20, cursor_archive_identity="abc"
    )


@pytest.mark.asyncio
async def test_walk_mode_resumes_from_cursor(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A walk cursor passes its decoded state through to walk_namespace_data."""
    ops = _patch_async_ops(monkeypatch, walk_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    cursor = Cursor.encode(
        tool="walk_namespace", state={"scan_at": 500, "l": 200, "ns": "A", "ai": "zz"}
    )
    await fn(zim_file_path="/x.zim", namespace="A", mode="walk", cursor=cursor)
    ops.walk_namespace_data.assert_awaited_once_with(
        "/x.zim",
        "A",
        cursor_state={"scan_at": 500, "l": 200, "ns": "A", "ai": "zz"},
        limit=200,
    )


@pytest.mark.asyncio
async def test_page_mode_rejects_foreign_tool_cursor(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A walk cursor must not be accepted by browse page mode."""
    _patch_async_ops(monkeypatch, browse_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    cursor = Cursor.encode(tool="walk_namespace", state={"scan_at": 5})
    result = await fn(zim_file_path="/x.zim", namespace="C", mode="page", cursor=cursor)
    assert result["operation"] == "cursor_mismatch"


@pytest.mark.asyncio
async def test_page_mode_rejects_namespace_mismatch(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cursor issued for namespace C must not resume against namespace M."""
    _patch_async_ops(monkeypatch, browse_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    cursor = Cursor.encode(tool="browse_namespace", state={"o": 10, "ns": "C"})
    result = await fn(zim_file_path="/x.zim", namespace="M", mode="page", cursor=cursor)
    assert result["operation"] == "cursor_context_mismatch"


@pytest.mark.asyncio
async def test_garbled_cursor_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An undecodable cursor returns a structured error, not page 1."""
    _patch_async_ops(monkeypatch, browse_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    result = await fn(
        zim_file_path="/x.zim", namespace="C", mode="page", cursor="!!not-base64!!"
    )
    assert result["operation"] == "cursor_decode"


# --------------------------------------------------------------------------
# zim_links
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outbound_resumes_from_cursor(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An outbound-links cursor resumes at its offset and forwards identity."""
    ops = _patch_async_ops(monkeypatch, extract_article_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    cursor = Cursor.encode(
        tool="extract_article_links",
        state={"o": 30, "l": 100, "ep": "A/Cat", "ai": "qq"},
    )
    await fn(
        zim_file_path="/x.zim",
        entry_path="A/Cat",
        direction="outbound",
        cursor=cursor,
        limit=100,
    )
    ops.extract_article_links_data.assert_awaited_once_with(
        "/x.zim", "A/Cat", limit=100, offset=30, cursor_archive_identity="qq"
    )


@pytest.mark.asyncio
async def test_related_rejects_cursor(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`direction='related'` does not paginate, so a cursor must be rejected."""
    _patch_async_ops(monkeypatch, get_related_articles_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    cursor = Cursor.encode(tool="extract_article_links", state={"o": 5})
    result = await fn(
        zim_file_path="/x.zim", entry_path="A/Cat", direction="related", cursor=cursor
    )
    assert result["operation"] == "cursor_unsupported"


@pytest.mark.asyncio
async def test_outbound_rejects_foreign_tool_cursor(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cursor issued by another tool must be rejected on the outbound path."""
    _patch_async_ops(monkeypatch, extract_article_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    cursor = Cursor.encode(tool="walk_namespace", state={"scan_at": 5})
    result = await fn(
        zim_file_path="/x.zim", entry_path="A/Cat", direction="outbound", cursor=cursor
    )
    assert result["operation"] == "cursor_mismatch"


@pytest.mark.asyncio
async def test_outbound_rejects_entry_mismatch(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cursor issued for one entry must not resume against a different one."""
    _patch_async_ops(monkeypatch, extract_article_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    cursor = Cursor.encode(tool="extract_article_links", state={"o": 5, "ep": "A/Dog"})
    result = await fn(
        zim_file_path="/x.zim", entry_path="A/Cat", direction="outbound", cursor=cursor
    )
    assert result["operation"] == "cursor_context_mismatch"
