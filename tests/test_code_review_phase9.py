"""Regression tests for code-review 2026-06-10 Phase 9 (tools API/UX + errors).

H13 (zim_get batch ignores view), H14 (zim_search cursor never used),
M28 (zim_search offset dropped), M5 (security error misrouted), M4 (error
templates reference removed tools), L6 (broad-except error envelope).
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.error_messages import (
    ERROR_CONFIGS,
    PERMISSION_ERROR_CONFIG,
    format_error_message,
    format_generic_error,
    get_error_config,
)
from openzim_mcp.exceptions import OpenZimMcpSecurityError
from openzim_mcp.tools.zim_get import _validate_branch_combination
from openzim_mcp.tools.zim_search import register as register_zim_search


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
