"""Crawl artefacts must not outrank articles on fulltext-shaped surfaces either.

v3.3.1 field report, fid 71, second half. The first pass sank scraper output
— ``/imagepages/`` caption stubs, ``/languages/`` translation hubs, ``.srt``
caption files — on title, suggest and the ``zim_query`` chooser, and left
fulltext alone. Fulltext is the surface ``zim_query`` search intents and
``synthesize`` answer from, which is what the 64%-relevant-at-#1 reranker
evaluation measured: ``zim_query 'search for hepatitis b'`` led with
``languages/hepatitisb.html``. On the shipped MedlinePlus archive, 40 topic
queries at ``limit=5`` with rate limiter, cache and reranker off, an artefact
led 4 pages and sat above an article on 14, on each of the seven fulltext
routes; afterwards 0 and 0, every page the same rows reordered.

Where the demote sits, and why it differs from title mode:

* **Where the page is assembled** — ``_perform_search`` and
  ``_build_filtered_results`` — not at a response edge. Title mode had to
  wait for the edge because its canonical promotion probe reads the title
  page as score-descending. Fulltext rows carry no score, and every consumer
  of the page (both tools, ``tell me about``, the cross-archive fan-out, the
  legacy markdown renderers) wants the article first. Demoting before the
  cache write also means a cached page can never disagree with a cold one.
* **Again after anything that reorders the page later**: the canonical-title
  splices (which can prepend a title-index hit that is itself an artefact, and
  whose list-article demote moves articles below whatever is last), the
  cross-encoder reranker (compact and cross-archive), and synthesize, whose
  reranker and section-affinity boost re-sort passages by score.

Still a demote, not a filter: nothing is dropped, and it reorders within the
page it is handed, so ``total``, ``done`` and every offset are unchanged.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from libzim.writer import Creator

from openzim_mcp.async_operations import AsyncZimOperations
from openzim_mcp.config import (
    CacheConfig,
    OpenZimMcpConfig,
    RateLimitConfig,
    SynthesizeConfig,
)
from openzim_mcp.constants import CANONICAL_TITLE_MATCH_SNIPPET
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.simple_tools import SimpleToolsHandler
from tests.conftest_v2_fixtures import _HtmlItem

_HOST = "medlineplus.gov"
_HUB = f"{_HOST}/languages/asthma.html"
_STUB = f"{_HOST}/ency/imagepages/1.htm"
_ASTHMA = f"{_HOST}/asthma.html"
_COPD = f"{_HOST}/copd.html"

# Built so Xapian ranks both artefacts above both articles for ``asthma`` —
# the only ordering under which a demote is observable. Checked against the
# un-demoted build: fulltext and filtered search both returned
# [hub, stub, asthma, copd].
_PAGES = [
    (_HUB, "Asthma - Multiple Languages", "asthma " * 30),
    (
        _ASTHMA,
        "Asthma",
        "asthma is a chronic disease of the airways " + "lungs breathing inhaler " * 10,
    ),
    (_STUB, "Asthma image", "asthma " * 20),
    (_COPD, "COPD", "copd lungs asthma differs " + "breathing " * 10),
]
_DEMOTED = [_ASTHMA, _COPD, _HUB, _STUB]


def _html(title: str, words: str) -> str:
    return (
        f"<html><head><title>{title}</title></head><body><main>"
        f"<h1>{title}</h1><p>{words}</p></main></body></html>"
    )


def _build_zim(out: Path, pages: List[tuple]) -> Path:
    with Creator(out).config_indexing(True, "eng") as creator:
        for path, title, words in pages:
            creator.add_item(_HtmlItem(path, title, _html(title, words)))
        creator.set_mainpath(_ASTHMA)
    return out


@pytest.fixture
def zim(tmp_path: Path) -> Path:
    return _build_zim(tmp_path / "medlineplus_like.zim", _PAGES)


# The same archive plus a list article, for the orderings where the catalog
# demote and the artefact demote meet. Bare ``List_of_…`` so ``_is_list_article``
# reads it as one; checked un-spliced, the fulltext page is [list, asthma,
# copd, hub, stub].
_LIST = "List_of_asthma_drugs"


@pytest.fixture
def zim_with_list(tmp_path: Path) -> Path:
    return _build_zim(
        tmp_path / "medlineplus_with_list.zim",
        [*_PAGES, (_LIST, "List of asthma drugs", "asthma drugs inhaler " * 12)],
    )


def _make_server(tmp_path: Path, **config: Any) -> OpenZimMcpServer:
    # Cache ON: every surface below is asked twice, so a demote that ran on
    # the cold path only — or rewrote a cached page in place — shows up as a
    # second call that disagrees with the first.
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
            **config,
        )
    )


@pytest.fixture
def server(tmp_path: Path, zim: Path) -> OpenZimMcpServer:
    return _make_server(tmp_path)


def _paths(rows: List[Dict[str, Any]]) -> List[str]:
    return [r["path"] for r in rows]


def _rendered_paths(text: str) -> List[str]:
    return re.findall(r"^Path: (.+)$", text, re.M)


# ---------------------------------------------------------------------------
# The data layer: where both fulltext pages are assembled
# ---------------------------------------------------------------------------


def test_the_fulltext_page_sinks_artefacts(server, zim):
    ops = server.zim_operations
    for _call in range(2):
        page = ops.search_zim_file_data(str(zim), "asthma", limit=5)
        assert _paths(page["results"]) == _DEMOTED
        assert page["total"] == 4 and page["done"] is True


def test_the_demote_never_moves_a_row_to_another_page(server, zim):
    """A page is reordered within itself. Pulling ``copd`` forward from page
    two would need an over-fetch and a recomputed resume point; instead page
    one leads with the one article it holds, and page two is untouched."""
    ops = server.zim_operations
    first = ops.search_zim_file_data(str(zim), "asthma", limit=3, offset=0)
    second = ops.search_zim_file_data(str(zim), "asthma", limit=3, offset=3)

    assert _paths(first["results"]) == [_ASTHMA, _HUB, _STUB]
    assert first["page_info"]["next_offset"] == 3
    assert _paths(second["results"]) == [_COPD]


def test_the_structured_filtered_page_sinks_artefacts(server, zim):
    ops = server.zim_operations
    for _call in range(2):
        page = ops.search_with_filters_data(str(zim), "asthma", "C", None, 5, 0)
        assert _paths(page["results"]) == _DEMOTED


def test_the_markdown_filtered_page_sinks_artefacts(server, zim):
    """A separate renderer with its own cache key; it shares only the row
    projection with the structured path."""
    ops = server.zim_operations
    for _call in range(2):
        text = ops.search_with_filters(str(zim), "asthma", "C", None, 5, 0)
        assert _rendered_paths(text) == _DEMOTED


# ---------------------------------------------------------------------------
# The tools, end to end
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [{}, {"namespace": "C"}, {"cross_file": True}],
    ids=["plain", "filtered", "cross_file"],
)
def test_zim_search_fulltext_leads_with_an_article(server, zim, extra):
    from openzim_mcp.tools import zim_search as tool

    cross = bool(extra.get("cross_file"))
    for _call in range(2):
        out = asyncio.run(
            tool._handle_fulltext_mode(
                ops=AsyncZimOperations(server.zim_operations),
                server=server,
                query="asthma",
                zim_file_path=None if cross else str(zim),
                cross_file=cross,
                namespace=extra.get("namespace"),
                content_type=None,
                limit=5,
                offset=0,
            )
        )
        rows = out["results"][0]["result"]["results"] if cross else out["results"]
        assert _paths(rows) == _DEMOTED


@pytest.mark.parametrize(
    "query, options",
    [
        ("search for asthma", {"compact": True}),
        ("search for asthma", {"compact": False}),
        ("search for asthma in namespace C", {"compact": True}),
        ("search for asthma in namespace C", {"compact": False}),
    ],
    ids=["search", "search-legacy", "filtered", "filtered-legacy"],
)
def test_zim_query_search_leads_with_an_article(server, zim, query, options):
    handler = server.simple_tools_handler
    for _call in range(2):
        text = handler.handle_zim_query(query, str(zim), {"limit": 5, **options})
        assert _rendered_paths(text) == _DEMOTED, text


# ---------------------------------------------------------------------------
# Re-orderers that run after the data layer
# ---------------------------------------------------------------------------


def _bare_handler() -> SimpleToolsHandler:
    return SimpleToolsHandler(MagicMock())


def _page(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "query": "asthma",
        "results": rows,
        "next_cursor": None,
        "total": len(rows),
        "done": True,
        "page_info": {"offset": 0, "limit": 5, "returned_count": len(rows)},
    }


def test_the_splice_sinks_a_prepended_artefact_canonical(monkeypatch):
    """The title index can answer with scraper output: ``title 'migraine
    headache'`` returns an image stub as its only row. Prepended as
    "(canonical title match)", it must sink like any other artefact."""
    from openzim_mcp import simple_tools as st

    monkeypatch.setattr(
        st,
        "find_title_match",
        lambda *_a, **_k: {"path": _STUB, "title": "Asthma image"},
    )
    page = _page([{"path": _COPD, "title": "COPD", "snippet": "copd"}])

    out = _bare_handler()._splice_title_match_into_search(page, "a.zim", "asthma")

    assert _paths(out["results"]) == [_COPD, _STUB]
    assert out["results"][1]["snippet"] == CANONICAL_TITLE_MATCH_SNIPPET
    assert _paths(page["results"]) == [_COPD], "the input page was mutated"


def test_the_splice_sinks_an_artefact_canonical_it_moved_to_the_top(monkeypatch):
    from openzim_mcp import simple_tools as st

    monkeypatch.setattr(
        st,
        "find_title_match",
        lambda *_a, **_k: {"path": _STUB, "title": "Asthma image"},
    )
    page = _page(
        [
            {"path": _COPD, "title": "COPD", "snippet": "copd"},
            {"path": _STUB, "title": "Asthma image", "snippet": "asthma"},
        ]
    )

    out = _bare_handler()._splice_title_match_into_search(page, "a.zim", "asthma")

    assert _paths(out["results"]) == [_COPD, _STUB]


def test_the_list_demote_does_not_sink_a_list_article_below_an_artefact():
    """The splice's catalog demote moves list articles to the END of the page,
    which is below the artefacts the data layer already sank there. A list
    article is still an article."""
    page = _page(
        [
            {"path": "A/List_of_asthma_drugs", "title": "List of asthma drugs"},
            {"path": "A/Asthma", "title": "Asthma"},
            {"path": "A/languages/asthma.html", "title": "Asthma - Languages"},
        ]
    )

    # ``A/Asthma`` is then a strong canonical match, so the splice returns
    # without probing the title index.
    out = _bare_handler()._splice_title_match_into_search(page, "a.zim", "asthma")

    assert _paths(out["results"]) == [
        "A/Asthma",
        "A/List_of_asthma_drugs",
        "A/languages/asthma.html",
    ]


def test_the_list_demote_does_not_sink_a_list_article_below_an_artefact_it_follows():
    """The same rule when the page arrives with the list article already
    below the article, as a data-layer page does. The splice leaves the top
    row where it was, but its catalog demote still moves the list article to
    the end, past the hub, so the exit demote must run even when the top row
    did not change."""
    page = _page(
        [
            {"path": "A/Asthma", "title": "Asthma"},
            {"path": "A/List_of_asthma_drugs", "title": "List of asthma drugs"},
            {"path": "A/languages/asthma.html", "title": "Asthma - Languages"},
        ]
    )

    out = _bare_handler()._splice_title_match_into_search(page, "a.zim", "asthma")

    assert _paths(out["results"]) == [
        "A/Asthma",
        "A/List_of_asthma_drugs",
        "A/languages/asthma.html",
    ]


def test_the_filtered_canonical_splice_sinks_an_artefact_canonical(
    server, zim, monkeypatch
):
    """``search_with_filters_with_canonical_splice`` moves the title-index hit
    to the top of the filtered page — its own copy of the splice, with its own
    list demote, rendering its own markdown."""
    from openzim_mcp.zim import search as search_mod

    monkeypatch.setattr(
        search_mod,
        "find_title_match",
        lambda *_a, **_k: {"path": _STUB, "title": "Asthma image"},
    )

    text = server.zim_operations.search_with_filters_with_canonical_splice(
        str(zim), "asthma", "C", None, 5, 0
    )

    assert _rendered_paths(text) == [_ASTHMA, _COPD, _STUB, _HUB], text


@pytest.mark.parametrize("route", ["data-layer", "zim_query-legacy"])
def test_the_filtered_canonical_splice_sinks_a_prepended_artefact_canonical(
    server, zim, monkeypatch, route
):
    """The other branch of the same splice: the title-index hit is NOT on the
    filtered page, so it is prepended as a synthetic "(canonical title match)"
    row instead of moved. ``breathing`` reaches it — the page holds only the
    two articles, and neither title is the query."""
    from openzim_mcp.zim import search as search_mod

    monkeypatch.setattr(
        search_mod,
        "find_title_match",
        lambda *_a, **_k: {"path": _STUB, "title": "Asthma image"},
    )
    ops = server.zim_operations
    # Guard: were the stub on the page, this would be the reorder branch,
    # which the test above already covers.
    page = ops.search_with_filters_data(str(zim), "breathing", "C", None, 5, 0)
    assert _paths(page["results"]) == [_COPD, _ASTHMA]

    for _call in range(2):
        if route == "data-layer":
            text = ops.search_with_filters_with_canonical_splice(
                str(zim), "breathing", "C", None, 5, 0
            )
        else:
            text = server.simple_tools_handler.handle_zim_query(
                "search for breathing in namespace C",
                str(zim),
                {"limit": 5, "compact": False},
            )

        assert "Match type: canonical title match" in text, text
        assert _rendered_paths(text) == [_COPD, _ASTHMA, _STUB], text


def test_the_filtered_canonical_splice_keeps_a_list_article_above_artefacts(
    tmp_path, zim_with_list, monkeypatch
):
    """The filtered splice's own catalog demote moves the list article to the
    end of the page, below the artefacts the data layer sank there. The
    canonical here is a real article, so nothing about it calls for a demote;
    the demote is still needed, because a list article is still an article."""
    from openzim_mcp.zim import search as search_mod

    monkeypatch.setattr(
        search_mod,
        "find_title_match",
        lambda *_a, **_k: {"path": _COPD, "title": "COPD"},
    )
    ops = _make_server(tmp_path).zim_operations

    for _call in range(2):
        text = ops.search_with_filters_with_canonical_splice(
            str(zim_with_list), "asthma", "C", None, 10, 0
        )

        assert _rendered_paths(text) == [_COPD, _ASTHMA, _LIST, _HUB, _STUB], text


def _artefact_loving_reranker() -> MagicMock:
    """A cross-encoder that scores every artefact above every article — the
    ordering a snippet like "Hepatitis B - Multiple Languages" plausibly
    earns. Stable within each class, so only the artefact demote can move a
    row between classes."""
    from openzim_mcp.zim.search import is_crawl_artefact

    stub = MagicMock()

    def _rerank(query: str, candidates: List[dict], top_k: int) -> List[dict]:
        scored = [
            {**c, "rerank_score": 10.0 if is_crawl_artefact(str(c["path"])) else 1.0}
            for c in candidates
        ]
        scored.sort(key=lambda c: c["rerank_score"], reverse=True)
        return scored[:top_k]

    stub.rerank = MagicMock(side_effect=_rerank)
    return stub


def test_the_compact_rerank_cannot_lift_an_artefact_back(server, zim):
    handler = server.simple_tools_handler
    with patch(
        "openzim_mcp.ml.reranker.BGEReranker.get",
        return_value=_artefact_loving_reranker(),
    ):
        text = handler.handle_zim_query(
            "search for asthma", str(zim), {"limit": 5, "compact": True}
        )

    assert "reranker=engaged" in text, text
    assert _rendered_paths(text) == _DEMOTED, text


def test_the_compact_rerank_sinks_a_pinned_artefact_canonical(server, zim, monkeypatch):
    """The rerank holds the splice's "(canonical title match)" row out of the
    cross-encoder and pins it ahead of everything it scored, which undoes the
    splice's exit demote when the title index answered with an image stub.
    So the demote runs over the pinned rows too, not only the scored ones.
    ``breathing`` reaches it: no row's title is a strong match, so the splice
    probes the title index, and the stub it gets back is not on the page."""
    from openzim_mcp import simple_tools as st

    monkeypatch.setattr(
        st,
        "find_title_match",
        lambda *_a, **_k: {"path": _STUB, "title": "Asthma image"},
    )
    reranker = _artefact_loving_reranker()
    with patch("openzim_mcp.ml.reranker.BGEReranker.get", return_value=reranker):
        text = server.simple_tools_handler.handle_zim_query(
            "search for breathing", str(zim), {"limit": 5, "compact": True}
        )

    assert "reranker=engaged" in text, text
    # The stub was pinned, not scored: were it handed to the cross-encoder,
    # the demote after the rerank would be tested only on scored rows.
    scored = [c["path"] for c in reranker.rerank.call_args.kwargs["candidates"]]
    assert scored == [_COPD, _ASTHMA], scored
    assert "Match type: canonical title match" in text, text
    assert _rendered_paths(text) == [_COPD, _ASTHMA, _STUB], text


def test_the_cross_archive_rerank_cannot_lift_an_artefact_back():
    per_file = [
        {
            "zim_file_path": "a.zim",
            "result": {
                "results": [
                    {"path": _ASTHMA, "title": "Asthma", "snippet": "a"},
                    {"path": _HUB, "title": "Asthma - Languages", "snippet": "b"},
                ]
            },
        },
        {
            "zim_file_path": "b.zim",
            "result": {
                "results": [
                    {"path": "b.org/copd.html", "title": "COPD", "snippet": "c"},
                    {"path": "b.org/x.srt", "title": "Captions", "snippet": "d"},
                ]
            },
        },
    ]
    handler = _bare_handler()
    handler.zim_operations.config.ml.reranker.final_top_k = 10
    with patch(
        "openzim_mcp.ml.reranker.BGEReranker.get",
        return_value=_artefact_loving_reranker(),
    ):
        out = handler._maybe_rerank_search_all(per_file=per_file, query="asthma")

    assert _paths(out[0]["result"]["results"]) == [_ASTHMA, _HUB]
    assert _paths(out[1]["result"]["results"]) == ["b.org/copd.html", "b.org/x.srt"]


# ---------------------------------------------------------------------------
# Synthesize
# ---------------------------------------------------------------------------


def _synthesize(server, zim) -> Dict[str, Any]:
    return server.simple_tools_handler.handle_zim_query(
        "asthma", str(zim), {"synthesize": True, "compact": True}
    )


def _is_artefact_order(paths: List[str]) -> bool:
    from openzim_mcp.zim.search import is_crawl_artefact

    flags = [is_crawl_artefact(p) for p in paths]
    return flags == sorted(flags)


def test_synthesize_cites_articles_before_artefacts(server, zim):
    body = _synthesize(server, zim)
    cited = [c["entry_path"] for c in body["citations"]]

    assert set(cited) >= {_ASTHMA, _HUB}, cited
    assert _is_artefact_order(cited), cited


def test_synthesize_lists_considered_articles_before_artefacts(server, zim):
    """``considered_articles`` keeps the order of the selected hits, so it is
    the one place a demote applied only to the final passages still shows
    the archive's own ranking."""
    body = _synthesize(server, zim)
    considered = [a["entry_path"] for a in body["considered_articles"]]

    assert {_HUB, _STUB, _COPD} <= set(considered), considered
    assert _is_artefact_order(considered), considered


