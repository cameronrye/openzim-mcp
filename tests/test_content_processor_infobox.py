"""Tests for extract_infobox (Phase A item #2)."""

import pytest
from bs4 import BeautifulSoup

from openzim_mcp.content_processor import ContentProcessor


@pytest.fixture
def processor() -> ContentProcessor:
    return ContentProcessor()


WIKI_INFOBOX_HTML = """
<div>
  <table class="infobox vcard">
    <tr><th colspan="2">Albert Einstein</th></tr>
    <tr><th>Born</th><td>14 March 1879</td></tr>
    <tr><th>Died</th><td>18 April 1955</td></tr>
    <tr><th>Nationality</th><td>German, Swiss, American</td></tr>
  </table>
  <p>Albert Einstein was a theoretical physicist.</p>
</div>
"""

INFOBOX_FREE_HTML = """
<div><p>Some plain prose with no infobox at all.</p></div>
"""


def test_extract_basic_infobox(processor):
    soup = BeautifulSoup(WIKI_INFOBOX_HTML, "html.parser")
    rows = processor.extract_infobox(soup)
    labels = [r["label"] for r in rows]
    assert "Born" in labels
    assert "Died" in labels
    assert "Nationality" in labels


def test_extract_infobox_removes_table_from_soup(processor):
    soup = BeautifulSoup(WIKI_INFOBOX_HTML, "html.parser")
    processor.extract_infobox(soup)
    assert soup.find("table", class_="infobox") is None
    assert "theoretical physicist" in soup.get_text()


def test_extract_infobox_empty_when_absent(processor):
    soup = BeautifulSoup(INFOBOX_FREE_HTML, "html.parser")
    assert processor.extract_infobox(soup) == []


def test_extract_infobox_capped_at_kv_limit():
    proc = ContentProcessor()
    rows_html = "".join(
        f"<tr><th>Field{i}</th><td>Value{i}</td></tr>" for i in range(50)
    )
    html = f'<table class="infobox">{rows_html}</table>'
    soup = BeautifulSoup(html, "html.parser")
    rows = proc.extract_infobox(soup, kv_limit=30)
    assert len(rows) == 30


# ---------------------------------------------------------------------------
# process_mime_content + html_to_plain_text compact propagation
# ---------------------------------------------------------------------------


def test_process_mime_content_compact_extracts_infobox(processor):
    """process_mime_content(compact=True) should surface KV pairs from an
    infobox and not produce pipe-table syntax for them."""
    html = WIKI_INFOBOX_HTML.encode("utf-8")
    result = processor.process_mime_content(html, "text/html", compact=True)
    assert "**Born:**" in result
    assert "**Died:**" in result
    # Infobox table itself must be gone — no pipe-soup
    assert "|" not in result


def test_process_mime_content_non_compact_no_kv_extraction(processor):
    """process_mime_content(compact=False) should NOT extract KV pairs —
    backward compat for callers that don't opt in."""
    html = WIKI_INFOBOX_HTML.encode("utf-8")
    result = processor.process_mime_content(html, "text/html", compact=False)
    # No bold KV prefix expected in default mode
    assert "**Born:**" not in result


# ---------------------------------------------------------------------------
# A11 D1 + D2 (post-a10 review)
# ---------------------------------------------------------------------------


CONCAT_INFOBOX_HTML = """
<table class="infobox">
  <tr><th colspan="2">Berlin</th></tr>
  <tr><th>Rank</th><td>5th in Europe<br>1st in Germany</td></tr>
  <tr><th>Demonyms</th><td>Berliner(s) (English)<br>Berliner (m), Berlinerin (f) (German)</td></tr>
  <tr><th>HDI (2022)</th><td>0.967<br>very high · 2nd of 16</td></tr>
  <tr><th>Dialects</th><td><span>Tokyo</span><span>Tama</span><span>Northern Izu Islands</span></td></tr>
</table>
"""


