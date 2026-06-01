"""Tests for openzim_mcp.synthesize."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from openzim_mcp.config import SynthesizeConfig
from openzim_mcp.synthesize import _rrf_fuse
from openzim_mcp.tool_schemas import SynthesizePassage


@pytest.fixture
def cp() -> Any:
    """A content_processor mock that passes HTML through unchanged."""
    from unittest.mock import MagicMock

    mock_cp = MagicMock()
    mock_cp.html_to_plain_text.side_effect = lambda html: html
    return mock_cp


def _passage(cite_id: str, text: str, rank: int, score: float) -> SynthesizePassage:
    """Build a SynthesizePassage TypedDict for tests; keeps fixtures terse."""
    return cast(
        SynthesizePassage,
        {
            "cite_id": cite_id,
            "text_markdown": text,
            "rank": rank,
            "score": score,
        },
    )


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


def test_extract_passages_passes_through_plain_markdown() -> None:
    """search_top_k already returns plain-markdown snippets via create_snippet;
    _extract_passages must not double-render or otherwise mutate them."""
    from openzim_mcp.synthesize import _extract_passages

    hits = [
        {"path": "A/Berlin", "snippet": "Berlin is the capital.", "score": 0.9},
        {"path": "A/Munich", "snippet": "Munich is in Bavaria.", "score": 0.7},
    ]

    passages = _extract_passages(hits, archive_name="wikipedia_en_simple")
    assert len(passages) == 2
    assert passages[0]["rank"] == 1
    assert passages[0]["text_markdown"] == "Berlin is the capital."
    assert passages[0]["cite_id"] == "wikipedia_en_simple/A/Berlin"  # no #section yet
    assert passages[0]["score"] == pytest.approx(0.9)


def test_extract_passages_preserves_rank_order() -> None:
    from openzim_mcp.synthesize import _extract_passages

    hits = [
        {"path": f"A/Doc{i}", "snippet": f"doc {i}", "score": 1.0 - 0.1 * i}
        for i in range(5)
    ]
    passages = _extract_passages(hits, archive_name="test")
    assert [p["rank"] for p in passages] == [1, 2, 3, 4, 5]


def test_extract_passages_preserves_bold_highlight_markers() -> None:
    """Highlighted ``**term**`` markers from create_snippet must survive — the
    earlier code path round-tripped through BeautifulSoup + html2text and
    could strip or rewrite them."""
    from openzim_mcp.synthesize import _extract_passages

    hits = [
        {"path": "A/X", "snippet": "the **target** was found here", "score": 1.0},
    ]
    passages = _extract_passages(hits, archive_name="zim")
    assert passages[0]["text_markdown"] == "the **target** was found here"


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
    passages = [_passage("wiki/A/Berlin", "Geography text here.", 1, 0.9)]

    def bundle_lookup(archive_name: str, path: str) -> dict | None:
        return bundle if (archive_name == "wiki" and path == "A/Berlin") else None

    attributed = _attribute_sections(
        passages, bundle_lookup=bundle_lookup, hit_keys=[("wiki", "A/Berlin")]
    )
    assert attributed[0]["cite_id"] == "wiki/A/Berlin#geography"


def test_attribute_sections_drops_section_on_bundle_failure() -> None:
    """Bundle build fails → cite_id stays at entry level; passage not dropped."""
    from openzim_mcp.synthesize import _attribute_sections

    def bundle_lookup(archive_name: str, path: str) -> None:
        raise RuntimeError("simulated archive read failure")

    passages = [_passage("wiki/A/Berlin", "Anything", 1, 0.5)]
    attributed = _attribute_sections(
        passages, bundle_lookup=bundle_lookup, hit_keys=[("wiki", "A/Berlin")]
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

    def bundle_lookup(archive_name: str, path: str) -> dict:
        return bundle

    passages = [_passage("wiki/A/Berlin", "totally unrelated string", 1, 0.1)]
    attributed = _attribute_sections(
        passages, bundle_lookup=bundle_lookup, hit_keys=[("wiki", "A/Berlin")]
    )
    assert attributed[0]["cite_id"] == "wiki/A/Berlin"


def test_attribute_sections_picks_innermost_nested_section() -> None:
    """Nested ranges → cite_id uses the deepest (smallest) containing section.

    Audit fix: the prior implementation iterated forward in document
    order and broke on the first containment match, which always
    yielded the OUTERMOST (parent) section. A passage in an h3 inside
    an h2 inside an h1 would cite the h1 — far less useful than
    citing the h3.
    """
    from openzim_mcp.synthesize import _attribute_sections

    # Parent h1 (0..200) contains child h2 (40..150) contains grandchild
    # h3 (80..120). Passage offset will fall inside the grandchild.
    bundle = {
        "rendered_markdown": (
            "# Berlin\n"  # 0..8
            + " " * 30  # 9..38
            + "\n## Geography\n"  # 39..52
            + " " * 26  # 53..78
            + "\n### Climate\n"  # 79..91
            + "Rainfall here is high. " * 2  # 92..137
            + "\n## Demographics\n"  # 138..154
            + "Population data."  # 155..170
        ),
        "sections": [
            # Parent h1 — spans the whole article
            {
                "id": "berlin",
                "title": "Berlin",
                "level": 1,
                "char_start": 0,
                "char_end": 200,
                "parent_id": None,
            },
            # Child h2 — Geography subsection
            {
                "id": "geography",
                "title": "Geography",
                "level": 2,
                "char_start": 40,
                "char_end": 138,
                "parent_id": "berlin",
            },
            # Grandchild h3 — Climate sub-subsection (innermost)
            {
                "id": "climate",
                "title": "Climate",
                "level": 3,
                "char_start": 92,
                "char_end": 137,
                "parent_id": "geography",
            },
        ],
    }
    # The passage text appears at offset 92 — inside all three sections.
    passages = [_passage("wiki/A/Berlin", "Rainfall here is high.", 1, 0.9)]

    def bundle_lookup(archive_name: str, path: str) -> dict:
        return bundle

    attributed = _attribute_sections(
        passages, bundle_lookup=bundle_lookup, hit_keys=[("wiki", "A/Berlin")]
    )
    # The deepest (smallest-range) containing section is "climate".
    assert attributed[0]["cite_id"] == "wiki/A/Berlin#climate"


def test_attribute_sections_normalized_fallback_search() -> None:
    """When passage text doesn't byte-match the bundle markdown verbatim
    (whitespace/inline-markup drift between snippet path and bundle
    rendering path), section attribution falls back to a whitespace-
    normalized probe instead of silently degrading to entry-level.
    """
    from openzim_mcp.synthesize import _attribute_sections, _locate_passage

    md = "## Geography\n\nBerlin   sits  in  the   North   European   Plain."
    # passage_text has different whitespace shape — newlines and
    # collapsed runs that wouldn't match md.find() literally.
    passage_text = "Berlin sits in the North European Plain."
    pos = _locate_passage(md, passage_text)
    assert pos >= 0, f"normalized probe should locate the passage in md (got {pos})"

    bundle = {
        "rendered_markdown": md,
        "sections": [
            {
                "id": "geography",
                "title": "Geography",
                "level": 2,
                "char_start": 13,
                "char_end": len(md),
                "parent_id": None,
            },
        ],
    }
    passages = [_passage("wiki/A/Berlin", passage_text, 1, 0.9)]
    attributed = _attribute_sections(
        passages,
        bundle_lookup=lambda a, p: bundle,
        hit_keys=[("wiki", "A/Berlin")],
    )
    assert attributed[0]["cite_id"] == "wiki/A/Berlin#geography"


# ---------------------------------------------------------------------------
# Task 20: citation rendering, budget enforcement, citation building
# ---------------------------------------------------------------------------


def test_render_answer_joins_passages_with_citations() -> None:
    from openzim_mcp.synthesize import _render_answer

    passages = [
        _passage("wiki/A/Berlin#geography", "Berlin is mostly flat.", 1, 0.9),
        _passage("wiki/A/Berlin#climate", "Climate is humid continental.", 2, 0.7),
    ]
    md = _render_answer(passages)
    assert "Berlin is mostly flat." in md
    assert "[cite: wiki/A/Berlin#geography]" in md
    assert "Climate is humid continental." in md
    assert "[cite: wiki/A/Berlin#climate]" in md


def test_enforce_budget_truncates_last_passage() -> None:
    from openzim_mcp.synthesize import _enforce_budget

    passages = [
        _passage("x/y", "A" * 50, 1, 1.0),
        _passage("x/y", "B" * 50, 2, 0.9),
    ]
    capped = _enforce_budget(passages, char_budget=70)
    # First passage is 50 chars; budget allows 70. Second passage truncates to 20.
    # No whitespace in the body, so the word-boundary snap is a no-op here.
    assert len(capped) == 2
    assert len(capped[0]["text_markdown"]) == 50
    assert len(capped[1]["text_markdown"]) == 20


def test_enforce_budget_snaps_to_word_boundary() -> None:
    from openzim_mcp.synthesize import _enforce_budget

    # A 21-char budget lands mid-word: body[:21] is "Photosynthesis is a c"
    # (cutting into "class"). The snap backs up to the last space so the
    # passage ends on a whole word.
    passages = [_passage("x/y", "Photosynthesis is a class of process", 1, 1.0)]
    capped = _enforce_budget(passages, char_budget=21)
    text = capped[0]["text_markdown"]
    assert text == "Photosynthesis is a"
    assert len(text) <= 21


def test_enforce_budget_keeps_hard_cut_for_unbroken_token() -> None:
    from openzim_mcp.synthesize import _enforce_budget

    # A single token longer than the budget has no usable word boundary
    # (snapping would discard >half the budget) — keep the hard cut.
    passages = [_passage("x/y", "x" * 40, 1, 1.0)]
    capped = _enforce_budget(passages, char_budget=10)
    assert len(capped[0]["text_markdown"]) == 10


def test_build_citations_dedupes_by_entry() -> None:
    from openzim_mcp.synthesize import _build_citations

    passages = [
        _passage("wiki/A/Berlin#geography", "", 1, 0.9),
        _passage("wiki/A/Berlin#climate", "", 2, 0.7),
        _passage("wiki/A/Munich#geography", "", 3, 0.5),
    ]
    bundle_titles = {("wiki", "A/Berlin"): "Berlin", ("wiki", "A/Munich"): "Munich"}
    bundle_section_titles = {
        ("wiki", "A/Berlin", "geography"): "Geography",
        ("wiki", "A/Berlin", "climate"): "Climate",
        ("wiki", "A/Munich", "geography"): "Geography",
    }
    citations = _build_citations(
        passages,
        archive_titles=bundle_titles,
        section_titles=bundle_section_titles,
    )
    # 3 unique cite_ids → 3 citations
    assert len(citations) == 3
    cite_ids = [c["cite_id"] for c in citations]
    assert "wiki/A/Berlin#geography" in cite_ids
    berlin_geo = next(c for c in citations if c["cite_id"] == "wiki/A/Berlin#geography")
    assert berlin_geo["title"] == "Berlin"
    assert berlin_geo["section_title"] == "Geography"
    assert berlin_geo["section_id"] == "geography"
    assert berlin_geo["entry_path"] == "A/Berlin"
    assert berlin_geo["archive"] == "wiki"


# ---------------------------------------------------------------------------
# Task 21: end-to-end synthesize_query tests
# ---------------------------------------------------------------------------


def test_synthesize_query_zero_hits_returns_empty_with_reason(
    cp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import MagicMock

    from openzim_mcp.synthesize import synthesize_query

    archive = MagicMock()
    archive.basename = "test"
    cache = MagicMock()
    config = SynthesizeConfig()

    search_handler = MagicMock()
    search_handler.search_top_k.return_value = []  # zero hits

    response = synthesize_query(
        "no results query",
        archives=[(archive, Path("test.zim"))],
        search_handler=search_handler,
        cache=cache,
        content_processor=cp,
        config=config,
    )
    assert response["passages"] == []
    assert response["citations"] == []
    assert response["answer_markdown"] == ""
    assert response["_meta"].get("reason") == "0_hits"


def test_synthesize_query_single_archive_uses_xapian_score_fallback(
    cp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import MagicMock

    from openzim_mcp.synthesize import synthesize_query

    archive = MagicMock()
    cache = MagicMock()
    config = SynthesizeConfig()

    search_handler = MagicMock()
    search_handler.search_top_k.return_value = [
        {"path": "A/Berlin", "snippet": "<p>Berlin info</p>", "score": 0.9},
    ]

    monkey_bundle = {
        "entry_path": "A/Berlin",
        "title": "Berlin",
        "content_type": "text/html",
        "word_count": 1,
        "char_count": 100,
        "rendered_markdown": "Berlin info\n",
        "sections": [
            {
                "id": "berlin",
                "title": "Berlin",
                "level": 1,
                "char_start": 0,
                "char_end": 12,
                "parent_id": None,
            }
        ],
        "links": {"internal": [], "external": [], "media": []},
        "infobox": None,
    }

    monkeypatch.setattr(
        "openzim_mcp.bundle.get_or_build_bundle",
        lambda archive, path, **kwargs: monkey_bundle,
    )

    response = synthesize_query(
        "berlin",
        archives=[(archive, Path("test.zim"))],
        search_handler=search_handler,
        cache=cache,
        content_processor=cp,
        config=config,
    )
    assert response["fallback_used"] == "xapian_score"
    assert response["archives_searched"] == ["test"]


def test_synthesize_query_multi_archive_uses_rrf_fusion(
    cp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import MagicMock

    from openzim_mcp.synthesize import synthesize_query

    a1 = MagicMock()
    a2 = MagicMock()
    search_handler = MagicMock()
    search_handler.search_top_k.side_effect = [
        [{"path": "A/Berlin", "snippet": "", "score": 0.9}],
        [{"path": "A/Berlin", "snippet": "", "score": 0.5}],  # both archives have it
    ]
    cache = MagicMock()

    monkeypatch.setattr(
        "openzim_mcp.bundle.get_or_build_bundle",
        lambda archive, path, **kwargs: None,
    )

    response = synthesize_query(
        "berlin",
        archives=[(a1, Path("wiki1.zim")), (a2, Path("wiki2.zim"))],
        search_handler=search_handler,
        cache=cache,
        content_processor=cp,
        config=SynthesizeConfig(),
    )
    assert response["fallback_used"] == "rrf_fusion"
    assert sorted(response["archives_searched"]) == ["wiki1", "wiki2"]


def test_synthesize_response_meta_envelope_populated(
    cp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: ``_meta`` must carry tokens_est/chars/truncated, not be
    an empty dict (Phase C #5 review finding).
    """
    from unittest.mock import MagicMock

    from openzim_mcp.synthesize import synthesize_query

    archive = MagicMock()
    search_handler = MagicMock()
    search_handler.search_top_k.return_value = [
        {"path": "A/Berlin", "snippet": "Berlin body text", "score": 0.9},
    ]
    monkeypatch.setattr(
        "openzim_mcp.bundle.get_or_build_bundle",
        lambda archive, path, **kw: None,
    )
    response = synthesize_query(
        "berlin",
        archives=[(archive, Path("wiki.zim"))],
        search_handler=search_handler,
        cache=MagicMock(),
        content_processor=cp,
        config=SynthesizeConfig(),
    )
    meta = response["_meta"]
    assert "tokens_est" in meta and meta["tokens_est"] >= 0
    assert "chars" in meta and meta["chars"] >= 0
    assert "truncated" in meta


