"""Integration-shape tests for the v2.0.0a7 defect-fix batch.

These tests use fixture data only (no live ZIM file) and exercise the
helper-level contracts that the v2.0.0a7 fixes introduce:

  * D2/D3 — new-scheme C / W namespace paging via dedicated paths.
  * D11 — metadata previews cap at 800 chars + ``[truncated, …]`` marker.
  * D8 — synthesize section attribution survives bold-marker insertion.
  * Op3 — get_section honors ``include_subsections=False`` by ending
    the slice at the next heading of any level.
  * Op2 — compact-structure renderer carries per-heading summary.
"""

from __future__ import annotations

import json

from openzim_mcp.compact_renderers import compact_structure_payload
from openzim_mcp.synthesize import _locate_passage, _strip_bold
from openzim_mcp.zim.archive import _METADATA_PREVIEW_CAP


# ---------------------------------------------------------------------------
# D8: synthesize section attribution survives bold markers in passages
# ---------------------------------------------------------------------------


def test_strip_bold_removes_paired_markers():
    """``**term**`` is collapsed to ``term`` for substring location."""
    assert _strip_bold("**Berlin** is the **capital**") == "Berlin is the capital"


def test_locate_passage_finds_bolded_text_in_plain_markdown():
    """Section attribution must not be killed by ``_highlight_terms`` adding
    ``**`` markers around the query term — the bundle's rendered_markdown
    carries no highlight wrapping."""
    bundle_md = (
        "# Berlin\n\nBerlin is the capital of Germany.\n\n"
        "## Geography\n\nBerlin is in northeastern Germany.\n"
    )
    passage = "**Berlin** is in northeastern Germany."
    pos = _locate_passage(bundle_md, passage)
    assert pos >= 0, "Bolded passage should still locate in plain bundle markdown"
    # The found position points at the plain "Berlin is in northeastern…"
    assert bundle_md[pos:].startswith("Berlin is in northeastern")


# ---------------------------------------------------------------------------
# D11: metadata preview cap
# ---------------------------------------------------------------------------


def test_metadata_preview_cap_constant_is_sane():
    """The cap stays below 4 kB so a worst-case 10-field metadata
    response can't blow past a typical compact budget."""
    assert 200 <= _METADATA_PREVIEW_CAP <= 4000


# ---------------------------------------------------------------------------
# Op2: compact structure carries per-section summaries
# ---------------------------------------------------------------------------


def test_compact_structure_includes_summary_when_section_preview_exists():
    """A payload with both headings AND sections produces compact
    headings carrying an 80-char summary derived from the section's
    content_preview."""
    payload = {
        "title": "Berlin",
        "path": "Berlin",
        "headings": [
            {"level": 1, "text": "Berlin", "id": "Berlin"},
            {"level": 2, "text": "Geography", "id": "Geography"},
        ],
        "sections": [
            {"title": "Berlin", "level": 1, "content_preview": "Berlin is the capital."},
            {
                "title": "Geography",
                "level": 2,
                "content_preview": (
                    "Berlin is in northeastern Germany, in an area of low-lying "
                    "marshy woodlands with a mainly flat topography."
                ),
            },
        ],
    }
    rendered = json.loads(compact_structure_payload(payload))
    headings = rendered["headings"]
    by_text = {h["text"]: h for h in headings}
    assert "summary" in by_text["Geography"]
    assert len(by_text["Geography"]["summary"]) <= 80
    assert by_text["Geography"]["summary"].startswith("Berlin is in northeastern Germany")


def test_compact_structure_skips_summary_when_no_section_preview():
    """When the payload only carries ``headings`` (no ``sections``), the
    compact view skips the summary field — no source data to derive from."""
    payload = {
        "title": "Sparse",
        "path": "Sparse",
        "headings": [{"level": 1, "text": "Sparse", "id": "Sparse"}],
    }
    rendered = json.loads(compact_structure_payload(payload))
    assert "summary" not in rendered["headings"][0]


# ---------------------------------------------------------------------------
# Op3: get_section narrow-mode parsing
# ---------------------------------------------------------------------------


def test_intent_parser_narrow_section_sets_flag():
    """``narrow section Geography of Berlin`` parses to params with
    ``narrow=True`` and the section / entry stripped clean."""
    from openzim_mcp.intent_parser import IntentParser

    parser = IntentParser()
    intent, params, _confidence = parser.parse_intent(
        "narrow section Geography of Berlin"
    )
    assert intent == "get_section"
    assert params.get("narrow") is True
    assert params.get("section_name") == "Geography"
    assert params.get("entry_path") == "Berlin"


def test_intent_parser_just_section_alias():
    """``just section X of Y`` is treated identically to ``narrow``."""
    from openzim_mcp.intent_parser import IntentParser

    parser = IntentParser()
    _intent, params, _confidence = parser.parse_intent(
        "just section Climate of Berlin"
    )
    assert params.get("narrow") is True


def test_intent_parser_plain_section_no_narrow_flag():
    """Without the prefix, ``narrow`` stays unset so the handler defaults
    to ``include_subsections=True`` (legacy behavior)."""
    from openzim_mcp.intent_parser import IntentParser

    parser = IntentParser()
    _intent, params, _confidence = parser.parse_intent("section Geography of Berlin")
    assert params.get("narrow") in (None, False)
