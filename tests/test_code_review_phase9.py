"""Regression tests for code-review 2026-06-10 Phase 9 (tools API/UX + errors).

H13 (zim_get batch ignores view), H14 (zim_search cursor never used),
M28 (zim_search offset dropped), M5 (security error misrouted), M4 (error
templates reference removed tools), L6 (broad-except error envelope).
"""

from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.error_messages import (
    ERROR_CONFIGS,
    PERMISSION_ERROR_CONFIG,
    format_error_message,
    format_generic_error,
    get_error_config,
)
from openzim_mcp.exceptions import OpenZimMcpSecurityError
from openzim_mcp.security import PathValidator
from openzim_mcp.tools.zim_get import _validate_branch_combination
from openzim_mcp.tools.zim_search import register as register_zim_search
from openzim_mcp.zim_operations import ZimOperations


# ---------------------------------------------------------------------------
# H13 — batch + non-full view is rejected
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("view", ["summary", "toc", "structure"])
def test_h13_batch_with_non_full_view_rejected(view):
    err = _validate_branch_combination(
        entry_path=None,
        entry_paths=["A/one", "A/two"],
        view=view,
        binary=False,
        main_page=False,
    )
    assert err is not None
    assert err["operation"] == "invalid_path_combination"


def test_h13_batch_full_view_ok():
    assert (
        _validate_branch_combination(
            entry_path=None,
            entry_paths=["A/one"],
            view="full",
            binary=False,
            main_page=False,
        )
        is None
    )


# ---------------------------------------------------------------------------
# zim_search fixture
# ---------------------------------------------------------------------------
@pytest.fixture
def search_server() -> MagicMock:
    srv = MagicMock()
    store: dict[str, Any] = {}

    def _tool(*, description: str = ""):
        def decorate(fn):
            store[fn.__name__] = (fn, description)
            return fn

        return decorate

    srv.mcp.tool = _tool
    srv._tools_store = store
    return srv


def _patch_ops(monkeypatch, **returns):
    ops = MagicMock()
    for name, value in returns.items():
        setattr(ops, name, AsyncMock(return_value=value))
    monkeypatch.setattr(
        "openzim_mcp.async_operations.AsyncZimOperations", lambda _z: ops
    )
    return ops


# H14 — a provided cursor is rejected (never silently looped)
@pytest.mark.asyncio
async def test_h14_cursor_rejected(search_server, monkeypatch):
    _patch_ops(monkeypatch)
    register_zim_search(search_server)
    fn, _ = search_server._tools_store["zim_search"]
    result = await fn(query="x", mode="fulltext", cursor="some-cursor-handle")
    assert result["operation"] == "invalid_combination"
    assert "cursor" in result["message"].lower()


# H14 residue — zim_search must not advertise a followable next_cursor.
# The shared data layer (search_zim_file_data / search_with_filters_data)
# emits a real ``next_cursor`` handle when results exceed offset+limit, but
# zim_search REJECTS a returned cursor (see test_h14_cursor_rejected). Surface
# ``next_cursor=None`` so a client never reads a handle it would only get
# rejected for. Driven end-to-end against the real climate-change ZIM so the
# data layer genuinely produces a non-None cursor (a mock can't prove the
# null-out happened in the tool layer).
def _build_search_server_for_zim(zim: Path) -> MagicMock:
    """A MagicMock server whose ``zim_operations`` is a real ZimOperations
    rooted at ``zim``. ``rate_limiter.check_rate_limit`` is a no-op MagicMock
    (never raises), and ``mcp.tool`` captures the registered function."""
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(zim.parent.parent)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=1000, snippet_length=100),
        logging=LoggingConfig(level="ERROR"),
    )
    real_ops = ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache),
        ContentProcessor(snippet_length=100),
    )

    srv = MagicMock()
    srv.zim_operations = real_ops
    store: dict[str, Any] = {}

    def _tool(*, description: str = ""):
        def decorate(fn):
            store[fn.__name__] = (fn, description)
            return fn

        return decorate

    srv.mcp.tool = _tool
    srv._tools_store = store
    return srv


@pytest.fixture
def climate_zim(real_content_zim_files: Dict[str, Optional[Path]]) -> Path:
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("climate-change ZIM fixture not available")
    return zim.resolve()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra_kwargs",
    [
        {},  # plain single-archive fulltext -> search_zim_file_data
        {"content_type": "text/html"},  # filtered path -> search_with_filters_data
    ],
)
async def test_h14_residue_next_cursor_nulled(climate_zim, extra_kwargs):
    srv = _build_search_server_for_zim(climate_zim)
    register_zim_search(srv)
    fn, _ = srv._tools_store["zim_search"]

    # limit=2 against a query with thousands of hits => data layer would
    # otherwise emit a real next_cursor (total >> offset+limit, done=False).
    result = await fn(
        query="climate",
        mode="fulltext",
        zim_file_path=str(climate_zim),
        limit=2,
        **extra_kwargs,
    )

    assert isinstance(result, dict)
    assert not result.get("error"), f"unexpected error payload: {result}"
    # Sanity: the page is not exhausted (``done`` is False), which is exactly
    # the condition under which the shared data layer encodes a non-None
    # next_cursor — so this call genuinely exercises the null-out path.
    assert result["done"] is False
    assert result["results"], "expected a non-empty first page"
    # The residue fix: zim_search advertises no followable cursor.
    assert result["next_cursor"] is None


