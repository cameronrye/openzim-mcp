"""Tests for the v2.0.0a9 D3 fix: synthesize promotes a canonical
title-index hit past BM25 noise.

Live a8 testing surfaced that ``tell me about Berlin`` (synthesize=True)
returned ``List_of_songs_about_Berlin``, ``Berlin_(disambiguation)``,
``Timeline_of_Berlin``, etc. — none of them the canonical ``Berlin``
article — because BM25 ranks longer titles with the topic word higher
than the bare topic. The non-synthesize path already promoted
title-index 1.0 hits (D6/Op7); D3 extends the same logic to synthesize.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from openzim_mcp.config import SynthesizeConfig
from openzim_mcp.synthesize import _promote_title_match, synthesize_query


def _cp() -> Any:
    """A content_processor mock that passes HTML through unchanged."""
    mock = MagicMock()
    mock.html_to_plain_text.side_effect = lambda html: html
    return mock


def test_promote_title_match_promotes_canonical_over_derivative():
    """Unit-level: ``_promote_title_match`` prepends the title-index hit
    when the top BM25 result isn't a strong title match for the query.
    """
    bm25_top_hits = [
        (
            "wiki",
            {"path": "List_of_songs_about_Berlin", "snippet": "...", "score": 0.5},
        ),
        ("wiki", {"path": "Berlin_(disambiguation)", "snippet": "...", "score": 0.3}),
    ]
    search_handler = MagicMock()
    # Title-index resolves "Berlin" to the canonical entry.
    search_handler.title_match_hit.return_value = {
        "path": "Berlin",
        "snippet": "Berlin is the capital...",
        "score": 1.0,
    }
    archive = MagicMock()

    promoted = _promote_title_match(
        bm25_top_hits,
        query="Berlin",
        archives=[(archive, Path("/fake/wiki.zim"))],
        archives_searched=["wiki"],
        search_handler=search_handler,
    )
    assert len(promoted) == 3
    assert promoted[0][1]["path"] == "Berlin"
    # The derivative BM25 hits are preserved at lower ranks.
    paths = [h["path"] for _, h in promoted]
    assert "List_of_songs_about_Berlin" in paths
    assert "Berlin_(disambiguation)" in paths


def test_promote_title_match_no_op_when_top_hit_already_canonical():
    """When the top BM25 hit IS a strong title match, the title-index
    fast path isn't consulted — preserves common-case latency."""
    bm25_top_hits = [
        ("wiki", {"path": "Berlin", "snippet": "Berlin is...", "score": 0.9}),
        ("wiki", {"path": "Berlin_Wall", "snippet": "...", "score": 0.7}),
    ]
    search_handler = MagicMock()
    archive = MagicMock()

    promoted = _promote_title_match(
        bm25_top_hits,
        query="Berlin",
        archives=[(archive, Path("/fake/wiki.zim"))],
        archives_searched=["wiki"],
        search_handler=search_handler,
    )
    assert promoted == bm25_top_hits
    # The title-index probe must NOT have been called when the top hit
    # already strong-matches.
    assert search_handler.title_match_hit.call_count == 0


def test_promote_title_match_reorders_when_canonical_is_lower_ranked():
    """If the canonical entry exists in the BM25 hits but at a lower
    rank, promote it without duplicating. The original top hits stay
    in the list — just reordered.
    """
    bm25_top_hits = [
        (
            "wiki",
            {"path": "List_of_songs_about_Berlin", "snippet": "...", "score": 0.5},
        ),
        ("wiki", {"path": "Berlin", "snippet": "Berlin is...", "score": 0.4}),
        ("wiki", {"path": "Berlin_Wall", "snippet": "...", "score": 0.3}),
    ]
    search_handler = MagicMock()
    search_handler.title_match_hit.return_value = {
        "path": "Berlin",
        "snippet": "Berlin is the capital...",
        "score": 1.0,
    }
    archive = MagicMock()

    promoted = _promote_title_match(
        bm25_top_hits,
        query="Berlin",
        archives=[(archive, Path("/fake/wiki.zim"))],
        archives_searched=["wiki"],
        search_handler=search_handler,
    )
    # No duplication.
    paths = [h["path"] for _, h in promoted]
    assert paths.count("Berlin") == 1
    # Berlin is now first.
    assert promoted[0][1]["path"] == "Berlin"
    # Other hits are preserved.
    assert "List_of_songs_about_Berlin" in paths
    assert "Berlin_Wall" in paths


