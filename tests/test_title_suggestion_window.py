"""Title lookups must not depend on the page size the caller asked for.

``find_entry_by_title_data`` read only the first ``limit + 1`` rows of the
suggestion index, and an exact title match is only recognised once its row
has been read. On the shipped MedlinePlus archive ``stroke`` ranks four
"Stroke - series" slideshow frames first and ``stroke.html`` (title "Stroke |
CVA | ..."), the exact match, ninth — so ``limit=3`` answered with a
slideshow frame while ``limit=10`` answered with the article. The internal
probes are the worst case: ``find_title_match`` asks for ``limit=3``, so
title-mode promotion picked the slideshow frame, hoisted it above the exact
match the page already held, and restamped it ``score: 1.0`` while it was
still ``fuzzy_suggest``. ``zim_query "tell me about cpr"`` offered "CPR -
adult - series" as its canonical title match for the same reason.

Every test drives the real ``ZimOperations`` / registered ``zim_search``
handler with only the libzim layer stubbed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

# The MedlinePlus shape, trimmed: four fuzzy rows rank ahead of the article
# whose own name is the query, which sits fifth.
_EXACT = "medlineplus.gov/stroke.html"
_STROKE_ROWS: List[Tuple[str, str]] = [
    ("medlineplus.gov/ency/presentations/100218_1.htm", "Stroke - series"),
    ("medlineplus.gov/strokerehabilitation.html", "Stroke Rehabilitation"),
    ("medlineplus.gov/ency/article/000726.htm", "Stroke: Medical Encyclopedia"),
    ("medlineplus.gov/ency/patientinstructions/000132.htm", "Stroke - discharge"),
    (_EXACT, "Stroke | CVA | Cerebrovascular Accident | MedlinePlus"),
    ("medlineplus.gov/hemorrhagicstroke.html", "Hemorrhagic Stroke"),
    ("medlineplus.gov/ischemicstroke.html", "Ischemic Stroke"),
]


def _entry(path: str, title: str) -> MagicMock:
    entry = MagicMock()
    entry.path = path
    entry.title = title
    entry.is_redirect = False
    return entry


class _Ctx:
    def __init__(self, value: Any) -> None:
        self._value = value

    def __enter__(self) -> Any:
        return self._value

    def __exit__(self, *exc: Any) -> bool:
        return False


def _wire_title_index(monkeypatch: pytest.MonkeyPatch, rows: List[Tuple[str, str]]):
    """An archive whose only working title lookup is the suggestion index.

    Returns the list every ``getResults`` call's ``count`` is appended to, so
    a test can see how much of the index each lookup read.
    """
    entries: Dict[str, MagicMock] = {p: _entry(p, t) for p, t in rows}
    archive = MagicMock()
    archive.has_new_namespace_scheme = True
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False
    archive.get_entry_by_path.side_effect = lambda p: entries[p]
    paths = [p for p, _ in rows]
    reads: List[int] = []

    def _suggester(_archive: Any) -> MagicMock:
        searcher = MagicMock()
        sugg = MagicMock()
        sugg.getEstimatedMatches.return_value = len(paths)

        def _results(start: int, count: int) -> List[str]:
            reads.append(count)
            return paths[start : start + count]

        sugg.getResults.side_effect = _results
        searcher.suggest.return_value = sugg
        return searcher

    monkeypatch.setattr(
        "openzim_mcp.zim_operations.zim_archive", lambda *a, **kw: _Ctx(archive)
    )
    monkeypatch.setattr("openzim_mcp.zim_operations.SuggestionSearcher", _suggester)
    return reads


def _server(tmp_path: Path, *, cache: bool) -> Tuple[OpenZimMcpServer, Path]:
    zim_file = tmp_path / "medlineplus.zim"
    zim_file.write_bytes(b"zim")
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        tool_mode="advanced",
        cache=(
            CacheConfig(enabled=True, max_size=100, ttl_seconds=600)
            if cache
            else CacheConfig(enabled=False)
        ),
    )
    return OpenZimMcpServer(config), zim_file


def _zim_search(server: OpenZimMcpServer) -> Any:
    return server.mcp._tool_manager._tools["zim_search"].fn


class TestDataLayerWindow:
    @pytest.mark.parametrize("limit", [1, 3, 10])
    def test_an_exact_title_past_the_page_still_leads(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: int
    ) -> None:
        """The exact match is the fifth index row; every page size must find
        it, because whether a row is exact is only known once it is read."""
        server, zim_file = _server(tmp_path, cache=False)
        _wire_title_index(monkeypatch, _STROKE_ROWS)

        out = server.zim_operations.find_entry_by_title_data(
            str(zim_file), "stroke", limit=limit
        )

        top = out["results"][0]
        # Positive: the article named by the query leads, as an exact match.
        assert top["path"] == _EXACT, out["results"]
        assert top["score"] == 1.0
        assert top["match_type"] == "direct"
        assert out["fast_path_hit"] is True
        # Negative: the page is still trimmed to the caller's size.
        assert len(out["results"]) == min(limit, len(_STROKE_ROWS))

    def test_page_size_does_not_change_the_top_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The audit's statement of the defect: two page sizes, two answers."""
        server, zim_file = _server(tmp_path, cache=False)
        _wire_title_index(monkeypatch, _STROKE_ROWS)
        ops = server.zim_operations

        small = ops.find_entry_by_title_data(str(zim_file), "stroke", limit=3)
        large = ops.find_entry_by_title_data(str(zim_file), "stroke", limit=10)

        assert small["results"][0] == large["results"][0]
        assert small["results"][0]["path"] == _EXACT

    def test_one_row_past_the_page_still_decides_done(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R2-4 is kept: ``done`` is False only when a row exists beyond the
        page, and True when the window holds no more than the page."""
        server, zim_file = _server(tmp_path, cache=False)
        _wire_title_index(monkeypatch, _STROKE_ROWS)
        ops = server.zim_operations

        trimmed = ops.find_entry_by_title_data(str(zim_file), "stroke", limit=3)
        whole = ops.find_entry_by_title_data(
            str(zim_file), "stroke", limit=len(_STROKE_ROWS)
        )

        assert trimmed["done"] is False
        assert trimmed["page_info"]["total_is_lower_bound"] is True
        assert whole["done"] is True
        assert "total_is_lower_bound" not in whole["page_info"]
        assert len(whole["results"]) == len(_STROKE_ROWS)


class TestTitleModeAcrossPageSizes:
    @pytest.mark.asyncio
    async def test_limit_3_and_limit_10_agree_on_the_exact_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Through the tool, with promotion live: the probes read the same
        window as the page, so neither can lead with a slideshow frame."""
        server, zim_file = _server(tmp_path, cache=False)
        _wire_title_index(monkeypatch, _STROKE_ROWS)
        tool = _zim_search(server)

        pages = [
            await tool(
                query="stroke", mode="title", zim_file_path=str(zim_file), limit=n
            )
            for n in (3, 10)
        ]

        for page in pages:
            top = page["results"][0]
            assert top["path"] == _EXACT, page["results"]
            assert top["match_type"] == "direct"
            # Negative: no fuzzy row anywhere on the page wears the 1.0 that
            # only an exact match has earned.
            assert all(r["score"] < 1.0 for r in page["results"][1:]), page["results"]
        assert pages[0]["results"][0] == pages[1]["results"][0]

    @pytest.mark.asyncio
    async def test_the_cached_page_agrees_with_the_cold_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cache enabled: the title page and the promotion probes are both
        cached per (title, limit), so a second call is served from what the
        first one stored."""
        server, zim_file = _server(tmp_path, cache=True)
        reads = _wire_title_index(monkeypatch, _STROKE_ROWS)
        tool = _zim_search(server)

        async def _call(limit: int) -> Dict[str, Any]:
            return await tool(
                query="stroke", mode="title", zim_file_path=str(zim_file), limit=limit
            )

        cold_small = await _call(3)
        cold_large = await _call(10)
        reads_after_cold = len(reads)
        warm_small = await _call(3)
        warm_large = await _call(10)

        # Positive: the warm calls really were cache hits.
        assert len(reads) == reads_after_cold, reads
        # Every call, cold or warm, leads with the exact match.
        for page in (cold_small, cold_large, warm_small, warm_large):
            assert page["results"][0]["path"] == _EXACT, page["results"]
            assert page["results"][0]["score"] == 1.0
        # Negative: the warm page is not a different page.
        assert warm_small["results"] == cold_small["results"]
        assert warm_large["results"] == cold_large["results"]


class TestPromotionCannotOutrankAnExactMatch:
    @pytest.mark.asyncio
    async def test_a_fuzzy_promotion_is_not_hoisted_or_restamped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Whatever a promotion pass resolves, a fuzzy row must not be placed
        above, or stamped 1.0 over, the exact match the page already leads
        with."""
        server, zim_file = _server(tmp_path, cache=False)
        _wire_title_index(monkeypatch, _STROKE_ROWS)
        tool = _zim_search(server)
        fuzzy_path, fuzzy_title = _STROKE_ROWS[0]
        fuzzy_promotion: Dict[str, Optional[str]] = {
            "path": fuzzy_path,
            "title": fuzzy_title,
            "zim_file": str(zim_file),
            "match_type": "fuzzy_suggest",
        }

        with patch(
            "openzim_mcp.topic_preprocessing.promote_topic_via_title_index",
            return_value=fuzzy_promotion,
        ):
            page = await tool(
                query="stroke", mode="title", zim_file_path=str(zim_file), limit=10
            )

        rows = page["results"]
        # Positive: the exact match keeps the lead and its own score.
        assert rows[0]["path"] == _EXACT, rows
        assert rows[0]["score"] == 1.0
        # Negative: the fuzzy row stays where the index ranked it, at the
        # score the index gave it, and nothing claims a promotion happened.
        fuzzy_rows = [r for r in rows if r["path"] == fuzzy_path]
        assert len(fuzzy_rows) == 1, rows
        assert fuzzy_rows[0]["score"] < 1.0
        assert fuzzy_rows[0]["match_type"] == "fuzzy_suggest"
        assert page["_meta"].get("promotion_applied") is not True

    @pytest.mark.asyncio
    async def test_a_promotion_still_leads_a_page_with_no_exact_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Control: without an exact row the hoist is what promotion is for."""
        server, zim_file = _server(tmp_path, cache=False)
        rows_no_exact = [row for row in _STROKE_ROWS if row[0] != _EXACT]
        _wire_title_index(monkeypatch, rows_no_exact)
        tool = _zim_search(server)
        promoted_path, promoted_title = rows_no_exact[2]

        with patch(
            "openzim_mcp.topic_preprocessing.promote_topic_via_title_index",
            return_value={
                "path": promoted_path,
                "title": promoted_title,
                "zim_file": str(zim_file),
                "match_type": "redirect",
            },
        ):
            page = await tool(
                query="stroke", mode="title", zim_file_path=str(zim_file), limit=10
            )

        assert page["results"][0]["path"] == promoted_path
        assert page["_meta"]["promotion_applied"] is True
