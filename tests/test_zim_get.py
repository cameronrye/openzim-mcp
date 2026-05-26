"""Tests for the Phase F ``zim_get`` tool (Task D5).

zim_get is the 4-branch oneOf collapse (7 legacy tools → 1). Tests
cover the branch-validation matrix + each branch's dispatch target.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.tools.zim_get import register as register_zim_get


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


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_zim_get_registers(server: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    assert "zim_get" in server._tools_store


def test_zim_get_description_attached(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    _, description = server._tools_store["zim_get"]
    assert "Fetch entries from a ZIM archive" in description
    assert "main_page" in description


# ---------------------------------------------------------------------------
# Branch dispatch (happy paths)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_entry_full_view(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_zim_entry_data={"content": "body"})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat")
    ops.get_zim_entry_data.assert_awaited_once_with(
        "/x.zim",
        "A/Cat",
        max_content_length=None,
        content_offset=0,
        compact=False,
    )


@pytest.mark.asyncio
async def test_single_entry_summary_view(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_entry_summary_data={"summary": "..."})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat", view="summary")
    ops.get_entry_summary_data.assert_awaited_once_with(
        "/x.zim", "A/Cat", compact=False
    )


@pytest.mark.asyncio
async def test_single_entry_toc_view(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_table_of_contents_data={"toc": []})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat", view="toc")
    ops.get_table_of_contents_data.assert_awaited_once_with("/x.zim", "A/Cat")


@pytest.mark.asyncio
async def test_single_entry_structure_view(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_article_structure_data={"sections": []})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat", view="structure")
    ops.get_article_structure_data.assert_awaited_once_with("/x.zim", "A/Cat")


@pytest.mark.asyncio
async def test_single_entry_binary(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_binary_entry_data={"bytes": b"png"})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", entry_path="I/cat.png", binary=True)
    ops.get_binary_entry_data.assert_awaited_once_with("/x.zim", "I/cat.png")


@pytest.mark.asyncio
async def test_batch_dispatches_to_get_entries(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_entries_data={"results": []})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", entry_paths=["A/Cat", "A/Dog"])
    ops.get_entries_data.assert_awaited_once_with(
        [
            {"zim_file_path": "/x.zim", "entry_path": "A/Cat"},
            {"zim_file_path": "/x.zim", "entry_path": "A/Dog"},
        ],
        max_content_length=None,
        compact=False,
    )


@pytest.mark.asyncio
async def test_main_page(server: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    ops = _patch_async_ops(monkeypatch, get_main_page_data={"content": "Welcome"})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", main_page=True)
    ops.get_main_page_data.assert_awaited_once_with("/x.zim")


@pytest.mark.asyncio
async def test_compact_default_is_false(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v2.0 preserves legacy get_zim_entry behavior — compact=False default."""
    ops = _patch_async_ops(monkeypatch, get_zim_entry_data={"content": "body"})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat")
    _, kwargs = ops.get_zim_entry_data.call_args
    assert kwargs["compact"] is False


# ---------------------------------------------------------------------------
# Invalid branch combinations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entry_path_and_entry_paths_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", entry_path="A", entry_paths=["B"])
    assert result["operation"] == "invalid_path_combination"


@pytest.mark.asyncio
async def test_binary_with_batch_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", entry_paths=["A"], binary=True)
    assert result["operation"] == "invalid_path_combination"


@pytest.mark.asyncio
async def test_binary_with_non_full_view_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(
        zim_file_path="/x.zim", entry_path="A", binary=True, view="summary"
    )
    assert result["operation"] == "invalid_path_combination"


@pytest.mark.asyncio
async def test_main_page_with_entry_path_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", main_page=True, entry_path="A")
    assert result["operation"] == "invalid_path_combination"


@pytest.mark.asyncio
async def test_main_page_with_non_full_view_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", main_page=True, view="summary")
    assert result["operation"] == "invalid_path_combination"


@pytest.mark.asyncio
async def test_no_path_branch_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim")  # no path / paths / main_page
    assert result["operation"] == "invalid_path_combination"


@pytest.mark.asyncio
async def test_invalid_view_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", entry_path="A", view="bogus")  # type: ignore[arg-type]
    assert result["operation"] == "invalid_view"