def test_select_top_hits_multi_credits_archive_with_best_rank() -> None:
    """When a path appears in multiple archives, attribute it to the
    archive that ranked it highest in its own list, not the first
    archive in ``archives_searched`` iteration order (Phase C #16).
    """
    from openzim_mcp.synthesize import _select_top_hits_multi

    # wiki1 ranks Berlin at index 1 (Munich first); wiki2 ranks Berlin at
    # index 0. The broken implementation always picked the first archive
    # in iteration order regardless of per-archive rank — i.e. wiki1 —
    # which would yield the wrong cite_id. The fixed implementation picks
    # the archive with the better (lower) rank, so Berlin must be
    # attributed to wiki2 here.
    per_archive_hits = [
        # wiki1: Berlin at rank 1 (Munich first)
        [
            {"path": "A/Munich", "snippet": "", "score": 0.95},
            {"path": "A/Berlin", "snippet": "", "score": 0.5},
        ],
        # wiki2: Berlin at rank 0 (top of this archive)
        [{"path": "A/Berlin", "snippet": "", "score": 0.95}],
    ]
    archives_searched = ["wiki1", "wiki2"]
    top_hits, fallback = _select_top_hits_multi(
        per_archive_hits, archives_searched, top_n=5
    )
    # Berlin is attributed to wiki2 (rank 0 there beats rank 1 in wiki1)
    berlin_archive = next(
        archive_name for archive_name, hit in top_hits if hit["path"] == "A/Berlin"
    )
    assert berlin_archive == "wiki2"
    assert fallback == "rrf_fusion"