def test_promote_title_match_empty_hits_finds_canonical_anyway():
    """Even with empty BM25 hits, a title-index probe may find a hit —
    surfaces the canonical article when full-text indexing missed it."""
    search_handler = MagicMock()
    search_handler.title_match_hit.return_value = {
        "path": "Berlin",
        "snippet": "Berlin is the capital...",
        "score": 1.0,
    }
    archive = MagicMock()

    promoted = _promote_title_match(
        [],
        query="Berlin",
        archives=[(archive, Path("/fake/wiki.zim"))],
        archives_searched=["wiki"],
        search_handler=search_handler,
    )
    assert len(promoted) == 1
    assert promoted[0][1]["path"] == "Berlin"


def test_synthesize_end_to_end_promotes_berlin(monkeypatch):
    """End-to-end: synthesize_query for ``Berlin`` against an archive
    whose BM25 returns derivatives but whose title-index resolves to
    ``Berlin`` directly — the rendered answer leads with the canonical
    entry.
    """
    archive = MagicMock()
    cache = MagicMock()
    config = SynthesizeConfig()

    search_handler = MagicMock()
    # BM25 returns derivative articles.
    search_handler.search_top_k.return_value = [
        {
            "path": "List_of_songs_about_Berlin",
            "snippet": "...songs...",
            "score": 0.9,
        },
        {"path": "Berlin_(disambiguation)", "snippet": "...disamb...", "score": 0.7},
    ]
    # Title index resolves "Berlin" → canonical Berlin entry.
    search_handler.title_match_hit.return_value = {
        "path": "Berlin",
        "snippet": "**Berlin** is the capital of Germany.",
        "score": 1.0,
    }

    bundle = {
        "entry_path": "Berlin",
        "title": "Berlin",
        "content_type": "text/html",
        "word_count": 5,
        "char_count": 40,
        "rendered_markdown": "Berlin is the capital of Germany.\n",
        "sections": [
            {
                "id": "berlin",
                "title": "Berlin",
                "level": 1,
                "char_start": 0,
                "char_end": 40,
                "parent_id": None,
            }
        ],
        "links": {"internal": [], "external": [], "media": []},
        "infobox": None,
    }
    monkeypatch.setattr(
        "openzim_mcp.synthesize.get_or_build_bundle",
        lambda archive, path, **kwargs: bundle if path == "Berlin" else None,
    )

    response = synthesize_query(
        "Berlin",
        archives=[(archive, Path("/fake/wiki.zim"))],
        search_handler=search_handler,
        cache=cache,
        content_processor=_cp(),
        config=config,
    )
    # The first citation must be Berlin (the canonical), not the BM25 top hit.
    assert response["citations"][0]["entry_path"] == "Berlin"
    # The answer body should be derived from Berlin, not from songs/disamb.
    assert "capital of Germany" in response["answer_markdown"]
    # And the answer should lead with the Berlin passage (not the
    # derivative). The first citation marker is the Berlin entry.
    first_cite_marker = (
        response["answer_markdown"].split("[cite:", 1)[1].split("]", 1)[0]
    )
    assert "/Berlin" in first_cite_marker and "List_of_songs" not in first_cite_marker


# ---------------------------------------------------------------------------
# D6: search-mode title-index splice
# ---------------------------------------------------------------------------


