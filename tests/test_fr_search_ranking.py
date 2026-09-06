"""Field-report fixes — search / ranking cluster.

Regression tests for the v3.3.1 real-world sweep findings that live in
``openzim_mcp/zim/search.py``, ``openzim_mcp/tools/zim_search.py`` and
``openzim_mcp/defaults.py``.

Findings pinned here:

* **fid 28 / 63 / 125** — one root cause. ``zim_search(mode='fulltext')``
  renders ``limit`` compact-HTML snippets with no ceiling of any kind, so
  the documented-legal ``limit=1000`` shipped a 1 MB / ~250 K-token body
  after 45-53 s of blocking render, with ``_meta.truncated: false`` telling
  the caller nothing had been cut. The retrieval loop now carries a
  character budget and a wall-clock deadline, stops on whichever binds
  first, and says so.
* **fid 58** — the canonical-title splice ``zim_query`` applies was never
  wired into the advanced fulltext dispatch, so ``zim_search`` buried the
  exact-title article (``iep.utm.edu/epistemo/`` at rank 27 of 100 for the
  query ``epistemology``) while ``zim_query`` put it at rank 1.
* **fid 59** — ``mode='title'`` deduped on the raw path, so warc2zim
  ``?quiz=1`` variants took two of ten slots on a MedlinePlus page. Fulltext
  already collapses them on ``canonical_result_path``.
* **fid 2 / 3** — ``cross_file=True`` with zero archives loaded returned an
  empty success indistinguishable from "no hits", and the single-archive
  ``missing_archive`` advice told the caller to pass a path that does not
  exist.

Every test drives the real object (``ZimOperations`` / the registered
``zim_search`` handler) with only the libzim layer stubbed, and asserts on
what the tool actually emits.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import CacheConfig, ContentConfig, OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.defaults import SEARCH
from openzim_mcp.security import PathValidator
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.zim_operations import ZimOperations

# ---------------------------------------------------------------------------
# Stubs — a warc2zim-shaped archive whose articles are long enough that the
# per-result snippet render is the dominant cost, as on the real corpora.
# ---------------------------------------------------------------------------

_SNIPPET_LENGTH = 3000

# One paragraph of ~120 chars; twenty-five of them render well past the
# snippet ceiling, so every row costs the full ``_SNIPPET_LENGTH``.
_PARAGRAPH = (
    "<p>Diabetes is a chronic health condition that affects how the body "
    "turns food into energy and regulates blood glucose levels.</p>"
)
_LONG_BODY = ("<html><body>" + _PARAGRAPH * 25 + "</body></html>").encode()


def _entry(path: str, title: Optional[str] = None) -> MagicMock:
    e = MagicMock()
    e.path = path
    e.title = title if title is not None else path.rsplit("/", 1)[-1]
    e.is_redirect = False
    item = MagicMock()
    item.mimetype = "text/html"
    item.content = _LONG_BODY
    e.get_item.return_value = item
    return e


def _ctx(value: Any) -> Any:
    class _C:
        def __enter__(self) -> Any:
            return value

        def __exit__(self, *a: Any) -> bool:
            return False

    return _C()


def _archive_stub(entries: Optional[Dict[str, MagicMock]] = None) -> MagicMock:
    archive = MagicMock()
    archive.has_new_namespace_scheme = True
    archive.has_fulltext_index = True
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False
    if entries is None:
        archive.get_entry_by_path.side_effect = _entry
    else:
        archive.get_entry_by_path.side_effect = lambda p: entries[p]
    return archive


def _search_stub(entry_ids: List[str], estimated: Optional[int] = None) -> MagicMock:
    search = MagicMock()
    search.getEstimatedMatches.return_value = (
        len(entry_ids) if estimated is None else estimated
    )
    search.getResults.side_effect = lambda start, count: entry_ids[
        start : start + count
    ]
    return search


def _make_ops(tmp_path: Path) -> ZimOperations:
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(
            max_content_length=100000, snippet_length=_SNIPPET_LENGTH
        ),
    )
    return ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(snippet_length=_SNIPPET_LENGTH),
    )


@pytest.fixture()
def ops_and_file(tmp_path: Path):
    ops = _make_ops(tmp_path)
    zim_file = tmp_path / "medlineplus.zim"
    zim_file.write_bytes(b"zim")
    return ops, zim_file


def _wire(monkeypatch, archive: MagicMock, search: MagicMock) -> None:
    """Point the search path at ``archive`` / ``search``.

    ``zim/search.py`` resolves both through ``openzim_mcp.zim_operations`` at
    call time, which is the seam the rest of the suite patches.
    """
    monkeypatch.setattr(
        "openzim_mcp.zim_operations.zim_archive", lambda *a, **kw: _ctx(archive)
    )
    searcher = MagicMock()
    searcher.return_value.search.return_value = search
    monkeypatch.setattr("openzim_mcp.zim_operations.Searcher", searcher)


def _row_chars(row: Dict[str, Any]) -> int:
    return (
        len(row.get("path", ""))
        + len(row.get("title", ""))
        + len(row.get("snippet", ""))
    )


def _stream(n: int, prefix: str = "medlineplus.gov/ency/article/") -> List[str]:
    return [f"{prefix}{i:06d}.htm" for i in range(n)]


# ---------------------------------------------------------------------------
# fid 28 / 63 / 125 — the fulltext page needs a response budget
# ---------------------------------------------------------------------------


class TestFulltextResponseBudget:
    """A documented-legal ``limit`` must not be an unbounded amplifier."""

    def test_wide_limit_stops_at_the_character_budget(
        self, ops_and_file, monkeypatch
    ) -> None:
        """fid 28/63: ``limit=1000`` shipped ~1 MB with ``truncated: false``.

        The page now stops on the character budget, reports the cut, and
        still serves a full page's worth of real rows.
        """
        ops, zim_file = ops_and_file
        stream = _stream(1000)
        _wire(monkeypatch, _archive_stub(), _search_stub(stream, estimated=5604))

        payload = ops.search_zim_file_data(str(zim_file), "diabetes", limit=1000)

        results = payload["results"]
        assembled = sum(_row_chars(r) for r in results)
        # Positive: a real page came back, every row a distinct article.
        assert len(results) >= 10, len(results)
        assert len({r["path"] for r in results}) == len(results)
        # Negative: it is not the unbounded 1000-row page any more.
        assert len(results) < 1000, len(results)
        assert assembled <= SEARCH.MAX_RESULT_CHARS + _SNIPPET_LENGTH, assembled
        # The cut is declared, not silent.
        assert payload["_meta"]["truncated"] is True, payload["_meta"]
        assert payload["page_info"]["budget_truncated"] is True
        assert payload["page_info"]["returned_count"] == len(results)
        assert payload["done"] is False
        assert payload["next_cursor"] is not None

    def test_budget_truncated_page_resumes_without_losing_a_row(
        self, ops_and_file, monkeypatch
    ) -> None:
        """The advertised resume point must be exact — no row skipped, none
        replayed. A budget cut that lost rows would be worse than the
        oversized page it replaced."""
        ops, zim_file = ops_and_file
        stream = _stream(1000)
        _wire(monkeypatch, _archive_stub(), _search_stub(stream, estimated=1000))

        page1 = ops.search_zim_file_data(str(zim_file), "diabetes", limit=1000)
        info = page1["page_info"]
        resume = info.get("source_consumed", info["returned_count"])
        page2 = ops.search_zim_file_data(
            str(zim_file), "diabetes", limit=1000, offset=resume
        )

        seen = [r["path"] for r in page1["results"]] + [
            r["path"] for r in page2["results"]
        ]
        assert seen == stream[: len(seen)], seen[:3]
        assert len(set(seen)) == len(seen)

    def test_narrow_limit_is_untouched_by_the_budget(
        self, ops_and_file, monkeypatch
    ) -> None:
        """The pairing negative-control: an ordinary page is not capped and
        does not claim to be."""
        ops, zim_file = ops_and_file
        stream = _stream(50)
        _wire(monkeypatch, _archive_stub(), _search_stub(stream, estimated=50))

        payload = ops.search_zim_file_data(str(zim_file), "diabetes", limit=10)

        assert len(payload["results"]) == 10
        assert payload["_meta"]["truncated"] is False
        assert "budget_truncated" not in payload["page_info"]

    def test_wall_clock_deadline_stops_a_slow_render(
        self, ops_and_file, monkeypatch
    ) -> None:
        """fid 125: a 45-53 s call outlives a typical MCP client timeout and
        the server has no cancellation. A deadline bounds the render loop
        even when the rows themselves are small enough to stay under the
        character budget."""
        ops, zim_file = ops_and_file
        stream = _stream(400)
        _wire(monkeypatch, _archive_stub(), _search_stub(stream, estimated=400))

        # A clock that advances one second per read: the deadline binds long
        # before the character budget would.
        ticks = iter(range(10_000))
        monkeypatch.setattr(
            "openzim_mcp.zim.search._monotonic", lambda: float(next(ticks))
        )

        payload = ops.search_zim_file_data(str(zim_file), "diabetes", limit=400)

        assert 0 < len(payload["results"]) <= SEARCH.RESULT_BUDGET_SECONDS + 2
        assert payload["page_info"]["budget_truncated"] is True
        assert payload["_meta"]["truncated"] is True

    def test_rendered_page_declares_the_cap_and_the_resume_offset(
        self, ops_and_file, monkeypatch
    ) -> None:
        """The markdown surface (``zim_query``'s renderer) must say the page
        was capped, not just the structured envelope."""
        ops, zim_file = ops_and_file
        stream = _stream(1000)
        _wire(monkeypatch, _archive_stub(), _search_stub(stream, estimated=5604))

        text = ops.search_zim_file(str(zim_file), "diabetes", limit=1000)

        assert "response-size budget" in text, text[-600:]
        # Positive control: the page still renders real hits and a usable
        # resume offset rather than only the warning.
        assert "## 1. " in text
        payload = ops.search_zim_file_data(str(zim_file), "diabetes", limit=1000)
        # The resume offset must land where the cut happened, not at the
        # ``offset + limit`` the requested page size would imply — that would
        # skip every row between the cut and result 1000.
        resume = payload["page_info"]["next_offset"]
        assert 0 < resume < 1000, payload["page_info"]
        assert f"pass `offset={resume}` for the next page" in text


# ---------------------------------------------------------------------------
# fid 59 — title mode must collapse warc2zim query-string variants
# ---------------------------------------------------------------------------

# The ranked title-index page the sweep observed for ``type 2 diabetes`` on
# medlineplus.gov_en_all_2025-01.zim. Ranks 4/5 and 7/8 are the same page
# twice: warc2zim files ``…?quiz=1`` as its own entry with an identical title.
_T2D_SUGGESTIONS: List[tuple] = [
    (
        "medlineplus.gov/genetics/condition/type-2-diabetes/",
        "Type 2 diabetes: MedlinePlus Genetics",
    ),
    (
        "medlineplus.gov/diabetestype2.html",
        "Type 2 Diabetes| Adult-Onset Diabetes | MedlinePlus",
    ),
    (
        "medlineplus.gov/ency/article/000313.htm",
        "Type 2 diabetes: MedlinePlus Medical Encyclopedia",
    ),
    (
        "medlineplus.gov/ency/quiz/001214_3.htm",
        "Type 2 Diabetes Facts Quiz: MedlinePlus Medical Encyclopedia",
    ),
    (
        "medlineplus.gov/ency/quiz/001214_3.htm?quiz=1",
        "Type 2 Diabetes Facts Quiz: MedlinePlus Medical Encyclopedia",
    ),
    (
        "medlineplus.gov/ency/patientinstructions/000328.htm",
        "Type 2 diabetes - self-care: MedlinePlus Medical Encyclopedia",
    ),
    (
        "medlineplus.gov/ency/quiz/000313_57.htm",
        "Type 2 Diabetes: How Healthy Is Your Lifestyle?: MedlinePlus",
    ),
    (
        "medlineplus.gov/ency/quiz/000313_57.htm?quiz=1",
        "Type 2 Diabetes: How Healthy Is Your Lifestyle?: MedlinePlus",
    ),
    (
        "medlineplus.gov/ency/patientinstructions/000217.htm",
        "Type 2 diabetes - what to ask your doctor: MedlinePlus",
    ),
    (
        "medlineplus.gov/diabetes.html",
        "Diabetes | Type 1 Diabetes | Type 2 Diabetes | MedlinePlus",
    ),
    ("medlineplus.gov/prediabetes.html", "Prediabetes | MedlinePlus"),
]


def _wire_title_index(monkeypatch, rows: List[tuple]) -> MagicMock:
    """A scraped archive whose only working lookup is the suggestion index."""
    entries = {path: _entry(path, title) for path, title in rows}
    archive = _archive_stub(entries)

    def _suggester(_archive: Any) -> MagicMock:
        searcher = MagicMock()
        sugg = MagicMock()
        paths = [p for p, _ in rows]
        sugg.getEstimatedMatches.return_value = len(paths)
        sugg.getResults.side_effect = lambda start, n: paths[start : start + n]
        searcher.suggest.return_value = sugg
        return searcher

    monkeypatch.setattr(
        "openzim_mcp.zim_operations.zim_archive", lambda *a, **kw: _ctx(archive)
    )
    monkeypatch.setattr("openzim_mcp.zim_operations.SuggestionSearcher", _suggester)
    return archive


class TestTitleModeCanonicalDedup:
    def test_query_string_variants_do_not_take_two_slots(
        self, ops_and_file, monkeypatch
    ) -> None:
        """fid 59: ``?quiz=1`` twins held ranks 4/5 and 7/8 — two of ten rows
        byte-identical to their neighbour. Fulltext already collapses them."""
        ops, zim_file = ops_and_file
        _wire_title_index(monkeypatch, _T2D_SUGGESTIONS)

        out = ops.find_entry_by_title_data(str(zim_file), "type 2 diabetes", limit=10)
        paths = [r["path"] for r in out["results"]]

        # Positive: the real pages are all still there, best score first.
        assert "medlineplus.gov/ency/quiz/001214_3.htm" in paths
        assert "medlineplus.gov/ency/quiz/000313_57.htm" in paths
        assert paths[0] == "medlineplus.gov/genetics/condition/type-2-diabetes/"
        # Negative: their query-string twins are gone, and no canonical path
        # appears twice anywhere on the page.
        assert "medlineplus.gov/ency/quiz/001214_3.htm?quiz=1" not in paths
        assert "medlineplus.gov/ency/quiz/000313_57.htm?quiz=1" not in paths
        canonicals = [p.split("?", 1)[0] for p in paths]
        assert len(set(canonicals)) == len(canonicals), canonicals

    def test_the_surviving_row_is_the_higher_scored_one(
        self, ops_and_file, monkeypatch
    ) -> None:
        """Dedup runs after the score sort, so whichever twin the title index
        ranked higher is the one that stays — the collapse must never demote
        a page to its weaker twin's rank."""
        ops, zim_file = ops_and_file
        rows = [
            ("medlineplus.gov/ency/quiz/001214_3.htm?quiz=1", "Type 2 Quiz"),
            ("medlineplus.gov/ency/article/000313.htm", "Type 2 diabetes"),
            ("medlineplus.gov/ency/quiz/001214_3.htm", "Type 2 Quiz"),
        ]
        _wire_title_index(monkeypatch, rows)

        out = ops.find_entry_by_title_data(str(zim_file), "type 2", limit=10)
        by_path = {r["path"]: r["score"] for r in out["results"]}

        # Positive: the better-ranked member of the pair is the survivor,
        # and the unrelated article is untouched.
        assert "medlineplus.gov/ency/quiz/001214_3.htm?quiz=1" in by_path
        assert "medlineplus.gov/ency/article/000313.htm" in by_path
        # Negative: the weaker twin is gone rather than sitting beside it.
        assert "medlineplus.gov/ency/quiz/001214_3.htm" not in by_path
        assert len(by_path) == 2, by_path

    def test_sibling_pages_are_never_collapsed(self, ops_and_file, monkeypatch) -> None:
        """Control: two genuinely different pages under one directory keep
        their own rows; only the query-string twin folds away."""
        ops, zim_file = ops_and_file
        rows = [
            ("medlineplus.gov/ency/article/000313.htm", "Type 2 diabetes"),
            ("medlineplus.gov/ency/article/000305.htm", "Type 1 diabetes"),
            ("medlineplus.gov/ency/article/000313.htm?x=1", "Type 2 diabetes"),
        ]
        _wire_title_index(monkeypatch, rows)

        out = ops.find_entry_by_title_data(str(zim_file), "diabetes", limit=10)
        paths = [r["path"] for r in out["results"]]

        assert "medlineplus.gov/ency/article/000313.htm" in paths
        assert "medlineplus.gov/ency/article/000305.htm" in paths
        assert len(paths) == 2, paths


# ---------------------------------------------------------------------------
# fid 58 — the advanced fulltext tool must be at least as relevant as the
# simple one on the same archive and query
# ---------------------------------------------------------------------------

# The ranked full-text page ``zim_search(mode='fulltext', limit=10)`` returned
# for ``epistemology`` on internet-encyclopedia-philosophy_en_all_2025-06.zim.
# ``iep.utm.edu/epistemo/`` — the article actually named Epistemology — was at
# rank 27 of 100 and absent from a default-sized page entirely, while
# ``zim_query`` put it at rank 1 with "Match type: canonical title match".
_IEP_CANONICAL = "iep.utm.edu/epistemo/"
_IEP_CANONICAL_TITLE = "Epistemology | Internet Encyclopedia of Philosophy"
_IEP_BM25_PAGE = [
    (
        "iep.utm.edu/ethno-ep/",
        "Ethnoepistemology | Internet Encyclopedia of Philosophy",
    ),
    (
        "iep.utm.edu/fem-epis/",
        "Feminist Epistemology | Internet Encyclopedia of Philosophy",
    ),
    (
        "iep.utm.edu/ref-epis/",
        "Reformed Epistemology | Internet Encyclopedia of Philosophy",
    ),
    (
        "iep.utm.edu/mor-epis/",
        "Moral Epistemology | Internet Encyclopedia of Philosophy",
    ),
    (
        "iep.utm.edu/virtue-epistemology/",
        "Virtue Epistemology | Internet Encyclopedia of Philosophy",
    ),
]


def _philosophy_server(tmp_path: Path, monkeypatch, *, title_index: List[str]):
    """An advanced-mode server over a stubbed IEP-shaped archive.

    ``title_index`` is what libzim's SuggestionSearcher returns for any
    query — the seam the canonical-title probe resolves through.
    """
    zim_file = tmp_path / "iep.zim"
    zim_file.write_bytes(b"zim")
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        tool_mode="advanced",
        cache=CacheConfig(enabled=False),
        content=ContentConfig(
            max_content_length=100000, snippet_length=_SNIPPET_LENGTH
        ),
    )
    server = OpenZimMcpServer(config)

    known = {path: _entry(path, title) for path, title in _IEP_BM25_PAGE}
    known[_IEP_CANONICAL] = _entry(_IEP_CANONICAL, _IEP_CANONICAL_TITLE)
    archive = _archive_stub(known)
    _wire(monkeypatch, archive, _search_stub([p for p, _ in _IEP_BM25_PAGE]))

    def _suggester(_archive: Any) -> MagicMock:
        searcher = MagicMock()
        sugg = MagicMock()
        sugg.getEstimatedMatches.return_value = len(title_index)
        sugg.getResults.side_effect = lambda start, n: title_index[start : start + n]
        searcher.suggest.return_value = sugg
        return searcher

    monkeypatch.setattr("openzim_mcp.zim_operations.SuggestionSearcher", _suggester)
    return server, zim_file