def test_d1_infobox_cell_text_separated(processor):
    """A11 D1 (post-a10): block-level children inside an infobox cell
    (``<br>``) used to concatenate without a separator. Every Wikipedia
    city article showed at least one instance: ``5th in Europe1st in
    Germany``, ``Berliner(s) (English)Berliner (m)``, ``0.967very
    high``, ``TokyoTamaNorthern Izu Islands``. The fix uses a
    block-level-aware text join (``_join_cell_text``) so block tags
    inject whitespace while inline spans concatenate directly.
    """
    soup = BeautifulSoup(CONCAT_INFOBOX_HTML, "html.parser")
    rows = {r["label"]: r["value"] for r in processor.extract_infobox(soup)}
    # ``<br>``-separated values (block-level) get a separator.
    assert rows["Rank"] == "5th in Europe 1st in Germany"
    assert (
        rows["Demonyms"]
        == "Berliner(s) (English) Berliner (m), Berlinerin (f) (German)"
    )
    assert rows["HDI (2022)"] == "0.967 very high · 2nd of 16"
    # Adjacent ``<span>`` children (inline) concatenate directly in
    # the helper, but each span here ends with text immediately
    # followed by the next span — Wikipedia uses this pattern for
    # comma-less compound strings like "TokyoTamaNorthern Izu Islands".
    # The helper preserves the contiguous text since no block-level
    # boundary separates them.
    assert rows["Dialects"] == "TokyoTamaNorthern Izu Islands"


# A11 D1 (post-a10 second pass): the first-revision fix used
# ``get_text(separator=" ")`` which inserted whitespace between EVERY
# descendant tag, corrupting Wikipedia's inline-span groups for number
# separators, units, and coordinates. The second-pass fix uses a
# block-level-aware helper instead. These tests lock the regression.
INLINE_SPAN_INFOBOX_HTML = """
<table class="infobox">
  <tr><th colspan="2">Berlin</th></tr>
  <tr><th>Population</th><td><span class="bday">3</span><span>,</span><span>913</span><span>,</span><span>644</span></td></tr>
  <tr><th>Area km2</th><td>891<wbr>.<wbr>3</td></tr>
  <tr><th>Coordinates</th><td>52<span>°</span>31<span>′</span>N 13<span>°</span>23<span>′</span>E</td></tr>
  <tr><th>Multi line</th><td>5th in Europe<br>1st in Germany</td></tr>
</table>
"""


def test_d1_inline_span_groups_concatenate_without_separator(processor):
    """A11 D1 second-pass: Wikipedia's inline span groups must stay
    unchanged. ``3<span>,</span>913,644`` is a single number, not three
    fields. Coordinates ``52°31′N`` similarly use inline spans for the
    degree/minute glyphs. The first-revision fix mangled both into
    ``3 , 913 , 644`` and ``52 ° 31 ′ N``.
    """
    soup = BeautifulSoup(INLINE_SPAN_INFOBOX_HTML, "html.parser")
    rows = {r["label"]: r["value"] for r in processor.extract_infobox(soup)}
    assert rows["Population"] == "3,913,644"
    assert rows["Area km2"] == "891.3"
    assert rows["Coordinates"] == "52°31′N 13°23′E"
    # And the block-level case still works alongside.
    assert rows["Multi line"] == "5th in Europe 1st in Germany"


D2_ORPHAN_BULLET_HTML = """
<table class="infobox">
  <tr><th colspan="2">Berlin</th></tr>
  <tr><th>Time zone</th><td>UTC+01:00 (CET)</td></tr>
  <tr><th>• Summer (DST)</th><td>UTC+02:00 (CEST)</td></tr>
  <tr><th>Area code</th><td>030</td></tr>
</table>
"""


def test_d2_orphan_bullet_inherits_previous_label(processor):
    """A11 D2 (post-a10): bullet-prefixed continuation rows ("• Summer
    (DST)") have no ``infobox-header`` parent in the markup but are
    visually owned by the immediately-preceding KV row's label
    ("Time zone"). Before this fix the row rendered as orphan
    ``**• Summer (DST):** UTC+02:00`` with no parent context.
    """
    soup = BeautifulSoup(D2_ORPHAN_BULLET_HTML, "html.parser")
    rows = {r["label"]: r["value"] for r in processor.extract_infobox(soup)}
    # The Time zone row stays bare (no inheritance — it's the parent).
    assert rows["Time zone"] == "UTC+01:00 (CET)"
    # The bullet row inherits Time zone as its virtual parent.
    assert rows["Time zone — • Summer (DST)"] == "UTC+02:00 (CEST)"
    # A subsequent non-bullet row breaks back out to bare.
    assert rows["Area code"] == "030"
