"""Tests for the v2.0.0a7 content_processor fixes.

Covers:
  * D4 — ``_highlight_terms`` skips matches inside existing markdown
    emphasis or link constructs so we don't produce
    ``**Artificial **photosynthesis****``-style malformed markdown.
  * Op1 — ``create_snippet(title=...)`` strips a leading ``# <title>``
    H1 that duplicates the entry title.
  * Op5 — infobox extraction prefixes labels with their parent section
    header so a row labelled ``City/State`` carries ``Area`` /
    ``Government`` / ``Population`` disambiguation.
  * Op6 — UNWANTED_HTML_SELECTORS strips ``figure`` /
    ``figcaption`` / ``.hatnote`` / ``.sidebar`` so the rendered article
    body leads with the actual prose, not the image caption or the
    "For other uses, see X" hatnote.
  * D13 — ``create_snippet`` falls back to a substring match when no
    whole-word match is found, capturing morphological variants
    (``photosynthetic`` for query ``photosynthesis``).
"""

from bs4 import BeautifulSoup

from openzim_mcp.content_processor import (
    ContentProcessor,
    _highlight_terms,
)


def test_highlight_skips_inside_existing_bold():
    """A query term inside ``**...**`` must not get a second bold layer."""
    text = "**Artificial photosynthesis** is a chemical process."
    out = _highlight_terms(text, "photosynthesis", max_hits=5)
    # Must NOT produce ``**Artificial **photosynthesis****`` — the inner
    # wrap would create unmatched ``****`` runs.
    assert "**Artificial **" not in out
    assert "****" not in out
    # The original bold span is preserved verbatim.
    assert "**Artificial photosynthesis**" in out


def test_highlight_skips_inside_italic():
    """A query term inside ``_..._`` must not get bolded."""
    text = "_Photosynthesis_ in Wiktionary."
    out = _highlight_terms(text, "photosynthesis", max_hits=5)
    # The italic run is preserved untouched.
    assert "_Photosynthesis_" in out
    # No nested bold inside the italic.
    assert "_**Photosynthesis**_" not in out


def test_highlight_skips_inside_link_text_and_url():
    """A query term inside a markdown link's text OR URL must not get bolded."""
    text = "see [Photosynthesis](Photosynthesis \"Photosynthesis\")"
    out = _highlight_terms(text, "photosynthesis", max_hits=5)
    # Link must remain a valid ``[text](href "tooltip")`` construct.
    assert "[Photosynthesis](Photosynthesis \"Photosynthesis\")" in out
    # No bold inside the link.
    assert "**Photosynthesis**" not in out


def test_highlight_still_bolds_plain_occurrences():
    """Plain query-term occurrences outside emphasis are still bolded."""
    text = "Photosynthesis converts CO2 into sugars."
    out = _highlight_terms(text, "photosynthesis", max_hits=5)
    assert out.startswith("**Photosynthesis**")


def test_highlight_mixed_case():
    """An emphasis-protected match and a plain match coexist correctly."""
    text = "**Artificial Photosynthesis** mimics Photosynthesis in plants."
    out = _highlight_terms(text, "photosynthesis", max_hits=5)
    # First "Photosynthesis" sits inside ``**...**`` → untouched.
    # Second "Photosynthesis" is plain prose → bolded.
    assert "**Artificial Photosynthesis**" in out
    # Count bold markers around the plain occurrence: that's one new pair
    # added beyond the original two markers of the bold span.
    assert out.count("**") == 4


def test_create_snippet_strips_leading_title_h1():
    """``title=Berlin`` strips ``# Berlin`` from the start of the content."""
    content = "# Berlin\n\nBerlin is the capital of Germany."
    proc = ContentProcessor()
    snippet = proc.create_snippet(content, query="capital", title="Berlin")
    # H1 line is gone; the lead sentence is preserved.
    assert not snippet.startswith("# Berlin")
    assert "Berlin is the **capital** of Germany." in snippet


def test_create_snippet_keeps_non_matching_h1():
    """An H1 that doesn't match the title is left alone (no query, so the
    snippet starts at paragraph 0 — the H1)."""
    content = "# Geography\n\nThe topography is flat."
    proc = ContentProcessor()
    snippet = proc.create_snippet(content, title="Berlin")
    # Heading is unrelated to title → stays.
    assert "# Geography" in snippet


def test_create_snippet_title_match_case_insensitive():
    """Title match is case-insensitive so casing drift between fields doesn't leak."""
    content = "# berlin\n\nLead paragraph."
    proc = ContentProcessor()
    snippet = proc.create_snippet(content, title="Berlin")
    assert "# berlin" not in snippet
    assert "Lead paragraph." in snippet


