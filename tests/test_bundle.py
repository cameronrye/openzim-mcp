"""Tests for openzim_mcp.bundle.

Bundle determinism, structural invariants, and offset-correctness for
the post-render text-matching algorithm. The cache-aware accessor
(get_or_build_bundle) has its own tests in this file.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openzim_mcp import bundle as _bundle_mod
from openzim_mcp.bundle import extract_entry_bundle
from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import CacheConfig
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

TABLE_HTML = """\
<html><body>
<h1>Data</h1>
<p>Intro paragraph.</p>
<h2>Stats</h2>
<table>
<tr><th>Year</th><th>Label</th></tr>
<tr><td>2001</td><td>alpha</td></tr>
<tr><td>2002</td><td>beta</td></tr>
<tr><td>2003</td><td>gamma</td></tr>
<tr><td>2004</td><td>delta</td></tr>
<tr><td>2005</td><td>epsilon</td></tr>
<tr><td>2006</td><td>zeta</td></tr>
<tr><td>2007</td><td>eta</td></tr>
<tr><td>2008</td><td>theta</td></tr>
<tr><td>2009</td><td>iota</td></tr>
<tr><td>2010</td><td>kappa</td></tr>
</table>
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
    """Return a default ContentProcessor instance."""
    return ContentProcessor()


def test_bundle_has_rendered_markdown(cp: ContentProcessor) -> None:
    """Bundle includes entry_path, title, and rendered_markdown with article text."""
    archive = _make_archive_with_entry(SAMPLE_HTML)
    bundle = extract_entry_bundle(archive, "A/Berlin", content_processor=cp)
    assert bundle["entry_path"] == "A/Berlin"
    assert bundle["title"] == "Berlin"
    assert "Berlin is the capital" in bundle["rendered_markdown"]


def test_bundle_sections_have_offsets(cp: ContentProcessor) -> None:
    """Sections are extracted in document order with correct titles and levels."""
    archive = _make_archive_with_entry(SAMPLE_HTML)
    bundle = extract_entry_bundle(archive, "A/Berlin", content_processor=cp)
    sections = bundle["sections"]
    titles = [s["title"] for s in sections]
    # The four headings in SAMPLE_HTML in document order.
    assert titles == ["Berlin", "Geography", "Climate", "History"]
    levels = [s["level"] for s in sections]
    assert levels == [1, 2, 3, 2]


def test_bundle_section_offsets_are_sorted_and_disjoint(cp: ContentProcessor) -> None:
    """Section char_start values are ascending and each [char_start, char_end) is valid."""
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


def test_bundle_slice_returns_section_body_without_heading(
    cp: ContentProcessor,
) -> None:
    """``char_start`` points to the body, not the heading line itself.

    The heading is exposed separately as ``section_title``/``level``, so
    including ``## Geography`` again in the slice is redundant and inflates
    ``char_count``/``word_count``.
    """
    archive = _make_archive_with_entry(SAMPLE_HTML)
    bundle = extract_entry_bundle(archive, "A/Berlin", content_processor=cp)
    md = bundle["rendered_markdown"]
    geography = next(s for s in bundle["sections"] if s["title"] == "Geography")
    slice_text = md[geography["char_start"] : geography["char_end"]]
    assert "Spree" in slice_text
    assert not slice_text.lstrip().startswith("## Geography")
    # Must not contain the next heading's title (History)
    assert "History" not in slice_text


def test_bundle_section_ids_unique(cp: ContentProcessor) -> None:
    """Every section carries a unique id slug."""
    archive = _make_archive_with_entry(SAMPLE_HTML)
    bundle = extract_entry_bundle(archive, "A/Berlin", content_processor=cp)
    ids = [s["id"] for s in bundle["sections"]]
    assert len(ids) == len(set(ids)), f"Duplicate section IDs: {ids}"


def test_bundle_links_categorized(cp: ContentProcessor) -> None:
    """Internal, external, and media links are extracted into separate buckets."""
    archive = _make_archive_with_entry(SAMPLE_HTML)
    bundle = extract_entry_bundle(archive, "A/Berlin", content_processor=cp)
    links = bundle["links"]
    # Spree is internal (relative url)
    assert any(li["url"] == "A/Spree_River" for li in links["internal"])
    # External link
    assert any(
        li["url"] == "https://en.wikipedia.org/wiki/Berlin" for li in links["external"]
    )
    # Media link
    assert any(li["url"] == "berlin.jpg" for li in links["media"])


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
    """word_count and char_count reflect the rendered_markdown length."""
    archive = _make_archive_with_entry(SAMPLE_HTML)
    bundle = extract_entry_bundle(archive, "A/Berlin", content_processor=cp)
    md = bundle["rendered_markdown"]
    assert bundle["char_count"] == len(md)
    assert bundle["word_count"] == len(md.split())


# ---------------------------------------------------------------------------
# get_or_build_bundle: cache-hit / cache-miss / eviction-round-trip
# ---------------------------------------------------------------------------


def test_get_or_build_bundle_cache_miss_then_hit(
    cp: ContentProcessor, tmp_path: Path
) -> None:
    """First call builds; second call returns cached without re-parsing."""
    config = CacheConfig(enabled=True, max_size=128, ttl_seconds=300)
    cache = OpenZimMcpCache(config, enable_background_cleanup=False)
    archive = _make_archive_with_entry(SAMPLE_HTML)
    validated_path = tmp_path / "test.zim"
    validated_path.touch()

    # First call: cache miss → build
    initial_misses = cache.stats()["misses"]
    bundle1 = _bundle_mod.get_or_build_bundle(
        archive,
        "A/Berlin",
        cache=cache,
        validated_path=validated_path,
        content_processor=cp,
    )
    after_first = cache.stats()
    assert after_first["misses"] == initial_misses + 1
    assert archive.get_entry_by_path.call_count == 1

    # Second call: cache hit → no archive access
    bundle2 = _bundle_mod.get_or_build_bundle(
        archive,
        "A/Berlin",
        cache=cache,
        validated_path=validated_path,
        content_processor=cp,
    )
    after_second = cache.stats()
    assert after_second["misses"] == after_first["misses"]  # no new miss
    assert after_second["hits"] >= after_first["hits"] + 1
    assert archive.get_entry_by_path.call_count == 1  # still one archive read
    assert bundle1 == bundle2


