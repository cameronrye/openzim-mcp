"""Tests for _boost_by_section_affinity — re-ranks section-attributed
passages whose section heading shares tokens with the query.

The motivating case: query 'famous people from big rapids michigan'
should bubble the #Notable_people passage above the #History passage
because 'people' (query token) appears in 'Notable people' (heading
tokens) but not in 'History'.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from openzim_mcp.config import SynthesizeConfig
from openzim_mcp.synthesize import _boost_by_section_affinity


def _passage(cite_id: str, score: float, rank: int = 0) -> Dict[str, Any]:
    return {
        "cite_id": cite_id,
        "text_markdown": f"text for {cite_id}",
        "rank": rank,
        "score": score,
    }


def _bundle_lookup_for(
    sections_by_path: Dict[str, List[Dict[str, Any]]],
) -> Any:
    """Build a fake bundle_lookup that returns sections for known paths."""

    def lookup(archive_name: str, entry_path: str) -> Any:
        sections = sections_by_path.get(entry_path)
        if sections is None:
            return None
        return {"sections": sections, "rendered_markdown": ""}

    return lookup


def test_boost_promotes_passage_when_section_heading_matches_query():
    """'famous people' query → 'Notable people' heading gets boosted.
    Verifies the multiplication happened; ordering effects covered in
    next test."""
    passages = [
        _passage("wiki/Big_Rapids,_Michigan#History", score=1.0, rank=1),
        _passage("wiki/Big_Rapids,_Michigan#Notable_people", score=0.6, rank=2),
    ]
    bundle_lookup = _bundle_lookup_for(
        {
            "Big_Rapids,_Michigan": [
                {"id": "History", "title": "History", "char_start": 0, "char_end": 100},
                {
                    "id": "Notable_people",
                    "title": "Notable people",
                    "char_start": 100,
                    "char_end": 200,
                },
            ]
        }
    )
    cfg = SynthesizeConfig()

    out = _boost_by_section_affinity(
        passages,
        query="famous people from big rapids michigan",
        bundle_lookup=bundle_lookup,
        config=cfg,
    )

    # Affinity for Notable_people heading: heading tokens {notable, people};
    # query tokens include {people}. Intersect = {people}. Affinity = 1/2 = 0.5.
    # 0.5 >= default threshold 0.25, so the default boost 1.5 applies:
    # new score = 0.6 * 1.5 = 0.9.
    notable_passage = next(
        p for p in out if p["cite_id"] == "wiki/Big_Rapids,_Michigan#Notable_people"
    )
    assert notable_passage["score"] == pytest.approx(0.6 * 1.5)


def test_boost_flips_order_and_renumbers_rank():
    """When the affinity boost re-sorts by score, the displaced passage's
    cite_id appears at position 1 AND the ``rank`` field is renumbered
    to match the new ordering.

    Regression-locks two coupled behaviors:
      (1) ordering — score-sort happens after the boost multiplier, so
          the boosted passage can overtake a prior leader;
      (2) rank renumbering — downstream consumers reading
          ``passages[].rank`` get the current positions, not stale
          BM25 positions inconsistent with the order they appear in.

    Both fall out of the same ``_boost_by_section_affinity`` call, but
    the rank-renumbering step is easy to forget after a sort, so the
    paired assertions guard against accidental regression of (2) while
    (1) keeps passing.
    """
    passages = [
        _passage("wiki/Big_Rapids,_Michigan#History", score=0.5, rank=1),
        _passage("wiki/Big_Rapids,_Michigan#Notable_people", score=0.4, rank=2),
    ]
    bundle_lookup = _bundle_lookup_for(
        {
            "Big_Rapids,_Michigan": [
                {"id": "History", "title": "History", "char_start": 0, "char_end": 100},
                {
                    "id": "Notable_people",
                    "title": "Notable people",
                    "char_start": 100,
                    "char_end": 200,
                },
            ]
        }
    )
    cfg = SynthesizeConfig()

    out = _boost_by_section_affinity(
        passages,
        query="famous people from big rapids",
        bundle_lookup=bundle_lookup,
        config=cfg,
    )
    # Notable_people: 0.4 * 1.5 = 0.6. History: 0.5. Notable_people now
    # leads on score and on rank; History gets rank 2.
    assert out[0]["cite_id"] == "wiki/Big_Rapids,_Michigan#Notable_people"
    assert out[0]["rank"] == 1
    assert out[1]["rank"] == 2


def test_boost_no_op_when_no_query_token_in_heading():
    """No shared tokens → no boost, original order preserved."""
    passages = [
        _passage("wiki/Big_Rapids,_Michigan#History", score=1.0, rank=1),
        _passage("wiki/Big_Rapids,_Michigan#Geography", score=0.6, rank=2),
    ]
    bundle_lookup = _bundle_lookup_for(
        {
            "Big_Rapids,_Michigan": [
                {"id": "History", "title": "History", "char_start": 0, "char_end": 100},
                {
                    "id": "Geography",
                    "title": "Geography",
                    "char_start": 100,
                    "char_end": 200,
                },
            ]
        }
    )
    cfg = SynthesizeConfig()

    out = _boost_by_section_affinity(
        passages,
        query="who founded big rapids",
        bundle_lookup=bundle_lookup,
        config=cfg,
    )
    history_passage = next(
        p for p in out if p["cite_id"] == "wiki/Big_Rapids,_Michigan#History"
    )
    geography_passage = next(
        p for p in out if p["cite_id"] == "wiki/Big_Rapids,_Michigan#Geography"
    )
    assert history_passage["score"] == pytest.approx(1.0)
    assert geography_passage["score"] == pytest.approx(0.6)


def test_boost_skips_article_level_citations():
    """Passages without a #section_id suffix are left untouched."""
    passages = [
        _passage("wiki/Big_Rapids,_Michigan", score=1.0, rank=1),
        _passage("wiki/Big_Rapids,_Michigan#Notable_people", score=0.6, rank=2),
    ]
    bundle_lookup = _bundle_lookup_for(
        {
            "Big_Rapids,_Michigan": [
                {
                    "id": "Notable_people",
                    "title": "Notable people",
                    "char_start": 0,
                    "char_end": 200,
                },
            ]
        }
    )
    cfg = SynthesizeConfig()

    out = _boost_by_section_affinity(
        passages,
        query="famous people",
        bundle_lookup=bundle_lookup,
        config=cfg,
    )
    article_passage = next(
        p for p in out if p["cite_id"] == "wiki/Big_Rapids,_Michigan"
    )
    assert article_passage["score"] == pytest.approx(1.0)


