"""Real-world sweep (v3.2.2): ``suggest`` mode must consult the title index.

Driving the installed server against a MedlinePlus archive, ``suggest``
for ``diab`` returned four rows — ``Diabetic Diet`` plus three genetics
pages — and reported ``total=4, done=True``. libzim's ``SuggestionSearcher``
on the same archive estimates 99 matches for that prefix and ranks the
canonical ``Diabetes`` page first.

The cause is strategy ordering in ``_generate_search_suggestions``: the
Xapian full-text pass ran first and short-circuited the whole function
whenever it returned anything at all, so the archive's purpose-built
title/prefix index — the thing the tool description advertises — only ran
when full-text found *nothing*. ``done=True`` then asserted completeness
over a set the server had never looked at.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations


def _entry(path: str, title: str) -> MagicMock:
    e = MagicMock()
    e.path = path
    e.title = title
    e.is_redirect = False
    return e


# The archive as libzim sees it: the canonical page plus a long tail, all
# reachable through the title index.
_TITLE_INDEX: Dict[str, str] = {
    "medlineplus.gov/diabetes.html": "Diabetes | Type 1 and Type 2 | MedlinePlus",
    "medlineplus.gov/diabetestype1.html": "Diabetes Type 1 | MedlinePlus",
    "medlineplus.gov/diabetickidneyproblems.html": "Diabetic Kidney Problems",
    "medlineplus.gov/diabeticeyeproblems.html": "Diabetic Eye Problems",
    "medlineplus.gov/diabeticdiet.html": "Diabetic Diet | MedlinePlus",
}

# What the Xapian full-text pass surfaces for the same prefix: the short
# title plus genetics pages that merely *contain* the term. Note the
# canonical ``Diabetes`` page is absent — that is the real-world shape.
_FULLTEXT_HITS: List[str] = [
    "medlineplus.gov/diabeticdiet.html",
    "medlineplus.gov/genetics/condition/type-1-diabetes/",
    "medlineplus.gov/genetics/condition/type-2-diabetes/",
    "medlineplus.gov/genetics/condition/gestational-diabetes/",
]

_FULLTEXT_TITLES: Dict[str, str] = {
    "medlineplus.gov/diabeticdiet.html": "Diabetic Diet | MedlinePlus",
    "medlineplus.gov/genetics/condition/type-1-diabetes/": (
        "Type 1 diabetes: MedlinePlus Genetics"
    ),
    "medlineplus.gov/genetics/condition/type-2-diabetes/": (
        "Type 2 diabetes: MedlinePlus Genetics"
    ),
    "medlineplus.gov/genetics/condition/gestational-diabetes/": (
        "Gestational diabetes: MedlinePlus Genetics"
    ),
}

_ALL_TITLES = {**_FULLTEXT_TITLES, **_TITLE_INDEX}


class _Ctx:
    def __init__(self, archive: Any) -> None:
        self._archive = archive

    def __enter__(self) -> Any:
        return self._archive

    def __exit__(self, *exc: Any) -> bool:
        return False


@pytest.fixture
def ops(tmp_path) -> ZimOperations:
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=1000, snippet_length=100),
        logging=LoggingConfig(level="ERROR"),
    )
    operations = ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache),
        ContentProcessor(snippet_length=100),
    )
    operations.path_validator = MagicMock()
    operations.path_validator.validate_path.return_value = "/zim/mlp.zim"
    operations.path_validator.validate_zim_file.return_value = "/zim/mlp.zim"
    return operations


@pytest.fixture
def patched_archive(monkeypatch):
    """Wire both retrieval paths: Xapian full-text and the title index."""

    def _apply(
        *,
        fulltext: List[str],
        suggestions: List[str],
        estimated: Optional[int] = None,
    ) -> None:
        archive = MagicMock()
        archive.get_entry_by_path.side_effect = lambda p: _entry(
            p, _ALL_TITLES.get(p, "")
        )
        archive.has_entry_by_title.return_value = False

        search = MagicMock()
        search.getEstimatedMatches.return_value = len(fulltext)
        search.getResults.side_effect = lambda start, count: list(
            fulltext[start : start + count]
        )
        searcher = MagicMock()
        searcher.search.return_value = search

        sugg = MagicMock()
        sugg.getEstimatedMatches.return_value = (
            estimated if estimated is not None else len(suggestions)
        )
        sugg.getResults.side_effect = lambda start, count: list(
            suggestions[start : start + count]
        )
        sugg_searcher = MagicMock()
        sugg_searcher.suggest.return_value = sugg

        query = MagicMock()
        query.set_query.return_value = query

        monkeypatch.setattr(
            "openzim_mcp.zim_operations.zim_archive", lambda *a, **kw: _Ctx(archive)
        )
        monkeypatch.setattr(
            "openzim_mcp.zim_operations.Searcher", lambda _archive: searcher
        )
        monkeypatch.setattr(
            "openzim_mcp.zim_operations.SuggestionSearcher",
            lambda _archive: sugg_searcher,
        )
        monkeypatch.setattr("openzim_mcp.zim_operations.Query", lambda: query)

    return _apply


def test_canonical_title_index_match_is_returned(ops, patched_archive):
    """``diab`` must surface the canonical ``Diabetes`` page."""
    patched_archive(
        fulltext=_FULLTEXT_HITS, suggestions=list(_TITLE_INDEX), estimated=99
    )
    out = ops.get_search_suggestions_data("/zim/mlp.zim", "diab", limit=10)
    paths = [r["path"] for r in out["results"]]
    assert "medlineplus.gov/diabetes.html" in paths


def test_title_index_matches_are_not_starved_by_fulltext(ops, patched_archive):
    """A weak full-text pass must not suppress the title index entirely."""
    patched_archive(
        fulltext=_FULLTEXT_HITS, suggestions=list(_TITLE_INDEX), estimated=99
    )
    out = ops.get_search_suggestions_data("/zim/mlp.zim", "diab", limit=10)
    paths = {r["path"] for r in out["results"]}
    # Every real title-prefix match fits inside limit=10 alongside the
    # full-text rows; none of them may be dropped.
    assert _TITLE_INDEX.keys() <= paths


def test_done_is_not_claimed_while_the_index_holds_more(ops, patched_archive):
    """``done=True`` must not assert completeness over an unread index."""
    patched_archive(
        fulltext=_FULLTEXT_HITS, suggestions=list(_TITLE_INDEX), estimated=99
    )
    out = ops.get_search_suggestions_data("/zim/mlp.zim", "diab", limit=3)
    assert out["page_info"]["returned_count"] == 3
    assert out["done"] is False


def test_fulltext_only_archive_still_returns_suggestions(ops, patched_archive):
    """An archive whose title index is empty keeps the full-text fallback."""
    patched_archive(fulltext=_FULLTEXT_HITS, suggestions=[], estimated=0)
    out = ops.get_search_suggestions_data("/zim/mlp.zim", "diab", limit=10)
    assert out["results"], "full-text suggestions must survive an empty title index"


def test_no_duplicate_paths_across_strategies(ops, patched_archive):
    """``diabeticdiet`` is in both sources; it must appear once."""
    patched_archive(
        fulltext=_FULLTEXT_HITS, suggestions=list(_TITLE_INDEX), estimated=99
    )
    out = ops.get_search_suggestions_data("/zim/mlp.zim", "diab", limit=10)
    paths = [r["path"] for r in out["results"]]
    assert len(paths) == len(set(paths))


class TestTitleIndexDedupesByTitle:
    """One article's asset frames must not fill the autocomplete page.

    The full-text pass that used to fill this page deduped by title. The
    title index did not — it was only ever a cold-path fallback — so
    promoting it surfaced MedlinePlus slideshow frames
    (``…/presentations/100117_1..5.htm``, all titled "Knee arthroscopy -
    series") and ``?quiz=1`` variants as separate suggestions: ``knee``
    came back as 10 rows carrying 3 distinct titles.
    """

    INDEX = {
        "medlineplus.gov/ency/presentations/100117_1.htm": "Knee arthroscopy - series",
        "medlineplus.gov/ency/presentations/100117_2.htm": "Knee arthroscopy - series",
        "medlineplus.gov/ency/presentations/100117_3.htm": "Knee arthroscopy - series",
        "medlineplus.gov/kneeinjuries.html": "Knee Injuries and Disorders",
        "medlineplus.gov/kneereplacement.html": "Knee Replacement",
    }

    @pytest.fixture(autouse=True)
    def _wire(self):
        _ALL_TITLES.update(self.INDEX)
        yield

    def test_repeated_titles_collapse_to_one_row(self, ops, patched_archive):
        patched_archive(fulltext=[], suggestions=list(self.INDEX), estimated=40)
        out = ops.get_search_suggestions_data("/zim/mlp.zim", "knee", limit=10)
        titles = [r["text"] for r in out["results"]]
        assert len(titles) == len(set(titles))

    def test_distinct_articles_survive_the_dedup(self, ops, patched_archive):
        patched_archive(fulltext=[], suggestions=list(self.INDEX), estimated=40)
        out = ops.get_search_suggestions_data("/zim/mlp.zim", "knee", limit=10)
        titles = {r["text"] for r in out["results"]}
        assert "Knee Injuries and Disorders" in titles
        assert "Knee Replacement" in titles

    def test_deduped_page_fills_to_limit(self, ops, patched_archive):
        """Collapsed duplicates must free their slots for real articles."""
        patched_archive(fulltext=[], suggestions=list(self.INDEX), estimated=40)
        out = ops.get_search_suggestions_data("/zim/mlp.zim", "knee", limit=3)
        assert out["page_info"]["returned_count"] == 3
        titles = [r["text"] for r in out["results"]]
        assert len(titles) == len(set(titles))


class TestFullTextWindowIsSizedByThePage:
    """The full-text fallback must not shrink its own candidate window.

    ``_get_suggestions_from_search`` sizes its Xapian window as
    ``limit * 5`` from the limit it is handed. Passing it only the leftover
    slots (``remaining + 1``) shrank that window — with one slot left it
    scanned 10 candidates instead of 50, found nothing that matched the
    title filter, and the page came back short under ``done=True``.
    """

    def test_last_slot_still_scans_the_full_page_window(self, ops, patched_archive):
        """Nine title hits leave one slot; the window must still be limit-sized.

        At ``limit=10`` the helper should scan ``(10 + 1) * 5 = 55``
        candidates. Sized by the single leftover slot it scanned ``(1 + 1) *
        5 = 10`` instead, so a match at candidate 20 was invisible.
        """
        index_hits = {
            f"medlineplus.gov/diabetes{i}.html": f"Diabetes Topic {i}" for i in range(9)
        }
        noise = [f"medlineplus.gov/noise/{i}.html" for i in range(20)]
        _ALL_TITLES.update(index_hits)
        _ALL_TITLES.update({p: f"Unrelated page {i}" for i, p in enumerate(noise)})
        _ALL_TITLES["medlineplus.gov/diabetesdeep.html"] = "Diabetes Deep Match"
        patched_archive(
            fulltext=noise + ["medlineplus.gov/diabetesdeep.html"],
            suggestions=list(index_hits),
            estimated=9,
        )
        out = ops.get_search_suggestions_data("/zim/mlp.zim", "diabetes", limit=10)
        paths = {r["path"] for r in out["results"]}
        assert "medlineplus.gov/diabetesdeep.html" in paths


class TestExactTitleOutranksLongerPrefixMatches:
    """Ranking must not demote the article the query names outright.

    MedlinePlus titles carry a ``| MedlinePlus`` site suffix and often list
    their synonyms ahead of it, so ``Diabetes | Type 1 Diabetes | Type 2
    Diabetes | MedlinePlus`` is one of the *longest* titles matching
    ``diabetes`` — and a shortest-title tiebreak buried it below
    ``Diabetes Mellitus``, ``Diabetes Complications`` and four others, even
    though libzim's own suggestion index ranks it first.
    """

    INDEX = {
        "medlineplus.gov/diabetesmellitus.html": "Diabetes Mellitus: MedlinePlus",
        "medlineplus.gov/diabetescomplications.html": (
            "Diabetes Complications | MedlinePlus"
        ),
        "medlineplus.gov/diabetesinsipidus.html": (
            "Diabetes Insipidus | DI | MedlinePlus"
        ),
        "medlineplus.gov/languages/diabetes.html": (
            "Diabetes - Multiple Languages: MedlinePlus"
        ),
        "medlineplus.gov/diabetes.html": (
            "Diabetes | Type 1 Diabetes | Type 2 Diabetes | MedlinePlus"
        ),
    }

    @pytest.fixture(autouse=True)
    def _wire(self, monkeypatch):
        _ALL_TITLES.update(self.INDEX)
        yield

    def test_exact_leading_segment_ranks_first(self, ops, patched_archive):
        patched_archive(fulltext=[], suggestions=list(self.INDEX), estimated=40)
        out = ops.get_search_suggestions_data("/zim/mlp.zim", "diabetes", limit=5)
        assert out["results"][0]["path"] == "medlineplus.gov/diabetes.html"

    def test_prefix_query_ordering_is_unchanged(self, ops, patched_archive):
        # ``diab`` names no article exactly, so nothing is promoted and the
        # existing shortest-title ranking still decides the page.
        patched_archive(fulltext=[], suggestions=list(self.INDEX), estimated=40)
        out = ops.get_search_suggestions_data("/zim/mlp.zim", "diab", limit=5)
        assert out["results"][0]["path"] == "medlineplus.gov/diabetesmellitus.html"
