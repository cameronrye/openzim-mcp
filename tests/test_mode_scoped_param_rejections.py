"""A parameter a mode cannot honour must be rejected, never dropped.

Every consolidated tool takes one flat argument list and dispatches on a
``mode`` / ``direction`` / ``view`` discriminator, so each surface carries
arguments only some branches can act on. Where a branch cannot act on one,
the wrapper has two options: reject the call with a structured envelope, or
drop the argument and answer as if it had never been passed.

Dropping is the worse of the two, and the failure is invisible from the
response. ``zim_search(mode="title", namespace="A")`` returned unfiltered
title hits — the model asked for one namespace, got every namespace, and
nothing in the payload said the filter had been discarded. The same shape
sat in three siblings: ``zim_links`` validated ``kind`` and then used it on
``direction="outbound"`` only; ``zim_links(direction="related")`` rejected a
``cursor`` (it does not paginate) but silently swallowed an ``offset`` that
does the same thing; ``zim_browse(mode="walk")`` handed back page one for
any ``offset``; and ``zim_get`` honoured ``content_offset`` on exactly one
of its five branches.

These tests pin the rejection for each. They are deliberately paired: every
"rejects X" case has a sibling asserting the *default* value of the same
argument still dispatches, because the cheap way to pass a rejection test is
to reject the whole parameter.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openzim_mcp.tools.zim_browse import register as register_zim_browse
from openzim_mcp.tools.zim_get import register as register_zim_get
from openzim_mcp.tools.zim_links import register as register_zim_links
from openzim_mcp.tools.zim_search import register as register_zim_search


@pytest.fixture
def server() -> MagicMock:
    """A stand-in server whose ``mcp.tool`` decorator stores the handler."""
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
    monkeypatch.setattr(
        "openzim_mcp.tools.zim_search.AsyncZimOperations",
        lambda _zim_ops: mock_ops,
        raising=False,
    )
    return mock_ops


# ---------------------------------------------------------------------------
# zim_search — namespace / content_type are fulltext-only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["title", "suggest"])
@pytest.mark.parametrize(
    "filter_kwargs", [{"namespace": "A"}, {"content_type": "text/html"}]
)
async def test_search_non_fulltext_mode_rejects_filters(
    server: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    filter_kwargs: dict[str, str],
) -> None:
    """A filter the mode cannot apply must not reach the data layer."""
    ops = _patch_async_ops(
        monkeypatch,
        find_entry_by_title_data={"results": [], "_meta": {}},
        get_search_suggestions_data={"suggestions": []},
    )
    with (
        patch(
            "openzim_mcp.topic_preprocessing.auto_select_zim_file",
            return_value="/data/wiki.zim",
        ),
        patch(
            "openzim_mcp.topic_preprocessing.promote_topic_via_title_index",
            return_value=None,
        ),
    ):
        register_zim_search(server)
        fn, _ = server._tools_store["zim_search"]
        result = await fn(query="Detroit", mode=mode, **filter_kwargs)

    param = next(iter(filter_kwargs))
    assert result.get("operation") == "invalid_combination", (
        f"`{param}` was accepted in mode={mode!r} and silently discarded; "
        f"got {result!r}"
    )
    # The message has to name the parameter, the mode, and the way out.
    assert f"`{param}`" in result["message"]
    assert mode in result["message"]
    assert "fulltext" in result["message"]
    ops.find_entry_by_title_data.assert_not_awaited()
    ops.get_search_suggestions_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_suggest_without_filters_still_dispatches(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard must key on the filters, not on the mode."""
    ops = _patch_async_ops(monkeypatch, get_search_suggestions_data={"suggestions": []})
    with patch(
        "openzim_mcp.topic_preprocessing.auto_select_zim_file",
        return_value="/data/wiki.zim",
    ):
        register_zim_search(server)
        fn, _ = server._tools_store["zim_search"]
        await fn(query="Det", mode="suggest")
    ops.get_search_suggestions_data.assert_awaited_once()


# ---------------------------------------------------------------------------
# zim_links — kind is outbound-only; related does not paginate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["inbound", "related"])
@pytest.mark.parametrize("kind", ["external", "media"])
async def test_links_non_outbound_direction_rejects_kind(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch, direction: str, kind: str
) -> None:
    """``kind`` selects an outbound bucket; the other directions have none."""
    ops = _patch_async_ops(
        monkeypatch,
        get_inbound_links_data={"results": []},
        get_related_articles_data={"results": []},
    )
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    result = await fn(
        zim_file_path="/x.zim", entry_path="A/Cat", direction=direction, kind=kind
    )
    assert result.get("operation") == "invalid_combination", (
        f"`kind={kind!r}` was accepted for direction={direction!r} and "
        f"silently discarded; got {result!r}"
    )
    assert "`kind`" in result["message"]
    assert direction in result["message"]
    assert "outbound" in result["message"]
    ops.get_inbound_links_data.assert_not_awaited()
    ops.get_related_articles_data.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["inbound", "related"])
