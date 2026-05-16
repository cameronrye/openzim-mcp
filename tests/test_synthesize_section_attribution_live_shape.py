"""Regression tests for the post-a14 beta-test sweep: section attribution
in synthesize must work on real-archive snippet shapes, not just on the
synthetic golden-snapshot fixtures.

Motivating defect: every cite_id in live ``synthesize=True`` responses
on Wikipedia carried ``section_id: null`` because BM25 snippets for the
article lead could not be located inside the bundle's
``rendered_markdown``. The downstream consequences were:

  * ``_boost_by_section_affinity`` was a no-op (the gate requires a
    ``#section_id`` suffix on the cite_id).
  * ``_build_considered_sections`` short-circuited to ``[]`` because
    the featured passage had no ``featured_section_id``.

The unit-test goldens for ``synthesize_berlin_geography`` etc. ship
with a synthetic archive whose snippet text aligned exactly with the
bundle's ``rendered_markdown``, so the live failure was invisible.

The actual proximate cause is that ``_locate_passage`` strips ``**``
bold markers from the *passage* before searching, but not from the
*markdown* it's searching inside. Real Wikipedia lead text contains
natural bold (``**Big Rapids**`` for the entity name) — once that
mismatch lands inside the probe window, every ``md.find`` and
``md_norm.find`` returns -1 and the passage falls through to
entry-level citation.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from openzim_mcp.bundle import extract_entry_bundle
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.synthesize import _attribute_sections, _locate_passage


# Wikipedia-shaped HTML: h1 with id="firstHeading", lead with natural
# bold on the entity name (the universal Wikipedia pattern), then h2
# sections.
WIKIPEDIA_SHAPED_HTML = """\
<html><body>
<h1 id="firstHeading">Big Rapids, Michigan</h1>
<p><b>Big Rapids</b> is a city and the seat of government of Mecosta
County, Michigan. The population was 7,727 at the 2020 census, down
from 10,601 in 2010.</p>
<h2 id="History">History</h2>
<p>Big Rapids was settled in 1855 by brothers George and Zera French.</p>
<h2 id="Notable_people">Notable people</h2>
<ul>
  <li>Matt Borland, NASCAR crew chief</li>
  <li>Justin Custer, racing driver</li>
</ul>
</body></html>
"""


def _make_archive_with_entry(html: str) -> Any:
    item = MagicMock()
    item.content = html.encode("utf-8")
    item.mimetype = "text/html"
    entry = MagicMock()
    entry.title = "Big Rapids, Michigan"
    entry.path = "Big_Rapids,_Michigan"
    entry.get_item.return_value = item
    archive = MagicMock()
    archive.get_entry_by_path.return_value = entry
    return archive


@pytest.fixture
def cp() -> ContentProcessor:
    return ContentProcessor()


def test_locate_passage_survives_natural_bold_in_markdown(
    cp: ContentProcessor,
) -> None:
    """When the bundle's ``rendered_markdown`` contains natural bold
    markers (Wikipedia's universal pattern: ``**EntityName**`` opens
    the lead paragraph) and the snippet's bold markers have been
    stripped before the locate call, ``_locate_passage`` must still
    find the snippet inside the markdown. Without this, real-archive
    lead passages drop to entry-level citation."""
    archive = _make_archive_with_entry(WIKIPEDIA_SHAPED_HTML)
    bundle = extract_entry_bundle(
        archive, "Big_Rapids,_Michigan", content_processor=cp
    )
    md = bundle["rendered_markdown"]
    # Sanity: the natural bold is present in the bundle.
    assert "**Big Rapids**" in md, (
        "Fixture invariant: Wikipedia-shaped HTML must produce "
        "**EntityName** in rendered_markdown; otherwise the test "
        "doesn't exercise the regression mode."
    )

    # The snippet form ``_locate_passage`` sees: bold markers already
    # stripped by ``_strip_bold`` at the top of the function. Pass a
    # bold-free snippet representing what the locate call works with.
    snippet_clean = "Big Rapids is a city and the seat of government"

    pos = _locate_passage(md, snippet_clean)
    assert pos >= 0, (
        f"_locate_passage failed on natural-bold markdown. "
        f"md head: {md[:120]!r}, snippet: {snippet_clean!r}"
    )


def test_pre_h1_chrome_passage_falls_back_to_first_section(
    cp: ContentProcessor,
) -> None:
    """Some archives (IEP, parts of Wikipedia with navboxes) render
    page chrome BEFORE the h1 heading. A passage whose locate-position
    lands in that pre-h1 chrome (pos < first_section.char_start) must
    still attribute to *some* section — the article's first section
    (the h1) is the natural anchor. Without this fallback, chrome-area
    BM25 snippets drop to entry-level citation."""
    html = """\
