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


def test_truncation_at_leading_highlight_does_not_collapse_to_ellipsis():
    """Regression: when the post-highlight slice begins with ``**`` and
    contains exactly one ``**`` marker (truncated mid-bold at position 0),
    the prior fix-up logic dropped the entire content via ``sliced[:0]``,
    leaving the caller with a content-free ``"..."``. The snippet must
    retain the term text (less the orphan ``**`` marker) so the caller
    still gets usable content.
    """
    # Setup: snippet_length=10, content begins with the matched term so
    # the term is preserved through the first truncation (no word boundary
    # split), highlighting adds 4 chars of ``**`` markers pushing length
    # over the cap, and the second truncation lands inside the closing
    # ``**`` of the leading highlight — leaving an orphan ``**`` at
    # position 0.
    processor = ContentProcessor(snippet_length=10)
    snippet = processor.create_snippet("Photo is the great article", query="Photo")
    # The bug produced exactly the string ``"..."``. The fix keeps the
    # term text so the result has more than just an ellipsis.
    assert snippet != "...", (
        f"Snippet collapsed to bare ellipsis; expected term text. " f"Got: {snippet!r}"
    )
    # Inferred contract: the matched term ``Photo`` should appear in the
    # result. The orphan ``**`` is dropped so the visible text is "Photo...".
    assert "Photo" in snippet
