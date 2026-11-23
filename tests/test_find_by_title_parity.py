"""``find article titled X`` must answer like ``zim_search(mode='title')``.

Simple mode's ``_handle_find_by_title`` called the title data layer and
rendered it, skipping the two steps the advanced title mode applies after
the lookup: the canonical-title promotion and the crawl-artefact demote. On
the shipped MedlinePlus archive ``hepatitis b`` put the
``languages/hepatitisb.html`` translation hub second in simple mode and
fifth in advanced, and ``swollen glands`` came back in opposite orders.

The same handler also passed ``limit`` straight to a data layer capped at
50, so ``zim_query``'s documented 51..1000 produced a generic "Error
Processing Query" with a traceback logged at ERROR. The links and related
intents clamp with a visible note; this one now does too.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

_HUB = "medlineplus.gov/languages/hepatitisb.html"
_EXACT = "medlineplus.gov/hepatitisb.html"
_ENCY = "medlineplus.gov/ency/article/000279.htm"
_IMAGE = "medlineplus.gov/ency/imagepages/9395.htm"
# The index ranks the translation hub ahead of the article it translates.
_HEPATITIS_ROWS: List[Tuple[str, str]] = [
    (_HUB, "Hepatitis B - Multiple Languages: MedlinePlus"),
    (_EXACT, "Hepatitis B | Hep B | MedlinePlus"),
    (_ENCY, "Hepatitis B: MedlinePlus Medical Encyclopedia"),
    (_IMAGE, "Hepatitis B virus: MedlinePlus Medical Encyclopedia Image"),
]
_BIG_RAPIDS = "A/Big_Rapids,_Michigan"


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
    monkeypatch: pytest.MonkeyPatch, rows_by_query: Dict[str, List[Tuple[str, str]]]
) -> None:
    """A title index whose answer depends on the probe string, as libzim's
    does; any string it does not know matches nothing."""
    entries: Dict[str, MagicMock] = {
        path: _entry(path, title)
        for rows in rows_by_query.values()
        for path, title in rows
    }
    archive = MagicMock()
    archive.has_new_namespace_scheme = True
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False
    archive.get_entry_by_path.side_effect = lambda p: entries[p]

    def _suggester(_archive: Any) -> MagicMock:
        searcher = MagicMock()

        def _suggest(text: str) -> MagicMock:
            paths = [p for p, _ in rows_by_query.get(text.lower(), [])]
            sugg = MagicMock()
            sugg.getEstimatedMatches.return_value = len(paths)
            sugg.getResults.side_effect = lambda start, n: paths[start : start + n]
            return sugg

        searcher.suggest.side_effect = _suggest
        return searcher

    monkeypatch.setattr(
        "openzim_mcp.zim_operations.zim_archive", lambda *a, **kw: _Ctx(archive)
    )
    monkeypatch.setattr("openzim_mcp.zim_operations.SuggestionSearcher", _suggester)


def _server(tmp_path: Path, *, cache: bool = False) -> Tuple[OpenZimMcpServer, Path]:
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


def _tool(server: OpenZimMcpServer, name: str) -> Any:
    return server.mcp._tool_manager._tools[name].fn


def _rendered_paths(markdown: str) -> List[str]:
    return re.findall(r"— `([^`]+)`", markdown)


async def _both(
    server: OpenZimMcpServer, zim_file: Path, title: str, **kw: Any
) -> Tuple[List[str], str]:
    advanced = await _tool(server, "zim_search")(
        query=title, mode="title", zim_file_path=str(zim_file), limit=6
    )
    simple = await _tool(server, "zim_query")(
        query=f"find article titled {title}", zim_file_path=str(zim_file), **kw
    )
    assert isinstance(simple, str), simple
    return [r["path"] for r in advanced["results"]], simple


class TestSameOrderAsTitleMode:
    @pytest.mark.asyncio
    async def test_the_translation_hub_sinks_in_both_modes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server, zim_file = _server(tmp_path)
        _wire_title_index(monkeypatch, {"hepatitis b": _HEPATITIS_ROWS})

        advanced, simple = await _both(server, zim_file, "hepatitis b", limit=6)

        assert _rendered_paths(simple) == advanced, simple
        # Positive: the exact article leads and the encyclopedia entry
        # follows it; the hub is still on the page.
        assert advanced[:2] == [_EXACT, _ENCY], advanced
        assert _HUB in advanced
        # Negative: the hub no longer outranks a real article.
        assert advanced.index(_HUB) > advanced.index(_ENCY)

    @pytest.mark.asyncio
    async def test_promotion_answers_in_both_modes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The full phrase names no title; promotion resolves its tail."""
        server, zim_file = _server(tmp_path)
        _wire_title_index(
            monkeypatch,
            {"big rapids michigan": [(_BIG_RAPIDS, "Big Rapids Michigan")]},
        )
        phrase = "famous people from big rapids michigan"

        advanced, simple = await _both(server, zim_file, phrase)

        assert advanced == [_BIG_RAPIDS], advanced
        assert _rendered_paths(simple) == advanced, simple
        assert "No article found" not in simple

    @pytest.mark.asyncio
    async def test_the_cached_page_keeps_the_shared_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cache enabled: the demote runs on a copy of the cached title page,
        so a second simple-mode call, and the advanced call after it, still
        read the index order and agree."""
        server, zim_file = _server(tmp_path, cache=True)
        _wire_title_index(monkeypatch, {"hepatitis b": _HEPATITIS_ROWS})
        query_tool = _tool(server, "zim_query")

        first = await query_tool(
            query="find article titled hepatitis b", zim_file_path=str(zim_file)
        )
        second = await query_tool(
            query="find article titled hepatitis b", zim_file_path=str(zim_file)
        )
        advanced, _ = await _both(server, zim_file, "hepatitis b")

        assert _rendered_paths(first) == _rendered_paths(second) == advanced
        assert advanced[0] == _EXACT
        assert advanced.index(_HUB) > advanced.index(_ENCY)

    @pytest.mark.asyncio
    async def test_the_json_rendering_carries_the_same_page(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``compact=False`` returns the payload as JSON; it is the same page."""
        server, zim_file = _server(tmp_path)
        _wire_title_index(monkeypatch, {"hepatitis b": _HEPATITIS_ROWS})

        advanced, simple = await _both(server, zim_file, "hepatitis b", compact=False)

        # The intent footer follows the JSON body.
        payload, _end = json.JSONDecoder().raw_decode(simple)
        assert [r["path"] for r in payload["results"]] == advanced
        assert payload["results"][0]["path"] == _EXACT


