"""Heading-location fixes from the fifth v3.0.0 sweep.

Two independent ways a real heading becomes unlocatable in the rendered
markdown, both ending the same way: ``_compute_section_offsets`` logs one
WARNING, ``continue``s, and the section is absent from the bundle — so
``view="toc"`` reports it does not exist and ``zim_get_section`` answers
``section_not_found`` for an id no listing ever offered.

* ``_strip_md_inline_decorations`` dropped ``*`` and backticks but never
  ``_``, which is exactly what html2text emits for ``<i>``/``<em>``.
  Wikipedia italicises the work title in the H1 of every article about a
  film, book, album, or newspaper (``<h1><i>2040</i> (film)</h1>`` →
  ``#  _2040_ (film)``), so the last-resort matcher compared
  ``'_2040_ (film)'`` against ``'2040 (film)'`` and missed.
* A heading containing ``<br>`` renders across TWO markdown lines, while
  ``_heading_visible_text`` concatenates the whole subtree into one
  string. Every matcher in the cascade is line-anchored, so no single-line
  pattern can bridge the break.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from openzim_mcp.bundle import (
    _compute_section_offsets,
    _match_decorated_heading_line,
    _strip_md_inline_decorations,
)
from openzim_mcp.content_processor import _build_headings


class TestUnderscoreEmphasisIsStripped:
    """html2text renders ``<i>x</i>`` as ``_x_``; the visible-text
    reduction must see through it exactly as it does through ``**x**``.
    """

    def test_underscore_emphasis_reduces_to_visible_text(self) -> None:
        assert _strip_md_inline_decorations("_2040_ (film)") == "2040 (film)"

    def test_asterisk_emphasis_still_reduces(self) -> None:
        # The pre-existing behaviour must not regress.
        assert _strip_md_inline_decorations("**Bold** title") == "Bold title"

    def test_interior_underscores_in_a_word_are_preserved(self) -> None:
        # ``snake_case_name`` is not emphasis — only delimiter-adjacent
        # underscore runs are. Deleting these would break headings whose
        # text really does carry underscores.
        assert _strip_md_inline_decorations("snake_case_name") == "snake_case_name"

    def test_decorated_heading_line_is_located(self) -> None:
        md = "#  _2040_ (film)\n\nbody\n"
        assert _match_decorated_heading_line(md, 1, "2040 (film)", 0) is not None

    def test_italic_h1_yields_a_section(self) -> None:
        html = "<h1 id='title_0'><i>2040</i> (film)</h1><p>Body text.</p>"
        headings = _build_headings(
            BeautifulSoup(html, "html.parser"), include_line_text=True
        )
        md = "#  _2040_ (film)\n\nBody text.\n"
        sections = _compute_section_offsets(md, headings)
        assert [s["id"] for s in sections] == ["title_0"]


class TestHeadingBrokenByLineBreak:
    """``<br>`` inside a heading pushes the tail onto the next markdown
    line; the heading must still be located by the part that stayed on
    the heading line.
    """

    def test_heading_with_br_is_located(self) -> None:
        html = (
            "<h2 id='alfabeto'>ALFABETO ITALIANO <br/>"
            "<font>італьянскі алфавіт</font></h2><p>Body.</p>"
        )
        headings = _build_headings(
            BeautifulSoup(html, "html.parser"), include_line_text=True
        )
        # The full visible text stays available for display...
        assert headings[0]["text"] == "ALFABETO ITALIANO італьянскі алфавіт"
        # ...but html2text only put the pre-break part on the heading line.
        md = "## ALFABETO ITALIANO  \nітальянскі алфавіт\n\nBody.\n"
        sections = _compute_section_offsets(md, headings)
        assert [s["id"] for s in sections] == ["alfabeto"]

    def test_heading_without_br_is_unaffected(self) -> None:
        html = "<h2 id='plain'>Plain Heading</h2><p>Body.</p>"
        headings = _build_headings(
            BeautifulSoup(html, "html.parser"), include_line_text=True
        )
        md = "## Plain Heading\n\nBody.\n"
        sections = _compute_section_offsets(md, headings)
        assert [s["id"] for s in sections] == ["plain"]

    def test_br_split_heading_does_not_swallow_a_sibling(self) -> None:
        # The located section must end at the next same-level heading,
        # not absorb it — the failure mode when the first heading is
        # dropped and the previous section's slice extends over it.
        html = (
            "<h2 id='first'>First <br/>tail</h2><p>A.</p>"
            "<h2 id='second'>Second</h2><p>B.</p>"
        )
        headings = _build_headings(
            BeautifulSoup(html, "html.parser"), include_line_text=True
        )
        md = "## First  \ntail\n\nA.\n\n## Second\n\nB.\n"
        sections = _compute_section_offsets(md, headings)
        assert [s["id"] for s in sections] == ["first", "second"]
        first = sections[0]
        assert "## Second" not in md[first["char_start"] : first["char_end"]]