@pytest.mark.asyncio
async def test_h14_residue_cross_file_nested_cursor_nulled(climate_zim):
    """cross_file fan-out must not leak a followable per-archive cursor.

    search_all_data nests each archive's SearchResponse under
    ``results[].result`` — those carry a real next_cursor when a per-archive
    page is unexhausted. zim_search rejects every cursor, so none may survive.
    """
    srv = _build_search_server_for_zim(climate_zim)
    register_zim_search(srv)
    fn, _ = srv._tools_store["zim_search"]

    result = await fn(query="climate", mode="fulltext", cross_file=True, limit=2)

    assert isinstance(result, dict)
    assert not result.get("error"), f"unexpected error payload: {result}"
    assert result["next_cursor"] is None
    rows = result.get("results") or []
    assert rows, "expected at least one per-archive result row"
    for row in rows:
        inner = row.get("result")
        if isinstance(inner, dict):
            assert (
                inner.get("next_cursor") is None
            ), f"nested next_cursor leaked for {row.get('zim_file_path')}"


def test_h14_strip_next_cursor_is_copy_on_write():
    """_strip_next_cursor must null cursors WITHOUT mutating its input.

    The data layer hands out cache-by-reference dicts shared with zim_query
    (which surfaces next_cursor). In-place mutation would poison the cache —
    the H12 defect class. This pins copy-on-write + nested nulling directly.
    """
    from openzim_mcp.tools.zim_search import _strip_next_cursor

    original = {
        "next_cursor": "REALCURSOR",
        "done": False,
        "results": [
            {
                "zim_file_path": "a.zim",
                "result": {"next_cursor": "NESTED", "done": False},
            },
            {"zim_file_path": "b.zim", "result": {"next_cursor": None}},
        ],
    }
    stripped = _strip_next_cursor(original)

    # Output advertises no followable cursor anywhere.
    assert stripped["next_cursor"] is None
    assert stripped["results"][0]["result"]["next_cursor"] is None
    # Input is untouched — cache-by-reference stays intact (no H12 poisoning).
    assert original["next_cursor"] == "REALCURSOR"
    assert original["results"][0]["result"]["next_cursor"] == "NESTED"


def test_h12_title_merge_promotion_is_copy_on_write():
    """Title-mode promotion must not mutate the cached find_title result.

    H15 caches single-archive title lookups (find_title:v1, returned by
    reference) and the internal promotion probes read the same key. If
    _merge_promotion_into_title_results mutated raw in place it would poison
    that shared cache (H12 defect class) — pin copy-on-write here.
    """
    from openzim_mcp.tools.zim_search import _merge_promotion_into_title_results

    raw = {
        "results": [{"path": "C/Other", "title": "Other"}],
        "_meta": {"x": 1},
    }
    promoted = {
        "path": "C/Canonical",
        "title": "Canonical",
        "snippet": "",
        "score": 1.0,
    }

    merged = _merge_promotion_into_title_results(raw, promoted)

    # Output hoists the promoted entry and flags promotion.
    assert merged["results"][0]["path"] == "C/Canonical"
    assert merged["_meta"]["promotion_applied"] is True
    # Input cached dict is untouched.
    assert raw["results"] == [{"path": "C/Other", "title": "Other"}]
    assert "promotion_applied" not in raw["_meta"]


# M28 — offset rejected in modes that can't honor it
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "title", "offset": 10},
        {"mode": "suggest", "offset": 10},
        {"mode": "fulltext", "cross_file": True, "offset": 10},
    ],
)
async def test_m28_offset_rejected_in_non_paginating_modes(
    search_server, monkeypatch, kwargs
):
    _patch_ops(monkeypatch)
    register_zim_search(search_server)
    fn, _ = search_server._tools_store["zim_search"]
    result = await fn(query="x", **kwargs)
    assert result["operation"] == "invalid_combination"
    assert "offset" in result["message"].lower()


@pytest.mark.asyncio
async def test_m28_offset_allowed_in_single_archive_fulltext(
    search_server, monkeypatch
):
    ops = _patch_ops(monkeypatch, search_zim_file_data={"results": [], "total": 0})
    monkeypatch.setattr(
        "openzim_mcp.topic_preprocessing.auto_select_zim_file", lambda _o: "/x.zim"
    )
    register_zim_search(search_server)
    fn, _ = search_server._tools_store["zim_search"]
    result = await fn(query="x", mode="fulltext", offset=10)
    # No rejection — the data layer was called with the offset.
    assert not (isinstance(result, dict) and result.get("error"))
    ops.search_zim_file_data.assert_awaited_once()
    assert ops.search_zim_file_data.await_args.kwargs.get("offset") == 10


# ---------------------------------------------------------------------------
# M5 — security violations render the security template, not permission
# ---------------------------------------------------------------------------
def test_m5_security_error_routes_to_security_template():
    err = OpenZimMcpSecurityError(
        "Access denied - Path is outside allowed directories: /etc/passwd"
    )
    config = get_error_config(err)
    assert config is ERROR_CONFIGS[OpenZimMcpSecurityError]
    assert config is not PERMISSION_ERROR_CONFIG


# ---------------------------------------------------------------------------
# M4 — error templates reference only registered v2 tools
# ---------------------------------------------------------------------------
_REMOVED_TOOLS = ("list_zim_files(", "get_server_health(", "get_server_configuration(")


def test_m4_no_removed_tool_names_in_templates():
    for config in (*ERROR_CONFIGS.values(), PERMISSION_ERROR_CONFIG):
        rendered = format_error_message(config, "op", "ctx", "details")
        for dead in _REMOVED_TOOLS:
            assert dead not in rendered, f"{dead} in {config.title}"
    generic = format_generic_error("op", "type", "ctx", "details")
    for dead in _REMOVED_TOOLS:
        assert dead not in generic
