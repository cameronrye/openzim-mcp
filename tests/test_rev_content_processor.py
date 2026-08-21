"""Regression tests for over-eager content stripping in ``content_processor``.

The D14/D43 strips (in-page fragment nav, nav-list snippet paragraphs) are
shape-based, and the shapes they match also describe ordinary article
content: a Wikipedia reference list, a short article whose body is mostly
a table of contents, a Title-Case list of proper nouns. These tests pin
the content side of that trade-off; the MedlinePlus side stays pinned by
tests/test_v3_field_fixes_content.py and test_v3_field_fixes_search.py.
"""

from bs4 import BeautifulSoup

from openzim_mcp.content_processor import (
    HTML_PARSER,
    ContentProcessor,
    _is_nav_list_paragraph,
    select_main_content,
)

# ---------------------------------------------------------------------------
# In-page fragment nav strip must not eat article content
# ---------------------------------------------------------------------------

_LEAD = "Foo is a small village in Bar county. " * 20

# Wikipedia's ``<div class="reflist">``: every anchor is a ``#cite_ref``
# backlink and every citation is short, so the block matched the in-page
# nav shape exactly — but its text is the citations, not the links.
_REFLIST_HTML = f"""<html><body><article>
<h1>Foo</h1>
<p>{_LEAD}</p>
<h2>References</h2>
<div class="reflist"><ol>
<li><a href="#cite_ref-1">^</a> Smith, J. (2001). A History of Foo. p. 12.</li>
<li><a href="#cite_ref-2">^</a> Jones, A. (2005). Bar County. p. 44.</li>
<li><a href="#cite_ref-3">^</a> Lee, K. (2010). Villages of Bar. p. 7.</li>
</ol></div>
</article></body></html>"""

# The PR's own guard-rail fixture with the outbound-link ``.see-also`` div
# removed: without it the whole ``.entry-content`` wrapper is a container
# whose only links are fragments, and the article body went with it.
_SHORT_ARTICLE_HTML = """<html><body><article>
<h1>Gaudapada</h1>
<div class="entry-content">
  <p>Gaudapada is one of the early philosophers of the Vedanta school.</p>
  <h3>Table of Contents</h3>
  <ol><li><a href="#H1">Life and Works</a></li><li><a href="#H2">Overview</a></li>
  <li><a href="#H3">Legacy</a></li></ol>
</div></article></body></html>"""

# A container that really is nothing but its links, and nothing else in the
# landmark: stripping it leaves an empty document, so the restore-if-empty
# fallback has to hand the caller the unstripped landmark back.
_NAV_ONLY_ARTICLE_HTML = """<html><body><article>
<nav><a href="#a">Summary</a><a href="#b">Start Here</a><a href="#c">Symptoms</a></nav>
</article></body></html>"""


def test_reference_list_of_short_citations_survives_nav_strip() -> None:
    text = select_main_content(BeautifulSoup(_REFLIST_HTML, HTML_PARSER)).get_text(
        " ", strip=True
    )
    assert "A History of Foo" in text
    assert "Bar County" in text
    assert "Villages of Bar" in text


def test_short_article_body_survives_nav_strip_without_outbound_link() -> None:
    text = select_main_content(
        BeautifulSoup(_SHORT_ARTICLE_HTML, HTML_PARSER)
    ).get_text(" ", strip=True)
    assert "early philosophers of the Vedanta school" in text
    assert "Table of Contents" in text
    assert "Life and Works" in text


def test_strip_that_empties_the_landmark_restores_it() -> None:
    text = select_main_content(
        BeautifulSoup(_NAV_ONLY_ARTICLE_HTML, HTML_PARSER)
    ).get_text(" ", strip=True)
    assert "Summary" in text


# ---------------------------------------------------------------------------
# Nav-list snippet drop must not cost the snippet its query anchor
# ---------------------------------------------------------------------------

_TWIN_TOWNS = (
    "Berlin is the capital of Germany.\n\n"
    "## Twin towns\n\n"
    "  * Los Angeles, United States\n  * Paris, France\n  * Madrid, Spain\n"
)


def test_snippet_anchors_on_a_title_case_list_the_query_matches() -> None:
    """A list of proper nouns is indistinguishable from a site menu by shape;
    a query hit inside it settles the question."""
    cp = ContentProcessor(snippet_length=300)
    snippet = cp.create_snippet(_TWIN_TOWNS, query="Los Angeles", max_paragraphs=1)
    assert "**Los** **Angeles**" in snippet


def test_snippet_still_skips_nav_list_the_query_misses() -> None:
    """The D29 floor: without a hit inside it, the list is still furniture."""
    cp = ContentProcessor(snippet_length=300)
    snippet = cp.create_snippet(_TWIN_TOWNS, query="capital", max_paragraphs=1)
    assert "Los Angeles" not in snippet
    assert "**capital**" in snippet


def test_single_item_list_is_not_navigation() -> None:
    assert _is_nav_list_paragraph("  * Related Issues\n") is False
    assert _is_nav_list_paragraph("  * Summary\n  * Start Here\n") is True


# ---------------------------------------------------------------------------
# Leading-title-H1 strip
# ---------------------------------------------------------------------------


def test_leading_h1_strip_handles_length_expanding_lowercase() -> None:
    """``'İ'.lower()`` is two code points, so slicing the folded title by the
    unfolded H1 length read the separator probe one character early."""
    out = ContentProcessor._strip_leading_title_heading(
        "# İstanbul\n\nBody text.\n", "İstanbul: MedlinePlus"
    )
    assert out == "Body text.\n"
