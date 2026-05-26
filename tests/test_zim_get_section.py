"""Tests for the Phase F ``zim_get_section`` tool (Task D6).

Renames Phase C's ``get_section`` with new compact/compact_budget
parameters (compact=True default).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.tools.zim_get_section import register as register_zim_get_section


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


def test_zim_get_section_registers(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get_section(server)
    assert "zim_get_section" in server._tools_store


@pytest.mark.asyncio
async def test_dispatches_to_get_section_data(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_section_data={"section": "..."})
    register_zim_get_section(server)
    fn, _ = server._tools_store["zim_get_section"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat", section_id="History")
    ops.get_section_data.assert_awaited_once_with(
        "/x.zim", "A/Cat", "History", max_chars=None
    )


@pytest.mark.asyncio
async def test_empty_section_id_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_get_section(server)
    fn, _ = server._tools_store["zim_get_section"]
    result = await fn(zim_file_path="/x.zim", entry_path="A/Cat", section_id="")
    assert result["operation"] == "invalid_section"