# --------------------------------------------------------------------------
# Deferred defect: cross-archive relevance leakage
#
# RRF fuses per-archive rankings by RANK only (search_top_k fabricates
# score=1/rank; libzim exposes no BM25), so a secondary archive's rank-1 hit
# scores ~1/61 and can join top_n with no relevance bar. The internal lexical
# floor drops a SECONDARY-archive hit that shares no query token with its
# entry path, and caps how many a single secondary archive contributes — with
# no model and no install-footprint change. Primary-archive hits are never
# touched, and at least one hit is always kept.
# --------------------------------------------------------------------------


def test_synthesize_config_has_cross_archive_knobs() -> None:
    cfg = SynthesizeConfig()
    assert cfg.max_secondary_archive_hits >= 0
    assert cfg.cross_archive_min_overlap >= 1


def test_drop_cross_archive_leakage_drops_off_topic_secondary_hit() -> None:
    from openzim_mcp.synthesize import _drop_cross_archive_leakage

    # Primary archive (wiki) is credited the top hit; the secondary archive's
    # only hit shares no token with "french revolution" in its path.
    top_hits = [
        ("wiki", {"path": "A/French_Revolution", "snippet": "x", "score": 0.03}),
        (
            "blackadder",
            {
                "path": "A/Blackadder_Goes_Forth",
                "snippet": "revolution!",
                "score": 0.016,
            },
        ),
        ("wiki", {"path": "A/Reign_of_Terror", "snippet": "x", "score": 0.016}),
    ]
    kept = _drop_cross_archive_leakage(
        top_hits,
        query="french revolution",
        fallback_used="rrf_fusion",
        max_secondary_archive_hits=2,
        min_overlap=1,
    )
    paths = [hit["path"] for _, hit in kept]
    # Off-topic secondary hit (no query-token overlap in its path) is dropped,
    # even though its SNIPPET contains "revolution" — the floor keys on path.
    assert "A/Blackadder_Goes_Forth" not in paths
    # Primary-archive hits stay, incl. the differently-titled Reign_of_Terror.
    assert "A/French_Revolution" in paths
    assert "A/Reign_of_Terror" in paths


