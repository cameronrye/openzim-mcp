"""Tests for the Phase F ``zim_links`` tool (Task D9).

Collapses ``extract_article_links`` + ``get_related_articles`` +
``get_inbound_links`` via the ``direction`` parameter.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.tools.zim_links import register as register_zim_links


@pytest.fixture
def server() -> MagicMock:
    """Return a stand-in server whose ``mcp.tool`` decorator stores the fn."""
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
    """Patch AsyncZimOperations so each named data method is an AsyncMock."""
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
    """The tool registers under the name ``zim_links``."""
    _patch_async_ops(monkeypatch)
    register_zim_links(server)
    assert "zim_links" in server._tools_store


@pytest.mark.asyncio
async def test_outbound_dispatches_to_extract_article_links(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`direction='outbound'` dispatches to extract_article_links_data."""
    ops = _patch_async_ops(monkeypatch, extract_article_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat", limit=20)
    ops.extract_article_links_data.assert_awaited_once_with(
        "/x.zim", "A/Cat", limit=20, offset=0, kind="internal"
    )


@pytest.mark.asyncio
async def test_outbound_threads_kind_external(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`kind='external'` is forwarded to the data layer so the external bucket
    is actually retrievable (BUG #2)."""
    ops = _patch_async_ops(monkeypatch, extract_article_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat", kind="external", limit=20)
    ops.extract_article_links_data.assert_awaited_once_with(
        "/x.zim", "A/Cat", limit=20, offset=0, kind="external"
    )


@pytest.mark.asyncio
async def test_outbound_invalid_kind_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown `kind` is rejected without touching the data layer."""
    ops = _patch_async_ops(monkeypatch, extract_article_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    result = await fn(zim_file_path="/x.zim", entry_path="A/Cat", kind="bogus")
    assert result["operation"] == "invalid_kind"
    ops.extract_article_links_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_related_dispatches_to_get_related_articles(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`direction='related'` dispatches to get_related_articles_data."""
    ops = _patch_async_ops(monkeypatch, get_related_articles_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat", direction="related")
    ops.get_related_articles_data.assert_awaited_once_with("/x.zim", "A/Cat", limit=10)


@pytest.mark.asyncio
async def test_unknown_direction_rejected(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unsupported `direction` value returns a structured error."""
    _patch_async_ops(monkeypatch)
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    result = await fn(zim_file_path="/x.zim", entry_path="A/Cat", direction="sideways")  # type: ignore[arg-type]
    assert result["operation"] == "invalid_direction"


# ---------------------------------------------------------------------------
# kind is outbound-only; related does not paginate
#
# ``kind`` buckets the links extracted from an article body, which only the
# outbound walk produces — yet the other two directions accepted one and
# dropped it, answering "what media links here" with the whole inbound set.
# ``offset`` on ``related`` was the same silent no-op the cursor guard below
# already refused, spelled the other way.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["inbound", "related"])
@pytest.mark.parametrize("kind", ["external", "media"])
async def test_non_outbound_direction_rejects_kind(
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
@pytest.mark.parametrize(
    ("direction", "expected_call"),
    [
        ("inbound", "get_inbound_links_data"),
        ("related", "get_related_articles_data"),
    ],
)
async def test_non_outbound_direction_allows_default_kind(
    server: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    direction: str,
    expected_call: str,
) -> None:
    """``kind`` defaults to "internal", which stays a valid call everywhere."""
    ops = _patch_async_ops(
        monkeypatch,
        get_inbound_links_data={"results": []},
        get_related_articles_data={"results": []},
    )
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    await fn(zim_file_path="/x.zim", entry_path="A/Cat", direction=direction)
    getattr(ops, expected_call).assert_awaited_once()


@pytest.mark.asyncio
async def test_related_rejects_offset(
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