def test_boost_threshold_gate_blocks_weak_overlap():
    """One matching token in a 6-token heading is 1/6 ≈ 0.167,
    below the default threshold of 0.25. No boost."""
    passages = [
        _passage("wiki/Foo#A_Very_Long_Heading_Name_Here", score=1.0, rank=1),
    ]
    bundle_lookup = _bundle_lookup_for(
        {
            "Foo": [
                {
                    "id": "A_Very_Long_Heading_Name_Here",
                    "title": "A very long heading name here",
                    "char_start": 0,
                    "char_end": 100,
                },
            ]
        }
    )
    cfg = SynthesizeConfig()

    # Query has only 'long' as overlap (heading tokens: a, very, long, heading, name, here = 6 tokens).
    # Affinity = 1/6 ≈ 0.167 < 0.25.
    out = _boost_by_section_affinity(
        passages,
        query="long stuff",
        bundle_lookup=bundle_lookup,
        config=cfg,
    )
    assert out[0]["score"] == pytest.approx(1.0)


def test_boost_handles_missing_section_in_bundle():
    """Section_id present on cite_id but not found in bundle → skip
    silently, no boost, no crash."""
    passages = [
        _passage("wiki/Foo#nonexistent_section", score=1.0, rank=1),
    ]
    bundle_lookup = _bundle_lookup_for({"Foo": []})
    cfg = SynthesizeConfig()

    out = _boost_by_section_affinity(
        passages,
        query="anything goes here",
        bundle_lookup=bundle_lookup,
        config=cfg,
    )
    assert out[0]["score"] == pytest.approx(1.0)


