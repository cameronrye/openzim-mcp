"""Tests for the Phase F ``zim_links`` tool (Task D9).

Collapses ``extract_article_links`` + ``get_related_articles`` via
the ``direction`` parameter. v2.0 omits ``"inbound"`` per spec.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.tools.zim_links import register as register_zim_links


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


def test_zim_links_registers(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_async_ops(monkeypatch)
    register_zim_links(server)
    assert "zim_links" in server._tools_store


@pytest.mark.asyncio
async def test_outbound_dispatches_to_extract_article_links(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, extract_article_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat", limit=20)
    ops.extract_article_links_data.assert_awaited_once_with(
        "/x.zim", "A/Cat", limit=20, offset=0
    )


@pytest.mark.asyncio
async def test_related_dispatches_to_get_related_articles(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_related_articles_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat", direction="related")
    ops.get_related_articles_data.assert_awaited_once_with("/x.zim", "A/Cat", limit=10)


@pytest.mark.asyncio
async def test_inbound_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v2.0: 'inbound' is NOT in the enum (link-graph sidecar lands in v2.5)."""
    _patch_async_ops(monkeypatch)
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    result = await fn(zim_file_path="/x.zim", entry_path="A/Cat", direction="inbound")  # type: ignore[arg-type]
    assert result["operation"] == "invalid_direction"
    assert "v2.5" in result["message"]
