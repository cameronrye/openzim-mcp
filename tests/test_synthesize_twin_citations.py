"""Synthesize must not cite one page twice under two URLs.

warc2zim files a query-string variant of a page (``quiz.htm?quiz=1``) as its
own entry with the same content, and Xapian ranks the twins side by side.
Every other search surface collapses them on ``canonical_result_path``;
``search_top_k``, synthesize's search stage, did not, so ``zim_query
"diabetes quiz" synthesize=True`` on MedlinePlus spent four of its ten
citations on twins.

Driven through ``zim_query`` on a real archive built with libzim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest
from libzim.reader import Archive
from libzim.writer import Creator

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.zim.search import canonical_result_path
from tests.conftest_v2_fixtures import _HtmlItem

_QUIZZES = [f"med.gov/ency/quiz/00{i}_q.htm" for i in range(5)]
_ARTICLES = [f"med.gov/article{i}.html" for i in range(6)]


def _pages() -> List[tuple]:
    pages = []
    for path, topic in zip(_QUIZZES, ["insulin", "glucose", "a1c", "diet", "sleep"]):
        words = f"diabetes quiz about {topic}. " * 8 + "quiz questions answers " * 5
        # The twin carries the same title and body, as warc2zim writes it, so
        # Xapian's order between the two changes from one build to the next.
        # The title names neither query word: synthesize's own title-match
        # promotion would otherwise add the other twin by exact path.
        title = f"Self-check: {topic}"
        pages.append((path, title, words))
        pages.append((path + "?quiz=1", title, words))
    for i, path in enumerate(_ARTICLES):
        words = "diabetes " * (10 - i) + "quiz " * 2 + "care treatment " * 10
        pages.append((path, f"Diabetes article {i}", words))
    return pages


@pytest.fixture(scope="module")
def quiz_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    zim = tmp_path_factory.mktemp("quiz") / "quiz.zim"
    with Creator(zim).config_indexing(True, "eng") as creator:
        for path, title, words in _pages():
            html = (
                f"<html><body><main><h1>{title}</h1><p>{words}</p></main></body></html>"
            )
            creator.add_item(_HtmlItem(path, title, html))
        creator.set_mainpath(_ARTICLES[0])
    return zim


def _server(zim: Path) -> OpenZimMcpServer:
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(zim.parent)], cache=CacheConfig(enabled=False)
        )
    )


def _cited(response: Any) -> List[str]:
    assert isinstance(response, dict), response
    return [c.get("entry_path") or c.get("path") for c in response["citations"]]


class TestSynthesizeCitesEachPageOnce:
    @pytest.mark.asyncio
    async def test_twins_collapse_and_the_freed_slots_fill(
        self, quiz_zim: Path
    ) -> None:
        tool = _server(quiz_zim).mcp._tool_manager._tools["zim_query"].fn

        response = await tool(query="diabetes quiz", synthesize=True, limit=10)

        cited = _cited(response)
        canonical = [canonical_result_path(p) for p in cited]
        # Negative: no page is cited under two URLs.
        assert len(set(canonical)) == len(canonical), cited
        # Positive: every quiz is still cited once, and the slots its twin
        # used to take go to the next distinct articles, so ten survive.
        for quiz in _QUIZZES:
            assert quiz in canonical, cited
        assert len(cited) == 10, cited
        assert any(path in _ARTICLES for path in cited), cited


class TestSearchTopK:
    def test_k_distinct_hits_in_rank_order(self, quiz_zim: Path) -> None:
        ops = _server(quiz_zim).zim_operations

        hits = ops.search_top_k(Archive(str(quiz_zim)), "diabetes quiz", k=8)

        paths = [h["path"] for h in hits]
        canonical = [canonical_result_path(p) for p in paths]
        # Positive: k hits come back, fetched past the twins.
        assert len(hits) == 8, paths
        # Negative: none of them is a twin of another.
        assert len(set(canonical)) == len(canonical), paths
        # Scores stay the rank-inverse of the distinct list.
        assert [h["score"] for h in hits] == [1.0 / r for r in range(1, 9)]

    def test_a_short_stream_returns_what_it_has(self, quiz_zim: Path) -> None:
        """Control: asking for more than the archive holds ends cleanly."""
        ops = _server(quiz_zim).zim_operations

        hits = ops.search_top_k(Archive(str(quiz_zim)), "diabetes quiz", k=40)

        canonical = [canonical_result_path(h["path"]) for h in hits]
        assert len(set(canonical)) == len(canonical)
        assert set(canonical) == set(_QUIZZES) | set(_ARTICLES)