def test_synthesize_considers_a_list_article_before_artefacts(tmp_path, zim_with_list):
    """The hit demote runs after the list-article demote, which moves list
    articles to the end, below any artefact. Run the other way round, the
    list article is last, behind the hub and the stub, and with three
    ``considered_articles`` slots it drops out of the list altogether."""
    from openzim_mcp.zim.search import is_crawl_artefact

    body = _make_server(tmp_path).simple_tools_handler.handle_zim_query(
        "asthma", str(zim_with_list), {"synthesize": True, "compact": True}
    )
    considered = [a["entry_path"] for a in body["considered_articles"]]

    assert _LIST in considered, considered
    assert any(is_crawl_artefact(p) for p in considered), considered
    assert _is_artefact_order(considered), considered


def test_synthesize_sinks_a_title_promoted_artefact(server, zim, monkeypatch):
    """The list-article demote exempts a title-promoted hit; the artefact
    demote must not. The title index can answer with an image stub
    (``title 'migraine headache'`` does on MedlinePlus), and a promoted stub
    left on top leads ``considered_articles``."""
    from openzim_mcp import synthesize as syn

    monkeypatch.setattr(
        syn,
        "find_title_match",
        lambda *_a, **_k: {"path": _STUB, "title": "Asthma image"},
    )
    promotions: List[Any] = []
    real_promote = syn._promote_title_match

    def _spy(*args: Any, **kwargs: Any) -> Any:
        out = real_promote(*args, **kwargs)
        promotions.append(out)
        return out

    monkeypatch.setattr(syn, "_promote_title_match", _spy)

    body = _synthesize(server, zim)
    considered = [a["entry_path"] for a in body["considered_articles"]]

    # The stub really was promoted; otherwise this tests the demote of an
    # ordinary hit, which the test above already does.
    (_archive, top), *_rest = promotions[0]
    assert top["path"] == _STUB and top.get("promoted"), promotions[0]
    assert _STUB in considered, considered
    assert _is_artefact_order(considered), considered


