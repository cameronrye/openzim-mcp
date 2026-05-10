"""Tests for openzim_mcp.synthesize."""

from __future__ import annotations

from typing import cast

import pytest

from openzim_mcp.synthesize import _rrf_fuse
from openzim_mcp.tool_schemas import SynthesizePassage


def test_rrf_fuse_single_ranking_preserves_order() -> None:
    """One ranking → output is the same order, with k-decayed scores."""
    rankings = [
        [("A/Doc1", 0.9), ("A/Doc2", 0.7), ("A/Doc3", 0.5)],
    ]
    fused = _rrf_fuse(rankings, k=60)
    paths = [p for p, _ in fused]
    assert paths == ["A/Doc1", "A/Doc2", "A/Doc3"]


def test_rrf_fuse_two_rankings_unifies() -> None:
    """Doc that appears high in both rankings beats one that appears in just one."""
    rankings = [
        [("A/Doc1", 0.9), ("A/Doc2", 0.7), ("A/Doc3", 0.5)],
        [("A/Doc1", 0.8), ("A/Doc4", 0.6), ("A/Doc2", 0.4)],
    ]
    fused = _rrf_fuse(rankings, k=60)
    paths = [p for p, _ in fused]
    # Doc1 appears at rank 1 in both → highest fused score.
    assert paths[0] == "A/Doc1"
    # Doc2 appears at ranks 2 + 3 → next.
    assert paths[1] == "A/Doc2"


def test_rrf_fuse_empty_rankings_returns_empty() -> None:
    assert _rrf_fuse([], k=60) == []


def test_rrf_fuse_score_formula() -> None:
    """Score(d) = sum over rankings of 1/(k + rank(d))."""
    rankings = [
        [("A/Doc1", 0.9)],  # rank 1 in this ranking
        [("A/Doc1", 0.5)],  # rank 1 in this ranking too
    ]
    fused = _rrf_fuse(rankings, k=60)
    expected = 1.0 / (60 + 1) + 1.0 / (60 + 1)
    assert fused[0][1] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Task 17: per-archive search stage
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock  # noqa: E402


def test_per_archive_search_single_archive() -> None:
    """Single archive → list[(entry_path, snippet, score)] from Xapian."""
    from openzim_mcp.synthesize import _per_archive_search

    archive = MagicMock()
    archive.basename = "wikipedia_en_simple"

    search_handler = MagicMock()
    search_handler.search_top_k.return_value = [
        {"path": "A/Berlin", "snippet": "...", "score": 0.9},
        {"path": "A/Munich", "snippet": "...", "score": 0.7},
    ]

    results = _per_archive_search(
        archive,
        search_handler=search_handler,
        query="german cities",
        k=5,
    )
    assert len(results) == 2
    assert results[0]["path"] == "A/Berlin"


# ---------------------------------------------------------------------------
# Task 18: passage extraction stage
# ---------------------------------------------------------------------------


def test_extract_passages_renders_markdown_from_snippets() -> None:
    """libzim snippets may come back as HTML; passages contain markdown."""
    from openzim_mcp.synthesize import _extract_passages

    hits = [
        {"path": "A/Berlin", "snippet": "<p>Berlin is the capital.</p>", "score": 0.9},
        {"path": "A/Munich", "snippet": "<p>Munich is in Bavaria.</p>", "score": 0.7},
    ]
    cp = MagicMock()
    cp.html_to_plain_text.side_effect = lambda html: html.replace("<p>", "").replace(
        "</p>", ""
    )

    passages = _extract_passages(
        hits, archive_name="wikipedia_en_simple", content_processor=cp
    )
    assert len(passages) == 2
    assert passages[0]["rank"] == 1
    assert passages[0]["text_markdown"] == "Berlin is the capital."
    assert passages[0]["cite_id"] == "wikipedia_en_simple/A/Berlin"  # no #section yet
    assert passages[0]["score"] == 0.9


