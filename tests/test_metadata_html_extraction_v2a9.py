"""Tests for the v2.0.0a9 D4/Op2 fix: HTML-aware metadata extraction.

The v2.0.0a7 D11 fix capped metadata previews at 800 chars but every
Wikipedia ZIM metadata field is a full HTML document wrapping a bare
string. The cap clipped inside ~750 chars of identical
``<!DOCTYPE html><head><title>X</title>…`` boilerplate, so each value
looked the same to the caller and the actual field text never
surfaced. ``_extract_metadata_text`` distils HTML wrappers down to
the readable text before the cap applies.
"""

from __future__ import annotations

from openzim_mcp.zim.archive import _extract_metadata_text

WIKIPEDIA_TITLE_HTML = """<!DOCTYPE html>
<html lang="en"><head>
    <meta charset="UTF-8">
    <title>Title</title>
    <link rel="canonical" href="https://en.wikipedia.org/wiki/Title">
</head><body>
<h1>Wikipedia</h1>
<p>The Free Encyclopedia</p>
</body></html>"""


WIKIPEDIA_LANGUAGE_HTML = """<!DOCTYPE html>
<html><head><title>Language</title></head>
<body>en</body></html>"""


def test_plain_text_metadata_passes_through_unchanged():
    """Counter, Date, Tags etc. are bare strings — no HTML to extract."""
    assert _extract_metadata_text("2026-02-26") == "2026-02-26"
    assert _extract_metadata_text("wikipedia;wikipedia_en") == "wikipedia;wikipedia_en"
    assert _extract_metadata_text("") == ""


def test_wikipedia_title_html_returns_actual_field_value():
    """A Wikipedia-style HTML-wrapped metadata field surfaces the
    readable body text (the actual value) instead of the boilerplate
    head/title."""
    extracted = _extract_metadata_text(WIKIPEDIA_TITLE_HTML)
    # The actual "value" of this field on Wikipedia exports is the body
    # content (the archive name + tagline). The template <title> says
    # "Title" which is just a heading echo.
    assert "Wikipedia" in extracted
    # The <!DOCTYPE> / <head> / <link> noise must NOT appear.
    assert "<!DOCTYPE" not in extracted
    assert "canonical" not in extracted
    assert "<title>" not in extracted


def test_wikipedia_language_html_returns_bare_string():
    """When the body is a single short value like ``"en"``, the
    extractor returns just that value."""
    extracted = _extract_metadata_text(WIKIPEDIA_LANGUAGE_HTML)
    # Body contains "en" — the title is just the key echo, body is
    # the actual value.
    assert "en" in extracted
    assert "<" not in extracted


def test_extraction_collapses_whitespace_runs():
    """Multi-line HTML body content should be collapsed to single-line
    text so the preview cap isn't burnt on layout whitespace."""
    multi_line_html = (
        "<!DOCTYPE html><html><head><title>K</title></head><body>"
        "<p>line one</p>\n<p>   line two   </p>"
        "</body></html>"
    )
    extracted = _extract_metadata_text(multi_line_html)
    assert "\n" not in extracted
    assert "  " not in extracted
    assert "line one" in extracted and "line two" in extracted


def test_extraction_handles_malformed_html_gracefully():
    """Broken HTML doesn't crash — the extractor returns either the
    parsed text it could recover or the raw input."""
    malformed = "<html><body>unclosed paragraph"
    # Must not raise.
    result = _extract_metadata_text(malformed)
    assert "unclosed paragraph" in result or result == malformed


def test_non_html_string_starting_with_lt_passes_through():
    """A string starting with ``<`` but not actually HTML
    (e.g. ``"<n/a>"``) doesn't get parsed."""
    s = "<n/a>"
    assert _extract_metadata_text(s) == s


def test_realistic_huge_html_extracts_useful_value():
    """Simulate Wikipedia's actual M/Title shape: ~1 MB HTML wrapping
    a short value. The extractor recovers just the value."""
    # Synthetic ~100 KB of boilerplate around the actual value.
    boilerplate_class_soup = "vector-feature-x " * 1000
    raw = (
        '<!DOCTYPE html>\n<html class="' + boilerplate_class_soup + '" lang="en">'
        "<head>" + "<meta>" * 200 + "<title>Title</title>"
        "<link rel='canonical' href='https://en.wikipedia.org/wiki/Title'></head>"
        "<body><h1>Wikipedia</h1><p>The free encyclopedia</p></body></html>"
    )
    extracted = _extract_metadata_text(raw)
    # Must be radically smaller than the input.
    assert len(extracted) < len(raw) / 100
    # And carry the useful body text.
    assert "Wikipedia" in extracted
    assert "free encyclopedia" in extracted.lower()