def test_the_budget_cap_cuts_scraper_output_before_articles(tmp_path, zim):
    """The passage demote runs before ``_enforce_budget``. The cap keeps
    passages in order until the budget runs out, so if it ran on the
    reranked order — hub and stub first — it would keep the scraper output
    and cut the articles, and the demote after it could only reorder what
    was left. 500 characters is the smallest budget the config accepts, and
    less than the four passages need."""
    from openzim_mcp.zim.search import is_crawl_artefact

    handler = _make_server(
        tmp_path, synthesize=SynthesizeConfig(output_char_budget=500)
    ).simple_tools_handler
    reranker = _artefact_loving_reranker()
    with patch("openzim_mcp.ml.reranker.BGEReranker.get", return_value=reranker):
        body = handler.handle_zim_query(
            "asthma", str(zim), {"synthesize": True, "compact": True}
        )
    cited = [c["entry_path"] for c in body["citations"]]

    assert reranker.rerank.called, "the reranker never ran"
    assert body["_meta"]["truncated"] is True, body["_meta"]
    assert [p for p in cited if not is_crawl_artefact(p)] == [_ASTHMA, _COPD], cited
    assert _is_artefact_order(cited), cited


def test_the_synthesize_rerank_cannot_lift_an_artefact_back(server, zim):
    with patch(
        "openzim_mcp.ml.reranker.BGEReranker.get",
        return_value=_artefact_loving_reranker(),
    ):
        body = _synthesize(server, zim)
    cited = [c["entry_path"] for c in body["citations"]]

    assert set(cited) >= {_ASTHMA, _HUB}, cited
    assert _is_artefact_order(cited), cited
    # Compact mode moves each passage's rank onto its citation; a reorder
    # that left the reranker's numbering in place would ship 3, 4, 1, 2.
    assert [c["rank"] for c in body["citations"]] == list(
        range(1, len(cited) + 1)
    ), body["citations"]


def test_a_sectioned_subtitle_passage_is_still_an_artefact():
    """Passages are classified on their cite_id, which carries a ``#section``
    suffix once attributed — and ``.srt`` only counts at the end of a path."""
    from openzim_mcp.synthesize import _demote_crawl_artefact_passages

    passages = [
        {"cite_id": "med/medlineplus.gov/media/captions/x.srt#start", "rank": 1},
        {"cite_id": "med/medlineplus.gov/asthma.html#summary", "rank": 2},
    ]

    out = _demote_crawl_artefact_passages(passages, query="asthma")

    assert [p["cite_id"] for p in out] == [
        "med/medlineplus.gov/asthma.html#summary",
        "med/medlineplus.gov/media/captions/x.srt#start",
    ]
    assert [p["rank"] for p in out] == [1, 2]
