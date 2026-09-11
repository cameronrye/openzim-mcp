"""Crawl artefacts must not outrank the article the caller asked for.

v3.3.1 field report, fid 71 — the report's own "bigger opportunity
underneath": both reranker configurations put a relevant article at #1 only
about 64% of the time and carry off-topic entries in every top-5.

The artefacts are scraper output, not articles: ``/imagepages/`` caption
stubs, ``/languages/`` translation hubs and ``.srt`` caption files.
``title 'migraine headache'`` returns an image-caption stub as its single
hit. Measured on the shipped MedlinePlus archive, 40 topic queries at
``limit=5``, rate limiter and cache off, v3.3.2 against this change:

                   rows  artefacts  artefact at #1  artefact above an article
    title           184    26.1%       4  ->  1           30  ->  0 pages
    suggest         184    26.6%       6  ->  1           29  ->  0 pages
    chooser          82    12.2%       7  ->  1            7  ->  0 lists

The artefact share does not move, and must not: the demote reorders the page
it is given and never evicts from it. The one remaining #1 is a page whose
every row is an artefact.

**``/category/`` is deliberately NOT an artefact.** On the IEP archive
those pages are the encyclopedia's own topic index and the correct #1, at
score 1.0, for "metaphysics", "philosophy of science", "feminist
philosophy" and "continental philosophy" — demoting them would turn four
right answers into wrong ones. Neither is ``/page/N/``: it was in the set and
was removed on measurement (see ``test_index_pagination_is_not_an_artefact``).

Three surfaces need it, not the two the finding names: single- and
cross-archive title mode at the response edge, suggest mode (served by
``get_search_suggestions_data``, a different function from
``_assemble_find_response``), and the ``zim_query`` chooser.

The demote is STABLE and drops nothing: relative order within each group is
the archive's own ranking, and every row the caller would have had is still
there. A page whose rows are *all* artefacts therefore comes back untouched
— which falls out of the partition rather than needing a guard, as the
mutation pass proved by deleting the guard and changing no behaviour.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from libzim.writer import Creator

from openzim_mcp.async_operations import AsyncZimOperations
from openzim_mcp.config import CacheConfig, OpenZimMcpConfig, RateLimitConfig
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.title_promotion import find_title_match
from openzim_mcp.zim.search import demote_crawl_artefacts, is_crawl_artefact
from tests.conftest_v2_fixtures import _HtmlItem

# ---------------------------------------------------------------------------
# What counts as an artefact
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "medlineplus.gov/ency/imagepages/18146.htm",
        "medlineplus.gov/languages/hepatitisb.html",
        "medlineplus.gov/media/captions/tutorial.srt",
        # Matched regardless of case; nothing pinned the flag before.
        "medlineplus.gov/ency/ImagePages/1.htm",
        "a.org/LANGUAGES/x.html",
        "a.org/captions/x.SRT",
    ],
)
def test_scraper_output_is_an_artefact(path: str) -> None:
    assert is_crawl_artefact(path) is True


@pytest.mark.parametrize(
    "path",
    [
        # The load-bearing exclusion: IEP's own topic index, and the correct
        # #1 at score 1.0 for four real queries.
        "iep.utm.edu/category/m-and-e/metaphysics/",
        "iep.utm.edu/category/traditions/feminist/",
        # Ordinary articles.
        "medlineplus.gov/hepatitisb.html",
        "medlineplus.gov/druginfo/natural/211.html",
        "iep.utm.edu/aristotle/",
        "A/Climate_change",
        # Near-misses that must not trip the patterns.
        "medlineplus.gov/imagepagesreview.html",
        "medlineplus.gov/languages-of-health.html",
        "A/Page_three",
        "medlineplus.gov/srt-therapy.html",
        # ``.srt`` counts only at the END of the path.
        "a.org/guide.srt.html",
        "",
    ],
)
def test_real_content_is_not_an_artefact(path: str) -> None:
    assert is_crawl_artefact(path) is False


def test_index_pagination_is_not_an_artefact():
    """``/page/N/`` was in the set and was removed on measurement.

    It matched nothing on MedlinePlus and exactly two entries on IEP, both
    false positives: ``category/…/metaphysics/page/2/`` is the continuation
    of the topic index ``/category/`` is kept for — page 1 lists 50 articles,
    page 2 lists 19 more with zero overlap, both at score 1.0. "Index
    pagination is scraper output wherever it lives" sounded right and, on
    every shipped archive, only ever discarded real content.
    """
    assert is_crawl_artefact("iep.utm.edu/category/s-l-m/science/") is False
    assert is_crawl_artefact("iep.utm.edu/category/s-l-m/science/page/2/") is False
    assert is_crawl_artefact("iep.utm.edu/page/3/") is False


# ---------------------------------------------------------------------------
# How the demote behaves
# ---------------------------------------------------------------------------


def _paths(rows):
    return [r["path"] for r in rows]


def test_artefacts_sink_below_articles():
    rows = [
        {"path": "medlineplus.gov/ency/imagepages/18146.htm"},
        {"path": "medlineplus.gov/migraine.html"},
        {"path": "medlineplus.gov/languages/migraine.html"},
        {"path": "medlineplus.gov/headache.html"},
    ]

    assert _paths(demote_crawl_artefacts(rows)) == [
        "medlineplus.gov/migraine.html",
        "medlineplus.gov/headache.html",
        "medlineplus.gov/ency/imagepages/18146.htm",
        "medlineplus.gov/languages/migraine.html",
    ]


def test_the_demote_is_stable_within_each_group():
    """Relative order is the archive's ranking, and the demote is not
    entitled to an opinion about it — only about which group a row is in.

    The rows below MUST include an artefact: with none, the function early
    -returns and this never reaches the partition at all. The first version
    of this test used five clean rows and so passed against a build that
    reversed the kept group.
    """
    rows = [
        {"path": "a.org/0.html"},
        {"path": "a.org/1.html"},
        {"path": "a.org/languages/x.html"},
        {"path": "a.org/2.html"},
        {"path": "a.org/ency/imagepages/9.htm"},
        {"path": "a.org/3.html"},
    ]

    assert _paths(demote_crawl_artefacts(rows)) == [
        "a.org/0.html",
        "a.org/1.html",
        "a.org/2.html",
        "a.org/3.html",
        "a.org/languages/x.html",
        "a.org/ency/imagepages/9.htm",
    ]


def test_a_page_of_nothing_but_artefacts_is_left_alone():
    """On a query whose honest answer IS an image page, the archive's own
    ranking is the best available. This falls out of the partition rather
    than from a special case — pinned as behaviour, since an explicit guard
    for it turned out to be unreachable."""
    rows = [
        {"path": "medlineplus.gov/ency/imagepages/1.htm"},
        {"path": "medlineplus.gov/languages/x.html"},
    ]

    assert demote_crawl_artefacts(rows) == rows


def test_nothing_is_dropped_ever():
    """A demote, not a filter: the caller keeps every row it would have had.
    Paired with the ordering tests so "artefacts are gone" cannot be
    satisfied by deleting them."""
    rows = [
        {"path": "medlineplus.gov/ency/imagepages/1.htm"},
        {"path": "medlineplus.gov/migraine.html"},
        {"path": "medlineplus.gov/media/x.srt"},
    ]

    out = demote_crawl_artefacts(rows)
    assert sorted(_paths(out)) == sorted(_paths(rows))
    assert len(out) == len(rows)


def test_an_empty_page_is_handled():
    assert demote_crawl_artefacts([]) == []


def test_rows_without_a_path_are_not_promoted_or_dropped():
    """Defensive: a malformed row must not crash the sort or vanish.

    Asserts both halves its name claims — that the pathless row is still
    there (not dropped) and that it did not jump the real row (not
    promoted). The first version checked only ``len(out) == 2``, which is
    satisfied by any ordering at all.
    """
    rows = [
        {"path": "a.org/languages/x.html"},
        {"title": "no path"},
        {"path": "a.org/real.html"},
    ]

    out = demote_crawl_artefacts(rows)

    assert {r.get("path") or r.get("title") for r in out} == {
        "a.org/languages/x.html",
        "no path",
        "a.org/real.html",
    }
    # A pathless row is not an artefact, so it keeps its place relative to
    # the other non-artefact row and both lead the demoted one.
    assert [r.get("path", "") for r in out][-1] == "a.org/languages/x.html"


# ---------------------------------------------------------------------------
# The wirings — each drives a real surface whose ranking actually inverts
# ---------------------------------------------------------------------------
#
# The first version of this file tested only the two pure helpers. All three
# call sites could be reverted and every test here, the full unit suite and
# the live suite still passed — the exact "tested the renderer, called the
# wiring covered" shape this project has shipped before. Each test below
# feeds a surface an ordering where an artefact outranks an article, which is
# the only condition under which the demote is observable.


def _server(tmp_path):
    (tmp_path / "a.zim").write_bytes(b"ZIM\x04" + b"\0" * 100)
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(tmp_path)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
            rate_limit=RateLimitConfig(enabled=False),
        )
    )


def test_the_title_response_edge_is_wired(tmp_path, monkeypatch):
    """``_handle_title_mode`` — driven end to end, not via its own helper.

    The first attempt at this test called ``_demote_artefacts_in_response``
    directly, so deleting the call from ``_handle_title_mode`` left it
    passing. Calling the helper you just wired proves the helper works and
    says nothing about the wiring; this drives the dispatch.
    """
    from openzim_mcp.tools import zim_search as tool

    server = _server(tmp_path)
    archive = str(tmp_path / "a.zim")

    class _Ops:
        async def find_entry_by_title_data(self, path, q, *, cross_file, limit):
            return {
                "results": [
                    {"path": "med.gov/languages/asthma.html", "score": 1.0},
                    {"path": "med.gov/asthma.html", "score": 0.9},
                ],
                "total": 2,
                "done": True,
                "_meta": {"chars": 1},
            }

    monkeypatch.setattr(tool, "_resolve_path", lambda *_a, **_k: archive)
    monkeypatch.setattr(
        "openzim_mcp.topic_preprocessing.promote_topic_via_title_index",
        lambda **_kw: None,
    )

    out = asyncio.run(
        tool._handle_title_mode(
            ops=_Ops(),
            server=server,
            query="asthma",
            zim_file_path=archive,
            cross_file=False,
            limit=5,
            offset=0,
            cursor=None,
        )
    )

    assert [r["path"] for r in out["results"]] == [
        "med.gov/asthma.html",
        "med.gov/languages/asthma.html",
    ]
    assert out["total"] == 2 and out["done"] is True


def test_the_cross_archive_title_branch_is_wired(tmp_path):
    """``cross_file=True`` returns from its own branch, ahead of the pinned
    path's demote, so the same lookup used to sink ``imagepages/`` stubs when
    pinned and lead with them here — while the API reference promised title
    mode sinks them."""
    from openzim_mcp.tools import zim_search as tool

    server = _server(tmp_path)

    class _Ops:
        async def find_entry_by_title_data(self, path, q, *, cross_file, limit):
            assert cross_file is True
            return {
                "results": [
                    {"path": "med.gov/languages/asthma.html", "score": 1.0},
                    {"path": "med.gov/asthma.html", "score": 0.9},
                ],
                "total": 2,
                "done": True,
                "files_searched": 1,
                "_meta": {"chars": 1},
            }

    out = asyncio.run(
        tool._handle_title_mode(
            ops=_Ops(),
            server=server,
            query="asthma",
            zim_file_path=None,
            cross_file=True,
            limit=5,
            offset=0,
            cursor=None,
        )
    )

    assert [r["path"] for r in out["results"]] == [
        "med.gov/asthma.html",
        "med.gov/languages/asthma.html",
    ]
    assert out["_meta"]["promotion_applied"] is False


def test_the_title_data_layer_is_deliberately_NOT_wired(tmp_path, monkeypatch):
    """The other half of the contract, and the regression this replaced.

    ``find_entry_by_title_data`` must keep emitting score-descending rows, or
    ``title_promotion.find_title_match`` — which reads ``results[0]`` under a
    score gate — silently stops resolving.
    """
    from openzim_mcp.zim import search as search_mod

    rows = [
        {"path": "med.gov/languages/asthma.html", "score": 1.0, "zim_file": "a"},
        {"path": "med.gov/asthma.html", "score": 0.9, "zim_file": "a"},
    ]
    assembled = search_mod._SearchMixin._assemble_find_response(
        _StubOps(),
        list(rows),
        title="asthma",
        limit=5,
        files=["a"],
        fast_path_hit=False,
        fuzzy_path_hit=False,
        verified_variants=[],
    )

    scores = [r["score"] for r in assembled["results"]]
    assert scores == sorted(scores, reverse=True), assembled["results"]
    assert assembled["results"][0]["path"] == "med.gov/languages/asthma.html"


class _StubOps:
    """Minimal ``self`` for ``_assemble_find_response`` — it is a pure
    transformation and touches only ``config.search``."""

    config = SimpleNamespace(search=SimpleNamespace(structured_suggestions_limit=3))


# ---------------------------------------------------------------------------
# Against a real archive, with the cache ON
# ---------------------------------------------------------------------------
#
# Every wiring test above runs with the cache off and calls once, so none of
# them could see the title demote reorder a CACHED page in place — which it
# did. ``_merge_promotion_into_title_results`` passes the cached
# ``find_title:v2`` page straight through when promotion changes nothing, and
# the edge then rewrote it; the next call's promotion probe read the demoted
# order, and on MedlinePlus a second ``title 'swollen glands'`` led with
# ``hormones.html`` at a fabricated 1.0.

_HOST = "medlineplus.gov"
# The artefact is the exact-title hit, so the title index ranks it first and
# the promotion probe resolves to it.
_ASTHMA_PAGES = [
    (f"{_HOST}/languages/asthma.html", "Asthma"),
    (f"{_HOST}/asthmainchildren.html", "Asthma in Children"),
]


def _medlineplus_like_zim(tmp_path: Path) -> Path:
    out = tmp_path / "medlineplus_like.zim"
    with Creator(out).config_indexing(True, "eng") as creator:
        for path, title in _ASTHMA_PAGES:
            creator.add_item(
                _HtmlItem(
                    path, title, f"<html><body><h1>{title}</h1><p>x</p></body></html>"
                )
            )
        creator.set_mainpath(_ASTHMA_PAGES[1][0])
    return out


def _cached_server(tmp_path: Path) -> OpenZimMcpServer:
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(tmp_path)],
            tool_mode="advanced",
            cache=CacheConfig(
                enabled=True,
                persistence_enabled=False,
                persistence_path=str(tmp_path / "cache"),
            ),
            rate_limit=RateLimitConfig(enabled=False),
        )
    )


def _title_page(ops, zim: Path, *, limit: int) -> list:
    page = ops.find_entry_by_title_data(str(zim), "asthma", limit=limit)
    return [(r["path"], r["score"]) for r in page["results"]]


def test_the_title_data_layer_stays_score_descending(tmp_path):
    """The public function the promotion probes actually call.

    ``test_the_title_data_layer_is_deliberately_NOT_wired`` drives the
    private ``_assemble_find_response``, so a demote added one function up —
    inside ``find_entry_by_title_data`` itself — passed every test while
    bringing the fabricated-promotion defect back on the first call.
    """
    zim = _medlineplus_like_zim(tmp_path)
    ops = _cached_server(tmp_path).zim_operations

    rows = _title_page(ops, zim, limit=5)
    scores = [score for _path, score in rows]

    assert len(scores) == 2, rows
    assert scores == sorted(scores, reverse=True), rows
    match = find_title_match(ops, str(zim), "asthma")
    assert match is not None and match["path"] == _ASTHMA_PAGES[0][0]


def test_the_title_edge_leaves_the_cached_page_alone(tmp_path):
    """A title call must not reorder the page the NEXT call's probe reads.

    ``limit=3`` is the size the promotion probe asks for, so this call and
    the probe share one cache key — the configuration in which the defect
    changed answers. The response is demoted; the cached page is not.
    """
    from openzim_mcp.tools import zim_search as tool

    zim = _medlineplus_like_zim(tmp_path)
    server = _cached_server(tmp_path)
    ops = server.zim_operations
    before = _title_page(ops, zim, limit=3)

    out = asyncio.run(
        tool._handle_title_mode(
            ops=AsyncZimOperations(ops),
            server=server,
            query="asthma",
            zim_file_path=str(zim),
            cross_file=False,
            limit=3,
            offset=0,
            cursor=None,
        )
    )

    assert [r["path"] for r in out["results"]] == [
        _ASTHMA_PAGES[1][0],
        _ASTHMA_PAGES[0][0],
    ]
    assert _title_page(ops, zim, limit=3) == before
    match = find_title_match(ops, str(zim), "asthma")
    assert match is not None and match["path"] == _ASTHMA_PAGES[0][0]


def test_the_suggest_wiring_is_live(tmp_path, monkeypatch):
    """``get_search_suggestions_data`` — a different function from the title
    assembly, which is why the finding that named two surfaces missed it."""
    from openzim_mcp.zim import search as search_mod

    server = _server(tmp_path)
    ops = server.zim_operations

    monkeypatch.setattr(
        search_mod._SearchMixin,
        "_generate_search_suggestions",
        lambda self, archive, q, limit: {
            "partial_query": q,
            "suggestions": [
                {"path": "med.gov/ency/imagepages/1.htm", "text": "X"},
                {"path": "med.gov/real.html", "text": "X"},
            ],
            "has_more": False,
        },
    )
    monkeypatch.setattr(search_mod, "_zim_ops_mod", _FakeArchiveModule(), raising=False)

    out = ops.get_search_suggestions_data(str(tmp_path / "a.zim"), "x", limit=5)

    assert [r["path"] for r in out["results"]] == [
        "med.gov/real.html",
        "med.gov/ency/imagepages/1.htm",
    ]


def test_the_suggest_demote_survives_a_cache_hit(tmp_path, monkeypatch):
    """The test above runs cache-off and calls once, so a demote applied only
    on the cold path — after the cache write — passed it, and every repeat
    of a query then served the raw order."""
    from openzim_mcp.zim import search as search_mod

    (tmp_path / "a.zim").write_bytes(b"ZIM\x04" + b"\0" * 100)
    ops = _cached_server(tmp_path).zim_operations
    monkeypatch.setattr(
        search_mod._SearchMixin,
        "_generate_search_suggestions",
        lambda self, archive, q, limit: {
            "partial_query": q,
            "suggestions": [
                {"path": "med.gov/ency/imagepages/1.htm", "text": "X"},
                {"path": "med.gov/real.html", "text": "X"},
            ],
            "has_more": False,
        },
    )
    monkeypatch.setattr(search_mod, "_zim_ops_mod", _FakeArchiveModule(), raising=False)

    want = ["med.gov/real.html", "med.gov/ency/imagepages/1.htm"]
    for _call in range(2):
        out = ops.get_search_suggestions_data(str(tmp_path / "a.zim"), "x", limit=5)
        assert [r["path"] for r in out["results"]] == want


class _FakeArchiveModule:
    """``zim_archive`` context manager yielding a do-nothing archive."""

    class _Ctx:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False

    def zim_archive(self, _path):
        return self._Ctx()


def test_the_chooser_wiring_is_live(tmp_path, monkeypatch):
    """``_collect_tell_me_about_strong_matches`` — the real method.

    Same correction as the title test: importing ``demote_crawl_artefacts``
    from ``simple_tools`` and calling it proves nothing about whether the
    method calls it.
    """
    from openzim_mcp import simple_tools as st

    server = _server(tmp_path)
    handler = st.SimpleToolsHandler(server.zim_operations)

    monkeypatch.setattr(st, "is_strong_title_match", lambda *_a, **_k: True)

    rows = [
        {"path": "med.gov/languages/asthma.html", "title": "Asthma"},
        {"path": "med.gov/asthma.html", "title": "Asthma"},
    ]

    out = handler._collect_tell_me_about_strong_matches(
        "asthma", str(tmp_path / "a.zim"), rows, "Asthma"
    )

    paths = [r["path"] for r in out]
    assert paths and paths[-1] == "med.gov/languages/asthma.html", paths
    assert "med.gov/asthma.html" in paths


def test_an_artefact_canonical_does_not_lead_the_chooser(tmp_path, monkeypatch):
    """The title-index canonical is prepended, then the list is demoted — so
    a canonical that is itself scraper output sinks with the rest.

    Deliberate: that canonical is the field report's own example of a wrong
    answer, an image-caption stub offered first as "(canonical title
    match)". Demoting before the prepend instead passed every test.
    """
    from openzim_mcp import simple_tools as st

    handler = st.SimpleToolsHandler(_server(tmp_path).zim_operations)
    monkeypatch.setattr(st, "is_strong_title_match", lambda *_a, **_k: True)
    monkeypatch.setattr(
        handler,
        "_promote_topic_via_title_index",
        lambda *_a, **_k: {
            "path": "med.gov/ency/imagepages/1.htm",
            "title": "Migraine headache",
        },
    )
    rows = [
        {"path": "med.gov/migraine.html", "title": "Migraine"},
        {"path": "med.gov/headache.html", "title": "Headache"},
    ]

    out = handler._collect_tell_me_about_strong_matches(
        "migraine headache", str(tmp_path / "a.zim"), rows, "Migraine"
    )

    paths = [r["path"] for r in out]
    assert paths[0] == "med.gov/migraine.html", paths
    assert paths[-1] == "med.gov/ency/imagepages/1.htm", paths
