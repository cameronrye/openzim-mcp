"""Rendering regressions from the 2026-11 sweep: titles, links, footers, Unicode.

Each class pins one defect that reproduced against ``main`` at e945188 and
names the inputs that exposed it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

import pytest
from libzim.writer import Creator

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer
from tests.conftest_v2_fixtures import _HtmlItem


def _build_zim(path: Path, pages: Iterable[Tuple[str, str, str]]) -> Path:
    """Write ``(entry path, stored title, html)`` pages into an indexed ZIM."""
    pages = list(pages)
    with Creator(path).config_indexing(True, "eng") as creator:
        for entry_path, title, html in pages:
            creator.add_item(_HtmlItem(entry_path, title, html))
        creator.set_mainpath(pages[0][0])
    return path


def _server(
    directory: Path, tool_mode: str = "advanced", *, cache: bool = True
) -> OpenZimMcpServer:
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(directory)],
            tool_mode=tool_mode,
            cache=CacheConfig(enabled=cache),
        )
    )


async def _call(server: OpenZimMcpServer, tool: str, **arguments: Any) -> Any:
    """Invoke a registered tool the way the SDK dispatches it."""
    return await server.mcp._tool_manager._tools[tool].fn(**arguments)


class TestImageOnlyH1KeepsTheStoredTitle:
    """An image-only ``<h1>`` renamed the search row after the first sentence.

    The heading renders as ``# `` and a blank line, and ``leading_h1``'s
    ``#\\s+`` matched the newlines too, so the "heading" it read was the
    lead paragraph. ``completed_title`` then saw the stored title "Aspirin"
    as a prefix of "Aspirin is a medication used to…" and swapped it in.
    """

    @pytest.fixture
    def archive(self, tmp_path: Path) -> Path:
        return _build_zim(
            tmp_path / "titles.zim",
            [
                (
                    "A/Aspirin",
                    "Aspirin",
                    '<html><body><h1><img src="logo.png" alt=""></h1>'
                    "<p>Aspirin is a medication used to reduce pain, fever, "
                    "or inflammation.</p></body></html>",
                ),
                (
                    "A/Alzheimer",
                    "Alzheimer",
                    "<html><body><h1>Alzheimer&#x27;s Disease</h1>"
                    "<p>Alzheimer medication can slow the decline for a time."
                    "</p></body></html>",
                ),
            ],
        )

    @pytest.mark.asyncio
    async def test_search_row_title_is_not_the_lead_sentence(
        self, archive: Path
    ) -> None:
        server = _server(archive.parent)
        # The completion reads the snippet render out of the cache, so the
        # second call is the one a warm server answers from cached rows.
        for _ in range(2):
            result = await _call(
                server, "zim_search", query="medication", zim_file_path=str(archive)
            )
            titles: Dict[str, str] = {r["path"]: r["title"] for r in result["results"]}
            assert titles.get("A/Aspirin") == "Aspirin", titles
            # A real truncated title next to it is still completed.
            assert titles.get("A/Alzheimer") == "Alzheimer's Disease", titles
