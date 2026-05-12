"""Tests for the v2.0.0a9 D7 + D8 + Op4 synthesize wire-shape cleanup.

D7: drop the contradictory ``more_at_offset`` field from the meta
envelope on synthesize responses — synthesize isn't resumable by
content offset, so emitting the field (with a value that mixed
``len(answer_md)`` against a ``total_chars`` measuring passage chars)
just confused callers.

D8 / Op4: in compact mode, the ``passages[]`` array was structurally
redundant after the text-dedup pass — it carried only cite_id, rank,
score, all of which could come from ``citations[]``. Compact mode now
drops the array entirely and folds rank/score into the citation row
itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from openzim_mcp.config import SynthesizeConfig
from openzim_mcp.synthesize import synthesize_query


def _cp() -> Any:
    mock = MagicMock()
    mock.html_to_plain_text.side_effect = lambda html: html
    return mock


def _wire_two_hits(monkeypatch):
    """Wire a 2-hit synthesize that will trigger truncation against a
    deliberately-tiny budget."""
    archive = MagicMock()
    cache = MagicMock()

    search_handler = MagicMock()
    # Two large passages so the budget bites at 500-char cap.
    search_handler.search_top_k.return_value = [
        {"path": "A/Doc1", "snippet": "X" * 800, "score": 0.9},
        {"path": "A/Doc2", "snippet": "Y" * 800, "score": 0.8},
    ]
    # No title-index hit needed.
    search_handler.title_match_hit.return_value = None

    bundle = {
        "entry_path": "A/Doc1",
        "title": "Doc1",
        "content_type": "text/html",
        "word_count": 100,
        "char_count": 500,
        "rendered_markdown": "X" * 500,
        "sections": [
            {
                "id": "doc1",
                "title": "Doc1",
                "level": 1,
                "char_start": 0,
                "char_end": 500,
                "parent_id": None,
            }
        ],
        "links": {"internal": [], "external": [], "media": []},
        "infobox": None,
    }
    monkeypatch.setattr(
        "openzim_mcp.bundle.get_or_build_bundle",
        lambda archive, path, **kwargs: bundle,
    )
    return archive, cache, search_handler


def test_synthesize_meta_omits_more_at_offset(monkeypatch):
    """D7: even when truncated, the synthesize meta MUST NOT carry
    ``more_at_offset`` — synthesize isn't paginable by content offset."""
    archive, cache, search_handler = _wire_two_hits(monkeypatch)
    config = SynthesizeConfig(output_char_budget=500)

    response = synthesize_query(
        "x",
        archives=[(archive, Path("test.zim"))],
        search_handler=search_handler,
        cache=cache,
        content_processor=_cp(),
        config=config,
    )
    meta = response["_meta"]
    assert meta.get("truncated") is True
    # The whole point of D7: this field MUST NOT appear in synthesize
    # responses, even when truncated.
    assert "more_at_offset" not in meta


def test_synthesize_compact_drops_passages_array(monkeypatch):
    """D8: compact-mode synthesize emits ``passages = []`` because
    every field on a compact passage (cite_id, rank, score) already
    appears on its citation row."""
    archive, cache, search_handler = _wire_two_hits(monkeypatch)
    config = SynthesizeConfig()

    response = synthesize_query(
        "x",
        archives=[(archive, Path("test.zim"))],
        search_handler=search_handler,
        cache=cache,
        content_processor=_cp(),
        config=config,
        omit_passage_text=True,
    )
    # The passages array is dropped entirely in compact mode.
    assert response["passages"] == []
    # citations[] carries the rank/score that USED to live on passages.
    assert response["citations"], "expected at least one citation"
    for citation in response["citations"]:
        assert "rank" in citation
        assert "score" in citation
        assert isinstance(citation["rank"], int)
        assert isinstance(citation["score"], float)


def test_synthesize_verbose_keeps_passages_array(monkeypatch):
    """Verbose mode (omit_passage_text=False) preserves the legacy
    passages array shape unchanged."""
    archive, cache, search_handler = _wire_two_hits(monkeypatch)
    config = SynthesizeConfig()

    response = synthesize_query(
        "x",
        archives=[(archive, Path("test.zim"))],
        search_handler=search_handler,
        cache=cache,
        content_processor=_cp(),
        config=config,
        omit_passage_text=False,
    )
    assert response["passages"], "verbose mode must keep passages[]"
    # Verbose citations DON'T carry rank/score — they live on passages.
    for citation in response["citations"]:
        assert "rank" not in citation
        assert "score" not in citation