def test_drop_cross_archive_leakage_keeps_overlapping_secondary_hit() -> None:
    from openzim_mcp.synthesize import _drop_cross_archive_leakage

    top_hits = [
        ("wiki", {"path": "A/French_Revolution", "snippet": "", "score": 0.03}),
        (
            "histwiki",
            {"path": "A/French_Revolution_of_1848", "snippet": "", "score": 0.016},
        ),
    ]
    kept = _drop_cross_archive_leakage(
        top_hits,
        query="french revolution",
        fallback_used="rrf_fusion",
        max_secondary_archive_hits=2,
        min_overlap=1,
    )
    paths = [hit["path"] for _, hit in kept]
    assert "A/French_Revolution_of_1848" in paths  # shares french+revolution


def test_drop_cross_archive_leakage_caps_secondary_archive() -> None:
    from openzim_mcp.synthesize import _drop_cross_archive_leakage

    top_hits = [
        ("wiki", {"path": "A/French_Revolution", "snippet": "", "score": 0.03}),
        ("hist", {"path": "A/French_Revolution_Causes", "snippet": "", "score": 0.02}),
        (
            "hist",
            {"path": "A/French_Revolution_Timeline", "snippet": "", "score": 0.019},
        ),
        ("hist", {"path": "A/French_Revolution_People", "snippet": "", "score": 0.018}),
    ]
    kept = _drop_cross_archive_leakage(
        top_hits,
        query="french revolution",
        fallback_used="rrf_fusion",
        max_secondary_archive_hits=2,
        min_overlap=1,
    )
    hist_kept = [hit["path"] for archive, hit in kept if archive == "hist"]
    assert len(hist_kept) == 2  # capped even though all three overlap


