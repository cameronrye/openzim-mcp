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
