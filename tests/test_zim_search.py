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

from openzim_mcp.constants import MAX_SEARCH_RESULT_LIMIT
from openzim_mcp.exceptions import OpenZimMcpValidationError
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


def test_description_documents_title_rows_with_score_not_snippet(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Title-mode rows are FindEntryHit {path, title, score} — the description
    must not claim they carry `snippet`, and must document `score` (the
    ranking signal callers gate on)."""
    _patch_async_ops(monkeypatch)
    register_zim_search(server)
    _fn, description = server._tools_store["zim_search"]
    assert "fulltext/title rows carry" not in description
    assert "title rows carry" in description
    assert "`score`" in description


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


@pytest.mark.asyncio
async def test_zim_search_rejects_limit_above_ceiling(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A limit past the ceiling would ask the data layer to materialise an
    # unbounded result set; reject it before any work happens.
    _patch_async_ops(monkeypatch)
    register_zim_search(server)
    fn, _ = server._tools_store["zim_search"]
    result = await fn(query="x", limit=MAX_SEARCH_RESULT_LIMIT + 1)
    assert result["operation"] == "invalid_limit"
    assert str(MAX_SEARCH_RESULT_LIMIT) in result["message"]


@pytest.mark.asyncio
async def test_zim_search_allows_limit_at_ceiling(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Exactly at the applicable ceiling is allowed — it reaches the data
    # layer unchanged. Cross-file's ceiling is search_all_data's
    # limit_per_file cap (50), not MAX_SEARCH_RESULT_LIMIT.
    ops = _patch_async_ops(monkeypatch, search_all_data={"results": []})
    register_zim_search(server)
    fn, _ = server._tools_store["zim_search"]
    await fn(query="x", mode="fulltext", cross_file=True, limit=50)
    ops.search_all_data.assert_awaited_once_with("x", limit_per_file=50)


@pytest.mark.asyncio
async def test_cross_file_limit_above_data_layer_cap_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cross_file maps `limit` to search_all_data's limit_per_file (cap 50).

    Validating only against MAX_SEARCH_RESULT_LIMIT let 51..1000 through to
    a data-layer OpenZimMcpValidationError rendered as a generic envelope
    naming the internal `limit_per_file` parameter — instead of the
    structured invalid_limit envelope the tool description promises.
    """
    ops = _patch_async_ops(monkeypatch, search_all_data={"results": []})
    register_zim_search(server)
    fn, _ = server._tools_store["zim_search"]
    result = await fn(query="x", mode="fulltext", cross_file=True, limit=60)
    assert result["operation"] == "invalid_limit"
    assert "50" in result["message"]
    assert not ops.search_all_data.called


@pytest.mark.asyncio
async def test_filtered_limit_above_data_layer_cap_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """namespace/content_type-filtered fulltext caps at 100 in the data layer."""
    ops = _patch_async_ops(monkeypatch, search_with_filters_data={"results": []})
    register_zim_search(server)
    fn, _ = server._tools_store["zim_search"]
    result = await fn(query="x", mode="fulltext", namespace="C", limit=150)
    assert result["operation"] == "invalid_limit"
    assert "100" in result["message"]
    assert not ops.search_with_filters_data.called


@pytest.mark.asyncio
async def test_title_limit_above_data_layer_cap_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """find_entry_by_title_data rejects limit > 50 — the surface must return
    the structured invalid_limit envelope instead of letting the data-layer
    exception surface through the generic broad-except envelope."""
    ops = _patch_async_ops(monkeypatch)
    ops.find_entry_by_title_data = AsyncMock(
        side_effect=OpenZimMcpValidationError(
            "limit must be between 1 and 50 (provided: 51)"
        )
    )
    with patch(
        "openzim_mcp.topic_preprocessing.auto_select_zim_file",
        return_value="/data/wiki.zim",
    ):
        register_zim_search(server)
        fn, _ = server._tools_store["zim_search"]
        result = await fn(query="x", mode="title", limit=51)
    assert result["operation"] == "invalid_limit"
    assert "50" in result["message"]
    ops.find_entry_by_title_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_suggest_limit_above_data_layer_cap_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch)
    ops.get_search_suggestions_data = AsyncMock(
        side_effect=OpenZimMcpValidationError("Limit must be between 1 and 50")
    )
    with patch(
        "openzim_mcp.topic_preprocessing.auto_select_zim_file",
        return_value="/data/wiki.zim",
    ):
        register_zim_search(server)
        fn, _ = server._tools_store["zim_search"]
        result = await fn(query="Det", mode="suggest", limit=51)
    assert result["operation"] == "invalid_limit"
    assert "50" in result["message"]
    ops.get_search_suggestions_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_limit_ceiling_hint_is_mode_aware(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The over-ceiling hint may only recommend `offset` where offset paging
    exists (single-archive fulltext) — the M28 guard rejects it elsewhere."""
    _patch_async_ops(monkeypatch)
    register_zim_search(server)
    fn, _ = server._tools_store["zim_search"]
    over = MAX_SEARCH_RESULT_LIMIT + 1

    single = await fn(query="x", mode="fulltext", limit=over)
    assert single["operation"] == "invalid_limit"
    assert "offset" in single["message"]

    cross = await fn(query="x", mode="fulltext", cross_file=True, limit=over)
    assert cross["operation"] == "invalid_limit"
    assert "offset" not in cross["message"]

    # Title/suggest get the tighter 50 cap even for absurd limits.
    title = await fn(query="x", mode="title", limit=over)
    assert title["operation"] == "invalid_limit"
    assert "50" in title["message"]
    assert "offset" not in title["message"]


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
async def test_title_promotion_row_normalised_and_counts_recomputed(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hoisted promotion row must satisfy the FindEntryHit contract
    (`score` present) and the merged page must preserve the
    total == returned_count == len(results) <= limit invariant that
    _assemble_find_response guarantees."""
    ops = _patch_async_ops(
        monkeypatch,
        find_entry_by_title_data={
            "results": [
                {"path": "A/Effects", "title": "Effects", "score": 0.95},
                {"path": "A/Other", "title": "Other", "score": 0.9},
            ],
            "next_cursor": None,
            "total": 2,
            "done": True,
            "page_info": {"offset": 0, "limit": 2, "returned_count": 2},
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
            return_value={
                "path": "A/Agriculture",
                "title": "Agriculture",
                "zim_file": "/data/wiki.zim",
                "match_type": "redirect",
            },
        ),
    ):
        register_zim_search(server)
        fn, _ = server._tools_store["zim_search"]
        result = await fn(query="agriculture effects", mode="title", limit=2)

    rows = result["results"]
    assert rows[0]["path"] == "A/Agriculture"
    assert rows[0]["score"] == 1.0
    assert rows[0]["match_type"] == "redirect"
    assert len(rows) == 2  # merged page re-trimmed to the caller's limit
    assert result["total"] == 2
    assert result["page_info"]["returned_count"] == 2
    assert result["_meta"]["promotion_applied"] is True
    ops.find_entry_by_title_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_title_promotion_survives_an_empty_raw_page(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A resolved promotion must not be discarded when the raw page is empty.

    Filler-prose queries are the class promotion exists for: the full-phrase
    lookup misses (``reason="0_hits"``) while the tail/window probes resolve
    the canonical. Returning the raw empty page throws that answer away and
    reports an undetectable miss — while, paradoxically, a query with one
    irrelevant raw hit gets the canonical injected at the top.
    """
    _patch_async_ops(
        monkeypatch,
        find_entry_by_title_data={
            "results": [],
            "next_cursor": None,
            "total": 0,
            "done": True,
            "page_info": {"offset": 0, "limit": 10, "returned_count": 0},
            "_meta": {"reason": "0_hits"},
        },
    )
    with (
        patch(
            "openzim_mcp.topic_preprocessing.auto_select_zim_file",
            return_value="/data/wiki.zim",
        ),
        patch(
            "openzim_mcp.topic_preprocessing.promote_topic_via_title_index",
            return_value={
                "path": "A/Big_Rapids,_Michigan",
                "title": "Big Rapids, Michigan",
                "match_type": "redirect",
            },
        ),
    ):
        register_zim_search(server)
        fn, _ = server._tools_store["zim_search"]
        result = await fn(query="famous people from big rapids michigan", mode="title")

    rows = result["results"]
    assert len(rows) == 1
    assert rows[0]["path"] == "A/Big_Rapids,_Michigan"
    assert rows[0]["score"] == 1.0
    assert result["total"] == 1
    assert result["page_info"]["returned_count"] == 1
    assert result["_meta"]["promotion_applied"] is True
    assert "reason" not in result["_meta"]  # the 0_hits verdict is stale now


@pytest.mark.asyncio
async def test_title_promotion_drops_the_zero_result_suggestions(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alt-spelling recovery hints must not ride along with a confident hit.

    ``_assemble_find_response`` fills ``_meta.suggestions`` only for the
    no-results and fuzzy-hit cases, and states the rule for the rest: a
    non-fuzzy hit carries none, "so confident matches aren't muddled by
    alt-spelling noise". Promotion converts a 0-hit page into exactly such a
    hit — a canonical title-index match — so a promoted page that keeps the
    suggestions hands the model "did you mean X?" recovery hints next to the
    answer it asked for, inviting a second lookup for a query already resolved.
    """
    _patch_async_ops(
        monkeypatch,
        find_entry_by_title_data={
            "results": [],
            "next_cursor": None,
            "total": 0,
            "done": True,
            "page_info": {"offset": 0, "limit": 10, "returned_count": 0},
            "_meta": {
                "reason": "0_hits",
                "suggestions": [{"type": "alt_spelling", "value": "Big Rapids"}],
            },
        },
    )
    with (
        patch(
            "openzim_mcp.topic_preprocessing.auto_select_zim_file",
            return_value="/data/wiki.zim",
        ),
        patch(
            "openzim_mcp.topic_preprocessing.promote_topic_via_title_index",
            return_value={
                "path": "A/Big_Rapids,_Michigan",
                "title": "Big Rapids, Michigan",
                "match_type": "redirect",
            },
        ),
    ):
        register_zim_search(server)
        fn, _ = server._tools_store["zim_search"]
        result = await fn(query="famous people from big rapids michigan", mode="title")

    assert result["_meta"]["promotion_applied"] is True
    assert "suggestions" not in result["_meta"]


@pytest.mark.asyncio
async def test_title_promotion_runs_off_the_event_loop(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Promotion probes are blocking libzim I/O and must not hold the loop.

    ``promote_topic_via_title_index`` performs up to dozens of uncached
    archive-open + SuggestionSearcher probes; every sibling data-layer call
    dispatches via ``AsyncZimOperations``/``to_thread``, and run inline this
    one freezes every concurrent session for the whole probe train.
    """
    import threading

    _patch_async_ops(
        monkeypatch,
        find_entry_by_title_data={"results": [], "_meta": {}},
    )
    loop_thread = threading.current_thread()
    seen_threads: list[threading.Thread] = []

    def recording_promotion(**kwargs: Any) -> None:
        seen_threads.append(threading.current_thread())
        return None

    with (
        patch(
            "openzim_mcp.topic_preprocessing.auto_select_zim_file",
            return_value="/data/wiki.zim",
        ),
        patch(
            "openzim_mcp.topic_preprocessing.promote_topic_via_title_index",
            side_effect=recording_promotion,
        ),
    ):
        register_zim_search(server)
        fn, _ = server._tools_store["zim_search"]
        await fn(query="anything", mode="title")

    assert seen_threads, "promotion was never invoked"
    assert all(thread is not loop_thread for thread in seen_threads), (
        "promote_topic_via_title_index ran on the event-loop thread; it must "
        "be offloaded via asyncio.to_thread"
    )


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


# ---------------------------------------------------------------------------
# namespace / content_type are fulltext-only
#
# Both were accepted in every mode and handed to ``_handle_fulltext_mode``
# alone, so ``mode="title"`` with ``namespace="A"`` returned title hits from
# every namespace, with nothing in the payload saying the filter had been
# discarded — a plausible answer to a wider question than the one asked. The
# rejection is paired with a no-filter case below, because the cheap way to
# pass a rejection test is to reject the whole mode.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["title", "suggest"])
@pytest.mark.parametrize(
    "filter_kwargs", [{"namespace": "A"}, {"content_type": "text/html"}]
)
async def test_non_fulltext_mode_rejects_filters(
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
async def test_suggest_without_filters_still_dispatches(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard keys on the filters, not on the mode."""
    ops = _patch_async_ops(monkeypatch, get_search_suggestions_data={"suggestions": []})
    with patch(
        "openzim_mcp.topic_preprocessing.auto_select_zim_file",
        return_value="/data/wiki.zim",
    ):
        register_zim_search(server)
        fn, _ = server._tools_store["zim_search"]
        await fn(query="Det", mode="suggest")
    ops.get_search_suggestions_data.assert_awaited_once()