class TestAdvancedFulltextCanonicalSplice:
    @pytest.mark.asyncio
    async def test_exact_title_article_is_promoted_onto_the_fulltext_page(
        self, tmp_path, monkeypatch
    ) -> None:
        """fid 58: the canonical-title splice was wired into ``zim_query``
        only, so the tool whose whole job is search buried the article the
        query names."""
        server, zim_file = _philosophy_server(
            tmp_path, monkeypatch, title_index=[_IEP_CANONICAL]
        )
        handler = server.mcp._tool_manager._tools["zim_search"].fn

        out = await handler(
            query="epistemology",
            mode="fulltext",
            zim_file_path=str(zim_file),
            limit=5,
        )

        paths = [r["path"] for r in out["results"]]
        # Positive: the canonical article leads and is labelled as a title
        # match, exactly as ``zim_query`` renders it.
        assert paths[0] == _IEP_CANONICAL, paths
        assert out["results"][0]["snippet"] == "(canonical title match)"
        # Positive: the splice is additive — every BM25 hit survives.
        for bm25_path, _title in _IEP_BM25_PAGE:
            assert bm25_path in paths, paths
        # ``_meta`` describes the page that ships, not the pre-splice one.
        body = json.dumps(
            {k: v for k, v in out.items() if k != "_meta"}, ensure_ascii=False
        )
        assert out["_meta"]["chars"] == len(body)

    @pytest.mark.asyncio
    async def test_no_splice_when_the_top_hit_already_is_the_canonical(
        self, tmp_path, monkeypatch
    ) -> None:
        """Negative control: a page whose rank 1 already names the query is
        left alone — no synthetic row, no duplicate."""
        server, zim_file = _philosophy_server(
            tmp_path, monkeypatch, title_index=[_IEP_CANONICAL]
        )
        handler = server.mcp._tool_manager._tools["zim_search"].fn

        out = await handler(
            query="ethnoepistemology",
            mode="fulltext",
            zim_file_path=str(zim_file),
            limit=5,
        )

        paths = [r["path"] for r in out["results"]]
        assert paths == [p for p, _ in _IEP_BM25_PAGE], paths
        assert all(r["snippet"] != "(canonical title match)" for r in out["results"])

    @pytest.mark.asyncio
    async def test_paged_results_are_not_re_spliced(
        self, tmp_path, monkeypatch
    ) -> None:
        """The splice is a page-1 promotion. Injecting it again at
        ``offset > 0`` would re-serve the canonical on every page."""
        server, zim_file = _philosophy_server(
            tmp_path, monkeypatch, title_index=[_IEP_CANONICAL]
        )
        handler = server.mcp._tool_manager._tools["zim_search"].fn

        out = await handler(
            query="epistemology",
            mode="fulltext",
            zim_file_path=str(zim_file),
            limit=2,
            offset=2,
        )

        paths = [r["path"] for r in out["results"]]
        assert _IEP_CANONICAL not in paths, paths
        assert paths, paths


