"""A filtered fulltext walk must not end on an empty page.

The filtered scanner called a page unfinished whenever it filled before the
end of the ranked stream. When everything after the last row was a
``?quiz=1`` twin of a row already counted, the next page was empty: on the
MedlinePlus clone ``asthma quiz`` with ``namespace="C"`` and ``limit=5``
said ``done: false`` on page 5, and page 6 returned 0 rows with ``done:
true``. A page now looks past itself for one more row a next page would
hold, as the unfiltered title and suggest lookups do (R2-4).

Driven through the registered ``zim_search`` tool on real archives built
with libzim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
from libzim.writer import Creator

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer
from tests.conftest_v2_fixtures import _HtmlItem


def _build(zim: Path, pages: List[str]) -> Path:
    """One archive of quiz pages, each filed twice as warc2zim does."""
    with Creator(zim).config_indexing(True, "eng") as creator:
        for n, path in enumerate(pages):
            words = f"asthma quiz number {n} " * (12 - n) + "inhaler breathing " * 5
            html = f"<html><body><main><h1>Quiz {n}</h1><p>{words}</p></main></body></html>"
            for variant in (path, path + "?quiz=1"):
                creator.add_item(_HtmlItem(variant, f"Quiz {n}", html))
        creator.set_mainpath(pages[0])
    return zim


@pytest.fixture(scope="module")
def two_quiz_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    zim = tmp_path_factory.mktemp("two") / "quiz.zim"
    return _build(zim, ["med.gov/ency/quiz/a.htm", "med.gov/ency/quiz/b.htm"])


@pytest.fixture(scope="module")
def three_quiz_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    zim = tmp_path_factory.mktemp("three") / "quiz.zim"
    return _build(
        zim,
        [
            "med.gov/ency/quiz/a.htm",
            "med.gov/ency/quiz/b.htm",
            "med.gov/ency/quiz/c.htm",
        ],
    )


def _tool(zim: Path, *, cache: bool = False) -> Any:
    server = OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(zim.parent)],
            tool_mode="advanced",
            cache=(
                CacheConfig(enabled=True, max_size=100, ttl_seconds=600)
                if cache
                else CacheConfig(enabled=False)
            ),
        )
    )
    return server.mcp._tool_manager._tools["zim_search"].fn


async def _page(tool: Any, zim: Path, offset: int) -> Dict[str, Any]:
    return await tool(
        query="asthma quiz",
        zim_file_path=str(zim),
        namespace="C",
        limit=2,
        offset=offset,
    )


class TestTheLastPageIsNotEmpty:
    @pytest.mark.asyncio
    async def test_a_page_whose_tail_is_twins_is_the_last_page(
        self, two_quiz_zim: Path
    ) -> None:
        page = await _page(_tool(two_quiz_zim), two_quiz_zim, 0)

        # Positive: both pages are served, once each.
        paths = sorted(r["path"].split("?", 1)[0] for r in page["results"])
        assert paths == ["med.gov/ency/quiz/a.htm", "med.gov/ency/quiz/b.htm"]
        # Negative: the page does not promise a next page that is empty.
        assert page["done"] is True, page
        assert "total_is_lower_bound" not in page["page_info"]

    @pytest.mark.asyncio
    async def test_a_walk_never_reaches_an_empty_page(self, two_quiz_zim: Path) -> None:
        tool = _tool(two_quiz_zim)
        offset, pages = 0, []
        while True:
            page = await _page(tool, two_quiz_zim, offset)
            pages.append(page)
            if page["done"] or len(pages) > 5:
                break
            offset = page["total"]

        assert all(p["results"] for p in pages), pages
        assert pages[-1]["done"] is True

    @pytest.mark.asyncio
    async def test_a_real_next_page_is_still_announced(
        self, three_quiz_zim: Path
    ) -> None:
        """Control: a third distinct page lies past the first, so page one
        is unfinished and page two serves it."""
        tool = _tool(three_quiz_zim)

        first = await _page(tool, three_quiz_zim, 0)
        second = await _page(tool, three_quiz_zim, first["total"])

        assert first["done"] is False
        assert first["page_info"]["total_is_lower_bound"] is True
        assert len(second["results"]) == 1, second
        assert second["done"] is True
        canonical = {
            r["path"].split("?", 1)[0] for r in first["results"] + second["results"]
        }
        assert len(canonical) == 3

    @pytest.mark.asyncio
    async def test_the_cached_page_keeps_its_verdict(self, two_quiz_zim: Path) -> None:
        """Cache enabled: the filtered page is cached with its ``done``, and
        the warm call must serve the same verdict."""
        tool = _tool(two_quiz_zim, cache=True)

        cold = await _page(tool, two_quiz_zim, 0)
        warm = await _page(tool, two_quiz_zim, 0)

        for page in (cold, warm):
            assert page["done"] is True
            assert len(page["results"]) == 2
        assert warm["results"] == cold["results"]
