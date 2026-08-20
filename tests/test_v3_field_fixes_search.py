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