def test_extract_passages_preserves_rank_order() -> None:
    from openzim_mcp.synthesize import _extract_passages

    hits = [
        {"path": f"A/Doc{i}", "snippet": f"<p>doc {i}</p>", "score": 1.0 - 0.1 * i}
        for i in range(5)
    ]
    cp = MagicMock()
    cp.html_to_plain_text.side_effect = lambda html: html
    passages = _extract_passages(hits, archive_name="test", content_processor=cp)
    assert [p["rank"] for p in passages] == [1, 2, 3, 4, 5]


def test_synthesize_query_signature_exists() -> None:
    """synthesize_query is callable; signature stable from this task on."""
    import inspect

    from openzim_mcp.synthesize import synthesize_query

    sig = inspect.signature(synthesize_query)
    assert {"query", "archives", "cache", "content_processor", "config"} <= set(
        sig.parameters
    )


# ---------------------------------------------------------------------------
# Task 19: section attribution stage
# ---------------------------------------------------------------------------


def test_attribute_sections_adds_section_id_when_match_in_first_section() -> None:
    """Passage text found in section 0 → cite_id gets #<section_id>."""
    from openzim_mcp.synthesize import _attribute_sections

    bundle = {
        "rendered_markdown": "# Berlin\n\nIntro paragraph.\n\n## Geography\n\nGeography text here.\n",
        "sections": [
            {
                "id": "berlin",
                "title": "Berlin",
                "level": 1,
                "char_start": 0,
                "char_end": 38,
                "parent_id": None,
            },
            {
                "id": "geography",
                "title": "Geography",
                "level": 2,
                "char_start": 38,
                "char_end": 75,
                "parent_id": "berlin",
            },
        ],
    }
    passages = [
        cast(
            SynthesizePassage,
            {
                "cite_id": "wiki/A/Berlin",
                "text_markdown": "Geography text here.",
                "rank": 1,
                "score": 0.9,
            },
        ),
    ]
    bundle_lookup = lambda path: bundle if path == "A/Berlin" else None

    attributed = _attribute_sections(
        passages, bundle_lookup=bundle_lookup, hit_paths=["A/Berlin"]
    )
    assert attributed[0]["cite_id"] == "wiki/A/Berlin#geography"


def test_attribute_sections_drops_section_on_bundle_failure() -> None:
    """Bundle build fails → cite_id stays at entry level; passage not dropped."""
    from openzim_mcp.synthesize import _attribute_sections

    def bundle_lookup(path: str) -> None:
        raise RuntimeError("simulated archive read failure")

    passages = [
        cast(
            SynthesizePassage,
            {
                "cite_id": "wiki/A/Berlin",
                "text_markdown": "Anything",
                "rank": 1,
                "score": 0.5,
            },
        ),
    ]
    attributed = _attribute_sections(
        passages, bundle_lookup=bundle_lookup, hit_paths=["A/Berlin"]
    )
    assert len(attributed) == 1
    assert attributed[0]["cite_id"] == "wiki/A/Berlin"  # unchanged


def test_attribute_sections_no_match_keeps_entry_level() -> None:
    """Passage text not located in any section → cite_id stays at entry level."""
    from openzim_mcp.synthesize import _attribute_sections

    bundle = {
        "rendered_markdown": "Whole article body here.",
        "sections": [
            {
                "id": "intro",
                "title": "Intro",
                "level": 1,
                "char_start": 0,
                "char_end": 24,
                "parent_id": None,
            },
        ],
    }
    bundle_lookup = lambda path: bundle
    passages = [
        cast(
            SynthesizePassage,
            {
                "cite_id": "wiki/A/Berlin",
                "text_markdown": "totally unrelated string",
                "rank": 1,
                "score": 0.1,
            },
        ),
    ]
    attributed = _attribute_sections(
        passages, bundle_lookup=bundle_lookup, hit_paths=["A/Berlin"]
    )
    assert attributed[0]["cite_id"] == "wiki/A/Berlin"
