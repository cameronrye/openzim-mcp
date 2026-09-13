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
from openzim_mcp.config import CacheConfig, OpenZimMcpConfig, RateLimitConfig
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


@pytest.fixture
def zim(tmp_path: Path) -> Path:
    out = tmp_path / "medlineplus_like.zim"
    with Creator(out).config_indexing(True, "eng") as creator:
        for path, title, words in _PAGES:
            creator.add_item(_HtmlItem(path, title, _html(title, words)))
        creator.set_mainpath(_ASTHMA)
    return out


@pytest.fixture
def server(tmp_path: Path, zim: Path) -> OpenZimMcpServer:
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
        )
    )


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

    out = _demote_crawl_artefact_passages(passages)

    assert [p["cite_id"] for p in out] == [
        "med/medlineplus.gov/asthma.html#summary",
        "med/medlineplus.gov/media/captions/x.srt#start",
    ]
    assert [p["rank"] for p in out] == [1, 2]