def test_boost_handles_bundle_lookup_returning_none():
    """Bundle lookup returns None → no crash, no boost."""
    passages = [
        _passage("wiki/Foo#Section", score=1.0, rank=1),
    ]

    def none_lookup(archive_name: str, entry_path: str) -> Any:
        return None

    cfg = SynthesizeConfig()

    out = _boost_by_section_affinity(
        passages,
        query="anything",
        bundle_lookup=none_lookup,
        config=cfg,
    )
    assert out[0]["score"] == pytest.approx(1.0)


def test_boost_handles_bundle_lookup_raising():
    """Bundle lookup raises → no crash, no boost."""
    passages = [
        _passage("wiki/Foo#Section", score=1.0, rank=1),
    ]

    def raising_lookup(archive_name: str, entry_path: str) -> Any:
        raise RuntimeError("bundle build failed")

    cfg = SynthesizeConfig()

    out = _boost_by_section_affinity(
        passages,
        query="anything",
        bundle_lookup=raising_lookup,
        config=cfg,
    )
    assert out[0]["score"] == pytest.approx(1.0)


def test_boost_empty_query_is_no_op():
    """Empty query has no tokens → return passages unchanged."""
    passages = [
        _passage("wiki/Foo#Notable_people", score=1.0, rank=1),
    ]
    bundle_lookup = _bundle_lookup_for(
        {
            "Foo": [
                {
                    "id": "Notable_people",
                    "title": "Notable people",
                    "char_start": 0,
                    "char_end": 100,
                },
            ]
        }
    )
    cfg = SynthesizeConfig()

    out = _boost_by_section_affinity(
        passages,
        query="",
        bundle_lookup=bundle_lookup,
        config=cfg,
    )
    assert out[0]["score"] == pytest.approx(1.0)


def test_boost_bundle_lookup_called_once_per_unique_article():
    """When two passages cite the same article's different sections,
    the bundle is looked up only once (memoization)."""
    passages = [
        _passage("wiki/Big_Rapids,_Michigan#Section_A", score=1.0, rank=1),
        _passage("wiki/Big_Rapids,_Michigan#Section_B", score=0.8, rank=2),
    ]
    call_count = {"n": 0}

    def counting_lookup(archive_name: str, entry_path: str) -> Any:
        call_count["n"] += 1
        return {
            "sections": [
                {
                    "id": "Section_A",
                    "title": "Section A",
                    "char_start": 0,
                    "char_end": 50,
                },
                {
                    "id": "Section_B",
                    "title": "Section B",
                    "char_start": 50,
                    "char_end": 100,
                },
            ]
        }

    cfg = SynthesizeConfig()
    _boost_by_section_affinity(
        passages,
        query="section",  # match against headings
        bundle_lookup=counting_lookup,
        config=cfg,
    )
    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# The affinity stage must not undo the positional stages that precede it
# ---------------------------------------------------------------------------


def _synthesize(bm25_hits, query, *, title_match=None):
    """Drive ``synthesize_query`` end-to-end over one mocked archive.

    Bundles resolve to ``None`` so section attribution is a no-op and the
    cite_ids stay article-level — the affinity stage's ORDERING behaviour
    is what's under test, not its boost arithmetic.
    """
    from pathlib import Path
    from unittest.mock import MagicMock

    from openzim_mcp.synthesize import synthesize_query

    search_handler = MagicMock()
    search_handler.search_top_k.return_value = bm25_hits
    search_handler.title_match_hit.return_value = title_match

    content_processor = MagicMock()
    content_processor.html_to_plain_text.side_effect = lambda html: html

    import openzim_mcp.bundle as bundle_mod

    real_get = bundle_mod.get_or_build_bundle
    bundle_mod.get_or_build_bundle = lambda archive, path, **kw: None
    try:
        return synthesize_query(
            query,
            archives=[(MagicMock(), Path("/fake/wiki.zim"))],
            search_handler=search_handler,
            cache=MagicMock(),
            content_processor=content_processor,
            config=SynthesizeConfig(),
        )
    finally:
        bundle_mod.get_or_build_bundle = real_get


