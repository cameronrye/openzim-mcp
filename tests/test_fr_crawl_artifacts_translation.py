"""A translation the caller asks for is not scraper output.

Review of the fulltext crawl-artefact demote found the regression it had not
considered. A caller who asks for "<topic> <language>" or "<topic> in
<language>" wants that topic's MedlinePlus translation hub, the very page the
demote sinks. Measured on the shipped archive, 700 such queries (50 hub topics
x Spanish, Chinese, French, Korean, Vietnamese, Arabic and Russian x both
forms), cache warm, real code of both trees: the requested hub led 332 of 700
fulltext pages before the demote and 106 after. It lost #1 on 226, and on
most of those the new #1 was unrelated ("asthma in children chinese" -> Dong
Quai), because fulltext matches the language word inside product names and
citations. On ``synthesize=True`` (147 "<topic> in <language>" queries) the
hub was the first citation on 63 before and 7 after. Title, suggest and
``tell me about`` never surfaced the hub for that phrasing, so fulltext was
the only surface that answered it.

The exemption, in full:

* A query asks for a translation of a topic when, lowercased and stripped of
  surrounding whitespace and trailing punctuation, it ENDS with one or more
  language words, optionally preceded by ``in``, and a topic remains before
  them. The topic's key is that text with every non-alphanumeric character
  removed, which is how MedlinePlus spells a hub's slug.
* The row exempt from the demote is exactly ``/languages/<key>.html``. Image
  stubs, ``.srt`` sidecars, other topics' hubs and the language portals still
  sink, for every query.
* Suffix only, on purpose: "japanese encephalitis" and "german measles" are
  about the disease.
* Exempt means not demoted. The hub keeps the position the archive ranked it
  at; it is never promoted past an article that ranked above it.

Every demote call site is handed the query its cache key is built from, so a
cached page cannot disagree with a cold one. The wiring tests below drive each
surface through the registered tool, with the cache on and every call made
twice, and each asks the question twice over: with the language, where the
hub keeps its lead, and without it, where the hub still sinks.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Callable, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from libzim.writer import Creator

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig, RateLimitConfig
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.zim import search as search_mod
from openzim_mcp.zim.search import (
    demote_crawl_artefacts,
    is_crawl_artefact,
    requested_translation_topic,
)
from tests.conftest_v2_fixtures import _HtmlItem

_M = "medlineplus.gov"
_ASTHMA_HUB = f"{_M}/languages/asthma.html"

# ---------------------------------------------------------------------------
# Which queries ask for a translation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query, topic",
    [
        ("asthma spanish", "asthma"),
        ("asthma in spanish", "asthma"),
        ("asthma in children chinese", "asthmainchildren"),
        ("asthma in children in chinese", "asthmainchildren"),
        ("alzheimer's disease chinese", "alzheimersdisease"),
        ("Children's Health in Spanish", "childrenshealth"),
        ("ASTHMA In SpAnIsH", "asthma"),
        ("  asthma   in \t spanish  ", "asthma"),
        ("asthma in spanish?", "asthma"),
        ("asthma in spanish ?!", "asthma"),
        ("breast cancer in cape verdean creole", "breastcancer"),
        ("breast cancer haitian creole", "breastcancer"),
        ("breast cancer in serbo-croatian", "breastcancer"),
        ("breast cancer serbo croatian", "breastcancer"),
        ("asthma chinese simplified", "asthma"),
        ("asthma in traditional chinese", "asthma"),
        ("asthma mandarin", "asthma"),
        ("asthma in cantonese", "asthma"),
        ("asthma persian", "asthma"),
        ("asthma in filipino", "asthma"),
        # A language word LEADING the topic is part of the topic.
        ("japanese encephalitis in japanese", "japaneseencephalitis"),
        ("german measles german", "germanmeasles"),
    ],
)
def test_a_trailing_language_asks_for_that_topics_translation(query, topic):
    assert requested_translation_topic(query) == topic


@pytest.mark.parametrize(
    "query, same_shape_that_asks",
    [
        # Suffix only: a leading language word names the disease.
        ("japanese encephalitis", "japanese encephalitis in japanese"),
        ("german measles", "german measles in german"),
        ("chinese medicine for asthma", "chinese medicine for asthma in chinese"),
        # No topic left once the language is taken off.
        ("chinese", "asthma chinese"),
        ("in chinese", "asthma in chinese"),
        ("chinese simplified", "asthma chinese simplified"),
        ("? chinese", "asthma chinese"),
        # No language at all.
        ("asthma in children", "asthma in children chinese"),
        ("asthma", "asthma spanish"),
        # English is the archive's own language.
        ("asthma english", "asthma spanish"),
        ("asthma in english", "asthma in spanish"),
        # Only a whole name counts, and only as a word of its own.
        ("asthma creole", "asthma haitian creole"),
        ("asthma cape verdean", "asthma cape verdean creole"),
        ("asthmachinese", "asthma chinese"),
        ("", "asthma spanish"),
    ],
)
def test_nothing_is_asked_for_without_a_topic_and_a_trailing_language(
    query, same_shape_that_asks
):
    assert requested_translation_topic(query) is None
    assert requested_translation_topic(same_shape_that_asks) is not None


def test_no_query_asks_for_nothing():
    assert requested_translation_topic(None) is None
    assert requested_translation_topic("asthma in spanish") == "asthma"


# ---------------------------------------------------------------------------
# Which row that exempts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path, query, without_the_language",
    [
        (_ASTHMA_HUB, "asthma in spanish", "asthma"),
        (_ASTHMA_HUB, "asthma spanish", "asthma"),
        (_ASTHMA_HUB, "  Asthma in SPANISH? ", "  Asthma? "),
        # The slug is complete where the stored title is cut ("Alzheimer").
        (
            f"{_M}/languages/alzheimersdisease.html",
            "alzheimer's disease chinese",
            "alzheimer's disease",
        ),
        (
            f"{_M}/languages/asthmainchildren.html",
            "asthma in children chinese",
            "asthma in children",
        ),
        (
            f"{_M}/languages/childrenshealth.html",
            "children's health in cape verdean creole",
            "children's health",
        ),
        (f"{_M}/Languages/Asthma.html", "ASTHMA IN SPANISH", "ASTHMA"),
    ],
)
def test_the_requested_hub_is_not_an_artefact_for_that_query(
    path, query, without_the_language
):
    assert is_crawl_artefact(path, query) is False
    # The same path is an artefact for the same topic asked without a
    # language, and when no query is given at all.
    assert is_crawl_artefact(path, without_the_language) is True
    assert is_crawl_artefact(path) is True


@pytest.mark.parametrize(
    "path, query, exempt_path, exempt_query",
    [
        # Another topic's hub.
        (
            _ASTHMA_HUB,
            "asthma in children chinese",
            f"{_M}/languages/asthmainchildren.html",
            "asthma in children chinese",
        ),
        (
            f"{_M}/languages/asthmainchildren.html",
            "asthma chinese",
            _ASTHMA_HUB,
            "asthma chinese",
        ),
        # Image stubs and caption files, for the very topic asked about.
        (
            f"{_M}/ency/imagepages/1.htm",
            "asthma in spanish",
            _ASTHMA_HUB,
            "asthma in spanish",
        ),
        (
            f"{_M}/media/captions/asthma.srt",
            "asthma in spanish",
            _ASTHMA_HUB,
            "asthma in spanish",
        ),
        (
            f"{_M}/languages/asthma.srt",
            "asthma in spanish",
            _ASTHMA_HUB,
            "asthma in spanish",
        ),
        # Language portals: asking for a topic in a language is not asking
        # for the language's front page ...
        (
            f"{_M}/languages/french.html",
            "health information in french",
            _ASTHMA_HUB,
            "asthma in french",
        ),
        (
            f"{_M}/languages/spanish.html",
            "asthma in spanish",
            _ASTHMA_HUB,
            "asthma in spanish",
        ),
        # ... and neither is a topic that happens to spell a language, nor
        # the portal index and help pages filed under the same directory.
        (
            f"{_M}/languages/french.html",
            "french in spanish",
            _ASTHMA_HUB,
            "asthma in spanish",
        ),
        (
            f"{_M}/languages/chinesesimplifiedmandarindialect.html",
            "chinese simplified mandarin dialect in spanish",
            f"{_M}/languages/asthmainchildren.html",
            "asthma in children in spanish",
        ),
        (
            f"{_M}/languages/languages.html",
            "languages in spanish",
            _ASTHMA_HUB,
            "asthma in spanish",
        ),
        (
            f"{_M}/languages/display.html",
            "display in chinese",
            _ASTHMA_HUB,
            "asthma in chinese",
        ),
        (
            f"{_M}/languages/criteria.html",
            "criteria spanish",
            _ASTHMA_HUB,
            "asthma spanish",
        ),
        # A leading language word is part of the topic, not a request.
        (
            f"{_M}/languages/japaneseencephalitis.html",
            "japanese encephalitis",
            f"{_M}/languages/japaneseencephalitis.html",
            "japanese encephalitis in japanese",
        ),
        (
            f"{_M}/languages/encephalitis.html",
            "japanese encephalitis",
            f"{_M}/languages/encephalitis.html",
            "encephalitis japanese",
        ),
        (
            f"{_M}/languages/measles.html",
            "german measles",
            f"{_M}/languages/measles.html",
            "measles in german",
        ),
        # No topic, or no language.
        (_ASTHMA_HUB, "chinese", _ASTHMA_HUB, "asthma chinese"),
        (_ASTHMA_HUB, "in chinese", _ASTHMA_HUB, "asthma in chinese"),
        (
            f"{_M}/languages/asthmainchildren.html",
            "asthma in children",
            f"{_M}/languages/asthmainchildren.html",
            "asthma in children chinese",
        ),
        (_ASTHMA_HUB, "asthma english", _ASTHMA_HUB, "asthma spanish"),
    ],
)
def test_everything_else_still_sinks(path, query, exempt_path, exempt_query):
    assert is_crawl_artefact(path, query) is True
    # Paired: the exemption is live for this shape of question, so the
    # assertion above is about THIS row, not a rule that never fires.
    assert is_crawl_artefact(exempt_path, exempt_query) is False


def _paths(rows: List[Dict[str, Any]]) -> List[str]:
    return [r["path"] for r in rows]


def test_an_exempt_hub_keeps_its_place_and_is_never_promoted():
    """Not demoted is all it gets: an article the archive ranked above the
    hub stays above it, and the artefacts it would have sunk with still sink."""
    rows = [
        {"path": f"{_M}/asthma.html"},
        {"path": _ASTHMA_HUB},
        {"path": f"{_M}/ency/imagepages/1.htm"},
        {"path": f"{_M}/copd.html"},
        {"path": f"{_M}/languages/copd.html"},
    ]

    assert _paths(demote_crawl_artefacts(rows, query="asthma in spanish")) == [
        f"{_M}/asthma.html",
        _ASTHMA_HUB,
        f"{_M}/copd.html",
        f"{_M}/ency/imagepages/1.htm",
        f"{_M}/languages/copd.html",
    ]
    assert _paths(demote_crawl_artefacts(rows, query="asthma")) == [
        f"{_M}/asthma.html",
        f"{_M}/copd.html",
        _ASTHMA_HUB,
        f"{_M}/ency/imagepages/1.htm",
        f"{_M}/languages/copd.html",
    ]


def test_the_hub_is_recognised_by_its_path_not_its_title():
    """Some stored hub titles are cut at the apostrophe; the slug never is."""
    rows = [
        {"path": f"{_M}/languages/alzheimersdisease.html", "title": "Alzheimer"},
        {"path": f"{_M}/ency/imagepages/9.htm", "title": "Alzheimer's disease"},
        {"path": f"{_M}/alzheimersdisease.html", "title": "Alzheimer's Disease"},
    ]

    out = demote_crawl_artefacts(rows, query="alzheimer's disease chinese")
    assert _paths(out) == [
        f"{_M}/languages/alzheimersdisease.html",
        f"{_M}/alzheimersdisease.html",
        f"{_M}/ency/imagepages/9.htm",
    ]
    assert _paths(demote_crawl_artefacts(rows, query="alzheimer's disease")) == [
        f"{_M}/alzheimersdisease.html",
        f"{_M}/languages/alzheimersdisease.html",
        f"{_M}/ency/imagepages/9.htm",
    ]


def test_no_query_is_exactly_the_path_only_demote():
    rows = [
        {"path": _ASTHMA_HUB},
        {"path": f"{_M}/asthma.html"},
        {"path": f"{_M}/ency/imagepages/1.htm"},
    ]

    assert demote_crawl_artefacts(rows) == demote_crawl_artefacts(rows, None)
    assert _paths(demote_crawl_artefacts(rows)) == [
        f"{_M}/asthma.html",
        _ASTHMA_HUB,
        f"{_M}/ency/imagepages/1.htm",
    ]
    assert _paths(demote_crawl_artefacts(rows, "asthma in spanish"))[0] == _ASTHMA_HUB


def test_the_query_is_parsed_once_per_page_not_once_per_row(monkeypatch):
    calls: List[Any] = []
    real = search_mod.requested_translation_topic

    def counting(query):
        calls.append(query)
        return real(query)

    monkeypatch.setattr(search_mod, "requested_translation_topic", counting)
    rows = [{"path": _ASTHMA_HUB}] + [
        {"path": f"{_M}/ency/imagepages/{i}.htm"} for i in range(6)
    ]

    out = demote_crawl_artefacts(rows, query="asthma in spanish")

    assert calls == ["asthma in spanish"]
    assert _paths(out)[0] == _ASTHMA_HUB


# ---------------------------------------------------------------------------
# The wirings, one surface per demote call site
# ---------------------------------------------------------------------------
#
# A three-entry archive whose title index AND full-text index both rank the
# hub first, then the image stub, then the article — for "asthma in spanish"
# and for "asthma" alike — so that on every surface the exemption is the only
# thing that can tell the two queries apart. The titles are not MedlinePlus's
# ("Asthma - Multiple Languages"): they are chosen so the title index, the
# suggestion searcher and the ``tell me about`` chooser all see the same
# three rows in that order, which on the real archive only fulltext does.

_HUB = _ASTHMA_HUB
_ARTICLE = f"{_M}/asthma.html"
_STUB = f"{_M}/ency/imagepages/1.htm"
_PAGES = [
    (_HUB, "Asthma in Spanish Info", "asthma in spanish " * 20),
    (_ARTICLE, "Asthma in Spanish Info for Parents", "asthma in spanish guide " * 5),
    (_STUB, "Asthma in Spanish Info Picture", "asthma in spanish " * 15),
]
_ASKED = [_HUB, _ARTICLE, _STUB]
_NOT_ASKED = [_ARTICLE, _HUB, _STUB]


@pytest.fixture
def zim(tmp_path: Path) -> Path:
    out = tmp_path / "medlineplus_like.zim"
    with Creator(out).config_indexing(True, "eng") as creator:
        for path, title, words in _PAGES:
            html = (
                f"<html><head><title>{title}</title></head><body><main>"
                f"<h1>{title}</h1><p>{words}</p></main></body></html>"
            )
            creator.add_item(_HtmlItem(path, title, html))
        creator.set_mainpath(_ARTICLE)
    return out


@pytest.fixture
def server(tmp_path: Path, zim: Path) -> OpenZimMcpServer:
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


def _tool(server: OpenZimMcpServer, name: str) -> Callable[..., Any]:
    return server.mcp._tool_manager._tools[name].fn


_RENDERED_PATH_RE = re.compile(r"(?:^Path: |— `)(medlineplus\.gov/[^`\s]+)", re.M)


def _rendered(text: Any) -> List[str]:
    assert isinstance(text, str), text
    return _RENDERED_PATH_RE.findall(text)


def _artefact_loving_reranker() -> MagicMock:
    """A cross-encoder that scores every artefact — the asked-for hub
    included — above every article, stable within each class."""
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


def _zim_search(**kwargs: Any) -> Callable[..., List[str]]:
    def run(server, zim, topic):
        cross = bool(kwargs.get("cross_file"))
        out = asyncio.run(
            _tool(server, "zim_search")(
                query=topic,
                zim_file_path=None if cross else str(zim),
                limit=5,
                **kwargs,
            )
        )
        if kwargs.get("mode", "fulltext") == "fulltext" and cross:
            return _paths(out["results"][0]["result"]["results"])
        return _paths(out["results"])

    return run


def _zim_query(template: str, **kwargs: Any) -> Callable[..., List[str]]:
    def run(server, zim, topic):
        return _rendered(
            asyncio.run(
                _tool(server, "zim_query")(
                    query=template.format(topic), zim_file_path=str(zim), **kwargs
                )
            )
        )

    return run


def _reranked(surface: Callable[..., List[str]]) -> Callable[..., List[str]]:
    def run(server, zim, topic):
        reranker = _artefact_loving_reranker()
        with patch("openzim_mcp.ml.reranker.BGEReranker.get", return_value=reranker):
            paths = surface(server, zim, topic)
        # A surface that skipped the rerank would pass on the demote before it
        # and prove nothing about the one after it.
        assert reranker.rerank.called, "the reranker never ran"
        return paths

    return run


def _title_index_answers_with_the_hub(
    surface: Callable[..., List[str]],
) -> Callable[..., List[str]]:
    """The filtered canonical splice runs only when the title index resolves
    the query to a score-1.0 entry, and moves that entry to the top. Here the
    index answers with the hub, the way ``title 'migraine headache'`` answers
    with an image stub on the real archive."""

    def run(server, zim, topic):
        with patch.object(
            search_mod,
            "find_title_match",
            lambda *_a, **_k: {"path": _HUB, "title": "Asthma in Spanish Info"},
        ):
            return surface(server, zim, topic)

    return run


def _synthesized(server, zim, topic) -> List[str]:
    """``synthesize=True`` through a phrasing whose intent prefix the handler
    strips, so the pipeline's search string differs from the caller's text."""
    body = asyncio.run(
        _tool(server, "zim_query")(
            query=f"what is {topic}", zim_file_path=str(zim), synthesize=True
        )
    )
    return [c["entry_path"] for c in body["citations"]]


# (surface, the demote call sites a page on it passes through)
_SURFACES = {
    # zim/search.py ``_perform_search`` + simple_tools splice (via the tool).
    "zim_search-fulltext": _zim_search(),
    # zim/search.py ``_perform_search`` only.
    "zim_search-fulltext-cross_file": _zim_search(cross_file=True),
    # zim/search.py ``_build_filtered_results`` (structured page).
    "zim_search-fulltext-namespace": _zim_search(namespace="C"),
    # zim/search.py ``get_search_suggestions_data``.
    "zim_search-suggest": _zim_search(mode="suggest"),
    # tools/zim_search.py ``_demote_artefacts_in_response``, pinned archive.
    "zim_search-title": _zim_search(mode="title"),
    # tools/zim_search.py ``_demote_artefacts_in_response``, fan-out branch.
    "zim_search-title-cross_file": _zim_search(mode="title", cross_file=True),
    # ``_perform_search`` + simple_tools splice.
    "zim_query-search": _zim_query("search for {}", limit=5),
    # ``_perform_search`` only (legacy markdown renderer).
    "zim_query-search-legacy": _zim_query("search for {}", limit=5, compact=False),
    # ``_perform_search`` only (fan-out renderer).
    "zim_query-search-all": _zim_query("search all files for {}", limit=5),
    # ``_build_filtered_results``.
    "zim_query-filtered": _zim_query("search for {} in namespace C", limit=5),
    # ``_build_filtered_results`` (markdown path, no canonical).
    "zim_query-filtered-legacy": _zim_query(
        "search for {} in namespace C", limit=5, compact=False
    ),
    # ``_build_filtered_results`` + ``_splice_canonical_into_filtered``.
    "zim_query-filtered-legacy-canonical": _title_index_answers_with_the_hub(
        _zim_query("search for {} in namespace C", limit=5, compact=False)
    ),
    # ``_perform_search`` + simple_tools ``tell me about`` chooser.
    "zim_query-tell-me-about": _zim_query("tell me about {}", limit=5),
    # ``_perform_search`` + splice + rerank.py ``_maybe_rerank_compact``.
    "zim_query-search-reranked": _reranked(_zim_query("search for {}", limit=5)),
    # ``_build_filtered_results`` + ``_maybe_rerank_compact``.
    "zim_query-filtered-reranked": _reranked(
        _zim_query("search for {} in namespace C", limit=5)
    ),
    # ``_perform_search`` + rerank.py ``_redistribute_reranked_hits``.
    "zim_query-search-all-reranked": _reranked(
        _zim_query("search all files for {}", limit=5)
    ),
    # synthesize.py ``_demote_crawl_artefact_hits`` + ``_passages``.
    "zim_query-synthesize": _synthesized,
    # The same, with the reranker re-sorting passages in between.
    "zim_query-synthesize-reranked": _reranked(_synthesized),
}


@pytest.mark.parametrize("surface", list(_SURFACES.values()), ids=list(_SURFACES))
def test_the_requested_hub_keeps_its_lead_on_every_surface(server, zim, surface):
    for call in range(2):
        assert surface(server, zim, "asthma in spanish") == _ASKED, call


@pytest.mark.parametrize("surface", list(_SURFACES.values()), ids=list(_SURFACES))
def test_without_the_language_the_hub_still_sinks_on_every_surface(
    server, zim, surface
):
    for call in range(2):
        assert surface(server, zim, "asthma") == _NOT_ASKED, call


@pytest.mark.parametrize(
    "surface",
    [_zim_search(mode="title"), _zim_search(mode="title", cross_file=True)],
    ids=["pinned", "cross_file"],
)
def test_title_mode_asks_with_the_query_it_looked_up(server, zim, surface):
    """Title mode strips a leading article before the lookup, and caches the
    lookup under the stripped string. The demote has to read the same string:
    "the asthma in spanish" is a request for ``asthma``, not ``theasthma``."""
    for call in range(2):
        assert surface(server, zim, "The asthma in spanish") == _ASKED, call
        assert surface(server, zim, "The asthma") == _NOT_ASKED, call


def test_the_filtered_splice_asks_with_the_query_not_its_display_form(server, zim):
    """``display_query`` is only an echo: a caller of the data layer that
    passes none still gets the exemption the matched query asks for."""
    ops = server.zim_operations
    with patch.object(
        search_mod,
        "find_title_match",
        lambda *_a, **_k: {"path": _HUB, "title": "Asthma in Spanish Info"},
    ):
        for call in range(2):
            asked = ops.search_with_filters_with_canonical_splice(
                str(zim), "asthma in spanish", "C", None, 5, 0
            )
            not_asked = ops.search_with_filters_with_canonical_splice(
                str(zim), "asthma", "C", None, 5, 0
            )
            assert _rendered(asked) == _ASKED, (call, asked)
            assert _rendered(not_asked) == _NOT_ASKED, (call, not_asked)
