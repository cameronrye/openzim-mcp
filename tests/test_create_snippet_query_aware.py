"""Tests for query-aware create_snippet (Phase A item #1)."""

import pytest

from openzim_mcp.content_processor import ContentProcessor


@pytest.fixture
def processor() -> ContentProcessor:
    return ContentProcessor(snippet_length=400)


SAMPLE = (
    "Photosynthesis is a biological process used by plants.\n\n"
    "It converts light energy into chemical energy.\n\n"
    "Chlorophyll, the green pigment in leaves, absorbs sunlight.\n\n"
    "The process requires water and carbon dioxide as inputs."
)


def test_query_match_selects_matching_paragraph(processor):
    snippet = processor.create_snippet(SAMPLE, query="chlorophyll")
    # Matched paragraph (3rd) should be present
    assert "Chlorophyll" in snippet
    # First paragraph should NOT lead the snippet (we jumped to the match)
    assert not snippet.startswith("Photosynthesis is")


def test_query_no_match_falls_back_to_lead(processor):
    snippet = processor.create_snippet(SAMPLE, query="quantum")
    assert snippet.startswith("Photosynthesis is")


def test_query_highlights_match(processor):
    snippet = processor.create_snippet(SAMPLE, query="chlorophyll")
    assert "**Chlorophyll**" in snippet or "**chlorophyll**" in snippet


def test_query_highlight_capped_at_five(processor):
    dense = "alpha alpha alpha alpha alpha alpha alpha alpha"
    snippet = processor.create_snippet(dense, query="alpha")
    assert snippet.count("**alpha**") <= 5


def test_query_aware_respects_snippet_length(processor):
    long = "Para about chlorophyll and biology. " * 200
    snippet = processor.create_snippet(long, query="chlorophyll")
    assert len(snippet) <= 400


def test_no_query_preserves_legacy_behavior(processor):
    snippet = processor.create_snippet(SAMPLE)
    assert snippet.startswith("Photosynthesis is")
