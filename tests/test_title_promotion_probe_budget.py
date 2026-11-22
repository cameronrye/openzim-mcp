"""One title-mode call must not cost a title-index probe per query word.

Promotion probes every trailing tail and every non-trailing window of up to
four tokens — about four probes per query word — and misses are not cached,
while each one-word window that misses runs the data layer's ~500-variant
typo sweep. Measured in title mode on the climate mini archive: 64 nonsense
words took 8.8 s and 400 took 54.5 s. The probes are now memoised per call
and capped, so the count no longer grows with the query.

Driven through the registered ``zim_search`` tool with only libzim stubbed;
the counter wraps the real ``ZimOperations.find_entry_by_title_data``.
"""

from __future__ import annotations

import random
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.topic_preprocessing import _PROMOTION_PROBE_BUDGET

# The title-page lookup itself (and a rewrite of it) sits outside the
# promotion budget.
_PAGE_LOOKUPS = 2


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
    """A title index that knows only ``rows_by_query``; anything else misses."""
    entries = {p: _entry(p, t) for rows in rows_by_query.values() for p, t in rows}
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


def _counted_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Tuple[Any, Path, List[Tuple[str, int]]]:
    """The zim_search handler, its archive, and a log of every title lookup."""
    zim_file = tmp_path / "wiki.zim"
    zim_file.write_bytes(b"zim")
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        tool_mode="advanced",
        cache=CacheConfig(enabled=False),
    )
    server = OpenZimMcpServer(config)
    ops = server.zim_operations
    real = ops.find_entry_by_title_data
    lookups: List[Tuple[str, int]] = []

    def _counting(
        zim_file_path: str, title: str, cross_file: bool = False, limit: int = 10
    ) -> Any:
        lookups.append((title, limit))
        return real(zim_file_path, title, cross_file, limit)

    monkeypatch.setattr(ops, "find_entry_by_title_data", _counting)
    return server.mcp._tool_manager._tools["zim_search"].fn, zim_file, lookups


def _nonsense(n: int, seed: int = 2) -> str:
    rng = random.Random(seed)
    return " ".join("".join(rng.choice("qxzjvkw") for _ in range(9)) for _ in range(n))


class TestProbeCountIsBounded:
    @pytest.mark.asyncio
    async def test_n_and_4n_words_cost_the_same_bounded_count(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _wire_title_index(monkeypatch, {})
        tool, zim_file, lookups = _counted_server(tmp_path, monkeypatch)
        bound = _PROMOTION_PROBE_BUDGET + _PAGE_LOOKUPS

        counts = []
        for n in (16, 64):
            lookups.clear()
            page = await tool(
                query=_nonsense(n), mode="title", zim_file_path=str(zim_file)
            )
            assert page["results"] == []
            counts.append(len(lookups))

        # Positive: both calls did probe (the budget is not zero) ...
        assert all(c > _PAGE_LOOKUPS for c in counts), counts
        # ... and neither exceeded a bound that does not depend on n.
        assert all(c <= bound for c in counts), (counts, bound)
        # Negative: quadrupling the query does not buy more probes.
        assert counts[1] == counts[0], counts

    @pytest.mark.asyncio
    async def test_no_title_is_probed_twice_in_one_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pass 3 walks Pass 1's tails again at a looser gate, and a miss is
        not cached by the data layer, so each repeat paid a full lookup."""
        _wire_title_index(monkeypatch, {})
        tool, zim_file, lookups = _counted_server(tmp_path, monkeypatch)

        await tool(query=_nonsense(3), mode="title", zim_file_path=str(zim_file))

        repeated = {key: n for key, n in Counter(lookups).items() if n > 1}
        # Positive: the tails were probed at all.
        tails = {title for title, limit in lookups if limit == 3}
        assert len(tails) >= 3, lookups
        # Negative: none of them twice.
        assert not repeated, repeated


class TestRealTopicsStillResolve:
    @pytest.mark.asyncio
    async def test_a_middle_entity_in_a_twelve_word_topic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Control: the cap leaves room for every window of a long real
        topic, including the one-word windows Pass 2 probes last."""
        _wire_title_index(monkeypatch, {"detroit": [("A/Detroit", "Detroit")]})
        tool, zim_file, _lookups = _counted_server(tmp_path, monkeypatch)
        topic = "what was the weather like in detroit during the winter of 1977"
        assert len(topic.split()) == 12

        page = await tool(query=topic, mode="title", zim_file_path=str(zim_file))

        assert [r["path"] for r in page["results"]] == ["A/Detroit"], page
        assert page["_meta"]["promotion_applied"] is True

    @pytest.mark.asyncio
    async def test_a_trailing_entity_resolves_on_the_first_tails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _wire_title_index(
            monkeypatch,
            {
                "big rapids michigan": [
                    ("A/Big_Rapids,_Michigan", "Big Rapids Michigan")
                ]
            },
        )
        tool, zim_file, _lookups = _counted_server(tmp_path, monkeypatch)

        page = await tool(
            query="famous people from big rapids michigan",
            mode="title",
            zim_file_path=str(zim_file),
        )

        assert [r["path"] for r in page["results"]] == ["A/Big_Rapids,_Michigan"]