class TestLimitAboveTheTitleCap:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("limit", [51, 200, 1000])
    async def test_is_clamped_with_a_note(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        limit: int,
    ) -> None:
        server, zim_file = _server(tmp_path)
        _wire_title_index(monkeypatch, {"hepatitis b": _HEPATITIS_ROWS})

        with caplog.at_level(logging.ERROR):
            out = await _tool(server, "zim_query")(
                query="find article titled hepatitis b",
                zim_file_path=str(zim_file),
                limit=limit,
            )

        assert isinstance(out, str), out
        # Positive: the hits render, and the clamp is visible.
        assert _rendered_paths(out)[0] == _EXACT, out
        assert f"`limit={limit}` exceeds this operation's maximum of 50" in out
        # Negative: no error envelope and nothing logged at ERROR.
        assert "Error Processing Query" not in out
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    @pytest.mark.asyncio
    async def test_a_limit_within_the_cap_carries_no_note(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        server, zim_file = _server(tmp_path)
        _wire_title_index(monkeypatch, {"hepatitis b": _HEPATITIS_ROWS})

        out = await _tool(server, "zim_query")(
            query="find article titled hepatitis b",
            zim_file_path=str(zim_file),
            limit=50,
        )

        assert _rendered_paths(out)[0] == _EXACT, out
        assert "exceeds this operation's maximum" not in out
