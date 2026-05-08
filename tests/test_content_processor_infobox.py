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