# ---------------------------------------------------------------------------
# fid 2 / 3 — zero archives loaded is its own failure, not "no hits"
# ---------------------------------------------------------------------------


@pytest.fixture()
def empty_server(tmp_path: Path):
    """An advanced-mode server whose allowed directory holds no archives."""
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        tool_mode="advanced",
        cache=CacheConfig(enabled=False),
    )
    server = OpenZimMcpServer(config)
    return server.mcp._tool_manager._tools["zim_search"].fn


class TestZeroArchivesIsNotZeroHits:
    @pytest.mark.asyncio
    async def test_cross_file_fan_out_over_nothing_is_an_error(
        self, empty_server
    ) -> None:
        """fid 2: a fan-out over zero archives returned ``isError=false`` with
        an empty result list — byte-identical to a genuine miss. Simple mode
        has said "No ZIM Archives Loaded" for this condition all along."""
        out = await empty_server(query="aspirin", cross_file=True)

        assert out.get("error") is True, out
        assert out["operation"] == "no_archives_loaded"
        # Positive: the message says what is wrong and where to get one.
        assert "no `.zim` files" in out["message"], out["message"]
        assert "library.kiwix.org" in out["message"], out["message"]
        # Negative: it must not read as a successful empty search.
        assert "results" not in out

    @pytest.mark.asyncio
    async def test_cross_file_title_mode_over_nothing_is_an_error(
        self, empty_server
    ) -> None:
        """Same condition through ``mode='title'``, which used to answer with
        a hint about per-archive promotion on a server with nothing to
        promote."""
        out = await empty_server(query="aspirin", mode="title", cross_file=True)

        assert out.get("error") is True, out
        assert out["operation"] == "no_archives_loaded"
        assert "promotion" not in out["message"].lower(), out["message"]
        assert "library.kiwix.org" in out["message"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["fulltext", "title", "suggest"])
    async def test_missing_archive_advice_names_the_real_cause(
        self, empty_server, mode
    ) -> None:
        """fid 3: ``_resolve_path`` returns None for two different worlds —
        zero archives and two-or-more — and the advice only fitted the
        second. Every step it listed ("pass a path", "load exactly one",
        "use cross_file") is a dead end when there is nothing loaded."""
        out = await empty_server(query="aspirin", mode=mode)

        assert out.get("error") is True, out
        assert out["operation"] == "no_archives_loaded", out
        # Negative: none of the three impossible remedies is offered.
        assert "load exactly one archive" not in out["message"], out["message"]
        assert "cross_file=True" not in out["message"], out["message"]
        # Positive: the acquisition route is.
        assert "library.kiwix.org" in out["message"]

    @pytest.mark.asyncio
    async def test_multi_archive_advice_is_unchanged(self, tmp_path) -> None:
        """Control: with archives loaded but none pinned, the original
        "pass ``zim_file_path``" advice is still exactly right."""
        for name in ("a.zim", "b.zim"):
            (tmp_path / name).write_bytes(b"zim")
        config = OpenZimMcpConfig(
            allowed_directories=[str(tmp_path)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        handler = OpenZimMcpServer(config).mcp._tool_manager._tools["zim_search"].fn

        out = await handler(query="aspirin", mode="fulltext")

        assert out.get("error") is True, out
        assert out["operation"] == "missing_archive", out
        assert "Pass `zim_file_path`" in out["message"], out["message"]


# ---------------------------------------------------------------------------
# fid 60 — a fulltext miss must offer the recovery title mode already makes
# ---------------------------------------------------------------------------

_DIABETES_PATH = "medlineplus.gov/diabetes.html"
_DIABETES_TITLE = "Diabetes | Type 1 Diabetes | Type 2 Diabetes | MedlinePlus"


def _wire_typo_corpus(monkeypatch, *, fulltext_hits: List[str]) -> None:
    """MedlinePlus's real behaviour for the typo ``diabetis``.

    Xapian matches nothing. ``SuggestionSearcher`` is a title-PREFIX matcher,
    so it also returns nothing for the typo itself — but it does resolve the
    Levenshtein-1 correction ``diabetes``, which is how ``mode='title'``
    recovers the identical query.
    """
    archive = _archive_stub({_DIABETES_PATH: _entry(_DIABETES_PATH, _DIABETES_TITLE)})
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False
    _wire(monkeypatch, archive, _search_stub(fulltext_hits))

    def _suggester(_archive: Any) -> MagicMock:
        searcher = MagicMock()

        def _suggest(text: str) -> MagicMock:
            paths = (
                [_DIABETES_PATH]
                if "diabetes".startswith(text.lower()) and len(text) >= 5
                else []
            )
            sugg = MagicMock()
            sugg.getEstimatedMatches.return_value = len(paths)
            sugg.getResults.side_effect = lambda s, n: paths[s : s + n]
            return sugg

        searcher.suggest.side_effect = _suggest
        return searcher

    monkeypatch.setattr("openzim_mcp.zim_operations.SuggestionSearcher", _suggester)


class TestFulltextZeroHitRecovery:
    def test_misspelling_yields_a_reissuable_alt_spelling(
        self, ops_and_file, monkeypatch
    ) -> None:
        """fid 60: fulltext's 0-hit branch calls ``SuggestionSearcher.suggest``,
        a title-PREFIX matcher that structurally cannot correct a typo, so the
        page shipped ``reason: "0_hits"`` with no ``suggestions`` key at all —
        while ``mode='title'`` recovered the same query."""
        ops, zim_file = ops_and_file
        _wire_typo_corpus(monkeypatch, fulltext_hits=[])

        payload = ops.search_zim_file_data(str(zim_file), "diabetis", limit=5)

        assert payload["_meta"]["reason"] == "0_hits"
        suggestions = payload["_meta"].get("suggestions") or []
        values = [s["value"] for s in suggestions if s["type"] == "alt_spelling"]
        # Positive: the correction is offered, as the article's own name
        # rather than its site-suffixed title — the footer renders it as
        # ``suggestions for <value>``, so the value has to be re-issuable.
        assert "Diabetes" in values, suggestions
        # Negative: the un-reissuable full title is not what ships.
        assert _DIABETES_TITLE not in values, suggestions

    def test_no_near_title_means_no_fabricated_suggestion(
        self, ops_and_file, monkeypatch
    ) -> None:
        """Control: a genuine miss with nothing near it stays a clean miss."""
        ops, zim_file = ops_and_file
        _wire_typo_corpus(monkeypatch, fulltext_hits=[])

        payload = ops.search_zim_file_data(str(zim_file), "zzzqqqx", limit=5)

        assert payload["_meta"]["reason"] == "0_hits"
        assert not payload["_meta"].get("suggestions"), payload["_meta"]

    def test_a_page_with_hits_pays_no_extra_title_probe(
        self, ops_and_file, monkeypatch
    ) -> None:
        """Control: the recovery is gated to the zero-hit branch, so an
        ordinary page carries no recovery hints."""
        ops, zim_file = ops_and_file
        _wire_typo_corpus(monkeypatch, fulltext_hits=[_DIABETES_PATH])

        payload = ops.search_zim_file_data(str(zim_file), "diabetes", limit=5)

        assert payload["results"], payload
        assert "suggestions" not in payload["_meta"], payload["_meta"]


# ---------------------------------------------------------------------------
# fid 73 — `total` is Xapian's estimate and must say so
# ---------------------------------------------------------------------------


class TestTotalIsFlaggedAsAnEstimate:
    def test_unfiltered_fulltext_marks_its_total_approximate(
        self, ops_and_file, monkeypatch
    ) -> None:
        """fid 73: the filtered path sets ``total_is_lower_bound`` and suggest
        sets its own reason; unfiltered fulltext shipped a bare round
        ``getEstimatedMatches()`` with no marker anywhere in the payload."""
        ops, zim_file = ops_and_file
        _wire(monkeypatch, _archive_stub(), _search_stub(_stream(20), estimated=900))

        payload = ops.search_zim_file_data(str(zim_file), "diabetes", limit=5)

        assert payload["total"] == 900
        assert payload["page_info"]["total_is_estimate"] is True, payload["page_info"]

    def test_an_empty_page_claims_no_estimate(self, ops_and_file, monkeypatch) -> None:
        """Control: zero is not an estimate of anything."""
        ops, zim_file = ops_and_file
        _wire(monkeypatch, _archive_stub(), _search_stub([], estimated=0))

        payload = ops.search_zim_file_data(str(zim_file), "zzzqqqx", limit=5)

        assert payload["total"] == 0
        assert "total_is_estimate" not in payload["page_info"]


# ---------------------------------------------------------------------------
# fid 62 — 0-hit recovery advice must lead with the step that recovers
# ---------------------------------------------------------------------------


class TestZeroHitAdviceOrdering:
    def test_title_lookup_leads_the_recovery_list(
        self, ops_and_file, monkeypatch
    ) -> None:
        """fid 62: the advice led with ``suggestions for X`` — prefix
        autocomplete, which provably returns nothing for a misspelling and
        renders as a raw JSON blob — while the step that actually recovers
        the query sat second."""
        ops, zim_file = ops_and_file
        _wire_typo_corpus(monkeypatch, fulltext_hits=[])

        text = ops.search_zim_file(str(zim_file), "diabetis")

        assert "**Try one of these:**" in text, text
        topic_lookup: int = text.index("`tell me about diabetis`")
        autocomplete = text.index("`suggestions for diabetis`")
        assert topic_lookup < autocomplete, text

    def test_the_swappable_bullet_survives_verbatim(
        self, ops_and_file, monkeypatch
    ) -> None:
        """``simple_tools._swap_tell_me_about_recovery_hint`` rewrites this
        exact bullet into ``find article titled X`` when the caller already
        tried ``tell me about`` — a narrow string replace, pinned by
        ``TestTellMeAboutNoResultsRecoveryNotCircular``. Reordering must not
        break the string it matches on, or the tell-me-about fallback would
        recommend the query that just failed."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        ops, zim_file = ops_and_file
        _wire_typo_corpus(monkeypatch, fulltext_hits=[])

        text = ops.search_zim_file(str(zim_file), "diabetis")
        swapped = SimpleToolsHandler._swap_tell_me_about_recovery_hint(text, "diabetis")

        # Positive: the swap fired, and the working recovery now leads.
        assert "`find article titled diabetis`" in swapped, swapped
        assert swapped.index("`find article titled diabetis`") < swapped.index(
            "`suggestions for diabetis`"
        ), swapped
        # Negative: the circular advice is gone from the swapped text.
        assert "`tell me about diabetis`" not in swapped, swapped


# ---------------------------------------------------------------------------
# fid 67 — the resume point must be a value, not a conditional rule
# ---------------------------------------------------------------------------


class TestResumePointIsAlwaysCarried:
    def test_next_offset_rides_every_unfinished_page(
        self, ops_and_file, monkeypatch
    ) -> None:
        """fid 67: the resume point was a RULE ("advance by
        ``source_consumed`` if present, else by ``limit``") documented in
        prose only, and ``source_consumed`` rides only the pages where the
        dedup collapsed something. A caller doing the obvious
        ``offset += limit`` re-served three of fifty rows on the shipped
        MedlinePlus corpus."""
        ops, zim_file = ops_and_file
        # A clean stream: nothing collapses, which is exactly the shape that
        # carries no ``source_consumed`` and left the caller guessing.
        _wire(monkeypatch, _archive_stub(), _search_stub(_stream(30)))

        payload = ops.search_zim_file_data(str(zim_file), "diabetes", limit=5)
        info = payload["page_info"]

        assert payload["done"] is False
        assert info["next_offset"] == 5, info
        assert "source_consumed" not in info, info

    def test_a_finished_page_advertises_no_next_offset(
        self, ops_and_file, monkeypatch
    ) -> None:
        """Control: the key means "there is a next page", so an exhausted
        page must not carry one."""
        ops, zim_file = ops_and_file
        _wire(monkeypatch, _archive_stub(), _search_stub(_stream(4)))

        payload = ops.search_zim_file_data(str(zim_file), "diabetes", limit=10)

        assert payload["done"] is True
        assert payload["results"]
        assert "next_offset" not in payload["page_info"]

    def test_following_next_offset_never_re_serves_a_row(
        self, ops_and_file, monkeypatch
    ) -> None:
        """The whole walk, over a stream carrying the query-string variants
        that make ``offset += limit`` wrong."""
        ops, zim_file = ops_and_file
        stream: List[str] = []
        for i in range(12):
            stream.append(f"medlineplus.gov/ency/quiz/{i:06d}.htm")
            if i % 3 == 0:
                stream.append(f"medlineplus.gov/ency/quiz/{i:06d}.htm?quiz=1")
        _wire(monkeypatch, _archive_stub(), _search_stub(stream))

        seen: List[str] = []
        offset = 0
        for _ in range(20):
            page = ops.search_zim_file_data(
                str(zim_file), "quiz", limit=4, offset=offset
            )
            seen.extend(r["path"] for r in page["results"])
            if page["done"]:
                break
            offset = page["page_info"]["next_offset"]

        assert len(seen) == len(set(seen)), seen
        # Positive: the walk actually enumerated every distinct page.
        assert len(seen) == 12, seen


# ---------------------------------------------------------------------------
# fid 66 — an unfinished cross-archive page must name a route that exists
# ---------------------------------------------------------------------------


def _two_archive_server(tmp_path: Path, monkeypatch, *, hits: int):
    """An advanced server over two stub archives that both have more hits."""
    for name in ("alpha.zim", "beta.zim"):
        (tmp_path / name).write_bytes(b"zim")
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        tool_mode="advanced",
        cache=CacheConfig(enabled=False),
        content=ContentConfig(
            max_content_length=100000, snippet_length=_SNIPPET_LENGTH
        ),
    )
    server = OpenZimMcpServer(config)
    _wire(monkeypatch, _archive_stub(), _search_stub(_stream(hits)))
    return server.mcp._tool_manager._tools["zim_search"].fn


class TestCrossFilePagingIsNotADeadEnd:
    @pytest.mark.asyncio
    async def test_unfinished_fan_out_names_the_per_archive_route(
        self, tmp_path, monkeypatch
    ) -> None:
        """fid 66: the block announced ``done: false`` with a nulled
        ``next_cursor``, while ``offset`` and ``cursor`` are both rejected
        for ``cross_file=True`` — every advertised continuation refused, and
        nothing said what to do instead."""
        handler = _two_archive_server(tmp_path, monkeypatch, hits=40)

        out = await handler(query="diabetes", cross_file=True, limit=2)

        blocks = out["results"]
        assert blocks, out
        assert any(b["result"]["done"] is False for b in blocks), blocks
        assert all(b["result"]["next_cursor"] is None for b in blocks), blocks
        hint = out["_meta"]["hint"]
        # Positive: the hint names the archive to pin and the knob that works.
        assert "alpha.zim" in hint, hint
        assert "offset" in hint, hint
        # Negative: it does not send the caller back to the refused knobs.
        assert "cursor` to page" not in hint, hint

    @pytest.mark.asyncio
    async def test_a_complete_fan_out_carries_no_paging_hint(
        self, tmp_path, monkeypatch
    ) -> None:
        """Control: when every archive was exhausted there is nothing to
        page, so no hint is attached."""
        handler = _two_archive_server(tmp_path, monkeypatch, hits=2)

        out = await handler(query="diabetes", cross_file=True, limit=5)

        assert all(b["result"]["done"] is True for b in out["results"]), out
        assert "hint" not in (out.get("_meta") or {}), out["_meta"]
