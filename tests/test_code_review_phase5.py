"""Regression tests for code-review 2026-06-10 Phase 5 (content_processor).

M2 (extract_infobox deletes zero-row content), M3 (snippet truncation splits
markdown links).
"""

from bs4 import BeautifulSoup

from openzim_mcp.content_processor import ContentProcessor


# M2 — a matched infobox node with zero KV rows must not be deleted
def test_m2_div_infobox_without_rows_is_preserved():
    cp = ContentProcessor(200)
    soup = BeautifulSoup(
        '<div class="infobox"><div class="label">Pop</div>'
        '<div class="data">1000</div></div>',
        "html.parser",
    )
    rows = cp.extract_infobox(soup)
    assert rows == []
    # Content must still be in the soup (not silently removed).
    assert soup.select_one(".infobox") is not None


def test_m2_table_infobox_with_rows_still_extracted_and_removed():
    cp = ContentProcessor(200)
    soup = BeautifulSoup(
        '<table class="infobox"><tr><th>Population</th><td>1000</td></tr></table>',
        "html.parser",
    )
    rows = cp.extract_infobox(soup)
    assert rows and rows[0]["value"] == "1000"
    # Real KV infobox is consumed so html2text doesn't pipe-soup it.
    assert soup.select_one("table.infobox") is None


# M3 — snippet truncation must not bold query terms inside a split link
def test_m3_snippet_does_not_bold_inside_split_link():
    cp = ContentProcessor(200)
    content = (
        "The city of Berlin is documented in "
        "[History of Berlin](A/History_of_Berlin) and elsewhere too."
    )
    snippet = cp.create_snippet(content, query="Berlin History", snippet_length=60)
    # No bold markers landed inside a link target/URL (which would break it).
    # Either the link is complete (skip-protected) or it was dropped — never
    # a dangling "[...** ...](" fragment.
    assert "](A/**" not in snippet
    assert "**History**](" not in snippet
    assert snippet.endswith("...") or "[" not in snippet.split("](")[0][-1:]
