"""Tests for considered_articles + considered_sections population in
synthesize_query (A14).

The featured passage's article and section are excluded from the
considered lists — these surfaces are for *alternatives* the caller can
pivot to, not duplicates of what's already in citations[].
"""

from __future__ import annotations

from typing import Any

from openzim_mcp.synthesize import (
    _build_considered_articles,
    _build_considered_sections,
)


def test_build_considered_articles_excludes_featured_and_caps_at_3():
    """Top_hits with 6 entries; passage capped to 1 (featured). The
    considered_articles list has the remaining 5 in order, capped at 3."""
    top_hits = [
        (
            "wiki",
            {
                "path": "Big_Rapids,_Michigan",
                "title": "Big Rapids, Michigan",
                "score": 1.0,
            },
        ),
        (
            "wiki",
            {
                "path": "Big_Rapids_Township,_Michigan",
                "title": "Big Rapids Twp",
                "score": 0.7,
            },
        ),
        (
            "wiki",
            {"path": "Ferris_State_University", "title": "Ferris State", "score": 0.6},
        ),
        (
            "wiki",
            {
                "path": "Mecosta_County,_Michigan",
                "title": "Mecosta County",
                "score": 0.5,
            },
        ),
        (
            "wiki",
            {
                "path": "Pere_Marquette_River",
                "title": "Pere Marquette River",
                "score": 0.4,
            },
        ),
        ("wiki", {"path": "Muskegon_River", "title": "Muskegon River", "score": 0.3}),
    ]
    capped_passages = [
        {
            "cite_id": "wiki/Big_Rapids,_Michigan#Notable_people",
            "text_markdown": "...",
            "rank": 1,
            "score": 1.5,
        }
    ]
    result = _build_considered_articles(top_hits, capped_passages, max_n=3)
    assert len(result) == 3
    assert all(a["entry_path"] != "Big_Rapids,_Michigan" for a in result)
    assert result[0]["entry_path"] == "Big_Rapids_Township,_Michigan"
    assert result[1]["entry_path"] == "Ferris_State_University"
    assert result[2]["entry_path"] == "Mecosta_County,_Michigan"


def test_build_considered_articles_empty_when_only_featured():
    """One top_hit, captured as the featured passage → empty list."""
    top_hits = [
        ("wiki", {"path": "Big_Rapids,_Michigan", "title": "Big Rapids", "score": 1.0}),
    ]
    capped_passages = [
        {
            "cite_id": "wiki/Big_Rapids,_Michigan#Notable_people",
            "text_markdown": "...",
            "rank": 1,
            "score": 1.5,
        }
    ]
    result = _build_considered_articles(top_hits, capped_passages, max_n=3)
    assert result == []


def test_build_considered_articles_includes_all_when_no_passages():
    """No featured passage → no exclusion applied; all top_hits pass through (capped at max_n)."""
    top_hits = [
        ("wiki", {"path": "A", "title": "A", "score": 1.0}),
        ("wiki", {"path": "B", "title": "B", "score": 0.5}),
    ]
    result = _build_considered_articles(top_hits, [], max_n=3)
    # With no featured to exclude, all top_hits make it (capped)
    assert len(result) == 2
    assert result[0]["entry_path"] == "A"


def test_build_considered_sections_returns_sections_minus_featured():
    """Featured cites Big_Rapids,_Michigan#Notable_people.
    considered_sections returns all OTHER sections in that article."""
    capped_passages = [
        {
            "cite_id": "wiki/Big_Rapids,_Michigan#Notable_people",
            "text_markdown": "...",
            "rank": 1,
            "score": 1.5,
        }
    ]

    def bundle_lookup(archive_name: str, entry_path: str) -> Any:
        if entry_path == "Big_Rapids,_Michigan":
            return {
                "sections": [
                    {"id": "History", "title": "History"},
                    {"id": "Geography", "title": "Geography"},
                    {"id": "Notable_people", "title": "Notable people"},
                    {"id": "Demographics", "title": "Demographics"},
                ]
            }
        return None

    result = _build_considered_sections(capped_passages, bundle_lookup, max_n=10)
    ids = [s["section_id"] for s in result]
    assert "Notable_people" not in ids
    assert set(ids) == {"History", "Geography", "Demographics"}


def test_build_considered_sections_empty_when_featured_is_article_level():
    """Featured passage has no #section_id → no anchor → []."""
    capped_passages = [
        {
            "cite_id": "wiki/Big_Rapids,_Michigan",
            "text_markdown": "...",
            "rank": 1,
            "score": 1.0,
        }
    ]

    def bundle_lookup(archive_name: str, entry_path: str) -> Any:
        return {"sections": [{"id": "History", "title": "History"}]}

    result = _build_considered_sections(capped_passages, bundle_lookup, max_n=10)
    assert result == []


def test_build_considered_sections_empty_when_no_passages():
    """Zero-hit response → no featured article → []."""
    result = _build_considered_sections([], lambda a, e: None, max_n=10)
    assert result == []


def test_build_considered_sections_caps_at_max_n():
    """20-section article capped at max_n=10."""
    sections = [{"id": f"S{i}", "title": f"Section {i}"} for i in range(20)]
    capped_passages = [
        {
            "cite_id": "wiki/Foo#S0",
            "text_markdown": "...",
            "rank": 1,
            "score": 1.0,
        }
    ]

    def bundle_lookup(archive_name: str, entry_path: str) -> Any:
        return {"sections": sections}

    result = _build_considered_sections(capped_passages, bundle_lookup, max_n=10)
    assert len(result) == 10
    # S0 (featured) is excluded
    assert all(s["section_id"] != "S0" for s in result)


def test_build_considered_sections_handles_bundle_none():
    """Bundle lookup returns None → []."""
    capped_passages = [
        {
            "cite_id": "wiki/Foo#Section",
            "text_markdown": "...",
            "rank": 1,
            "score": 1.0,
        }
    ]

    def none_lookup(archive_name: str, entry_path: str) -> Any:
        return None

    result = _build_considered_sections(capped_passages, none_lookup, max_n=10)
    assert result == []


def test_build_considered_sections_handles_bundle_lookup_raising():
    """Bundle lookup raises → [] (no crash)."""
    capped_passages = [
        {
            "cite_id": "wiki/Foo#Section",
            "text_markdown": "...",
            "rank": 1,
            "score": 1.0,
        }
    ]

    def raising_lookup(archive_name: str, entry_path: str) -> Any:
        raise RuntimeError("bundle build failed")

    result = _build_considered_sections(capped_passages, raising_lookup, max_n=10)
    assert result == []
