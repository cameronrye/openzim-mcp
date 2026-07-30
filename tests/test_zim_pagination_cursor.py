"""Cursor-pagination wiring for the advanced ``zim_browse`` / ``zim_links`` tools.

These tools historically accepted a ``cursor`` argument the handler never read,
so a documented resume contract was a silent no-op. The tests below pin the
wiring: an encoded cursor resumes at the right offset / walk state, forwards the
archive identity, and a cursor that was issued by another tool, for another
namespace/entry, or is undecodable is rejected with a structured error rather
than silently restarting at page 1.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.pagination import Cursor
from openzim_mcp.security import PathValidator
from openzim_mcp.tools.zim_browse import register as register_zim_browse
from openzim_mcp.tools.zim_links import register as register_zim_links
from openzim_mcp.zim_operations import ZimOperations


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
        "/x.zim",
        namespace="C",
        limit=50,
        offset=20,
        cursor_archive_identity="abc",
        include_assets=False,
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
        include_assets=False,
    )


@pytest.mark.asyncio
async def test_walk_mode_resumes_from_emitted_cursor(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cursor as the walkers actually emit it (key ``o``) resumes at its
    scan position instead of silently restarting at entry 0."""
    ops = _patch_async_ops(monkeypatch, walk_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    cursor = Cursor.encode(
        tool="walk_namespace", state={"o": 200, "l": 200, "ns": "C", "ai": "zz"}
    )
    await fn(zim_file_path="/x.zim", namespace="C", mode="walk", cursor=cursor)
    ops.walk_namespace_data.assert_awaited_once_with(
        "/x.zim",
        "C",
        cursor_state={"scan_at": 200, "l": 200, "ns": "C", "ai": "zz"},
        limit=200,
        include_assets=False,
    )


@pytest.mark.asyncio
async def test_page_mode_resumes_with_lowercase_namespace(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cursor encodes the canonical namespace ('C'), so repeating the
    lowercase spelling that succeeded on page 1 must resume, not reject."""
    ops = _patch_async_ops(monkeypatch, browse_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    cursor = Cursor.encode(
        tool="browse_namespace", state={"o": 20, "l": 50, "ns": "C", "ai": "abc"}
    )
    result = await fn(
        zim_file_path="/x.zim", namespace="c", mode="page", cursor=cursor, limit=50
    )
    assert result == {"results": []}
    ops.browse_namespace_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_page_mode_resumes_with_longform_namespace(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The long-form alias 'content' canonicalises to 'C' in the data layer,
    so a resume spelled the same way must not be rejected."""
    ops = _patch_async_ops(monkeypatch, browse_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    cursor = Cursor.encode(
        tool="browse_namespace", state={"o": 20, "l": 50, "ns": "C", "ai": "abc"}
    )
    result = await fn(
        zim_file_path="/x.zim",
        namespace="content",
        mode="page",
        cursor=cursor,
        limit=50,
    )
    assert result == {"results": []}
    ops.browse_namespace_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_walk_mode_resumes_with_lowercase_namespace(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Walk cursors encode the canonical namespace too, so a lowercase
    replay must resume the walk instead of rejecting it."""
    ops = _patch_async_ops(monkeypatch, walk_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    cursor = Cursor.encode(
        tool="walk_namespace", state={"o": 200, "l": 200, "ns": "M", "ai": "zz"}
    )
    result = await fn(zim_file_path="/x.zim", namespace="m", mode="walk", cursor=cursor)
    assert result == {"results": []}
    ops.walk_namespace_data.assert_awaited_once()


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
async def test_page_mode_cursor_adopts_pinned_assets_flag(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resuming with only the cursor (include_assets back at its default)
    must reuse the flag the cursor was issued under, not silently flip the
    row stream the offset was counted against."""
    ops = _patch_async_ops(monkeypatch, browse_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    cursor = Cursor.encode(
        tool="browse_namespace",
        state={"o": 50, "l": 50, "ns": "C", "ai": "abc", "as": True},
    )
    await fn(
        zim_file_path="/x.zim", namespace="C", mode="page", cursor=cursor, limit=50
    )
    ops.browse_namespace_data.assert_awaited_once_with(
        "/x.zim",
        namespace="C",
        limit=50,
        offset=50,
        cursor_archive_identity="abc",
        include_assets=True,
    )


@pytest.mark.asyncio
async def test_page_mode_cursor_assets_contradiction_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit include_assets=True contradicting the cursor's pinned
    flag is rejected rather than silently misaligning the pages."""
    _patch_async_ops(monkeypatch, browse_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    cursor = Cursor.encode(
        tool="browse_namespace",
        state={"o": 50, "l": 50, "ns": "C", "ai": "abc", "as": False},
    )
    result = await fn(
        zim_file_path="/x.zim",
        namespace="C",
        mode="page",
        cursor=cursor,
        include_assets=True,
    )
    assert result["operation"] == "cursor_context_mismatch"


@pytest.mark.asyncio
async def test_walk_mode_cursor_adopts_pinned_assets_flag(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A walk resume with only the cursor adopts the pinned assets flag."""
    ops = _patch_async_ops(monkeypatch, walk_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    cursor = Cursor.encode(
        tool="walk_namespace",
        state={"o": 200, "l": 200, "ns": "C", "ai": "zz", "as": True},
    )
    await fn(zim_file_path="/x.zim", namespace="C", mode="walk", cursor=cursor)
    ops.walk_namespace_data.assert_awaited_once_with(
        "/x.zim",
        "C",
        cursor_state={"scan_at": 200, "l": 200, "ai": "zz", "ns": "C"},
        limit=200,
        include_assets=True,
    )


# --------------------------------------------------------------------------
# cursor issuance — the assets flag is pinned where the cursor is built
# --------------------------------------------------------------------------


def _assets_ops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ZimOperations:
    """ZimOperations over a mocked new-scheme C archive that interleaves an
    asset with real articles, so browse/walk emit a resume cursor."""
    entries = ["_zim_static/wombat.js", "Apple", "Banana", "Cherry"]
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
    )
    ops = ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(),
    )
    archive = MagicMock()
    archive.has_new_namespace_scheme = True
    archive.entry_count = len(entries)

    def _by_id(i: int) -> MagicMock:
        entry = MagicMock()
        entry.path = entries[i]
        entry.title = entries[i]
        entry.is_redirect = False
        item = MagicMock()
        item.mimetype = "text/html"
        entry.get_item.return_value = item
        return entry

    archive._get_entry_by_id.side_effect = _by_id
    monkeypatch.setattr(
        "openzim_mcp.zim_operations.zim_archive",
        lambda *a, **kw: contextlib.nullcontext(archive),
    )
    monkeypatch.setattr(
        "openzim_mcp.pagination.archive_identity", lambda *a, **kw: "test-id"
    )
    ops.path_validator = MagicMock()
    ops.path_validator.validate_path.return_value = str(tmp_path / "x.zim")
    ops.path_validator.validate_zim_file.return_value = str(tmp_path / "x.zim")
    monkeypatch.setattr(
        ops,
        "_materialise_browse_entry",
        lambda archive, path, has_new_scheme: {"path": path, "title": path},
    )
    return ops


@pytest.mark.parametrize("flag", [True, False])
def test_browse_cursor_pins_include_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: bool
) -> None:
    """The browse cursor records the assets flag its offset was counted
    under: ``o`` is a content-row offset against the filtered row stream, so
    a bare-cursor follow-up must stay on the same stream."""
    ops = _assets_ops(tmp_path, monkeypatch)
    page = ops.browse_namespace_data(
        str(tmp_path / "x.zim"), "C", limit=1, include_assets=flag
    )
    state = dict(
        Cursor.decode(page["next_cursor"], expected_tool="browse_namespace")["s"]
    )
    assert state["as"] is flag


def test_walk_cursor_pins_include_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Walk cursors pin the flag too, so an exhaustive walk started with
    assets visible keeps them visible across bare resumes."""
    ops = _assets_ops(tmp_path, monkeypatch)
    page = ops.walk_namespace_data(
        str(tmp_path / "x.zim"), "C", limit=1, include_assets=True
    )
    state = dict(
        Cursor.decode(page["next_cursor"], expected_tool="walk_namespace")["s"]
    )
    assert state["as"] is True


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
        "/x.zim",
        "A/Cat",
        limit=100,
        offset=30,
        kind="internal",
        cursor_archive_identity="qq",
    )


@pytest.mark.asyncio
async def test_outbound_cursor_honors_kind(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cursor encoding the 'media' bucket resumes against that bucket even
    when `kind` is left at its default (BUG #2: state['k'] is honoured)."""
    ops = _patch_async_ops(monkeypatch, extract_article_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    cursor = Cursor.encode(
        tool="extract_article_links",
        state={"o": 30, "l": 100, "ep": "A/Cat", "k": "media", "ai": "qq"},
    )
    await fn(
        zim_file_path="/x.zim",
        entry_path="A/Cat",
        direction="outbound",
        cursor=cursor,
        limit=100,
    )
    ops.extract_article_links_data.assert_awaited_once_with(
        "/x.zim",
        "A/Cat",
        limit=100,
        offset=30,
        kind="media",
        cursor_archive_identity="qq",
    )


@pytest.mark.asyncio
async def test_outbound_cursor_kind_mismatch_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit non-default `kind` that contradicts the cursor's bucket is
    rejected rather than silently resuming the wrong bucket."""
    _patch_async_ops(monkeypatch, extract_article_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    cursor = Cursor.encode(
        tool="extract_article_links",
        state={"o": 5, "ep": "A/Cat", "k": "external"},
    )
    result = await fn(
        zim_file_path="/x.zim",
        entry_path="A/Cat",
        direction="outbound",
        kind="media",
        cursor=cursor,
    )
    assert result["operation"] == "cursor_context_mismatch"


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
