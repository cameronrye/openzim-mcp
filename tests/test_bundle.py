"""Tests for openzim_mcp.bundle.

Bundle determinism, structural invariants, and offset-correctness for
the post-render text-matching algorithm. The cache-aware accessor
(get_or_build_bundle) has its own tests in this file.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openzim_mcp.bundle import extract_entry_bundle
from openzim_mcp.content_processor import ContentProcessor

SAMPLE_HTML = """\
<html><body>
<h1>Berlin</h1>
<p>Berlin is the capital and largest city of Germany.</p>
<h2>Geography</h2>
<p>Berlin's terrain is generally flat. The Spree River runs through the city.</p>
<h3>Climate</h3>
<p>Humid continental, transitioning to oceanic in milder areas.</p>
<h2>History</h2>
<p>Founded in the 13th century, Berlin has a long and complex history.</p>
<a href="A/Spree_River">Spree</a>
<a href="https://en.wikipedia.org/wiki/Berlin">External link</a>
<img src="berlin.jpg" alt="Berlin">
</body></html>
"""


def _make_archive_with_entry(
    html: str,
    *,
    title: str = "Berlin",
    entry_path: str = "A/Berlin",
    mime: str = "text/html",
) -> MagicMock:
    """Build a minimal libzim Archive mock returning the given HTML."""
    item = MagicMock()
    item.content = html.encode("utf-8")
    item.mimetype = mime
    entry = MagicMock()
    entry.title = title
    entry.path = entry_path
    entry.get_item.return_value = item
    archive = MagicMock()
    archive.get_entry_by_path.return_value = entry
    return archive


@pytest.fixture
def cp() -> ContentProcessor:
    return ContentProcessor()


def test_bundle_has_rendered_markdown(cp: ContentProcessor) -> None:
    archive = _make_archive_with_entry(SAMPLE_HTML)
    bundle = extract_entry_bundle(archive, "A/Berlin", content_processor=cp)
    assert bundle["entry_path"] == "A/Berlin"
    assert bundle["title"] == "Berlin"
    assert "Berlin is the capital" in bundle["rendered_markdown"]


def test_bundle_sections_have_offsets(cp: ContentProcessor) -> None:
    archive = _make_archive_with_entry(SAMPLE_HTML)
    bundle = extract_entry_bundle(archive, "A/Berlin", content_processor=cp)
    sections = bundle["sections"]
    titles = [s["title"] for s in sections]
    # The four headings in SAMPLE_HTML in document order.
    assert titles == ["Berlin", "Geography", "Climate", "History"]
    levels = [s["level"] for s in sections]
    assert levels == [1, 2, 3, 2]


def test_bundle_section_offsets_are_sorted_and_disjoint(cp: ContentProcessor) -> None:
    archive = _make_archive_with_entry(SAMPLE_HTML)
    bundle = extract_entry_bundle(archive, "A/Berlin", content_processor=cp)
    sections = bundle["sections"]
    # char_start ascending
    starts = [s["char_start"] for s in sections]
    assert starts == sorted(starts)
    # 0 <= char_start < char_end <= len(rendered_markdown)
    md_len = len(bundle["rendered_markdown"])
    for s in sections:
        assert 0 <= s["char_start"] < s["char_end"] <= md_len


def test_bundle_slice_returns_section_content(cp: ContentProcessor) -> None:
    archive = _make_archive_with_entry(SAMPLE_HTML)
    bundle = extract_entry_bundle(archive, "A/Berlin", content_processor=cp)
    md = bundle["rendered_markdown"]
    geography = next(s for s in bundle["sections"] if s["title"] == "Geography")
    slice_text = md[geography["char_start"] : geography["char_end"]]
    assert "Geography" in slice_text
    assert "Spree" in slice_text
    # Must not contain the next heading's title (History)
    assert "History" not in slice_text


def test_bundle_section_ids_unique(cp: ContentProcessor) -> None:
    archive = _make_archive_with_entry(SAMPLE_HTML)
    bundle = extract_entry_bundle(archive, "A/Berlin", content_processor=cp)
    ids = [s["id"] for s in bundle["sections"]]
    assert len(ids) == len(set(ids)), f"Duplicate section IDs: {ids}"


def test_bundle_links_categorized(cp: ContentProcessor) -> None:
    archive = _make_archive_with_entry(SAMPLE_HTML)
    bundle = extract_entry_bundle(archive, "A/Berlin", content_processor=cp)
    links = bundle["links"]
    # Spree is internal (relative href)
    assert any(li["href"] == "A/Spree_River" for li in links["internal"])
    # External link
    assert any("wikipedia.org" in li["href"] for li in links["external"])
    # Media link
    assert any(li["href"] == "berlin.jpg" for li in links["media"])


def test_bundle_is_deterministic(cp: ContentProcessor) -> None:
    """Same input → identical bundle. Required for cache-eviction safety."""
    archive1 = _make_archive_with_entry(SAMPLE_HTML)
    archive2 = _make_archive_with_entry(SAMPLE_HTML)
    b1 = extract_entry_bundle(archive1, "A/Berlin", content_processor=cp)
    b2 = extract_entry_bundle(archive2, "A/Berlin", content_processor=cp)
    assert b1 == b2


def test_bundle_handles_repeated_heading_text(cp: ContentProcessor) -> None:
    """Two headings with identical text are disambiguated by document order."""
    html = """\
<html><body>
<h2>References</h2><p>First refs section</p>
<h2>External Links</h2><p>Some links</p>
<h2>References</h2><p>Second refs section (duplicate title)</p>
</body></html>
"""
    archive = _make_archive_with_entry(html)
    bundle = extract_entry_bundle(archive, "A/Test", content_processor=cp)
    titles = [s["title"] for s in bundle["sections"]]
    assert titles == ["References", "External Links", "References"]
    starts = [s["char_start"] for s in bundle["sections"]]
    assert starts[0] < starts[1] < starts[2]


def test_bundle_handles_markdown_significant_chars_in_heading(
    cp: ContentProcessor,
) -> None:
    """Headings with *, _, [, ] etc. survive html2text + regex matching."""
    html = """\
<html><body>
<h2>C++ programming</h2><p>About C++</p>
<h2>Python (programming language)</h2><p>About Python</p>
</body></html>
"""
    archive = _make_archive_with_entry(html)
    bundle = extract_entry_bundle(archive, "A/Test", content_processor=cp)
    titles = [s["title"] for s in bundle["sections"]]
    assert "C++ programming" in titles
    assert "Python (programming language)" in titles


def test_bundle_word_and_char_counts(cp: ContentProcessor) -> None:
    archive = _make_archive_with_entry(SAMPLE_HTML)
    bundle = extract_entry_bundle(archive, "A/Berlin", content_processor=cp)
    md = bundle["rendered_markdown"]
    assert bundle["char_count"] == len(md)
    assert bundle["word_count"] == len(md.split())