async def test_links_non_outbound_direction_allows_default_kind(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch, direction: str
) -> None:
    """``kind`` defaults to "internal"; that must stay a valid call."""
    ops = _patch_async_ops(
        monkeypatch,
        get_inbound_links_data={"results": []},
        get_related_articles_data={"results": []},
    )
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat", direction=direction)
    if direction == "inbound":
        ops.get_inbound_links_data.assert_awaited_once()
    else:
        ops.get_related_articles_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_links_related_rejects_offset(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``related`` already rejects a cursor; ``offset`` is the same request."""
    ops = _patch_async_ops(monkeypatch, get_related_articles_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    result = await fn(
        zim_file_path="/x.zim", entry_path="A/Cat", direction="related", offset=10
    )
    assert result.get("operation") == "invalid_combination", (
        f"`offset` was accepted for direction='related' and silently "
        f"discarded — every page is page one; got {result!r}"
    )
    assert "`offset`" in result["message"]
    assert "related" in result["message"]
    ops.get_related_articles_data.assert_not_awaited()


# ---------------------------------------------------------------------------
# zim_browse — walk resumes by cursor, never by offset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browse_walk_rejects_offset(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Walk mode never forwarded ``offset``; page one came back regardless."""
    ops = _patch_async_ops(monkeypatch, walk_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    result = await fn(
        zim_file_path="/x.zim", namespace="C", mode="walk", limit=3, offset=3
    )
    assert result.get("operation") == "invalid_combination", (
        f"`offset` was accepted in mode='walk' and silently discarded; "
        f"got {result!r}"
    )
    assert "`offset`" in result["message"]
    assert "walk" in result["message"]
    assert "cursor" in result["message"]
    ops.walk_namespace_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_browse_walk_without_offset_still_dispatches(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, walk_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    await fn(zim_file_path="/x.zim", namespace="C", mode="walk", limit=3)
    ops.walk_namespace_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_browse_page_still_honours_offset(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard is walk-only — page mode's offset is load-bearing."""
    ops = _patch_async_ops(monkeypatch, browse_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    await fn(zim_file_path="/x.zim", namespace="C", mode="page", limit=3, offset=3)
    assert ops.browse_namespace_data.await_args.kwargs["offset"] == 3


# ---------------------------------------------------------------------------
# zim_get — content_offset pages a full single-entry body and nothing else
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("view", ["summary", "toc", "structure"])
async def test_get_non_full_view_rejects_content_offset(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch, view: str
) -> None:
    """Only the ``view='full'`` branch forwards ``content_offset``."""
    ops = _patch_async_ops(
        monkeypatch,
        get_entry_summary_data={"summary": ""},
        get_table_of_contents_data={"toc": []},
        get_article_structure_data={"sections": []},
    )
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(
        zim_file_path="/x.zim", entry_path="A/Cat", view=view, content_offset=500
    )
    assert result.get("operation") == "invalid_path_combination", (
        f"`content_offset` was accepted for view={view!r} and silently "
        f"discarded; got {result!r}"
    )
    assert "content_offset" in result["message"]
    ops.get_entry_summary_data.assert_not_awaited()
    ops.get_table_of_contents_data.assert_not_awaited()
    ops.get_article_structure_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_main_page_rejects_content_offset(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_main_page_data={"content": ""})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", main_page=True, content_offset=500)
    assert result.get("operation") == "invalid_path_combination", (
        f"`content_offset` was accepted for main_page=True and silently "
        f"discarded; got {result!r}"
    )
    ops.get_main_page_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_binary_rejects_content_offset(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_binary_entry_data={"bytes": 0})
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(
        zim_file_path="/x.zim",
        entry_path="I/cat.png",
        binary=True,
        content_offset=500,
    )
    assert result.get("operation") == "invalid_path_combination", (
        f"`content_offset` was accepted for binary=True and silently "
        f"discarded; got {result!r}"
    )
    ops.get_binary_entry_data.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "expected_call"),
    [
        ({"entry_path": "A/Cat", "view": "summary"}, "get_entry_summary_data"),
        ({"main_page": True}, "get_main_page_data"),
        ({"entry_path": "I/cat.png", "binary": True}, "get_binary_entry_data"),
    ],
)
async def test_get_zero_content_offset_still_dispatches(
    server: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, Any],
    expected_call: str,
) -> None:
    """content_offset=0 is the default — it must never trip the guard."""
    ops = _patch_async_ops(
        monkeypatch,
        get_entry_summary_data={"summary": ""},
        get_main_page_data={"content": ""},
        get_binary_entry_data={"bytes": 0},
    )
    register_zim_get(server)
    fn, _ = server._tools_store["zim_get"]
    result = await fn(zim_file_path="/x.zim", content_offset=0, **kwargs)
    assert "operation" not in result, result
    getattr(ops, expected_call).assert_awaited_once()
