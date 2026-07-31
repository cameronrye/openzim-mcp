r"""Truncation-message clarity tests.

The prior message read ``... only showing first N characters ...`` where
``N`` referred to body chars, but readers couldn't tell because the
surrounding response wrapper (``# Title\nPath:...\nType:...``) was also
counted in their visual estimate. The message must reference 'body
content' explicitly.
"""

from openzim_mcp.content_processor import ContentProcessor


def test_message_specifies_body_content():
    """The truncation tail must say 'body content' to disambiguate."""
    cp = ContentProcessor(snippet_length=100)
    body = "x" * 5000
    out = cp.truncate_content(body, max_length=120)
    # The message must say "of body content" (or similar) so a caller looking
    # at the visible response can tell that 120 refers to body, not wrapper.
    assert "body content" in out, out


def test_total_reported_is_full_body_length():
    """The reported total must match the unsliced body length."""
    cp = ContentProcessor(snippet_length=100)
    body = "x" * 5000
    out = cp.truncate_content(body, max_length=200)
    assert "total of 5,000" in out


def test_short_body_returned_unmodified():
    """Body shorter than max_length must round-trip with no message."""
    cp = ContentProcessor(snippet_length=100)
    body = "short body"
    out = cp.truncate_content(body, max_length=1000)
    assert out == body


def test_content_offset_hint_is_a_valid_int_literal():
    """The ``content_offset`` hint is copied straight back into a typed
    parameter, so it must NOT carry a thousands separator: ``100,000`` is
    rejected by pydantic (``TypeAdapter(int).validate_python("100,000")``
    raises) and the same response already reports the raw int in ``_meta``.

    The human-readable counts in the same sentence keep their separators.
    """
    import re

    cp = ContentProcessor(snippet_length=100)
    body = "x" * 300_000
    out = cp.truncate_content(body, max_length=100_000, current_offset=0)

    match = re.search(r"content_offset=([^`]+)`", out)
    assert match is not None, out
    assert int(match.group(1)) == 100_000
    # The prose counts are still grouped for readability.
    assert "total of 300,000 characters" in out
