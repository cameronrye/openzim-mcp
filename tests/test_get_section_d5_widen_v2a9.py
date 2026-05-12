"""Tests for the v2.0.0a9 D5 fix: ``include_subsections=False`` widens
to the first child subsection when the section has no lead prose.

Live a8 testing showed ``narrow section Geography of Berlin`` returning
just the H2 heading + a single H3 subheading line, because the Geography
section opens directly with a ``### Topography`` subsection with no
lead paragraph between the H2 and H3. The D5 fix detects this and
widens to the end of the first child subsection so the caller gets
actual content; ``narrow_widened_to_first_child=True`` flags the
widening so the caller knows what happened.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from openzim_mcp.zim.structure import _StructureMixin


def _stub_structure_mixin():
    """Build a minimal _StructureMixin instance for unit testing."""

    class _Stub(_StructureMixin):
        def __init__(self):
            self.cache = MagicMock()
            self.cache.get = lambda k: None
            self.cache.set = lambda k, v: None
            self.content_processor = MagicMock()
            config = MagicMock()
            config.content.max_content_length = 8000
            self.config = config

    return _Stub()


def _run_get_section_against_stub_bundle(bundle: dict) -> dict:
    """Stub the bundle module's ``get_or_build_bundle`` to return ``bundle``,
    then call ``_get_section_data`` on a stub mixin and return the result.

    The stub-restore-in-finally pattern is the same across every D5 test;
    keeping it in one place avoids drift and the indentation hazards that
    raw try/finally blocks invite.
    """
    import openzim_mcp.bundle as _bundle_mod

    mixin = _stub_structure_mixin()
    original_get_or_build = _bundle_mod.get_or_build_bundle
    _bundle_mod.get_or_build_bundle = lambda *a, **kw: bundle  # type: ignore[assignment]
    try:
        return mixin._get_section_data(
            archive=MagicMock(),
            validated_path=Path("/fake.zim"),
            entry_path="Berlin",
            section_id="Geography",
            max_chars=None,
            include_subsections=False,
        )
    finally:
        _bundle_mod.get_or_build_bundle = original_get_or_build  # type: ignore[assignment]


def test_narrow_widens_to_first_child_when_no_lead():
    """Geography H2 with no lead paragraph (opens directly with H3) →
    narrow scope widens to the end of the first child H3 (Topography).
    """
    bundle = {
        "entry_path": "Berlin",
        "title": "Berlin",
        "rendered_markdown": (
            "## Geography\n"
            "### Topography\n"
            "Berlin is in northeastern Germany on a flat plain.\n"
            "### Climate\n"
            "Berlin has an oceanic climate.\n"
        ),
        "sections": [
            {
                "id": "Geography",
                "title": "Geography",
                "level": 2,
                "char_start": 0,
                "char_end": 110,  # extends through both H3s
                "parent_id": None,
            },
            {
                "id": "Topography",
                "title": "Topography",
                "level": 3,
                "char_start": 13,  # right after "## Geography\n"
                "char_end": 70,  # ends at "### Climate"
                "parent_id": "Geography",
            },
            {
                "id": "Climate",
                "title": "Climate",
                "level": 3,
                "char_start": 70,
                "char_end": 110,
                "parent_id": "Geography",
            },
        ],
        "links": {"internal": [], "external": [], "media": []},
        "infobox": None,
    }
    result = _run_get_section_against_stub_bundle(bundle)

    # The body must include Topography's text — D5 widened to the
    # first child.
    assert "Berlin is in northeastern Germany" in result["content_markdown"]
    # The widening must be flagged so the caller knows.
    assert result.get("narrow_widened_to_first_child") is True
    # And the Climate H3 (the SECOND child) must NOT appear — we only
    # widened to the FIRST child.
    assert "oceanic climate" not in result["content_markdown"]


def test_narrow_returns_lead_when_section_has_lead_prose():
    """When the section has substantive lead prose before the first
    subheading, narrow scope returns just the lead — no widening.
    """
    bundle = {
        "entry_path": "Berlin",
        "title": "Berlin",
        "rendered_markdown": (
            "## Geography\n"
            "Berlin is in northeastern Germany on a flat plain that stretches "
            "from the North Sea coast to the Carpathians.\n"
            "### Topography\n"
            "Detailed topography content.\n"
        ),
        "sections": [
            {
                "id": "Geography",
                "title": "Geography",
                "level": 2,
                "char_start": 0,
                "char_end": 200,
                "parent_id": None,
            },
            {
                "id": "Topography",
                "title": "Topography",
                "level": 3,
                "char_start": 130,
                "char_end": 200,
                "parent_id": "Geography",
            },
        ],
        "links": {"internal": [], "external": [], "media": []},
        "infobox": None,
    }
    result = _run_get_section_against_stub_bundle(bundle)
    # Body has the lead prose ...
    assert "northeastern Germany" in result["content_markdown"]
    # ... but NOT the Topography subsection.
    assert "Detailed topography" not in result["content_markdown"]
    # And NOT flagged as widened.
    assert result.get("narrow_widened_to_first_child") is not True