def test_affinity_stage_preserves_list_article_demotion():
    """``_demote_list_articles`` moved ``List_of_cats`` below ``Cat``, and
    the affinity stage must not put it back.

    The positional stages express their decision as list POSITION and
    never rewrite ``score`` (which stays the Xapian value), so the
    unconditional score-sort that used to close ``_boost_by_section_
    affinity`` restored the exact BM25 order and silently discarded both
    ``_demote_list_articles`` and ``_promote_title_match`` — the original
    ``List_of_songs_about_Berlin`` regression those stages exist to fix.

    Must be asserted at ``synthesize_query`` level: helper-level tests
    never see the two stages, which is why this shipped.
    """
    response = _synthesize(
        [
            {"path": "List_of_cats", "snippet": "A list of cats.", "score": 1.0},
            {"path": "Cat", "snippet": "The cat is a domestic species.", "score": 0.5},
        ],
        query="cat",
    )
    assert response["passages"][0]["cite_id"].endswith("/Cat")
    assert response["citations"][0]["entry_path"] == "Cat"


def test_affinity_stage_preserves_title_match_reorder():
    """Same guarantee for ``_promote_title_match``'s already-present
    branch: the canonical is reordered to the front of ``top_hits``
    without its score being touched, so a score-sort would undo it.

    ``Timeline_of_Berlin`` is deliberately not a list article, so
    ``_demote_list_articles`` is a no-op here and the reorder under test
    is unambiguously the title-match promotion's."""
    response = _synthesize(
        [
            {"path": "Timeline_of_Berlin", "snippet": "1237: founded.", "score": 1.0},
            {"path": "Berlin", "snippet": "Berlin is the capital.", "score": 0.6},
        ],
        query="berlin",
        title_match={
            "path": "Berlin",
            "snippet": "Berlin is the capital.",
            "score": 1.0,
        },
    )
    assert response["passages"][0]["cite_id"].endswith("/Berlin")
    assert response["citations"][0]["entry_path"] == "Berlin"


# ---------------------------------------------------------------------------
# ...and the affinity boost must stay a CONSERVATIVE multiplier, not an
# absolute precedence over every unboosted passage.
# ---------------------------------------------------------------------------


_AFFINITY_ORDER_PASSAGES = [
    # Top hit by a wide margin; its section heading shares nothing with the
    # query.
    ("wiki/A/Berlin#Culture", 1.0),
    # Weakest hit; its one-word heading "History" is fully covered by the
    # query, so affinity == 1.0 and the gate trips.
    ("wiki/A/Checkpoint_Charlie#History", 0.2),
]

_AFFINITY_ORDER_BUNDLES = {
    "A/Berlin": [
        {"id": "Culture", "title": "Culture", "char_start": 0, "char_end": 100},
    ],
    "A/Checkpoint_Charlie": [
        {"id": "History", "title": "History", "char_start": 0, "char_end": 100},
    ],
}


def _order_for(boost: float) -> List[str]:
    cfg = SynthesizeConfig(section_affinity_boost=boost)
    out = _boost_by_section_affinity(
        [
            _passage(cite_id, score=score, rank=i)
            for i, (cite_id, score) in enumerate(_AFFINITY_ORDER_PASSAGES, start=1)
        ],
        query="history of berlin",
        bundle_lookup=_bundle_lookup_for(_AFFINITY_ORDER_BUNDLES),
        config=cfg,
    )
    return [p["cite_id"] for p in out]


def test_weak_affinity_match_does_not_leapfrog_a_far_stronger_hit():
    """A boosted passage must not outrank an unboosted one whose score is
    5x higher.

    Regression: partitioning on "was this boosted?" and concatenating
    ``matched + rest`` made the affinity boost an ABSOLUTE precedence —
    ``section_affinity_boost`` stopped affecting the ordering at all and
    a single incidental heading-token overlap ("History" against
    "history of berlin") inverted the whole ranking. The boost is
    documented in ``config.py`` as conservative: "won't dominate strong
    BM25 hits".
    """
    assert _order_for(1.5)[0] == "wiki/A/Berlin#Culture"


