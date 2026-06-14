"""Real-world-test regressions for article structure / section handling."""

from __future__ import annotations

from openzim_mcp.zim.structure import _section_preview


def test_section_preview_is_bounded_by_char_end():
    """A section's preview must stop at ``char_end`` (the next equal-or-
    higher-level heading) instead of bleeding a fixed window into the
    following section.
    """
    # "AAAA" is section content [0:4]; char_end=4 is the start of the next
    # section's heading "## NEXT".
    md = "AAAA## NEXT\n\nBBBB body of next section"
    out = _section_preview(md, char_start=0, char_end=4, preview_chars=300)
    assert out == "AAAA"
    assert "NEXT" not in out


def test_section_preview_still_capped_at_preview_chars():
    md = "x" * 1000
    out = _section_preview(md, char_start=0, char_end=1000, preview_chars=300)
    assert len(out) == 300


# ---------------------------------------------------------------------------
# "get article X section Y" must route to get_section (it previously
# mis-routed to `structure` and errored "Cannot find entry").
# ---------------------------------------------------------------------------

from openzim_mcp.intent_parser import IntentParser  # noqa: E402


def test_get_article_section_suffix_routes_to_get_section():
    intent, params, _cert = IntentParser.parse_intent(
        "get article Quantum computing section History"
    )
    assert intent == "get_section", (intent, params)
    assert (params.get("entry_path") or "").lower() == "quantum computing"
    assert (params.get("section_name") or "").lower() == "history"


def test_plain_path_section_suffix_routes_to_get_section():
    intent, params, _cert = IntentParser.parse_intent("Biology section Evolution")
    assert intent == "get_section", (intent, params)
    assert (params.get("entry_path") or "").lower() == "biology"
    assert (params.get("section_name") or "").lower() == "evolution"


def test_existing_section_of_form_still_works():
    intent, params, _cert = IntentParser.parse_intent("section Evolution of Biology")
    assert intent == "get_section"
    assert (params.get("section_name") or "").lower() == "evolution"
    assert (params.get("entry_path") or "").lower() == "biology"


# ---------------------------------------------------------------------------
# show structure: budget-aware rendering must stay valid JSON and never
# silently chop the heading skeleton mid-string.
# ---------------------------------------------------------------------------

import json  # noqa: E402

from openzim_mcp.compact_renderers import compact_structure_payload  # noqa: E402


def _structure_payload(n: int):
    headings = [
        {"level": 2, "text": f"Section number {i} with a longish title", "id": f"s{i}"}
        for i in range(n)
    ]
    sections = [
        {"title": h["text"], "level": 2, "content_preview": "summary prose " * 8}
        for h in headings
    ]
    return {"title": "Big", "path": "Big", "headings": headings, "sections": sections}


def test_structure_keeps_all_headings_and_valid_json_within_budget():
    out = compact_structure_payload(_structure_payload(48), budget=5000)
    data = json.loads(out)  # must be valid JSON, not a severed string
    assert len(data["headings"]) == 48  # full skeleton preserved
    assert len(out) <= 5000


def test_structure_records_omitted_when_even_skeleton_too_big():
    out = compact_structure_payload(_structure_payload(48), budget=800)
    data = json.loads(out)  # still valid JSON
    assert len(out) <= 800
    assert len(data["headings"]) < 48
    # The drop is reported, not silent.
    assert data["headings_omitted"] == 48 - len(data["headings"])


def test_structure_no_budget_returns_full_with_summaries():
    out = compact_structure_payload(_structure_payload(3))
    data = json.loads(out)
    assert len(data["headings"]) == 3
    assert any("summary" in h for h in data["headings"])
