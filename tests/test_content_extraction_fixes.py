"""Regression tests for the content-extraction bug sweep (P4/P15/P22/P34).

P4  — one malformed ``href`` aborted ALL link extraction. ``urlparse`` raises
      ``ValueError("Invalid IPv6 URL")`` on an unbalanced ``[`` in the
      authority (``http://[YOUR-DOMAIN]/x``, Cloudflare's
      ``//[email protected]``, ``ftp://[::1``). The single broad ``try`` in
      ``_extract_links_from_soup`` wrapped the whole anchor loop AND the media
      loop, so every later ``<a>`` and all media links were silently dropped;
      ``_parse_internal_link_edges`` called ``_classify_anchor`` unguarded, so
      a link-graph build died on the first such article.

P15 — the markdown-link regexes terminated at the first ``)``. html2text
      backslash-escapes parens in URLs (``Mercury_\\(planet\\)``) for
      parenthetically-disambiguated Wikipedia titles, so ``[^\\n)]*`` stopped
      mid-construct: bold leaked into link URLs/titles and
      ``_truncate_before_dangling_link`` false-positived on the escaped
      ``\\)`` prefix, leaving unterminated links in snippets.

P22 — ``_join_cell_text`` was rewritten (628fb32) from an iterative
      ``descendants`` walk to a recursive one. ``html.parser`` does not
      auto-close inline tags, so N unclosed ``<i>``/``<span>`` in an infobox
      cell produce an N-deep tree and ``RecursionError`` at ~900 levels —
      failing the whole article render and propagating out of
      ``_extract_infobox`` into summary/toc/structure/section.

P34 — query highlighting never fired for accented terms. ``_split_query_terms``
      folds (NFKD + strip combining + lower) but the pattern was applied to the
      RAW text, so ``query="café"`` highlighted nothing and ``query="cafe"``
      never matched ``Café``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

import pytest
from bs4 import BeautifulSoup

from openzim_mcp.content_processor import (
    _COMPLETE_LINK_RE,
    HTML_PARSER,
    ContentProcessor,
    _classify_anchor,
    _highlight_terms,
    _join_cell_text,
    _truncate_before_dangling_link,
)
from openzim_mcp.zim.structure import _StructureMixin

# An href whose unbalanced '[' makes urlparse raise ValueError.
BAD_HREF = "ftp://[::1"


def _cell(html: str) -> Any:
    node = BeautifulSoup(html, HTML_PARSER).find(["td", "th"])
    assert node is not None
    return node


class TestP4MalformedHrefDoesNotAbortExtraction:
    """P4 — a single unparsable href must not truncate link extraction."""

    def test_bad_href_between_good_anchors_keeps_everything(self) -> None:
        proc = ContentProcessor()
        html = (
            '<a href="/w/A">a</a>'
            f'<a href="{BAD_HREF}">b</a>'
            '<a href="/w/B">c</a>'
            '<img src="i.png">'
        )
        result = proc.extract_html_links(html)
        internal = [link["url"] for link in result["internal_links"]]
        # The anchor AFTER the bad one used to be dropped entirely.
        assert "/w/A" in internal
        assert "/w/B" in internal
        # The unparsable href is classified by the string fallback, not lost.
        assert BAD_HREF in internal
        # The media loop lives after the anchor loop inside the same ``try``,
        # so it was collateral damage too.
        assert [m["url"] for m in result["media_links"]] == ["i.png"]
        # Nothing failed, so no error is reported to the caller. ``bundle``
        # discards the ``error`` key, which is how this shipped as
        # confidently-wrong ``category_totals``.
        assert result.get("error") is None

    def test_cloudflare_obfuscated_mailto_authority(self) -> None:
        proc = ContentProcessor()
        html = (
            '<a href="//[email protected]">x</a>'
            '<a href="https://ok.example/y">y</a>'
            '<img src="j.png">'
        )
        result = proc.extract_html_links(html)
        external = [link["url"] for link in result["external_links"]]
        # Protocol-relative -> external regardless of the unparsable authority.
        assert "//[email protected]" in external
        assert "https://ok.example/y" in external
        assert [m["url"] for m in result["media_links"]] == ["j.png"]
        assert result.get("error") is None

    def test_bracket_authority_still_classified_external(self) -> None:
        """The string fallback must still read the scheme off the href."""
        links_data: Dict[str, Any] = {
            "internal_links": [],
            "external_links": [],
            "media_links": [],
        }
        soup = BeautifulSoup('<a href="http://[YOUR-DOMAIN]/x">d</a>', HTML_PARSER)
        anchor = soup.find("a")
        assert anchor is not None
        _classify_anchor(anchor, links_data)
        assert len(links_data["external_links"]) == 1
        # No authority can be recovered, so the domain degrades to "".
        assert links_data["external_links"][0]["domain"] == ""

    @pytest.mark.parametrize(
        ("href", "bucket", "domain"),
        [
            ("http:example.com", "external_links", ""),
            ("https:/example.com", "external_links", ""),
            ("HTTP://E.com/x", "external_links", "E.com"),
            ("//cdn.x/y", "external_links", "cdn.x"),
            ("/wiki/Foo", "internal_links", None),
            ("#sec", "internal_links", None),
        ],
    )
    def test_existing_classification_unchanged(
        self, href: str, bucket: str, domain: str | None
    ) -> None:
        links_data: Dict[str, Any] = {
            "internal_links": [],
            "external_links": [],
            "media_links": [],
        }
        soup = BeautifulSoup(f'<a href="{href}">t</a>', HTML_PARSER)
        anchor = soup.find("a")
        assert anchor is not None
        _classify_anchor(anchor, links_data)
        assert len(links_data[bucket]) == 1, href
        if domain is not None:
            assert links_data[bucket][0]["domain"] == domain

    def test_parse_internal_link_edges_returns_not_raises(self) -> None:
        html = (
            '<a href="A.html">a</a>'
            f'<a href="{BAD_HREF}">b</a>'
            '<a href="B.html">c</a>'
        )
        edges = _StructureMixin._parse_internal_link_edges(
            html, source_path="Source", archive=None
        )
        targets = [t for t, _ in edges]
        assert "A.html" in targets
        assert "B.html" in targets

    def test_per_anchor_guard_survives_a_raising_classifier(self) -> None:
        """Fix 2 — defence in depth for any other classifier failure."""
        proc = ContentProcessor()
        soup = BeautifulSoup(
            '<a href="/w/A">a</a><a href="/w/boom">b</a>'
            '<a href="/w/B">c</a><img src="i.png">',
            HTML_PARSER,
        )
        real = _classify_anchor

        def exploding(link: Any, links_data: Dict[str, Any]) -> None:
            if link.get("href") == "/w/boom":
                raise RuntimeError("kaboom")
            real(link, links_data)

        import openzim_mcp.content_processor as cp_mod

        original = cp_mod._classify_anchor
        cp_mod._classify_anchor = exploding  # type: ignore[assignment]
        try:
            result = proc._extract_links_from_soup(soup)
        finally:
            cp_mod._classify_anchor = original  # type: ignore[assignment]

        internal = [link["url"] for link in result["internal_links"]]
        assert internal == ["/w/A", "/w/B"]
        assert [m["url"] for m in result["media_links"]] == ["i.png"]
        assert result["error"] == "kaboom"

    def test_link_graph_build_skips_an_exploding_entry(self) -> None:
        """Fix 3 — one bad article must not abort a multi-hour build."""
        from openzim_mcp.linkgraph import builder as builder_mod

        class _Item:
            def __init__(self, html: str) -> None:
                self.content = html.encode()

        class _Entry:
            is_redirect = False

            def __init__(self, path: str, html: str) -> None:
                self.path = path
                self._html = html

            def get_item(self) -> _Item:
                return _Item(self._html)

        class _Archive:
            has_new_namespace_scheme = False
            entry_count = 2

            def _get_entry_by_id(self, entry_id: int) -> _Entry:
                return _Entry(
                    f"C/Article{entry_id}", f'<a href="T{entry_id}.html">t</a>'
                )

        real_parse = _StructureMixin._parse_internal_link_edges

        def exploding(html: str, *, source_path: str, archive: Any) -> Any:
            if source_path == "C/Article0":
                raise ValueError("Invalid IPv6 URL")
            return real_parse(html, source_path=source_path, archive=archive)

        original = _StructureMixin._parse_internal_link_edges
        _StructureMixin._parse_internal_link_edges = staticmethod(  # type: ignore[method-assign]
            exploding
        )
        try:
            out = list(builder_mod.iter_article_links(_Archive()))
        finally:
            _StructureMixin._parse_internal_link_edges = original  # type: ignore[method-assign]

        assert [path for path, _ in out] == ["C/Article1"]


class TestP15EscapedParensInLinks:
    """P15 — only an UNESCAPED ``)`` may close a markdown link."""

    ESCAPED_LINK = '[Mercury](../A/Mercury_\\(planet\\) "Mercury \\(planet\\)")'

    def test_no_bold_leaks_past_an_escaped_paren(self) -> None:
        text = f"{self.ESCAPED_LINK} is the first planet."
        out = _highlight_terms(text, "planet", max_hits=10)
        # The whole link construct — destination AND title — stays verbatim.
        assert self.ESCAPED_LINK in out
        # The prose occurrence outside the link is still highlighted.
        assert "first **planet**" in out

    def test_no_bold_inside_an_escaped_paren_url_path(self) -> None:
        text = '[M](../A/Mercury_\\(planet\\)-orbit "M") and orbit talk'
        out = _highlight_terms(text, "orbit", max_hits=10)
        assert "\\)-**orbit**" not in out
        assert "../A/Mercury_\\(planet\\)-orbit" in out

    def test_complete_link_re_spans_the_whole_construct(self) -> None:
        m = _COMPLETE_LINK_RE.match(self.ESCAPED_LINK)
        assert m is not None
        assert m.group(0) == self.ESCAPED_LINK

    @pytest.mark.parametrize(
        "cut",
        [
            "See [Mercury](../A/Mercury_\\(planet",
            "See [Mercury](../A/Mercury_\\(planet\\",
            'See [Mercury](../A/Mercury_\\(planet\\) "Mercury \\(pla',
            "See [Mercury](../A/Mercury_\\(planet\\)",
        ],
    )
    def test_mid_title_cut_is_truncated_not_kept(self, cut: str) -> None:
        """A cut anywhere inside the construct must drop the fragment."""
        assert _truncate_before_dangling_link(cut) == "See"

    def test_terminated_escaped_link_is_left_alone(self) -> None:
        text = f"See {self.ESCAPED_LINK}"
        assert _truncate_before_dangling_link(text) == text

    def test_plain_prose_parentheticals_still_highlight(self) -> None:
        text = "Photosynthesis (also called assimilation) in plants."
        out = _highlight_terms(text, "assimilation", max_hits=10)
        assert "**assimilation**" in out

    @pytest.mark.parametrize("snippet_length", [64, 70, 80, 85, 86, 92])
    def test_snippet_does_not_end_in_an_unterminated_link(
        self, snippet_length: int
    ) -> None:
        """M3's whole purpose: the cap must never leave a half-written link.

        64/70/80/85 cut AFTER the escaped ``\\)`` in the destination, which is
        exactly where the old ``[^\\n)]*`` regexes reported a *complete* link
        and left the fragment in place. 86/92 cut past the construct's real
        close, so the link must survive intact — pinning the other direction,
        that the repair does not over-truncate a terminated link away.
        """
        proc = ContentProcessor()
        markdown = f"The solar system planet {self.ESCAPED_LINK} orbits the Sun."
        out = proc.create_snippet(
            markdown, query="solar", snippet_length=snippet_length
        )
        # Literal oracle — deliberately NOT the module's own regex. Validating
        # this output with ``_COMPLETE_LINK_RE`` made the test hollow: the old
        # ``[^\n)]*`` body reported the truncated ``[Mercury](..._\(planet\)``
        # fragment as a *complete* link, so the oracle and the defect cancelled
        # and all four lengths passed on precisely the output the test exists
        # to reject. Either the cap dropped the construct entirely, or the
        # whole construct survived — never a half-written one.
        assert "](" not in out or self.ESCAPED_LINK in out, out


class TestP22CellTextIsIterative:
    """P22 — deep inline nesting must not blow the recursion limit."""

    def test_deeply_nested_inline_tags_do_not_recurse(self) -> None:
        html = "<td>" + "<i>" * 3000 + "deep" + "</i>" * 3000 + "</td>"
        assert _join_cell_text(_cell(html)) == "deep"

    def test_deeply_nested_block_tags_do_not_recurse(self) -> None:
        html = "<td>" + "<div>x" * 2000 + "</div>" * 2000 + "</td>"
        out = _join_cell_text(_cell(html))
        assert out.startswith("x; x; x")
        assert out.count("x") == 2000

    def test_unclosed_inline_tags_still_render_the_article(self) -> None:
        """The reachable symptom: the whole compact render fell over.

        ``html.parser`` does not auto-close ``<span>``, so 1500 of them nest
        1500-deep. The recursive walk raised inside ``html_to_plain_text``,
        which then degraded to a bare ``get_text()`` fallback — losing the
        infobox key/value structure for the entire article.
        """
        proc = ContentProcessor()
        html = (
            "<html><body><table class='infobox'><tr><th>Label</th>"
            "<td>" + "<span>" * 1500 + "value" + "</td></tr></table>"
            "<p>Body paragraph.</p></body></html>"
        )
        out = proc.process_mime_content(html.encode(), "text/html", compact=True)
        assert "maximum recursion depth exceeded" not in out
        assert "**Label:** value" in out
        assert "Body paragraph." in out

    @pytest.mark.parametrize(
        ("html", "expected"),
        [
            # Inline number separators must NOT gain whitespace.
            ("<td>3<span>,</span>913<span>,</span>644</td>", "3,913,644"),
            # <wbr> unit microformats.
            ("<td>891<wbr>.<wbr>3</td>", "891.3"),
            # Coordinate templates.
            ("<td>52<span>°</span>31<span>′</span>N</td>", "52°31′N"),
            # <br> splits multi-value cells.
            (
                "<td>5th in Europe<br>1st in Germany</td>",
                "5th in Europe; 1st in Germany",
            ),
            # The close-sentinel case 628fb32 existed to fix.
            (
                "<td><div>5th in Europe</div>1st in Germany</td>",
                "5th in Europe; 1st in Germany",
            ),
            # Comments are filtered before the string path.
            ("<td>3<!-- a-template -->,913,644</td>", "3,913,644"),
            # Nested <ul>/<li>.
            ("<td><ul><li>alpha</li><li>beta</li></ul></td>", "alpha; beta"),
            # Nested tables.
            (
                "<td><table><tr><td>a</td><td>b</td></tr>"
                "<tr><td>c</td></tr></table></td>",
                "a; b; c",
            ),
            # Empty-wrapper-only cells emit no stray separators.
            ("<td><div></div><div>  </div></td>", ""),
            ("<td><div><span></span></div></td>", ""),
            # Inline spans still concatenate with their literal whitespace.
            ("<td><span>New</span><span> </span><span>York</span></td>", "New York"),
        ],
    )
    def test_pinned_behaviours_are_byte_identical(
        self, html: str, expected: str
    ) -> None:
        assert _join_cell_text(_cell(html)) == expected

    def test_extract_infobox_failure_degrades_to_none(self) -> None:
        from openzim_mcp import bundle as bundle_mod

        class _Exploding:
            def extract_infobox(self, soup: Any) -> List[Dict[str, str]]:
                raise RecursionError("maximum recursion depth exceeded")

        soup = BeautifulSoup("<table class='infobox'></table>", HTML_PARSER)
        assert bundle_mod._extract_infobox(soup, _Exploding()) is None  # type: ignore[arg-type]


class TestP34AccentFoldedHighlighting:
    """P34 — highlighting must fold the haystack the way the query is folded."""

    def test_accented_query_highlights_accented_text(self) -> None:
        out = _highlight_terms("Le café est ouvert.", "café", max_hits=10)
        assert "**café**" in out

    def test_unaccented_query_highlights_accented_text(self) -> None:
        out = _highlight_terms("Le Café est ouvert.", "cafe", max_hits=10)
        # Original casing AND accents are preserved in the output.
        assert "**Café**" in out

    def test_accented_query_highlights_unaccented_text(self) -> None:
        out = _highlight_terms("The cafe is open.", "café", max_hits=10)
        assert "**cafe**" in out

    def test_umlaut_term(self) -> None:
        out = _highlight_terms("Zürich is in Switzerland.", "Zürich", max_hits=10)
        assert "**Zürich**" in out

    def test_ascii_highlighting_unchanged(self) -> None:
        out = _highlight_terms(
            "The Theory of relativity by Einstein.", "relativity einstein", max_hits=10
        )
        assert out == "The Theory of **relativity** by **Einstein**."

    def test_max_hits_still_counts_from_the_left(self) -> None:
        out = _highlight_terms("café café café", "café", max_hits=2)
        assert out == "**café** **café** café"

    def test_accented_term_inside_a_link_is_still_protected(self) -> None:
        text = "[](../A/Café.jpg)Café is a place."
        out = _highlight_terms(text, "café", max_hits=10)
        assert "](../A/Café.jpg)" in out
        assert out.count("**") == 2

    def test_word_boundaries_still_apply(self) -> None:
        out = _highlight_terms("cafeteria and café", "café", max_hits=10)
        assert "**cafeteria**" not in out
        assert "**café**" in out

    def test_ligature_expansion_maps_back_to_the_source_character(self) -> None:
        """``_fold`` is not length-preserving: ``ﬁ`` folds to two chars."""
        out = _highlight_terms("The ﬁle is here.", "file", max_hits=10)
        assert "**ﬁle**" in out

    def test_snippet_highlights_accented_query(self) -> None:
        proc = ContentProcessor()
        markdown = "Intro paragraph.\n\nZürich is the largest city in Switzerland."
        out = proc.create_snippet(markdown, query="Zürich")
        assert "**Zürich**" in out

    def test_no_stray_markers_when_nothing_matches(self) -> None:
        text = "Nothing relevant here."
        assert _highlight_terms(text, "café", max_hits=10) == text
        assert not re.search(r"\*\*", _highlight_terms(text, "café", max_hits=10))
