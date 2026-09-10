"""Crawl artefacts must not outrank the article the caller asked for.

v3.3.1 field report, fid 71 — the report's own "bigger opportunity
underneath": both reranker configurations put a relevant article at #1 only
about 64% of the time and carry off-topic entries in every top-5.

Measured on the shipped archives at v3.3.2, with the rate limiter disabled
so the sweep is not reading its own throttling as clean pages:

    MedlinePlus, 20 topic queries, top-5
      fulltext  101 rows  12 artefacts  11.9%
      title      94 rows  23 artefacts  24.5%
      suggest    94 rows  22 artefacts  23.4%

The artefacts are scraper output, not articles: ``/imagepages/`` caption
stubs, ``/languages/`` translation hubs, ``.srt`` caption files, and
``/page/N/`` index pagination. ``title 'migraine headache'`` returns an
image-caption stub as its single hit.

**``/category/`` is deliberately NOT an artefact.** On the IEP archive
those pages are the encyclopedia's own topic index and the correct #1, at
score 1.0, for "metaphysics", "philosophy of science", "feminist
philosophy" and "continental philosophy" — demoting them would turn four
right answers into wrong ones. The shapes are matched independently, so
``category/m-and-e/metaphysics/page/2/`` is still demoted: it is index
pagination that happens to live under a category.

Three surfaces need it, not the two the finding names — suggest mode is
served by ``get_search_suggestions_data``, a different function from
``_assemble_find_response``, and measured worst of the three.

The demote is STABLE and drops nothing: relative order within each group is
the archive's own ranking, and every row the caller would have had is still
there. A page whose rows are *all* artefacts therefore comes back untouched
— which falls out of the partition rather than needing a guard, as the
mutation pass proved by deleting the guard and changing no behaviour.
"""

from __future__ import annotations

import pytest

from openzim_mcp.zim.search import demote_crawl_artefacts, is_crawl_artefact

# ---------------------------------------------------------------------------
# What counts as an artefact
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "medlineplus.gov/ency/imagepages/18146.htm",
        "medlineplus.gov/languages/hepatitisb.html",
        "medlineplus.gov/media/captions/tutorial.srt",
        "iep.utm.edu/category/m-and-e/metaphysics/page/2/",
        "iep.utm.edu/page/3/",
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
        "",
    ],
)
def test_real_content_is_not_an_artefact(path: str) -> None:
    assert is_crawl_artefact(path) is False


def test_a_category_page_is_kept_but_its_pagination_is_not():
    """The shapes are independent, not a precedence chain. Stated because
    "skip anything under /category/" is the obvious wrong simplification —
    it would keep index pagination that is pure scraper output."""
    assert is_crawl_artefact("iep.utm.edu/category/s-l-m/science/") is False
    assert is_crawl_artefact("iep.utm.edu/category/s-l-m/science/page/2/") is True


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
    """Defensive: a malformed row must not crash the sort or vanish."""
    rows = [{"title": "no path"}, {"path": "a.org/real.html"}]

    out = demote_crawl_artefacts(rows)
    assert len(out) == 2
