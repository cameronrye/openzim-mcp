"""Tests for the Phase F ``zim_metadata`` tool (Task D8).

Thin wrapper over the D2 combined ``get_archive_metadata_data``
wrapper. Tests verify registration, the lack of `main_page_path`
in the response shape, and metadata + namespaces populate.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.tools.zim_metadata import register as register_zim_metadata


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


def test_zim_metadata_registers(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_metadata(server)
    assert "zim_metadata" in server._tools_store


def test_description_lacks_main_page_path(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_metadata(server)
    _, description = server._tools_store["zim_metadata"]
    # The spec is explicit: NO main_page_path field. The description
    # documents that omission.
    assert "main_page_path" in description
    assert "zim_get(main_page=True)" in description


@pytest.mark.asyncio
async def test_dispatches_to_get_archive_metadata(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(
        monkeypatch,
        get_archive_metadata_data={
            "metadata": {"Name": "wiki"},
            "namespaces": [{"letter": "A", "total": 8, "is_authoritative": True}],
            "_meta": {},
        },
    )
    register_zim_metadata(server)
    fn, _ = server._tools_store["zim_metadata"]
    result = await fn(zim_file_path="/data/wiki.zim")
    ops.get_archive_metadata_data.assert_awaited_once_with("/data/wiki.zim")
    assert "main_page_path" not in result
    assert result["metadata"] == {"Name": "wiki"}
    assert result["namespaces"][0]["letter"] == "A"