def test_affinity_boost_magnitude_still_controls_ordering():
    """``section_affinity_boost`` must remain a real magnitude knob.

    Under the partition, boosts of 1.0001, 1.5 and 10.0 all produced the
    identical order. Here 1.5 (conservative) leaves the strong hit on
    top while 10.0 (0.2 * 10 = 2.0 > 1.0) is enough to overtake it.
    """
    assert _order_for(1.5)[0] == "wiki/A/Berlin#Culture"
    assert _order_for(10.0)[0] == "wiki/A/Checkpoint_Charlie#History"


def test_maybe_boost_passage_reports_the_boost_for_a_zero_score():
    """The boost decision is RETURNED, never inferred from a score
    comparison: ``0.0 * boost == 0.0``, so a zero-score passage whose
    heading matches the query would otherwise be mis-classified as
    unboosted."""
    from openzim_mcp.synthesize import _maybe_boost_passage

    out, matched = _maybe_boost_passage(
        _passage("wiki/Foo#Notable_people", score=0.0, rank=1),
        query_tokens={"people"},
        bundle_lookup=_bundle_lookup_for(
            {
                "Foo": [
                    {
                        "id": "Notable_people",
                        "title": "Notable people",
                        "char_start": 0,
                        "char_end": 100,
                    }
                ]
            }
        ),
        cache={},
        threshold=0.25,
        boost=1.5,
    )
    assert matched is True
    assert out["score"] == pytest.approx(0.0)


def _synthesize_with_bundles(bm25_hits, query, bundles):
    """``_synthesize``, but with real section-bearing bundles so the
    affinity stage actually boosts."""
    from pathlib import Path
    from unittest.mock import MagicMock

    from openzim_mcp.synthesize import synthesize_query

    search_handler = MagicMock()
    search_handler.search_top_k.return_value = bm25_hits
    search_handler.title_match_hit.return_value = None

    content_processor = MagicMock()
    content_processor.html_to_plain_text.side_effect = lambda html: html

    import openzim_mcp.bundle as bundle_mod

    real_get = bundle_mod.get_or_build_bundle
    bundle_mod.get_or_build_bundle = lambda archive, path, **kw: bundles.get(path)
    try:
        return synthesize_query(
            query,
            archives=[(MagicMock(), Path("/fake/wiki.zim"))],
            search_handler=search_handler,
            cache=MagicMock(),
            content_processor=content_processor,
            config=SynthesizeConfig(),
        )
    finally:
        bundle_mod.get_or_build_bundle = real_get


def test_strong_top_hit_keeps_the_lead_end_to_end():
    """Same guarantee asserted through ``synthesize_query``, where the
    answer text and citations are actually built — helper-level coverage
    is exactly what let the absolute-precedence bug ship."""
    berlin_md = "# Berlin\n\nBerlin is the capital of Germany.\n\n## Culture\n\nMuseums abound.\n"
    charlie_md = (
        "# Checkpoint Charlie\n\n## History\n\nA crossing point opened in 1961.\n"
    )
    bundles = {
        "A/Berlin": {
            "title": "Berlin",
            "rendered_markdown": berlin_md,
            "sections": [
                {"id": "Berlin", "title": "Berlin", "char_start": 0, "char_end": 38},
                {
                    "id": "Culture",
                    "title": "Culture",
                    "char_start": 38,
                    "char_end": len(berlin_md),
                },
            ],
        },
        "A/Checkpoint_Charlie": {
            "title": "Checkpoint Charlie",
            "rendered_markdown": charlie_md,
            "sections": [
                {
                    "id": "Checkpoint_Charlie",
                    "title": "Checkpoint Charlie",
                    "char_start": 0,
                    "char_end": 22,
                },
                {
                    "id": "History",
                    "title": "History",
                    "char_start": 22,
                    "char_end": len(charlie_md),
                },
            ],
        },
    }
    response = _synthesize_with_bundles(
        [
            {"path": "A/Berlin", "snippet": "Museums abound.", "score": 1.0},
            {
                "path": "A/Checkpoint_Charlie",
                "snippet": "A crossing point opened in 1961.",
                "score": 0.2,
            },
        ],
        "history of berlin",
        bundles,
    )
    assert response["passages"][0]["cite_id"] == "wiki/A/Berlin#Culture"
    assert response["citations"][0]["cite_id"] == "wiki/A/Berlin#Culture"
