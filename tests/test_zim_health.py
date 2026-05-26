"""Tests for the Phase F ``zim_health`` tool (Task D10).

Zero-parameter wrapper over the D2 combined ``get_health_data`` —
returns health + configuration + loaded_archives in one envelope.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.tools.zim_health import register as register_zim_health


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


def test_zim_health_registers(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_health(server)
    assert "zim_health" in server._tools_store


@pytest.mark.asyncio
async def test_returns_combined_shape(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = {
        "health": {"status": "healthy"},
        "configuration": {"server_name": "test"},
        "loaded_archives": [{"name": "wiki.zim"}],
        "_meta": {},
    }
    ops = _patch_async_ops(monkeypatch, get_health_data=fake)
    register_zim_health(server)
    fn, _ = server._tools_store["zim_health"]
    result = await fn()
    ops.get_health_data.assert_awaited_once_with(server)
    assert result["health"] == {"status": "healthy"}
    assert result["configuration"] == {"server_name": "test"}
    assert result["loaded_archives"][0]["name"] == "wiki.zim"