<html><body>
<nav><a href="../">Home</a> | <a href="../about/">About</a></nav>
<h1 id="firstHeading">Big Rapids, Michigan</h1>
<p><b>Big Rapids</b> is a city.</p>
<h2 id="Notable_people">Notable people</h2>
<p>Some notable folks here.</p>
</body></html>
"""
    archive = _make_archive_with_entry(html)
    bundle = extract_entry_bundle(
        archive, "Big_Rapids,_Michigan", content_processor=cp
    )
    md = bundle["rendered_markdown"]

    # Pick a sub-string from the *chrome* (before the h1 line).
    h1_pos = md.find("# Big Rapids")
    assert h1_pos > 0, "Test fixture: chrome should render before the h1"
    chrome_text = md[:h1_pos].rstrip()
    # The pre-h1 chrome typically contains link text; pick a substring
    # likely to be ≥12 chars so locate's whitespace-normalize fallback
    # path is engaged if the exact-find misses.
    probe = chrome_text[-60:].strip() if len(chrome_text) >= 60 else chrome_text
    if len(probe) < 12:
        import pytest as _pt
        _pt.skip(
            "Chrome too short for the >=12-char normalize probe; can't "
            "exercise this fallback on this fixture shape."
        )

    passage = {
        "cite_id": "wiki/Big_Rapids,_Michigan",
        "text_markdown": probe,
        "rank": 1,
        "score": 1.0,
    }

    def bundle_lookup(_archive_name: str, _entry_path: str) -> Any:
        return bundle

    attributed = _attribute_sections(
        [passage],
        bundle_lookup=bundle_lookup,
        hit_keys=[("wiki", "Big_Rapids,_Michigan")],
    )

    new_cite_id = attributed[0]["cite_id"]
    assert "#" in new_cite_id, (
        f"Pre-h1 chrome passage failed to attribute. cite_id stayed at "
        f"entry level: {new_cite_id!r}. The first section should be the "
        f"natural fallback when no section brackets the passage."
    )


def test_lead_passage_attributes_to_a_section_on_wikipedia_shaped_html(
    cp: ContentProcessor,
) -> None:
    """End-to-end: a passage whose text falls in the article lead must
    attribute to *some* section (here: the h1 'firstHeading' section
    that spans the lead). Without this, every BM25-lead-snippet on
    real Wikipedia falls through to entry-level citation."""
    archive = _make_archive_with_entry(WIKIPEDIA_SHAPED_HTML)
    bundle = extract_entry_bundle(
        archive, "Big_Rapids,_Michigan", content_processor=cp
    )

    passage = {
        "cite_id": "wiki/Big_Rapids,_Michigan",
        # Same text the BM25 snippet path would deliver post-strip:
        # the natural-bold ``**Big Rapids**`` has been stripped, but
        # the raw text content of the lead paragraph is preserved.
        "text_markdown": "Big Rapids is a city and the seat of government",
        "rank": 1,
        "score": 1.0,
    }

    def bundle_lookup(_archive_name: str, _entry_path: str) -> Any:
        return bundle

    attributed = _attribute_sections(
        [passage],
        bundle_lookup=bundle_lookup,
        hit_keys=[("wiki", "Big_Rapids,_Michigan")],
    )

    new_cite_id = attributed[0]["cite_id"]
    assert "#" in new_cite_id, (
        f"Lead passage failed to attribute. cite_id stayed at entry "
        f"level: {new_cite_id!r}. Pre-h2 lead content has no containing "
        f"section that ``_attribute_sections`` can find."
    )
