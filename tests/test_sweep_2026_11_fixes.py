"""Regressions from the 2026-11 dead-code, bug and docs sweep.

Each class pins one defect that reproduced against ``main`` at 92aeb89 and
names the inputs that exposed it.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.pagination import Cursor
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.simple_tools import SimpleToolsHandler
from openzim_mcp.tools.zim_links import register as register_zim_links
from tests.test_mcp_session import _connected_client, _text


@pytest.fixture
def climate_zim(real_content_zim_files: Dict[str, Optional[Path]]) -> Path:
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("wikipedia_climate ZIM fixture not available")
    return zim


@asynccontextmanager
async def _session(directory: Path, tool_mode: str) -> AsyncIterator[Any]:
    config = OpenZimMcpConfig(
        allowed_directories=[str(directory)],
        tool_mode=tool_mode,
        cache=CacheConfig(enabled=False),
    )
    async with _connected_client(OpenZimMcpServer(config)) as session:
        yield session


class TestLinksCursorAcceptsLeadingSlash:
    """``zim_links`` rejected its own cursor when ``entry_path`` had a ``/``.

    The data layer strips a client's leading slash before it mints the
    cursor, so ``s.ep`` held ``A/Climate_change`` while the guard compared it
    with the raw ``/A/Climate_change``: page 2 of the same call came back as
    ``cursor_context_mismatch``.
    """

    @pytest.mark.asyncio
    async def test_outbound_page_two_resumes_with_a_slashed_path(
        self, climate_zim: Path
    ) -> None:
        base = {"zim_file_path": str(climate_zim), "limit": 5}
        async with _session(climate_zim.parent, "advanced") as session:
            first = json.loads(
                _text(
                    await session.call_tool(
                        "zim_links", {**base, "entry_path": "/A/Climate_change"}
                    )
                )
            )
            assert first["next_cursor"], first
            slashed = await session.call_tool(
                "zim_links",
                {
                    **base,
                    "entry_path": "/A/Climate_change",
                    "cursor": first["next_cursor"],
                },
            )
            plain = await session.call_tool(
                "zim_links",
                {
                    **base,
                    "entry_path": "A/Climate_change",
                    "cursor": first["next_cursor"],
                },
            )

        assert slashed.is_error is not True, _text(slashed)
        page_two = json.loads(_text(slashed))
        assert page_two["results"], page_two
        assert page_two["results"] == json.loads(_text(plain))["results"]
        assert page_two["results"] != first["results"]

    @pytest.mark.asyncio
    async def test_inbound_page_two_resumes_with_a_slashed_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ops = MagicMock()
        ops.get_inbound_links_data = AsyncMock(return_value={"results": []})
        monkeypatch.setattr(
            "openzim_mcp.async_operations.AsyncZimOperations", lambda _zim_ops: ops
        )
        server = MagicMock()
        store: Dict[str, Any] = {}

        def _tool(**_kw: Any) -> Any:
            def decorate(fn: Any) -> Any:
                store[fn.__name__] = fn
                return fn

            return decorate

        server.mcp.tool = _tool
        register_zim_links(server)
        cursor = Cursor.encode(
            tool="get_inbound_links", state={"o": 3, "ep": "A/Cat", "ai": "x"}
        )

        result = await store["zim_links"](
            zim_file_path="/x.zim",
            entry_path="/A/Cat",
            direction="inbound",
            cursor=cursor,
        )

        assert result == {"results": []}, result
        assert ops.get_inbound_links_data.await_args.kwargs["offset"] == 3

    def test_simple_mode_guard_accepts_a_slashed_path(self) -> None:
        assert (
            SimpleToolsHandler._cursor_entry_mismatch(
                {"_cursor_ep": "A/Climate_change"}, "/A/Climate_change"
            )
            is None
        )

    def test_simple_mode_guard_still_rejects_another_entry(self) -> None:
        error = SimpleToolsHandler._cursor_entry_mismatch(
            {"_cursor_ep": "A/Dog"}, "/A/Cat"
        )
        assert error is not None
        assert "A/Dog" in str(error)
