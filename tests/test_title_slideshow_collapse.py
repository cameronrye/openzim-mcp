"""A title page must not spend its rows on one slideshow.

MedlinePlus files every frame of a slideshow under its own path with one
shared title, so ``zim_search(mode='title', query='stroke', limit=10)``
gave four of its ten rows to "Stroke - series" frames
(``ency/presentations/100218_1.htm`` .. ``_4.htm``). Suggest mode has
collapsed same-title rows since its title-index pass was introduced; title
mode only collapsed ``?quiz=1`` URL twins.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

_EXACT = "medlineplus.gov/stroke.html"
_FRAMES = [f"medlineplus.gov/ency/presentations/100218_{n}.htm" for n in (1, 2, 3, 4)]
# The live archive's order for ``stroke``, trimmed: the frames lead the index.
_ROWS: List[Tuple[str, str]] = [
    *[(frame, "Stroke - series") for frame in _FRAMES],
    ("medlineplus.gov/strokerehabilitation.html", "Stroke Rehabilitation"),
    ("medlineplus.gov/ency/article/000726.htm", "Stroke: Medical Encyclopedia"),
    (_EXACT, "Stroke | CVA | Cerebrovascular Accident | MedlinePlus"),
    (
        "medlineplus.gov/ency/imagepages/17133.htm",
        "Stroke: Medical Encyclopedia Image",
    ),
    ("medlineplus.gov/hemorrhagicstroke.html", "Hemorrhagic Stroke"),
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


def _wire_title_index(
    monkeypatch: pytest.MonkeyPatch, rows: List[Tuple[str, str]]
) -> List[int]:
    """An archive whose only working title lookup is the suggestion index."""
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


async def _title_page(
    server: OpenZimMcpServer, zim_file: Path, *, limit: int
) -> Dict[str, Any]:
    tool = server.mcp._tool_manager._tools["zim_search"].fn
    return await tool(
        query="stroke", mode="title", zim_file_path=str(zim_file), limit=limit
    )


class TestSlideshowFramesCollapse:
    @pytest.mark.asyncio
    async def test_one_row_per_slideshow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server, zim_file = _server(tmp_path, cache=False)
        _wire_title_index(monkeypatch, _ROWS)

        page = await _title_page(server, zim_file, limit=10)

        paths = [r["path"] for r in page["results"]]
        titles = [r["title"] for r in page["results"]]
        # Positive: the exact match leads, and the slideshow keeps one row —
        # the frame the index ranked first.
        assert paths[0] == _EXACT, paths
        assert _FRAMES[0] in paths
        # Negative: the other frames are gone, and no title repeats.
        assert not set(_FRAMES[1:]) & set(paths), paths
        assert len(set(titles)) == len(titles), titles
        # The counts describe the page that ships.
        assert page["total"] == len(paths)
        assert page["page_info"]["returned_count"] == len(paths)

    @pytest.mark.asyncio
    async def test_the_freed_rows_go_to_other_articles(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A small page fills with distinct articles instead of frames."""
        server, zim_file = _server(tmp_path, cache=False)
        _wire_title_index(monkeypatch, _ROWS)

        page = await _title_page(server, zim_file, limit=3)

        paths = [r["path"] for r in page["results"]]
        assert paths == [
            _EXACT,
            _FRAMES[0],
            "medlineplus.gov/strokerehabilitation.html",
        ], paths
        # More distinct articles lie beyond this page, and it says so.
        assert page["done"] is False

    @pytest.mark.asyncio
    async def test_similar_but_distinct_titles_are_kept(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Control: an article and its image page differ by one word and are
        two rows, not one."""
        server, zim_file = _server(tmp_path, cache=False)
        _wire_title_index(monkeypatch, _ROWS)

        page = await _title_page(server, zim_file, limit=10)

        paths = [r["path"] for r in page["results"]]
        assert "medlineplus.gov/ency/article/000726.htm" in paths
        assert "medlineplus.gov/ency/imagepages/17133.htm" in paths

    @pytest.mark.asyncio
    async def test_the_cached_page_is_the_collapsed_page(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cache enabled: the collapse happens before the page is stored, so
        the warm call serves the same frame-free page."""
        server, zim_file = _server(tmp_path, cache=True)
        reads = _wire_title_index(monkeypatch, _ROWS)

        cold = await _title_page(server, zim_file, limit=10)
        reads_after_cold = len(reads)
        warm = await _title_page(server, zim_file, limit=10)

        assert len(reads) == reads_after_cold, reads
        for page in (cold, warm):
            paths = [r["path"] for r in page["results"]]
            assert _FRAMES[0] in paths
            assert not set(_FRAMES[1:]) & set(paths), paths
        assert warm["results"] == cold["results"]