def test_drop_cross_archive_leakage_noop_for_single_archive() -> None:
    from openzim_mcp.synthesize import _drop_cross_archive_leakage

    top_hits = [("wiki", {"path": "A/Cats", "snippet": "", "score": 1.0})]
    # Single-archive (xapian_score) path is never gated.
    assert (
        _drop_cross_archive_leakage(
            top_hits,
            query="dogs",
            fallback_used="xapian_score",
            max_secondary_archive_hits=0,
            min_overlap=1,
        )
        == top_hits
    )


def test_synthesize_drops_off_topic_cross_archive_leak(
    cp: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import MagicMock

    from openzim_mcp.synthesize import synthesize_query

    wiki = MagicMock()
    blackadder = MagicMock()
    search_handler = MagicMock()
    search_handler.search_top_k.side_effect = [
        [
            {
                "path": "A/French_Revolution",
                "snippet": "The French Revolution was a period of upheaval.",
                "score": 0.9,
            }
        ],
        [
            {
                "path": "A/Blackadder_Goes_Forth",
                "snippet": "Baldrick has a cunning plan",
                "score": 0.5,
            }
        ],
    ]
    monkeypatch.setattr(
        "openzim_mcp.bundle.get_or_build_bundle",
        lambda archive, path, **kw: None,
    )
    response = synthesize_query(
        "french revolution",
        archives=[(wiki, Path("wiki.zim")), (blackadder, Path("blackadder.zim"))],
        search_handler=search_handler,
        cache=MagicMock(),
        content_processor=cp,
        config=SynthesizeConfig(),
    )
    assert response["fallback_used"] == "rrf_fusion"
    # The off-topic secondary-archive hit is filtered out entirely.
    assert "Blackadder" not in str(response)
    assert "Baldrick" not in str(response)
    # The on-topic primary hit survives.
    assert "French Revolution" in response["answer_markdown"]
