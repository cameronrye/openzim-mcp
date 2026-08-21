"""Rendering-fidelity fixes from the v3.0.0 sweep.

Three independent output defects, all in the "what the caller actually
sees" layer:

* ``_truncate_search_snippets`` cut compact-search snippets at a hard
  250-char boundary without running the truncation repairs its two
  sibling cut sites in ``create_snippet`` both run, so a cut landing
  inside a ``**bold**`` run (query highlight or infobox ``**Label:**``)
  emitted an unpaired marker.
* ``_heading_visible_text`` concatenated HTML comment bodies into the
  heading text whenever the heading also carried an unwanted-selector
  descendant, so the heading no longer matched the rendered markdown
  and its whole section was dropped from the bundle.
* The ``include_subsections=False`` "essentially no body" test added the
  heading line's length to its budget even though the measured slice
  starts past the heading, so a long-titled section swallowed the first
  subsection the caller had explicitly asked to exclude.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

from openzim_mcp import content_processor as cp
from openzim_mcp.compact_format import _CompactFormatMixin

_SEARCH_HEAD = (
    'Found 1 matches for "population", showing 1-1:\n\n'
    "## 1. Berlin\n"
    "Path: Berlin\n"
)
_SEARCH_TAIL = "\n\n---\nShowing 1-1 of 1 (end of results)\n"


def _rendered_search(snippet: str) -> str:
    return f"{_SEARCH_HEAD}Snippet: {snippet}{_SEARCH_TAIL}"


class TestSnippetCapRepairsTruncationDamage:
    """``_CompactFormatMixin._truncate_search_snippets`` — the 250-char cap
    must leave well-formed markdown behind, like ``create_snippet`` does.
    """

    def test_cap_inside_a_bold_run_leaves_no_unpaired_marker(self) -> None:
        # The cap lands inside "**population**": 240 filler chars, a
        # space, then the opening marker at offset 241.
        snippet = (
            "A" * 240 + " **population** and more prose that runs well past the cap."
        )
        out = _CompactFormatMixin._truncate_search_snippets(
            _rendered_search(snippet), max_chars=250
        )

        assert out.count("**") % 2 == 0, "cap emitted an unpaired bold marker"
        assert "**populat" not in out
        # Still capped, and still marked as truncated.
        assert "runs well past the cap" not in out
        assert "..." in out

    def test_cap_inside_a_markdown_link_drops_the_dangling_fragment(self) -> None:
        # The cap lands inside the link target, leaving "[Berlin](https".
        snippet = (
            "B" * 235 + " [Berlin](https://example.com/Berlin) and trailing prose."
        )
        out = _CompactFormatMixin._truncate_search_snippets(
            _rendered_search(snippet), max_chars=250
        )

        assert "](" not in out, "cap emitted a half-written markdown link"
        assert "[Berlin]" not in out
        assert "..." in out

    def test_infobox_label_run_split_by_the_cap_is_repaired(self) -> None:
        # Compact mode prepends the infobox as "**Label:** value" lines;
        # a cut inside one of those labels is the common real-world case.
        snippet = (
            "**Population:** 3,850,809\n"
            "**Country:** Germany\n"
            "**Mayor:** Kai Wegner\n"
            + "filler word " * 14
            + "\n**Postal codes:** 10115"
        )
        out = _CompactFormatMixin._truncate_search_snippets(
            _rendered_search(snippet), max_chars=250
        )

        assert out.count("**") % 2 == 0, "cap emitted an unpaired bold marker"

    def test_short_snippets_and_plain_text_caps_are_unchanged(self) -> None:
        short = _rendered_search("Short snippet.")
        assert _CompactFormatMixin._truncate_search_snippets(short, 250) == short

        plain = _rendered_search("x" * 1000)
        out = _CompactFormatMixin._truncate_search_snippets(plain, 250)
        assert out.startswith(f"{_SEARCH_HEAD}Snippet: " + "x" * 250 + "...")


def _heading(html: str):
    tag = BeautifulSoup(html, "html.parser").find(["h1", "h2", "h3"])
    assert tag is not None
    return tag


class TestHeadingTextExcludesComments:
    """``content_processor._heading_visible_text`` — the cleanup branch must
    agree with the ``get_text()`` branch about comments.
    """

    def test_comment_is_not_concatenated_into_heading_text(self) -> None:
        heading = _heading(
            "<h2>History<!-- mw-cite -->"
            '<span class="mw-editsection">[edit]</span></h2>'
        )
        assert cp._heading_visible_text(heading) == "History"

    def test_comment_only_heading_yields_no_text(self) -> None:
        heading = _heading(
            '<h2><!-- placeholder --><span class="mw-editsection">[edit]</span></h2>'
        )
        assert cp._heading_visible_text(heading) == ""

    def test_commented_heading_keeps_its_section_in_the_bundle(self) -> None:
        from openzim_mcp.bundle import _compute_section_offsets

        html = (
            "<h1>Berlin</h1><p>Berlin is the capital of Germany.</p>"
            "<h2>History<!-- mw-cite -->"
            '<span class="mw-editsection">[edit]</span></h2>'
            "<p>Founded in the 13th century.</p>"
            '<h2>Geography<span class="mw-editsection">[edit]</span></h2>'
            "<p>Berlin lies in northeastern Germany.</p>"
        )
        rendered = (
            "# Berlin\n\nBerlin is the capital of Germany.\n\n"
            "## History\n\nFounded in the 13th century.\n\n"
            "## Geography\n\nBerlin lies in northeastern Germany.\n"
        )
        headings = cp._build_headings(BeautifulSoup(html, "html.parser"))
        sections = _compute_section_offsets(rendered, headings)

        titles = [s["title"] for s in sections]
        assert titles == ["Berlin", "History", "Geography"]
        # ... and it owns its own body rather than leaving it to be
        # absorbed by the preceding section's slice.
        history = sections[1]
        assert (
            rendered[history["char_start"] : history["char_end"]]
            == "Founded in the 13th century.\n\n"
        )


_LEAD = "Short lead paragraph here about it, roughly sixty chars.\n"
_CHILD_BODY = "Child body text goes here and is quite long indeed.\n"


def _narrow_bundle(title: str) -> dict:
    md = (
        f"## {title}\n"
        f"{_LEAD}"
        "### Details\n"
        f"{_CHILD_BODY}"
        "## Next\n"
        "Next section body.\n"
    )
    next_heading = md.index("## Next")
    return {
        "entry_path": "Berlin",
        "title": "Berlin",
        "content_type": "text/html",
        "rendered_markdown": md,
        "sections": [
            {
                "id": "target",
                "title": title,
                "level": 2,
                "heading_start": 0,
                "char_start": md.index(_LEAD),
                "char_end": next_heading,
                "parent_id": None,
            },
            {
                "id": "Details",
                "title": "Details",
                "level": 3,
                "heading_start": md.index("### Details"),
                "char_start": md.index(_CHILD_BODY),
                "char_end": next_heading,
                "parent_id": "target",
            },
            {
                "id": "Next",
                "title": "Next",
                "level": 2,
                "heading_start": next_heading,
                "char_start": md.index("Next section body."),
                "char_end": len(md),
                "parent_id": None,
            },
        ],
        "links": {"internal": [], "external": [], "media": []},
        "infobox": None,
    }


def _run_narrow(bundle: dict) -> dict:
    import openzim_mcp.bundle as _bundle_mod
    from tests.test_get_section_d5_widen_v2a9 import _stub_structure_mixin

    mixin = _stub_structure_mixin()
    original = _bundle_mod.get_or_build_bundle
    _bundle_mod.get_or_build_bundle = lambda *a, **kw: bundle  # type: ignore[assignment]
    try:
        return mixin._get_section_data(
            archive=MagicMock(),
            validated_path=Path("/fake.zim"),
            entry_path="Berlin",
            section_id="target",
            max_chars=None,
            include_subsections=False,
        )
    finally:
        _bundle_mod.get_or_build_bundle = original  # type: ignore[assignment]


class TestNarrowEmptyBodyTestIgnoresTitleLength:
    """``_StructureMixin._get_section_data`` — the "essentially no body"
    budget must measure the body slice only, not the title's length.
    """

    @pytest.mark.parametrize(
        "title",
        [
            "Impact",
            "Environmental impact and sustainability considerations",
        ],
    )
    def test_lead_prose_is_never_widened_to_the_first_child(self, title: str) -> None:
        result = _run_narrow(_narrow_bundle(title))

        assert result["content_markdown"] == _LEAD
        assert "### Details" not in result["content_markdown"]
        assert result.get("narrow_widened_to_first_child") is not True

    def test_title_length_does_not_change_the_narrow_slice(self) -> None:
        short = _run_narrow(_narrow_bundle("Impact"))
        long = _run_narrow(
            _narrow_bundle("Environmental impact and sustainability considerations")
        )
        assert short["content_markdown"] == long["content_markdown"]

    def test_genuinely_empty_body_still_widens(self) -> None:
        """The D5 widening itself must survive: a section whose heading is
        immediately followed by a subheading still gets the child's lead.
        """
        md = "## Geography\n### Topography\nBerlin lies on a flat plain.\n"
        bundle = {
            "entry_path": "Berlin",
            "title": "Berlin",
            "content_type": "text/html",
            "rendered_markdown": md,
            "sections": [
                {
                    "id": "target",
                    "title": "Geography",
                    "level": 2,
                    "heading_start": 0,
                    "char_start": md.index("### Topography"),
                    "char_end": len(md),
                    "parent_id": None,
                },
                {
                    "id": "Topography",
                    "title": "Topography",
                    "level": 3,
                    "heading_start": md.index("### Topography"),
                    "char_start": md.index("Berlin lies"),
                    "char_end": len(md),
                    "parent_id": "target",
                },
            ],
            "links": {"internal": [], "external": [], "media": []},
            "infobox": None,
        }
        result = _run_narrow(bundle)

        assert "flat plain" in result["content_markdown"]
        assert result.get("narrow_widened_to_first_child") is True
