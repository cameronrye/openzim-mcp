"""Tests for _boost_by_section_affinity — re-ranks section-attributed
passages whose section heading shares tokens with the query.

The motivating case: query 'famous people from big rapids michigan'
should bubble the #Notable_people passage above the #History passage
because 'people' (query token) appears in 'Notable people' (heading
tokens) but not in 'History'.
"""

from __future__ import annotations

from typing import Any, Dict, List

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
    cfg = SynthesizeConfig()  # threshold=0.25, boost=1.5

    out = _boost_by_section_affinity(
        passages,
        query="famous people from big rapids michigan",
        bundle_lookup=bundle_lookup,
        config=cfg,
    )

    # Affinity for Notable_people heading: heading tokens {notable, people};
    # query tokens include {people}. Intersect = {people}. Affinity = 1/2 = 0.5.
    # 0.5 >= 0.25 → boost. New score = 0.6 * 1.5 = 0.9.
    notable_passage = next(
        p for p in out if p["cite_id"] == "wiki/Big_Rapids,_Michigan#Notable_people"
    )
    assert notable_passage["score"] == 0.6 * 1.5


def test_boost_flips_order_when_boosted_passage_overtakes():
    """When the boosted passage's new score exceeds the prior leader,
    it ranks first."""
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
    # Notable_people: 0.4 * 1.5 = 0.6. History: 0.5. Notable_people wins.
    assert out[0]["cite_id"] == "wiki/Big_Rapids,_Michigan#Notable_people"


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
    assert history_passage["score"] == 1.0
    assert geography_passage["score"] == 0.6


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
    assert article_passage["score"] == 1.0


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
    assert out[0]["score"] == 1.0


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
    assert out[0]["score"] == 1.0


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
    assert out[0]["score"] == 1.0


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
    assert out[0]["score"] == 1.0


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
    assert out[0]["score"] == 1.0


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


def test_boost_renumbers_rank_to_match_new_order():
    """After the affinity boost re-sorts by score, the passages'
    ``rank`` field is renumbered to match the new ordering. Otherwise
    downstream consumers reading `passages[].rank` get stale BM25
    positions inconsistent with the order they actually appear in."""
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
    # Notable_people boosted 0.4 → 0.6, History stays 0.5. Notable_people
    # is now first AND its rank should be 1; History gets rank 2.
    assert out[0]["cite_id"] == "wiki/Big_Rapids,_Michigan#Notable_people"
    assert out[0]["rank"] == 1
    assert out[1]["rank"] == 2