def test_create_snippet_substring_fallback_picks_inflected_paragraph():
    """When no whole-word query match is found, substring match catches
    inflected forms instead of falling back to the lead paragraph."""
    content = (
        "Govindjee\n\nGovindjee was a botanist.\n\n"
        "He studied photosynthetic activity in plants."
    )
    proc = ContentProcessor()
    snippet = proc.create_snippet(content, query="photosynthesis")
    # Phase A #1 says: pick a paragraph that mentions the query term. With
    # only the substring "photosynthet" present (a morphological form),
    # the legacy code dropped to the lead ("Govindjee was a botanist.").
    # D13 fix: substring fallback picks the photosynthetic-bearing paragraph.
    assert "photosynthetic" in snippet
    assert "botanist" not in snippet


WIKI_INFOBOX_WITH_SECTIONS = """
<table class="infobox">
  <tr><th colspan="2">Berlin</th></tr>
  <tr><th colspan="2">Government</th></tr>
  <tr><th>Governing Mayor</th><td>Kai Wegner</td></tr>
  <tr><th colspan="2">Area</th></tr>
  <tr><th>City/State</th><td>891.3 km2</td></tr>
  <tr><th colspan="2">Population</th></tr>
  <tr><th>City/State</th><td>3,913,644</td></tr>
</table>
"""


def test_infobox_disambiguates_repeated_label_via_section():
    """When the same label (``City/State``) repeats under different
    section headers, the extracted rows carry the parent context so a
    small model can tell them apart."""
    soup = BeautifulSoup(WIKI_INFOBOX_WITH_SECTIONS, "html.parser")
    proc = ContentProcessor()
    rows = proc.extract_infobox(soup)
    labels = [r["label"] for r in rows]
    # First ``City/State`` is under Area; second under Population.
    assert "Area — City/State" in labels
    assert "Population — City/State" in labels
    # Governing Mayor inherits "Government" context.
    assert "Government — Governing Mayor" in labels


def test_infobox_skips_title_row():
    """The first ``<th>``-only row (article title duplicate) is not
    emitted as a label even when it has no explicit ``infobox-above``
    class. Without this, the title leaks into every row's label
    prefix."""
    soup = BeautifulSoup(WIKI_INFOBOX_WITH_SECTIONS, "html.parser")
    proc = ContentProcessor()
    rows = proc.extract_infobox(soup)
    for r in rows:
        assert not r["label"].startswith("Berlin —")


def test_figure_and_figcaption_stripped():
    """Image captions sit between the H1 and the lead paragraph in
    Wikipedia exports; stripping ``figure`` / ``figcaption`` removes the
    "Schematic of …" noise that was leading every snippet."""
    html = (
        "<html><body>"
        "<h1>Photosynthesis</h1>"
        "<figure><figcaption>Schematic of photosynthesis</figcaption></figure>"
        "<p>Photosynthesis is the biological process that converts light "
        "into chemical energy.</p>"
        "</body></html>"
    )
    proc = ContentProcessor()
    rendered = proc.html_to_plain_text(html, compact=True)
    assert "Schematic of photosynthesis" not in rendered
    assert "biological process" in rendered


def test_hatnote_stripped():
    """Disambiguation hatnotes ("For other uses, see X") leak ahead of
    the lead paragraph; strip them so the lead bubbles to the top."""
    html = (
        "<html><body>"
        "<h1>Mercury</h1>"
        "<div class='hatnote'>For other uses, see Mercury (disambiguation).</div>"
        "<p>Mercury is the smallest planet in the Solar System.</p>"
        "</body></html>"
    )
    proc = ContentProcessor()
    rendered = proc.html_to_plain_text(html, compact=True)
    assert "Mercury (disambiguation)" not in rendered
    assert "smallest planet" in rendered


def test_sidebar_stripped():
    """The "Part of a series on …" right-rail nav is pure pipe-soup
    noise; strip it via the ``.sidebar`` selector so it doesn't crowd
    the lead."""
    html = (
        "<html><body>"
        "<h1>Quantum entanglement</h1>"
        "<div class='sidebar'>"
        "<table><tr><th>Quantum mechanics</th></tr>"
        "<tr><td>Schrödinger equation</td></tr></table>"
        "</div>"
        "<p>Quantum entanglement is the phenomenon wherein two particles share a state.</p>"
        "</body></html>"
    )
    proc = ContentProcessor()
    rendered = proc.html_to_plain_text(html, compact=True)
    assert "Schrödinger equation" not in rendered
    assert "phenomenon wherein two particles" in rendered
