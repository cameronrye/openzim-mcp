"""Regression tests for the search / title-promotion / intent review lane.

Each test pins a defect the review found in the v3 field-defect branch:
the rendered footer ignoring the dedup resume point, cache keys not bumped
alongside their payload change, "City, State" titles inverting into person
names, the typo sweep running unbounded, the unconditional "about" peel and
the archive-hint term strip on a non-routed call.
"""

import re
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# search.py — the rendered footer must advance by the dedup resume point
# ---------------------------------------------------------------------------


def test_rendered_footer_advances_by_source_consumed(tmp_path) -> None:
    """The markdown footer is what the model pages with; it must match the
    cursor. A deduped page mints a cursor, so the ``source_consumed``
    correction previously sat on an unreachable branch and the footer
    replayed the previous page's last row."""
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
    with patch("openzim_mcp.zim_operations.Searcher") as searcher:
        searcher.return_value.search.return_value = make_search_stub(entry_ids)
        page1, _ = ops._perform_search(
            make_archive_stub(), "quiz", 2, 0, validated_path=zim_file
        )

    assert page1["page_info"]["source_consumed"] == 3
    assert "pass `offset=3` for the next page" in ops._format_search_text(page1)


def test_rendered_footer_unchanged_without_dedup(tmp_path) -> None:
    """A page that collapsed nothing keeps the plain ``offset + limit``
    footer — the correction must not perturb the common case."""
    from tests.zim_stubs import make_archive_stub, make_ops, make_search_stub

    ops = make_ops(tmp_path)
    zim_file = tmp_path / "test.zim"
    zim_file.write_bytes(b"zim")
    with patch("openzim_mcp.zim_operations.Searcher") as searcher:
        searcher.return_value.search.return_value = make_search_stub(
            ["C/a.htm", "C/b.htm", "C/c.htm", "C/d.htm"]
        )
        page, _ = ops._perform_search(
            make_archive_stub(), "quiz", 2, 0, validated_path=zim_file
        )

    assert "source_consumed" not in page["page_info"]
    assert "pass `offset=2` for the next page" in ops._format_search_text(page)


# ---------------------------------------------------------------------------
# search.py — cache keys must move when their payload shape moves
# ---------------------------------------------------------------------------


_SEARCH_SRC = Path("openzim_mcp/zim/search.py").read_text(encoding="utf-8")

# The pre-3.0.1 spellings. Each of these payloads changed in the v3
# field-defect pass (dedup + ``page_info.source_consumed``, the
# ``_snippet_query`` anchoring, ``total_is_lower_bound``, the widened
# ``exact_ci`` score), so a cache persisted by 3.0.0 must not satisfy them.
_STALE_SEARCH_KEYS = (
    'f"search_v2b:{validated_path}:"',
    'f"search_filtered:{validated_path}:"',
    'f"search_filtered_v2b:{validated_path}:"',
    'f"find_title:v1:{files[0]}:"',
)


def test_changed_search_payloads_left_their_stale_cache_keys_behind() -> None:
    for stale in _STALE_SEARCH_KEYS:
        assert stale not in _SEARCH_SRC, stale


def test_every_search_cache_key_carries_a_version_token() -> None:
    keys = re.findall(
        r'f"(search[a-z_]*|find_title):[^"]*\{(?:validated_path|files\[0\])\}',
        _SEARCH_SRC,
    )
    assert keys, "no search cache keys found"
    for prefix in keys:
        assert re.search(r"_?v\d", prefix) or f'f"{prefix}:v' in _SEARCH_SRC, prefix


# ---------------------------------------------------------------------------
# title_promotion.py — the Last, First inversion must not eat City, State
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("topic", "path", "title"),
    [
        ("Texas", "A/Paris,_Texas", "Paris, Texas"),
        ("Illinois", "A/Springfield,_Illinois", "Springfield, Illinois"),
        ("Missouri", "A/Kansas_City,_Missouri", "Kansas City, Missouri"),
    ],
)
def test_city_state_titles_do_not_strong_match_the_bare_state(
    topic: str, path: str, title: str
) -> None:
    """``Paris, Texas`` inverts to ``Texas Paris``, which the unconditional
    candidate-extends-topic rule read as the article for ``Texas`` — so a
    weak top hit was accepted as canonical and the title-index probe that
    would have found ``A/Texas`` never ran."""
    from openzim_mcp.title_promotion import is_strong_title_match

    assert is_strong_title_match(topic, path, title) is False


