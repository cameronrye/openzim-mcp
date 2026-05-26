"""Tests for the Phase F ``zim_search`` tool (Task D4).

zim_search is the load-bearing Criterion D cell from Gate 0b — the
3-mode dispatch (fulltext / title / suggest) plus the conditional
single-archive title-mode promotion path. These tests mock the
underlying data layer and verify:

  - Registration shape (tool name + description attached)
  - Each mode's invalid-combination matrix (cross_file × suggest,
    namespace × cross-archive, zim_file_path × cross_file)
  - Title mode wires Tier 1 preprocessing + Z3/Z4/OPP-1 promotion
    only on the single-archive path
  - Cross-archive title mode disables promotion and surfaces the
    hint
  - Suggest mode rejects cross_file=True with invalid_combination
  - Auto-archive resolution kicks in when zim_file_path is omitted
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openzim_mcp.tools.zim_search import register as register_zim_search


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
    # auto_select returns a single archive path by default.
    return srv


def _patch_async_ops(monkeypatch: pytest.MonkeyPatch, **method_returns: Any) -> Any:
    """Patch AsyncZimOperations construction so the tool's `ops` is a mock."""
    mock_ops = MagicMock()
    for name, value in method_returns.items():
        mock = AsyncMock(return_value=value)
        setattr(mock_ops, name, mock)
    monkeypatch.setattr(
        "openzim_mcp.tools.zim_search.AsyncZimOperations",
        lambda _zim_ops: mock_ops,
        raising=False,
    )
    # The "from ..async_operations import AsyncZimOperations" inside register()
    # needs the module-level constructor patched too.
    monkeypatch.setattr(
        "openzim_mcp.async_operations.AsyncZimOperations",
        lambda _zim_ops: mock_ops,
    )
    return mock_ops


# ---------------------------------------------------------------------------
# Registration shape
# ---------------------------------------------------------------------------


