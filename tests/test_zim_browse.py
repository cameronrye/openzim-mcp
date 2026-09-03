"""Tests for the Phase F ``zim_browse`` tool (Task D7).

Collapses ``browse_namespace`` + ``walk_namespace`` via the ``mode``
parameter.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.pagination import Cursor
from openzim_mcp.tools.zim_browse import register as register_zim_browse


@pytest.fixture
def server() -> MagicMock:
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
    mock_ops = MagicMock()
    for name, value in method_returns.items():
        setattr(mock_ops, name, AsyncMock(return_value=value))
    monkeypatch.setattr(
        "openzim_mcp.async_operations.AsyncZimOperations",
        lambda _zim_ops: mock_ops,
    )
    return mock_ops


def test_zim_browse_registers(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_browse(server)
    assert "zim_browse" in server._tools_store


@pytest.mark.asyncio
async def test_page_mode_dispatches_to_browse_namespace(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, browse_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    await fn(zim_file_path="/x.zim", namespace="C", limit=10)
    ops.browse_namespace_data.assert_awaited_once_with(
        "/x.zim", namespace="C", limit=10, offset=0, include_assets=False
    )


@pytest.mark.asyncio
async def test_page_mode_threads_include_assets(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG #8: include_assets=True is forwarded so asset entries can be
    discovered (then fetched via zim_get(binary=True))."""
    ops = _patch_async_ops(monkeypatch, browse_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    await fn(zim_file_path="/x.zim", namespace="C", limit=10, include_assets=True)
    ops.browse_namespace_data.assert_awaited_once_with(
        "/x.zim", namespace="C", limit=10, offset=0, include_assets=True
    )


@pytest.mark.asyncio
async def test_walk_mode_dispatches_to_walk_namespace(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, walk_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    await fn(zim_file_path="/x.zim", namespace="A", mode="walk")
    ops.walk_namespace_data.assert_awaited_once_with(
        "/x.zim", "A", limit=200, include_assets=False
    )


@pytest.mark.asyncio
async def test_invalid_mode_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    result = await fn(zim_file_path="/x.zim", namespace="C", mode="grep")  # type: ignore[arg-type]
    assert result["operation"] == "invalid_mode"


# ---------------------------------------------------------------------------
# walk resumes by cursor, never by a bare offset
#
# ``walk_namespace_data`` has no offset parameter, so a bare ``offset`` here
# was accepted and dropped: the caller got page one back, indistinguishable
# from an exhausted namespace. Page mode's offset is load-bearing and
# unaffected. A cursor *plus* an offset is not that defect — the offset loses
# to the cursor, which is the precedence rule every paginating tool follows —
# so the walk must still resume, and that is what
# ``test_walk_with_a_cursor_still_resumes_when_an_offset_tags_along`` pins.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_walk_rejects_offset(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, walk_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    result = await fn(
        zim_file_path="/x.zim", namespace="C", mode="walk", limit=3, offset=3
    )
    assert result.get("operation") == "invalid_combination", (
        f"a bare `offset` was accepted in mode='walk' and silently discarded; "
        f"got {result!r}"
    )
    assert "`offset`" in result["message"]
    assert "walk" in result["message"]
    assert "cursor" in result["message"]
    ops.walk_namespace_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_walk_without_offset_still_dispatches(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, walk_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    await fn(zim_file_path="/x.zim", namespace="C", mode="walk", limit=3)
    ops.walk_namespace_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_page_mode_still_honours_offset(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard is walk-only."""
    ops = _patch_async_ops(monkeypatch, browse_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    await fn(zim_file_path="/x.zim", namespace="C", mode="page", limit=3, offset=3)
    assert ops.browse_namespace_data.await_args.kwargs["offset"] == 3


@pytest.mark.asyncio
async def test_walk_with_a_cursor_still_resumes_when_an_offset_tags_along(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cursor resume is not the silent-drop defect, so it must not be
    rejected alongside it.

    The Cursors section of the API reference states the precedence rule for
    every paginating tool: an explicit `offset` *loses* to a cursor. A client
    that keeps sending the offset it started the run from — or that fills the
    argument from a template — was resuming correctly before the bare-offset
    guard existed, and still has to.
    """
    ops = _patch_async_ops(monkeypatch, walk_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    cursor = Cursor.encode(
        tool="walk_namespace", state={"o": 42, "l": 3, "ns": "C", "ai": "qq"}
    )

    result = await fn(
        zim_file_path="/x.zim",
        namespace="C",
        mode="walk",
        limit=3,
        cursor=cursor,
        offset=3,
    )

    assert result == {"results": []}, (
        f"a cursor-driven walk was rejected because an offset came with it; "
        f"got {result!r}"
    )
    ops.walk_namespace_data.assert_awaited_once()
    assert ops.walk_namespace_data.await_args.kwargs["cursor_state"]["scan_at"] == 42


@pytest.mark.asyncio
async def test_walk_reports_a_bad_cursor_before_the_offset_guard(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cursor fault is the specific one; report it, not the offset."""
    ops = _patch_async_ops(monkeypatch, walk_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]

    result = await fn(
        zim_file_path="/x.zim",
        namespace="C",
        mode="walk",
        limit=3,
        cursor="not-a-cursor",
        offset=3,
    )

    assert result["operation"] == "cursor_decode"
    ops.walk_namespace_data.assert_not_awaited()
