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
from unittest.mock import MagicMock

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


# ---------------------------------------------------------------------------
# page_info.next_offset rides filtered pages too
# ---------------------------------------------------------------------------
#
# v3.3.1 field report (fid 67) made the resume point a value on plain
# fulltext pages: ``page_info.next_offset``, present exactly when there is a
# next page. The filtered branch of the same tool never got it, so a caller
# paging ``namespace="C"`` had to know that its resume point is ``total``
# (the consumed filter slots), not ``offset + returned_count``.


async def _filtered(tool: Any, zim: Path, offset: int, limit: int) -> Dict[str, Any]:
    return await tool(
        query="asthma quiz",
        zim_file_path=str(zim),
        namespace="C",
        limit=limit,
        offset=offset,
    )


class TestFilteredNextOffset:
    @pytest.mark.asyncio
    async def test_an_unfinished_page_names_its_resume_point(
        self, three_quiz_zim: Path
    ) -> None:
        page = await _filtered(_tool(three_quiz_zim), three_quiz_zim, 0, 1)

        assert page["done"] is False
        # Positive: the resume point is a value, and it is the slot count the
        # cursor encodes.
        assert page["page_info"]["next_offset"] == page["total"] == 1
        # Same field, same meaning, as an unfiltered page of this archive.
        plain = await _tool(three_quiz_zim)(
            query="asthma quiz", zim_file_path=str(three_quiz_zim), limit=1
        )
        assert "next_offset" in plain["page_info"]

    @pytest.mark.asyncio
    async def test_following_next_offset_walks_every_page_once(
        self, three_quiz_zim: Path
    ) -> None:
        tool = _tool(three_quiz_zim)
        offset, seen = 0, []
        for _ in range(6):
            page = await _filtered(tool, three_quiz_zim, offset, 1)
            seen += [r["path"].split("?", 1)[0] for r in page["results"]]
            if page["done"]:
                # Negative: a finished page advertises no continuation.
                assert "next_offset" not in page["page_info"], page["page_info"]
                break
            offset = page["page_info"]["next_offset"]

        assert sorted(seen) == [
            "med.gov/ency/quiz/a.htm",
            "med.gov/ency/quiz/b.htm",
            "med.gov/ency/quiz/c.htm",
        ], seen

    @pytest.mark.asyncio
    async def test_the_cached_page_carries_it_too(self, three_quiz_zim: Path) -> None:
        """Cache enabled: the field is part of the cached filtered page."""
        tool = _tool(three_quiz_zim, cache=True)

        cold = await _filtered(tool, three_quiz_zim, 0, 1)
        warm = await _filtered(tool, three_quiz_zim, 0, 1)

        for page in (cold, warm):
            assert page["page_info"]["next_offset"] == 1
        assert warm["results"] == cold["results"]


def _stub_entry(path: str) -> MagicMock:
    entry = MagicMock()
    entry.path = path
    entry.title = path.rsplit("/", 1)[-1]
    entry.is_redirect = False
    item = MagicMock()
    item.mimetype = "text/html"
    item.content = b"<html><body><p>asthma quiz questions</p></body></html>"
    entry.get_item.return_value = item
    return entry


class _StubCtx:
    def __init__(self, value: Any) -> None:
        self._value = value

    def __enter__(self) -> Any:
        return self._value

    def __exit__(self, *exc: Any) -> bool:
        return False


class TestNextOffsetCountsFailedCandidates:
    @pytest.mark.asyncio
    async def test_an_unreadable_hit_still_moves_the_resume_point(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A hit that fails to materialise consumes a filter slot without
        being served, so ``offset + returned_count`` lands one slot early and
        re-serves a row; ``next_offset`` must be the consumed-slot count."""
        stream = [
            "med.gov/a.htm",
            "med.gov/broken.htm",
            "med.gov/b.htm",
            "med.gov/c.htm",
        ]
        entries = {p: _stub_entry(p) for p in stream if "broken" not in p}

        def _get(path: str) -> MagicMock:
            if path not in entries:
                raise KeyError(path)
            return entries[path]

        archive = MagicMock()
        archive.has_new_namespace_scheme = True
        archive.has_fulltext_index = True
        archive.get_entry_by_path.side_effect = _get
        search = MagicMock()
        search.getEstimatedMatches.return_value = len(stream)
        search.getResults.side_effect = lambda start, n: stream[start : start + n]
        searcher = MagicMock()
        searcher.return_value.search.return_value = search
        monkeypatch.setattr(
            "openzim_mcp.zim_operations.zim_archive",
            lambda *a, **kw: _StubCtx(archive),
        )
        monkeypatch.setattr("openzim_mcp.zim_operations.Searcher", searcher)
        zim_file = tmp_path / "stub.zim"
        zim_file.write_bytes(b"zim")
        tool = _tool(zim_file)

        offset, served, resume_points = 0, [], []
        for _ in range(6):
            page = await _filtered(tool, zim_file, offset, 1)
            served += [r["path"] for r in page["results"]]
            if page["done"]:
                break
            resume_points.append(page["page_info"]["next_offset"])
            offset = resume_points[-1]

        # Positive: every readable hit is served, in rank order, once.
        assert served == ["med.gov/a.htm", "med.gov/b.htm", "med.gov/c.htm"], served
        # The page holding ``b`` also consumed the unreadable slot before it.
        assert resume_points == [1, 3], resume_points