def test_zim_search_registers(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_search(server)
    assert "zim_search" in server._tools_store


def test_zim_search_description_attached(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_search(server)
    _fn, description = server._tools_store["zim_search"]
    assert "three modes" in description.lower()
    assert "suggest" in description.lower()


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zim_search_rejects_invalid_mode(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_search(server)
    fn, _ = server._tools_store["zim_search"]
    result = await fn(query="x", mode="grep")  # type: ignore[arg-type]
    assert result["operation"] == "invalid_mode"


@pytest.mark.asyncio
async def test_zim_search_rejects_zim_file_path_with_cross_file(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_search(server)
    fn, _ = server._tools_store["zim_search"]
    result = await fn(query="x", zim_file_path="/data/a.zim", cross_file=True)
    assert result["operation"] == "invalid_combination"


@pytest.mark.asyncio
async def test_zim_search_rejects_negative_offset(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_search(server)
    fn, _ = server._tools_store["zim_search"]
    result = await fn(query="x", offset=-1)
    assert result["operation"] == "invalid_offset"


# ---------------------------------------------------------------------------
# Suggest mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggest_rejects_cross_file(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_search(server)
    fn, _ = server._tools_store["zim_search"]
    result = await fn(query="prefix", mode="suggest", cross_file=True)
    assert result["operation"] == "invalid_combination"
    assert "SuggestionSearcher" in result["message"]


@pytest.mark.asyncio
async def test_suggest_calls_suggestions_data(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(
        monkeypatch, get_search_suggestions_data={"results": ["Detroit"]}
    )
    with patch(
        "openzim_mcp.topic_preprocessing.auto_select_zim_file",
        return_value="/data/wiki.zim",
    ):
        register_zim_search(server)
        fn, _ = server._tools_store["zim_search"]
        result = await fn(query="Det", mode="suggest")
    ops.get_search_suggestions_data.assert_awaited_once_with(
        "/data/wiki.zim", "Det", 10
    )
    assert result == {"results": ["Detroit"]}


# ---------------------------------------------------------------------------
# Fulltext mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fulltext_single_archive_passes_through(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, search_zim_file_data={"results": []})
    with patch(
        "openzim_mcp.topic_preprocessing.auto_select_zim_file",
        return_value="/data/wiki.zim",
    ):
        register_zim_search(server)
        fn, _ = server._tools_store["zim_search"]
        await fn(query="rome", mode="fulltext", limit=5)
    ops.search_zim_file_data.assert_awaited_once_with(
        "/data/wiki.zim", "rome", limit=5, offset=0
    )


@pytest.mark.asyncio
async def test_fulltext_cross_file_uses_search_all(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, search_all_data={"results": []})
    register_zim_search(server)
    fn, _ = server._tools_store["zim_search"]
    await fn(query="rome", mode="fulltext", cross_file=True, limit=3)
    ops.search_all_data.assert_awaited_once_with("rome", limit_per_file=3)


@pytest.mark.asyncio
async def test_fulltext_with_filters_uses_filters_data(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, search_with_filters_data={"results": []})
    with patch(
        "openzim_mcp.topic_preprocessing.auto_select_zim_file",
        return_value="/data/wiki.zim",
    ):
        register_zim_search(server)
        fn, _ = server._tools_store["zim_search"]
        await fn(query="cats", mode="fulltext", namespace="A", content_type="text/html")
    ops.search_with_filters_data.assert_awaited_once_with(
        "/data/wiki.zim",
        "cats",
        namespace="A",
        content_type="text/html",
        limit=None,
        offset=0,
    )


@pytest.mark.asyncio
async def test_fulltext_filter_with_cross_file_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch, search_all_data={"results": []})
    register_zim_search(server)
    fn, _ = server._tools_store["zim_search"]
    result = await fn(query="cats", mode="fulltext", cross_file=True, namespace="A")
    assert result["operation"] == "invalid_combination"


# ---------------------------------------------------------------------------
# Title mode — wired path applies preprocessing + promotion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_title_single_archive_applies_promotion(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wired path: preprocessing + promotion are applied on single-
    archive title mode. The mock promotion returns a row that gets
    hoisted to the top of `results`."""
    ops = _patch_async_ops(
        monkeypatch,
        find_entry_by_title_data={
            "results": [
                {"entry_path": "Tesla's_Wireless_Electricity", "title": "Wireless"},
                {"entry_path": "Nikola_Tesla", "title": "Tesla"},
            ],
            "_meta": {},
        },
    )
    with (
        patch(
            "openzim_mcp.topic_preprocessing.auto_select_zim_file",
            return_value="/data/wiki.zim",
        ),
        patch(
            "openzim_mcp.topic_preprocessing.promote_topic_via_title_index",
            return_value={"entry_path": "Nikola_Tesla", "title": "Tesla"},
        ),
    ):
        register_zim_search(server)
        fn, _ = server._tools_store["zim_search"]
        result = await fn(query="Tesla electricity", mode="title")

    # Promotion hoisted Nikola_Tesla to the top, displacing Wireless_Electricity.
    assert result["results"][0]["entry_path"] == "Nikola_Tesla"
    assert result["_meta"]["promotion_applied"] is True
    ops.find_entry_by_title_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_title_cross_file_disables_promotion(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Promotion is per-archive — cross-archive title mode must NOT
    apply Z3/Z4/OPP-1, and must surface the hint in _meta."""
    ops = _patch_async_ops(
        monkeypatch,
        find_entry_by_title_data={
            "results": [{"entry_path": "X", "title": "X"}],
            "_meta": {},
        },
    )
    with patch(
        "openzim_mcp.topic_preprocessing.promote_topic_via_title_index"
    ) as promote_mock:
        register_zim_search(server)
        fn, _ = server._tools_store["zim_search"]
        result = await fn(query="Tesla electricity", mode="title", cross_file=True)

    promote_mock.assert_not_called()
    assert result["_meta"]["promotion_applied"] is False
    assert "per-archive" in result["_meta"]["hint"]
    ops.find_entry_by_title_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_title_promotion_returning_none_passes_through(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When promotion rejects all candidates (returns None), raw
    title-lookup results pass through unchanged."""
    raw = {
        "results": [{"entry_path": "Detroit", "title": "Detroit"}],
        "_meta": {},
    }
    _patch_async_ops(monkeypatch, find_entry_by_title_data=raw)
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
        result = await fn(query="Detroit", mode="title")
    assert result["results"][0]["entry_path"] == "Detroit"
    assert "promotion_applied" not in result["_meta"]


@pytest.mark.asyncio
async def test_title_no_archive_returns_structured_error(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No archive available + single-archive title mode → clean
    missing_archive error rather than guessing."""
    _patch_async_ops(monkeypatch, find_entry_by_title_data={"results": []})
    with patch(
        "openzim_mcp.topic_preprocessing.auto_select_zim_file",
        return_value=None,
    ):
        register_zim_search(server)
        fn, _ = server._tools_store["zim_search"]
        result = await fn(query="x", mode="title")
    assert result["operation"] == "missing_archive"