@pytest.mark.parametrize(
    ("topic", "title"),
    [
        ("immanuel kant", "Kant, Immanuel | Internet Encyclopedia of Philosophy"),
        ("Immanuel Kant", "Kant, Immanuel: Aesthetics"),
        ("kansas city missouri", "Kansas City, Missouri"),
    ],
)
def test_inversion_still_matches_a_topic_that_names_both_halves(
    topic: str, title: str
) -> None:
    """D49's case is a topic naming the whole person; that still matches."""
    from openzim_mcp.title_promotion import is_strong_title_match

    assert is_strong_title_match(topic, "iep.utm.edu/x/", title) is True


# ---------------------------------------------------------------------------
# search.py — the typo sweep must honour its own extra-probe budget
# ---------------------------------------------------------------------------


def test_typo_sweep_stops_within_its_extra_probe_budget(tmp_path, monkeypatch) -> None:
    """The sweep documents a ``first_hit + _TYPO_MAX_EXTRA_PROBES`` cap, but
    the early-out also demanded a FULL suggestion pool — unreachable when
    the misspelling reaches a single article, so every one of the ~400
    variants was swept and (since D26) paid for a title-index suggestion
    query. The canonical hit must still be returned."""
    from openzim_mcp.zim.search import _SearchMixin
    from tests.test_v3_field_fixes_search import (
        _DIABETES_PATH,
        _DIABETES_TITLE,
        _entry,
        _make_ops,
        _medlineplus_lookup,
        _patch_archive,
        _scraped_archive,
        _suggester_by_query,
    )

    calls: list[str] = []

    def _counting_lookup(text: str) -> list[str]:
        calls.append(text)
        return _medlineplus_lookup(text)

    ops = _make_ops(tmp_path, monkeypatch)
    archive = _scraped_archive(
        {_DIABETES_PATH: _entry(_DIABETES_PATH, _DIABETES_TITLE)}
    )
    _patch_archive(monkeypatch, archive, _suggester_by_query(_counting_lookup))

    out = ops.find_entry_by_title_data("/zim/test.zim", "Diabtes", limit=10)

    assert out["results"][0]["path"] == _DIABETES_PATH
    variant_count = len(_SearchMixin._typo_variants("Diabtes"))
    assert len(calls) < variant_count, "the sweep ran every variant"


# ---------------------------------------------------------------------------
# intent_parser.py — "About X" titles survive a prepositional anchor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected_path"),
    [
        ("summary of About a Boy", "about a boy"),
        ("toc of About Schmidt", "about schmidt"),
        ("links in About a Boy", "about a boy"),
        ("structure of About Time", "about time"),
    ],
)
def test_about_is_not_peeled_off_a_prepositional_tail(
    query: str, expected_path: str
) -> None:
    """After ``of`` / ``in`` the user is spelling the title out, so peeling
    ``about`` pointed the resolver at a different article — and with both
    ``About Schmidt`` and ``Schmidt`` in the index it did so confidently."""
    from openzim_mcp.intent_parser import IntentParser

    _intent, params, _ = IntentParser.parse_intent(query)
    assert params.get("entry_path", "").lower() == expected_path


@pytest.mark.parametrize(
    "query",
    ["get the article about Immanuel Kant", "show an entry about Immanuel Kant"],
)
def test_about_is_still_peeled_after_the_object_noun(query: str) -> None:
    """D48's shape — ``about`` bridging the object noun to the title."""
    from openzim_mcp.intent_parser import IntentParser

    _intent, params, _ = IntentParser.parse_intent(query)
    assert params.get("entry_path", "").lower() == "immanuel kant"
