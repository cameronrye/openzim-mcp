"""Headings whose inline markup abuts adjacent text must still be located.

html2text puts a space after emphasis it closes, even when the source had
none: ``<h2><b>Foo</b>bar</h2>`` renders as ``## **Foo** bar`` while
``_heading_visible_text`` reads ``Foobar`` off the soup. Stripping the
decorations leaves ``'Foo bar'`` against ``'Foobar'``, so the last-resort
matcher missed and ``_compute_section_offsets`` dropped the section — the
same ending as the fifth sweep's two cases: ``view="toc"`` never lists it
and ``zim_get_section`` answers ``section_not_found`` for it.

Code spans do not gain the space, which is why this survived the earlier
pass: the obvious ``<code>`` fixture matches either way.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from openzim_mcp.bundle import _compute_section_offsets, _match_decorated_heading_line
from openzim_mcp.content_processor import _build_headings


class TestEmphasisAbuttingText:
    def test_bold_abutting_following_text_is_located(self) -> None:
        assert (
            _match_decorated_heading_line("## **Foo** bar\n", 2, "Foobar", 0)
            is not None
        )

    def test_italic_abutting_following_text_is_located(self) -> None:
        assert (
            _match_decorated_heading_line("##  _Early_ life\n", 2, "Earlylife", 0)
            is not None
        )

    def test_genuinely_different_headings_still_do_not_match(self) -> None:
        """The relaxation is whitespace-only; it must not fuse distinct text."""
        assert _match_decorated_heading_line("## **Foo** bar\n", 2, "Foobaz", 0) is None

    def test_spaced_heading_still_matches_spaced_text(self) -> None:
        assert (
            _match_decorated_heading_line("## **Foo** bar\n", 2, "Foo bar", 0)
            is not None
        )


class TestAbuttingHeadingYieldsASection:
    def test_bold_abutting_heading_yields_a_section(self) -> None:
        html = "<h2 id='abut'><b>Foo</b>bar</h2><p>Body text.</p>"
        headings = _build_headings(
            BeautifulSoup(html, "html.parser"), include_line_text=True
        )
        md = "## **Foo** bar\n\nBody text.\n"
        sections = _compute_section_offsets(md, headings)
        assert [s["id"] for s in sections] == ["abut"]

    def test_abutting_heading_does_not_swallow_a_sibling(self) -> None:
        html = (
            "<h2 id='first'><b>Foo</b>bar</h2><p>A.</p>"
            "<h2 id='second'>Second</h2><p>B.</p>"
        )
        headings = _build_headings(
            BeautifulSoup(html, "html.parser"), include_line_text=True
        )
        md = "## **Foo** bar\n\nA.\n\n## Second\n\nB.\n"
        sections = _compute_section_offsets(md, headings)
        assert [s["id"] for s in sections] == ["first", "second"]
        first = sections[0]
        assert "## Second" not in md[first["char_start"] : first["char_end"]]
