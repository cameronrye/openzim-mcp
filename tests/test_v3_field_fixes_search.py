"""v3.0.0 field-defect fixes — search cluster (D26-D32).

Regression tests for the 2026-08-19 real-world sweep findings in the
``zim_search`` surface. The sweep ran against two site-scraped (zimit /
warc2zim) archives — MedlinePlus and the Internet Encyclopedia of
Philosophy — whose titles carry a site suffix (``Diabetes | MedlinePlus``)
and whose paths are domain-prefixed URLs, the archive class the
title-lookup and snippet code had never been exercised on.

Each test names the defect it pins; the mock archives model the exact
shapes observed on the real corpora.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List
from unittest.mock import MagicMock

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import CacheConfig, ContentConfig, OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations

# ---------------------------------------------------------------------------
# Shared mock builders
# ---------------------------------------------------------------------------


def _ctx(value: Any):
    """Minimal context manager wrapping ``value`` for ``zim_archive``."""

    class _C:
        def __enter__(self) -> Any:
            return value

        def __exit__(self, *a: Any) -> bool:
            return False

    return _C()


def _entry(path: str, title: str) -> MagicMock:
    """A non-redirect libzim Entry mock."""
    e = MagicMock()
    e.path = path
    e.title = title
    e.is_redirect = False
    return e


def _make_ops(tmp_path: Path, monkeypatch) -> ZimOperations:
    """A cache-enabled ``ZimOperations`` whose path validation is a no-op."""
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=True, max_size=50, ttl_seconds=60),
        content=ContentConfig(max_content_length=10000, snippet_length=200),
    )
    ops = ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(snippet_length=200),
    )
    monkeypatch.setattr(ops, "_validate_zim_path", lambda p: Path("/zim/test.zim"))
    return ops


def _scraped_archive(entries: Dict[str, MagicMock]) -> MagicMock:
    """An archive modelled on a zimit scrape: suffixed titles, URL paths.

    Neither the exact-title index nor the ``C/``/``A/`` path conventions
    resolve anything — exactly the shape that made the typo sweep
    structurally unverifiable on the real corpora.
    """
    archive = MagicMock()
    archive.has_new_namespace_scheme = True
    archive.has_entry_by_title.return_value = False
    archive.has_entry_by_path.return_value = False
    archive.get_entry_by_path.side_effect = lambda p: entries[p]
    return archive


def _suggester_by_query(
    lookup: Callable[[str], List[str]],
) -> Callable[[Any], Any]:
    """A ``SuggestionSearcher`` factory whose ``suggest`` consults ``lookup``."""

    def _factory(_archive: Any) -> Any:
        searcher = MagicMock()

        def _suggest(text: str) -> Any:
            paths = lookup(text)
            sugg = MagicMock()
            sugg.getEstimatedMatches.return_value = len(paths)
            sugg.getResults.side_effect = lambda start, n: paths[start : start + n]
            return sugg

        searcher.suggest.side_effect = _suggest
        return searcher

    return _factory


def _patch_archive(monkeypatch, archive: Any, searcher_factory: Any) -> None:
    monkeypatch.setattr(
        "openzim_mcp.zim_operations.zim_archive",
        lambda *a, **kw: _ctx(archive),
    )
    monkeypatch.setattr(
        "openzim_mcp.zim_operations.SuggestionSearcher", searcher_factory
    )


# ---------------------------------------------------------------------------
# D26 — title-mode typo tolerance on scraped archives
# ---------------------------------------------------------------------------

_DIABETES_PATH = "medlineplus.gov/diabetes.html"
_DIABETES_TITLE = "Diabetes | Type 1 Diabetes | Type 2 Diabetes | MedlinePlus"


def _medlineplus_lookup(text: str) -> List[str]:
    """The real corpus prefix-matches ``Diabete``/``Diabetes`` to the
    Diabetes topic page and returns nothing for the typo itself."""
    if "diabetes".startswith(text.lower()) and len(text) >= 5:
        return [_DIABETES_PATH]
    return []


def test_d26_typo_variant_verified_via_title_index_on_suffixed_archive(
    tmp_path, monkeypatch
) -> None:
    """``Diabtes`` must resolve to the Diabetes page through the title index.

    On a scraped archive no variant ever satisfies ``has_entry_by_title``
    (titles are suffixed) or the ``C/``/``A/`` probes (paths are URLs), so
    the Levenshtein-1 sweep verified nothing and the caller got a bare
    empty page. Verifying candidates via suggestion search instead turns
    the corrected spelling into a ``typo_corrected`` row plus an
    ``alt_spelling`` suggestion.
    """
    ops = _make_ops(tmp_path, monkeypatch)
    archive = _scraped_archive(
        {_DIABETES_PATH: _entry(_DIABETES_PATH, _DIABETES_TITLE)}
    )
    _patch_archive(monkeypatch, archive, _suggester_by_query(_medlineplus_lookup))

    out = ops.find_entry_by_title_data("/zim/test.zim", "Diabtes", limit=10)

    assert out["fuzzy_path_hit"] is True, out
    assert out["results"], out
    top = out["results"][0]
    assert top["path"] == _DIABETES_PATH
    assert top["title"] == _DIABETES_TITLE
    assert top["match_type"] == "typo_corrected"
    suggestions = out["_meta"].get("suggestions") or []
    assert any(
        s["type"] == "alt_spelling" and s["value"] == _DIABETES_TITLE
        for s in suggestions
    ), suggestions


def test_d26_title_index_verification_requires_a_whole_word(
    tmp_path, monkeypatch
) -> None:
    """A prefix that is not a whole word is not a verified spelling.

    The suggestion index prefix-matches ``Diabete`` to ``Diabetes ...``
    too; accepting that would surface a non-word as a corrected
    spelling. Only a candidate that ends on a word boundary of the
    matched title counts.
    """
    ops = _make_ops(tmp_path, monkeypatch)
    archive = _scraped_archive(
        {_DIABETES_PATH: _entry(_DIABETES_PATH, _DIABETES_TITLE)}
    )
    _patch_archive(monkeypatch, archive, _suggester_by_query(_medlineplus_lookup))

    assert ops._verify_variant_via_title_index(archive, "Diabete") is None
    hit = ops._verify_variant_via_title_index(archive, "Diabetes")
    assert hit is not None and hit.path == _DIABETES_PATH


def test_d26_five_char_typo_generates_deletion_variant() -> None:
    """``Kannt`` -> ``Kant``: the deletion edit must exist for 5-char input.

    The sweep gated deletions to 6+ characters, so the most common typo
    of a short name (a doubled letter) was never even generated.
    """
    from openzim_mcp.zim.search import _SearchMixin

    variants = _SearchMixin._typo_variants("Kannt")
    assert "Kant" in variants
    # The 4-char floor still holds: ``test`` must not spray 3-char probes.
    assert all(len(v) >= 4 for v in _SearchMixin._typo_variants("test"))


def test_d26_suffixed_exact_title_scores_one(tmp_path, monkeypatch) -> None:
    """``virtue ethics`` against ``Virtue Ethics | Internet Encyclopedia of
    Philosophy`` is an exact title match, not a 0.95 fuzzy suggestion.

    Scraped archives suffix every title with the site name, so the
    strict score-1.0 gate the promotion passes rely on could never be
    met — ``what is diabetes`` / ``tell me about virtue ethics`` always
    fell through to a bare 0-hit page.
    """
    path = "iep.utm.edu/virtue/"
    title = "Virtue Ethics | Internet Encyclopedia of Philosophy"
    ops = _make_ops(tmp_path, monkeypatch)
    archive = _scraped_archive({path: _entry(path, title)})
    _patch_archive(
        monkeypatch,
        archive,
        _suggester_by_query(
            lambda text: [path] if text.lower().startswith("virtue") else []
        ),
    )

    out = ops.find_entry_by_title_data("/zim/test.zim", "virtue ethics", limit=10)

    assert out["results"][0]["path"] == path
    assert out["results"][0]["score"] == 1.0
    assert out["results"][0]["match_type"] == "direct"
    assert out["fast_path_hit"] is True


def test_d26_z4_reads_the_candidate_name_from_the_title_on_url_paths() -> None:
    """``tell me about virtue ethics`` -> ``Virtue Ethics`` is not tangential.

    The Z4 shape predicates tokenize the candidate *path* as a stand-in
    for its title, which holds on Wikipedia (``Virtue_ethics``) but not on
    scraped archives, where ``iep.utm.edu/virtue/`` reads as the four
    unrelated tokens ``iep utm edu virtue`` and every on-topic candidate
    was rejected as a multi-token tangential promotion. URL-shaped paths
    must fall back to the site-suffix-stripped title; Wikipedia-style
    paths keep their existing verdicts.
    """
    from openzim_mcp.title_promotion import (
        is_tangential_multi_token_shape,
        passes_z4,
    )

    scraped = {
        "path": "iep.utm.edu/virtue/",
        "title": "Virtue Ethics | Internet Encyclopedia of Philosophy",
    }
    topic = "tell me about virtue ethics"
    assert is_tangential_multi_token_shape(scraped, topic) is False
    assert passes_z4(scraped, topic, lambda _token: None) is True

    # The b11 motivating rejection is untouched on a Wikipedia-style path.
    wikipedia = {"path": "A/Mozarthaus_Vienna", "title": "Mozarthaus Vienna"}
    assert is_tangential_multi_token_shape(wikipedia, "Mozart Vienna") is True


# ---------------------------------------------------------------------------
# D27 — plain fulltext dedupes query-string variants of the same page
# ---------------------------------------------------------------------------


def test_d27_plain_fulltext_page_emits_each_page_once(tmp_path) -> None:
    """``foo.htm`` and ``foo.htm?quiz=1`` are one page, emitted once.

    The filtered scanner already collapses warc2zim query-string variants
    on ``canonical_result_path``; the plain path appended raw hits, so a
    MedlinePlus page of 40 carried 19 duplicates. The page must fill to
    ``limit`` with distinct pages and report how many ranked rows it
    consumed so a client can resume cleanly.
    """
    from unittest.mock import patch

    from openzim_mcp.pagination import Cursor
    from tests.zim_stubs import make_archive_stub, make_ops, make_search_stub

    ops = make_ops(tmp_path)
    zim_file = tmp_path / "test.zim"
    zim_file.write_bytes(b"zim")
    entry_ids = [
        "C/quiz/001214_3.htm",
        "C/quiz/001214_3.htm?quiz=1",
        "C/quiz/000249_49.htm",
        "C/quiz/007617_46.htm",
        "C/quiz/007617_46.htm?quiz=1",
        "C/quiz/000123_9.htm",
    ]

    def _perform(ids, limit, offset):
        with patch("openzim_mcp.zim_operations.Searcher") as searcher:
            searcher.return_value.search.return_value = make_search_stub(ids)
            return ops._perform_search(
                make_archive_stub(), "quiz", limit, offset, validated_path=zim_file
            )

    page1, total = _perform(entry_ids, 2, 0)
    assert total == len(entry_ids)
    assert [r["path"] for r in page1["results"]] == [
        "C/quiz/001214_3.htm",
        "C/quiz/000249_49.htm",
    ]
    assert page1["page_info"]["returned_count"] == 2
    # Three ranked rows were examined to fill two slots.
    assert page1["page_info"]["source_consumed"] == 3
    assert page1["done"] is False
    cursor = Cursor.decode(page1["next_cursor"], expected_tool="search_zim_file")
    assert cursor["s"]["o"] == 3

    # Resuming where the first page stopped yields the remaining pages,
    # deduped again, and exhausts the stream.
    page2, _ = _perform(entry_ids, 2, 3)
    assert [r["path"] for r in page2["results"]] == [
        "C/quiz/007617_46.htm",
        "C/quiz/000123_9.htm",
    ]
    assert page2["done"] is True
    assert page2["next_cursor"] is None

    # A page without variants is byte-identical to before: no extra key.
    clean, _ = _perform(["C/a.htm", "C/b.htm", "C/c.htm"], 2, 0)
    assert [r["path"] for r in clean["results"]] == ["C/a.htm", "C/b.htm"]
    assert "source_consumed" not in clean["page_info"]


# ---------------------------------------------------------------------------
# D28 — low_relevance must not flag hits Xapian matched by stem or fold
# ---------------------------------------------------------------------------


def test_d28_low_relevance_proxy_folds_diacritics_and_stems() -> None:
    """``diabet*`` / ``Godel`` hits that ARE the topic are not low_relevance.

    The relevance proxy compared exact ASCII lowercase tokens, so the
    wildcard stem ``diabet`` never equalled ``diabetes`` and ``gödel``
    tokenised to ``del``; the flag told the model to distrust the best
    possible results. Compare modulo the same stemming/diacritic folding
    Xapian applied: fold both sides and accept a shared stem prefix.
    """
    from openzim_mcp.zim.search import _all_results_weakly_match

    diabetes_hits = [
        {"path": "medlineplus.gov/diabetes.html", "title": "Diabetes | MedlinePlus"},
        {"path": "medlineplus.gov/diabetestype2.html", "title": "Type 2 Diabetes"},
    ]
    assert _all_results_weakly_match(diabetes_hits, "diabet*") is False
    # Inflection in the other direction (query longer than the title token).
    assert (
        _all_results_weakly_match(
            [{"path": "C/Symptom", "title": "Symptom"}], "symptoms"
        )
        is False
    )

    godel_hits = [
        {"path": "iep.utm.edu/lp-argue/", "title": "Lucas-Penrose Argument about Gödel"}
    ]
    assert _all_results_weakly_match(godel_hits, "Godel") is False
    assert _all_results_weakly_match(godel_hits, "Gödel") is False

    # Genuinely unrelated hits still trip the flag.
    assert (
        _all_results_weakly_match([{"path": "A/Banana", "title": "Banana"}], "insulin")
        is True
    )
    # A short shared prefix is not a stem: ``cat`` must not vouch for
    # ``catalogue``.
    assert (
        _all_results_weakly_match(
            [{"path": "A/Catalogue", "title": "Catalogue"}], "cats"
        )
        is True
    )


# ---------------------------------------------------------------------------
# D29 — snippets skip site boilerplate and navigation blocks
# ---------------------------------------------------------------------------

# Trimmed from medlineplus.gov/ency/article/000305.htm as rendered at the
# snippet stage (compact markdown of the main-content landmark).
_ENCY_MARKDOWN = (
    "# Type 1 diabetes\n\n"
    "To use the sharing features on this page, please enable JavaScript.\n\n"
    "Type 1 diabetes is a lifelong ([chronic](002312.htm)) disease in which "
    "there is a high level of sugar (glucose) in the blood.\n\n"
    "## Causes\n\n"
    "Type 1 diabetes can occur at any age. It is most often diagnosed in "
    "children, adolescents, or young adults.\n\n"
    "## Symptoms\n\n"
    "  * Being very thirsty\n  * Feeling hungry\n  * Having blurry eyesight\n"
)

# Trimmed from medlineplus.gov/diabetes.html: the "On this page" nav block.
_TOPIC_MARKDOWN = (
    "#  Diabetes \n\n"
    "On this page\n\n"
    "### Basics\n\n"
    "  * Summary\n  * Start Here\n  * Diagnosis and Tests\n"
    "  * Prevention and Risk Factors\n\n"
    "### Research\n\n"
    "  * Statistics and Research\n  * Clinical Trials\n\n"
    "## Summary\n\n"
    "### What is diabetes?\n\n"
    "Diabetes, also known as diabetes mellitus, is a disease in which your "
    "[blood glucose](bloodglucose.html), or blood sugar, levels are too high.\n"
)


def test_d29_snippet_skips_the_no_javascript_boilerplate() -> None:
    """A query that matches the H1 must not yield '# H1 + enable JavaScript'.

    On MedlinePlus the ``<noscript>`` share-widget sentence sits directly
    under every H1, and the ``: MedlinePlus Medical Encyclopedia`` title
    suffix kept the H1 strip from firing — 13 of 30 ``insulin`` snippets
    were that boilerplate and nothing else.
    """
    cp = ContentProcessor(snippet_length=300)
    snippet = cp.create_snippet(
        _ENCY_MARKDOWN,
        query="diabetes",
        title="Type 1 diabetes: MedlinePlus Medical Encyclopedia",
        max_paragraphs=2,
    )
    assert "sharing features" not in snippet
    assert "Type 1 **diabetes** is a lifelong" in snippet
    # The H1 duplicates the (suffixed) title and is stripped like on
    # Wikipedia-class archives.
    assert not snippet.startswith("#")


def test_d29_snippet_skips_on_this_page_navigation_lists() -> None:
    """Lead fallback and fill must step over nav lists to reach prose."""
    cp = ContentProcessor(snippet_length=400)
    # No query term anywhere: the lead fallback used to be the nav block.
    lead = cp.create_snippet(
        _TOPIC_MARKDOWN,
        query="insulin",
        title="Diabetes | Type 1 Diabetes | Type 2 Diabetes | MedlinePlus",
        max_paragraphs=2,
    )
    assert "On this page" not in lead
    assert "Start Here" not in lead
    assert "Diabetes, also known as diabetes mellitus" in lead

    # A content list (sentence-case items) is NOT navigation and still
    # anchors a snippet for a term inside it.
    symptoms = cp.create_snippet(_ENCY_MARKDOWN, query="thirsty", max_paragraphs=1)
    assert "Being very **thirsty**" in symptoms