def test_search_compact_splices_title_match_into_first_page():
    """D6: in compact mode, ``search for Einstein`` splices the canonical
    ``Albert_Einstein`` entry past BM25-buried-by-derivatives ranking.
    """
    from openzim_mcp.simple_tools import SimpleToolsHandler

    handler = SimpleToolsHandler.__new__(SimpleToolsHandler)
    handler.zim_operations = MagicMock()

    # BM25 returns derivatives first.
    bm25_payload = {
        "query": "Einstein",
        "results": [
            {
                "path": "List_of_things_named_after_Albert_Einstein",
                "title": "List of things named after Albert Einstein",
                "snippet": "...",
            },
            {"path": "Evelyn_Einstein", "title": "Evelyn Einstein", "snippet": "..."},
        ],
        "total": 19843,
        "page_info": {"offset": 0, "limit": 5, "returned_count": 2},
        "_meta": {},
    }
    # Title-index resolves "Einstein" → Albert_Einstein (score 1.0).
    title_data = {
        "results": [
            {
                "path": "Albert_Einstein",
                "title": "Albert Einstein",
                "score": 1.0,
                "zim_file": "/fake/wiki.zim",
            }
        ]
    }
    handler.zim_operations.find_entry_by_title_data.return_value = title_data

    spliced = handler._splice_title_match_into_search(
        bm25_payload, "/fake/wiki.zim", "Einstein"
    )
    paths = [r["path"] for r in spliced["results"]]
    # Canonical is now first.
    assert paths[0] == "Albert_Einstein"
    # The original BM25 hits are still present.
    assert "List_of_things_named_after_Albert_Einstein" in paths
    assert "Evelyn_Einstein" in paths


def test_search_compact_no_splice_when_top_hit_strong_match():
    """No promotion when the BM25 top hit already strong-matches."""
    from openzim_mcp.simple_tools import SimpleToolsHandler

    handler = SimpleToolsHandler.__new__(SimpleToolsHandler)
    handler.zim_operations = MagicMock()
    bm25_payload = {
        "query": "Photosynthesis",
        "results": [
            {"path": "Photosynthesis", "title": "Photosynthesis", "snippet": "..."},
        ],
        "total": 1,
        "page_info": {"offset": 0, "limit": 5, "returned_count": 1},
        "_meta": {},
    }
    spliced = handler._splice_title_match_into_search(
        bm25_payload, "/fake/wiki.zim", "Photosynthesis"
    )
    # find_entry_by_title_data should not be invoked when the top hit
    # is already a strong title match.
    handler.zim_operations.find_entry_by_title_data.assert_not_called()
    # And results are unchanged.
    assert spliced["results"][0]["path"] == "Photosynthesis"
    assert len(spliced["results"]) == 1


def test_search_compact_no_splice_when_title_match_already_present():
    """When the canonical entry is already in results (at any rank),
    it gets reordered to first — never duplicated."""
    from openzim_mcp.simple_tools import SimpleToolsHandler

    handler = SimpleToolsHandler.__new__(SimpleToolsHandler)
    handler.zim_operations = MagicMock()
    bm25_payload = {
        "query": "Berlin",
        "results": [
            {
                "path": "List_of_songs_about_Berlin",
                "title": "List of songs about Berlin",
                "snippet": "...",
            },
            {"path": "Berlin", "title": "Berlin", "snippet": "..."},
        ],
        "total": 5000,
        "page_info": {"offset": 0, "limit": 5, "returned_count": 2},
        "_meta": {},
    }
    handler.zim_operations.find_entry_by_title_data.return_value = {
        "results": [{"path": "Berlin", "title": "Berlin", "score": 1.0}]
    }
    spliced = handler._splice_title_match_into_search(
        bm25_payload, "/fake/wiki.zim", "Berlin"
    )
    paths = [r["path"] for r in spliced["results"]]
    # No duplication, Berlin first.
    assert paths == ["Berlin", "List_of_songs_about_Berlin"]