def test_get_or_build_bundle_eviction_rebuild_identical(
    cp: ContentProcessor, tmp_path: Path
) -> None:
    """After eviction, rebuild produces a bundle == the original."""
    config = CacheConfig(enabled=True, max_size=128, ttl_seconds=300)
    cache = OpenZimMcpCache(config, enable_background_cleanup=False)
    archive = _make_archive_with_entry(SAMPLE_HTML)
    validated_path = tmp_path / "test.zim"
    validated_path.touch()

    bundle1 = _bundle_mod.get_or_build_bundle(
        archive,
        "A/Berlin",
        cache=cache,
        validated_path=validated_path,
        content_processor=cp,
    )

    # Force eviction by clearing the cache entirely
    cache.clear()

    bundle2 = _bundle_mod.get_or_build_bundle(
        archive,
        "A/Berlin",
        cache=cache,
        validated_path=validated_path,
        content_processor=cp,
    )

    assert bundle1 == bundle2  # determinism — required for cursor-survival


def test_get_or_build_bundle_different_paths_different_keys(
    cp: ContentProcessor, tmp_path: Path
) -> None:
    """Two different validated_paths produce two cache entries."""
    config = CacheConfig(enabled=True, max_size=128, ttl_seconds=300)
    cache = OpenZimMcpCache(config, enable_background_cleanup=False)
    archive_a = _make_archive_with_entry(SAMPLE_HTML)
    archive_b = _make_archive_with_entry(SAMPLE_HTML)
    path_a = tmp_path / "a.zim"
    path_b = tmp_path / "b.zim"
    path_a.touch()
    path_b.touch()

    _bundle_mod.get_or_build_bundle(
        archive_a,
        "A/Berlin",
        cache=cache,
        validated_path=path_a,
        content_processor=cp,
    )
    _bundle_mod.get_or_build_bundle(
        archive_b,
        "A/Berlin",
        cache=cache,
        validated_path=path_b,
        content_processor=cp,
    )

    # Both archives were touched (different cache keys)
    assert archive_a.get_entry_by_path.call_count == 1
    assert archive_b.get_entry_by_path.call_count == 1
    assert cache.stats()["misses"] >= 2


# ---------------------------------------------------------------------------
# Bundle invariants from spec § "Invariants"
# ---------------------------------------------------------------------------

DEEP_NESTED_HTML = """\
<html><body>
<h1>Top</h1><p>Top intro.</p>
<h2>Section A</h2><p>A intro.</p>
<h3>A.1</h3><p>A.1 body.</p>
<h3>A.2</h3><p>A.2 body.</p>
<h2>Section B</h2><p>B intro.</p>
<h3>B.1</h3><p>B.1 body.</p>
<h4>B.1.a</h4><p>B.1.a body.</p>
</body></html>
"""


def test_bundle_parent_child_range_nesting(cp: ContentProcessor) -> None:
    """Child section offsets fall inside the parent's offset range."""
    archive = _make_archive_with_entry(DEEP_NESTED_HTML)
    bundle = extract_entry_bundle(archive, "A/Test", content_processor=cp)
    sections = bundle["sections"]
    by_id = {s["id"]: s for s in sections}

    for s in sections:
        if s.get("parent_id"):
            parent = by_id[s["parent_id"]]
            assert parent["char_start"] <= s["char_start"]
            assert s["char_end"] <= parent["char_end"]
            assert parent["level"] < s["level"]


def test_bundle_same_level_disjoint(cp: ContentProcessor) -> None:
    """Two h2s under the same h1 must not overlap each other."""
    archive = _make_archive_with_entry(DEEP_NESTED_HTML)
    bundle = extract_entry_bundle(archive, "A/Test", content_processor=cp)
    sections = bundle["sections"]
    h2s = [s for s in sections if s["level"] == 2]
    assert len(h2s) == 2
    a, b = h2s
    assert a["char_end"] <= b["char_start"]


def test_bundle_compact_false_keeps_full_table(cp: ContentProcessor) -> None:
    """compact=False retains full table rows; compact=True replaces oversized tables."""
    archive = _make_archive_with_entry(TABLE_HTML, title="Data", entry_path="A/Data")
    raw = extract_entry_bundle(archive, "A/Data", content_processor=cp, compact=False)
    compact = extract_entry_bundle(
        archive, "A/Data", content_processor=cp, compact=True
    )
    # compact=False keeps the real table cells; compact=True replaces with a placeholder
    assert "alpha" in raw["rendered_markdown"]
    assert "[Table" not in raw["rendered_markdown"]
    assert "[Table" in compact["rendered_markdown"]
    assert "alpha" not in compact["rendered_markdown"]


def test_bundle_cache_key_distinguishes_compact_mode(tmp_path) -> None:
    """Cache keys for compact=True and compact=False are distinct for the same entry."""
    from openzim_mcp.bundle import _bundle_cache_key

    p = tmp_path / "x.zim"
    p.touch()
    assert _bundle_cache_key(p, "A/Data", True) != _bundle_cache_key(p, "A/Data", False)
