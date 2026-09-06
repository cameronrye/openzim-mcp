"""Real-world sweep fixes for the intent-parser / simple-tools surface.

Every test here drives the real object end to end — ``handle_zim_query``
(which runs ``IntentParser.parse_intent`` and the dispatcher for real) or
``synthesize_query`` — and asserts on the RENDERED output, so the wiring
is covered rather than a renderer called with a hand-supplied kwarg.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

from openzim_mcp.exceptions import OpenZimMcpArchiveError
from openzim_mcp.simple_tools import SimpleToolsHandler

# ---------------------------------------------------------------------------
# fid 46 / fid 57 — ``section <name> of <path>`` resolution
# ---------------------------------------------------------------------------

_ARISTOTLE_PATH = "iep.utm.edu/aristotle/"

_ARISTOTLE_HEADINGS: List[Dict[str, Any]] = [
    {"level": 1, "text": "Aristotle (384 B.C.E.-322 B.C.E.)", "id": "h0"},
    {"level": 2, "text": "Table of Contents", "id": "toc"},
    {"level": 2, "text": "1. Life and Lost Works", "id": "h1"},
    {"level": 2, "text": "a. The Meaning and Purpose of Logic", "id": "h2"},
]

_ARISTOTLE_BODIES = {
    "toc": "1. Life and Lost Works\n2. Analytics or Logic\n3. Metaphysics",
    "h1": "Aristotle was born in Stagira in north Greece.",
    "h2": "Logic for Aristotle is the instrument of the sciences.",
}


def _iep_handler(
    *,
    content_type: str = "text/html",
    headings: Optional[List[Dict[str, Any]]] = None,
    entry_path: str = _ARISTOTLE_PATH,
) -> Tuple[SimpleToolsHandler, MagicMock]:
    """A one-archive handler whose only loadable entry is ``entry_path``.

    Any other path raises the way a real archive does for an entry that
    is not there, which is what makes the mis-split ``entry_path`` of
    ``section Table of Contents of <path>`` observable.
    """
    ops = MagicMock()
    ops.list_zim_files_data.return_value = [{"path": "/zim/iep.zim"}]
    ops.config.tool_mode = "simple"
    live_headings = _ARISTOTLE_HEADINGS if headings is None else headings

    def _structure(_zim: str, path: str) -> Dict[str, Any]:
        if path != entry_path:
            raise OpenZimMcpArchiveError(f"Entry not found: {path}")
        return {
            "title": "Aristotle",
            "path": path,
            "content_type": content_type,
            "headings": live_headings,
        }

    def _section(_zim: str, _entry: str, section_id: str, **_kw: Any) -> Dict[str, Any]:
        body = _ARISTOTLE_BODIES.get(section_id)
        if body is None:
            return {"error": True, "message": f"no section {section_id!r}"}
        return {"content_markdown": body, "section_id": section_id}

    ops.get_article_structure_data.side_effect = _structure
    ops.get_section_data.side_effect = _section
    return SimpleToolsHandler(ops), ops


def test_section_name_containing_of_reaches_the_section() -> None:
    """fid 46: a section name the tool's own miss-list prints back.

    ``Table of Contents`` splits at the first `` of ``, so pre-fix the
    dispatcher looked up an article called ``contents of
    iep.utm.edu/aristotle/`` and blamed the path.
    """
    handler, ops = _iep_handler()
    out = handler.handle_zim_query(
        f"section Table of Contents of {_ARISTOTLE_PATH}",
        zim_file_path="/zim/iep.zim",
    )
    assert "# Table of Contents" in out
    assert "2. Analytics or Logic" in out
    assert "Could not load article" not in out
    section_ids = [c.args[2] for c in ops.get_section_data.call_args_list]
    assert section_ids == ["toc"]


def test_section_name_with_two_connectors_reaches_the_section() -> None:
    """fid 46: two `` of ``s in the name — the split must walk both."""
    handler, _ = _iep_handler()
    out = handler.handle_zim_query(
        f"section a. The Meaning and Purpose of Logic of {_ARISTOTLE_PATH}",
        zim_file_path="/zim/iep.zim",
    )
    assert "# a. The Meaning and Purpose of Logic" in out
    assert "instrument of the sciences" in out
    assert "Could not load article" not in out


def test_quoted_section_name_does_not_leak_its_closing_quote() -> None:
    """fid 46: the documented escape hatch. Pre-fix the closing quote rode
    into the path (``entry_path='contents" of iep.utm.edu/aristotle/'``).
    """
    from openzim_mcp.intent_parser import IntentParser

    intent, params, _ = IntentParser.parse_intent(
        f'section "Table of Contents" of {_ARISTOTLE_PATH}'
    )
    assert intent == "get_section"
    assert params["section_name"] == "table of contents"
    assert params["entry_path"] == _ARISTOTLE_PATH
    assert '"' not in params["entry_path"]

    handler, _ = _iep_handler()
    out = handler.handle_zim_query(
        f'section "Table of Contents" of {_ARISTOTLE_PATH}',
        zim_file_path="/zim/iep.zim",
    )
    assert "# Table of Contents" in out


def test_unambiguous_single_connector_split_is_unchanged() -> None:
    """The parser's own split still wins when it resolves — no candidate
    walk may steal a name that already matches."""
    handler, ops = _iep_handler()
    out = handler.handle_zim_query(
        f"section 1. Life and Lost Works of {_ARISTOTLE_PATH}",
        zim_file_path="/zim/iep.zim",
    )
    assert "# 1. Life and Lost Works" in out
    assert "born in Stagira" in out
    assert ops.get_article_structure_data.call_count == 1


def test_unresolvable_section_reference_still_reports_the_parsed_path() -> None:
    """A genuinely missing article keeps the old diagnosis (and does not
    silently succeed against some other split)."""
    handler, _ = _iep_handler()
    out = handler.handle_zim_query(
        "section Life of iep.utm.edu/nosuchpage/",
        zim_file_path="/zim/iep.zim",
    )
    assert "Could not load article `iep.utm.edu/nosuchpage/`" in out


def test_section_of_a_binary_entry_points_at_the_binary_fetch() -> None:
    """fid 57: an image has no headings for a reason ``tell me about``
    cannot fix — the one route that can never return its bytes."""
    handler, _ = _iep_handler(
        content_type="image/jpeg",
        headings=[],
        entry_path="iep.utm.edu/wp-content/media/anselm.jpg",
    )
    out = handler.handle_zim_query(
        "section Life of iep.utm.edu/wp-content/media/anselm.jpg",
        zim_file_path="/zim/iep.zim",
    )
    assert "image/jpeg" in out
    assert "get binary content of" in out
    assert "for the full body" not in out


def test_html_article_without_headings_keeps_the_full_body_advice() -> None:
    """Pair for the negative above: the non-binary arm is untouched."""
    handler, _ = _iep_handler(content_type="text/html", headings=[])
    out = handler.handle_zim_query(
        f"section Life of {_ARISTOTLE_PATH}",
        zim_file_path="/zim/iep.zim",
    )
    assert "No sections found" in out
    assert f"tell me about {_ARISTOTLE_PATH}" in out
    assert "get binary content of" not in out


# ---------------------------------------------------------------------------
# fid 7 / fid 42 / fid 56 — the ambiguous-archive ("No ZIM File Specified") gate
# ---------------------------------------------------------------------------

_LIBRARY_DIR = "/Users/tester/Developer/kiwix-library/archives"
_LIBRARY_NAMES = [
    "wikipedia_en_all_maxi_2024-01",
    "wiktionary_en_all_nopic_2024-02",
    "wikivoyage_en_all_maxi_2024-03",
    "stackoverflow.com_en_all_2024-04",
    "medlineplus.gov_en_all_2025-01",
    "internet-encyclopedia-philosophy_en_all_2025-06",
    "gutenberg_en_all_2024-05",
    "wikibooks_en_all_maxi_2024-06",
    "wikiquote_en_all_maxi_2024-07",
    "wikisource_en_all_maxi_2024-08",
    "phet_en_2024-09",
    "ted_en_all_2024-10",
]


def _library_handler(names: Optional[List[str]] = None) -> SimpleToolsHandler:
    """A handler with a multi-archive library loaded and no auto-select."""
    ops = MagicMock()
    ops.config.tool_mode = "simple"
    ops.config.meta.footer_enabled = True
    entries = [
        {
            "name": f"{n}.zim",
            "path": f"{_LIBRARY_DIR}/{n}.zim",
            "directory": _LIBRARY_DIR,
            "size": "1854.75 MB",
            "size_bytes": 1944841111,
            "modified": "2026-05-01T16:34:00.117549",
            "readable": True,
        }
        for n in (names if names is not None else _LIBRARY_NAMES)
    ]
    ops.list_zim_files_data.return_value = entries
    ops.list_zim_files.return_value = repr(entries)
    return SimpleToolsHandler(ops)


def test_gate_honours_the_compact_budget() -> None:
    """fid 7: the gate used to ``return`` before the compact cap, so
    ``compact_budget`` was inert on the default mode's most-emitted
    response."""
    handler = _library_handler()
    opts = {"compact": True, "compact_budget": 500}
    out = handler.handle_zim_query("tell me about photosynthesis", options=opts)
    assert isinstance(out, str)
    assert len(out) <= 900, len(out)
    # …and it really is the gate, capped — not some other short response.
    assert "No ZIM File Specified" in out
    assert "Response truncated" in out


def test_gate_goes_through_the_finalize_pipeline() -> None:
    """fid 7: the missing ``> ~N tokens`` footer was the tell that the gate
    skipped post-processing entirely."""
    handler = _library_handler()
    out = handler.handle_zim_query(
        "tell me about photosynthesis", options={"compact": True}
    )
    assert isinstance(out, str)
    assert "tokens" in out.rsplit("\n\n", 1)[-1]
    assert "intent=no_zim_file_specified" in out
    assert "cert=1.00" in out


def test_gate_offers_cross_archive_routes_for_a_content_intent() -> None:
    """fid 42, positive half: the two cross-archive bullets are correct for
    the intents that honour them."""
    handler = _library_handler()
    out = handler.handle_zim_query("search for photosynthesis")
    assert isinstance(out, str)
    assert "search all files for" in out
    assert "synthesize=True" in out


def test_gate_withholds_cross_archive_routes_for_a_structural_intent() -> None:
    """fid 42, negative half: ``list namespaces`` rejects ``synthesize=True``
    with an isError payload and re-parses ``search all files for list
    namespaces`` straight back to this gate, so neither bullet may be
    offered for it."""
    handler = _library_handler()
    out = handler.handle_zim_query("list namespaces")
    assert isinstance(out, str)
    assert "No ZIM File Specified" in out
    assert "synthesize=True" not in out
    assert "search all files for" not in out
    # The one route that does work is still there, and it is actionable.
    assert "zim_file_path" in out
    assert f"{_LIBRARY_DIR}/wikipedia_en_all_maxi_2024-01.zim" in out


def test_gate_names_real_paths_in_the_actionable_bullet() -> None:
    """fid 56: the working bullet needed a value the caller had to dig out
    of a JSON blob printed underneath it."""
    handler = _library_handler(names=_LIBRARY_NAMES[:2])
    out = handler.handle_zim_query("list namespaces")
    assert isinstance(out, str)
    bullet = next(line for line in out.splitlines() if "zim_file_path" in line)
    assert f"{_LIBRARY_DIR}/wikipedia_en_all_maxi_2024-01.zim" in bullet
    assert f"{_LIBRARY_DIR}/wiktionary_en_all_nopic_2024-02.zim" in bullet
    # The size / modified / readable noise cannot affect the retry.
    assert "size_bytes" not in out
    assert "modified" not in out


def test_gate_falls_back_to_the_raw_listing_when_the_probe_fails() -> None:
    """A backend listing that goes sideways must degrade, never raise."""
    ops = MagicMock()
    ops.config.tool_mode = "simple"
    ops.config.meta.footer_enabled = True
    ops.list_zim_files_data.side_effect = [
        [{"path": "/zim/a.zim"}, {"path": "/zim/b.zim"}],  # _no_archives_loaded
        RuntimeError("listing backend down"),
    ]
    ops.list_zim_files.return_value = "Found 2 ZIM files: /zim/a.zim /zim/b.zim"
    out = SimpleToolsHandler(ops).handle_zim_query("search for biology")
    assert isinstance(out, str)
    assert "Found 2 ZIM files" in out
    assert "Pass the `zim_file_path` argument" in out


# ---------------------------------------------------------------------------
# fid 98 — the catch-all must branch on exception TYPE, not message substrings
# ---------------------------------------------------------------------------


def _handler_raising(exc: BaseException, *, archives: List[str]) -> SimpleToolsHandler:
    ops = MagicMock()
    ops.config.tool_mode = "simple"
    ops.config.meta.footer_enabled = True
    ops.list_zim_files_data.return_value = [{"path": p} for p in archives]
    ops.list_zim_files.return_value = repr(archives)
    ops.search_zim_file_data.side_effect = exc
    ops.search_zim_file.side_effect = exc
    return SimpleToolsHandler(ops)


def test_unmatched_archive_name_gets_the_path_not_found_envelope() -> None:
    """fid 98: ``OpenZimMcpArchiveNameError``'s message matches none of the
    substring markers, so a mistyped archive NAME — the most likely
    ``zim_file_path`` mistake — fell through to the generic envelope with
    no list of loaded archives."""
    from openzim_mcp.exceptions import OpenZimMcpArchiveNameError

    handler = _handler_raising(
        OpenZimMcpArchiveNameError(
            "Path did not match any loaded archive: wikipedia.zim"
        ),
        archives=["/zim/medlineplus.zim", "/zim/iep.zim"],
    )
    out = handler.handle_zim_query("search for stoicism", zim_file_path="wikipedia.zim")
    assert isinstance(out, dict)
    assert out["operation"] == "zim_path_not_found"
    assert "/zim/medlineplus.zim" in out["message"]
    assert "/zim/iep.zim" in out["message"]
    assert "Check server logs" not in out["message"]


def test_absolute_missing_path_keeps_its_existing_envelope() -> None:
    """Positive pair: the case that already worked must keep working."""
    from openzim_mcp.exceptions import OpenZimMcpValidationError

    handler = _handler_raising(
        OpenZimMcpValidationError("ZIM file does not exist: /zim/nope.zim"),
        archives=["/zim/medlineplus.zim", "/zim/iep.zim"],
    )
    out = handler.handle_zim_query("search for stoicism", zim_file_path="/zim/nope.zim")
    assert isinstance(out, dict)
    assert out["operation"] == "zim_path_not_found"
    assert "/zim/medlineplus.zim" in out["message"]


def test_zero_archive_server_gets_the_acquisition_hint_not_auto_select() -> None:
    """fid 98: with nothing loaded, "omit the path to auto-select" and "pass
    one of these paths" are both dead ends."""
    from openzim_mcp import onboarding
    from openzim_mcp.exceptions import OpenZimMcpArchiveNameError

    handler = _handler_raising(
        OpenZimMcpArchiveNameError(
            "Path did not match any loaded archive: wikipedia.zim"
        ),
        archives=[],
    )
    out = handler.handle_zim_query("search for stoicism", zim_file_path="wikipedia.zim")
    assert isinstance(out, dict)
    assert out["operation"] == "zim_path_not_found"
    assert onboarding.KIWIX_LIBRARY_HOST in out["message"]
    assert "auto-select" not in out["message"]


def test_an_unrelated_backend_failure_still_gets_the_generic_envelope() -> None:
    """Negative pair: the type branch must not swallow everything."""
    handler = _handler_raising(
        RuntimeError("xapian index corrupted"),
        archives=["/zim/medlineplus.zim", "/zim/iep.zim"],
    )
    out = handler.handle_zim_query(
        "search for stoicism", zim_file_path="/zim/medlineplus.zim"
    )
    assert isinstance(out, dict)
    assert out["operation"] == "zim_query"
    assert "xapian index corrupted" in out["message"]


# ---------------------------------------------------------------------------
# fid 53 — backend ``_meta.reason`` must reach the empty-result footer
# ---------------------------------------------------------------------------


def _footer_handler() -> Tuple[SimpleToolsHandler, MagicMock]:
    ops = MagicMock()
    ops.config.tool_mode = "simple"
    ops.config.meta.footer_enabled = True
    ops.list_zim_files_data.return_value = [{"path": "/zim/med.zim"}]
    return SimpleToolsHandler(ops), ops


def test_bad_namespace_reason_reaches_the_browse_footer() -> None:
    """fid 53: ``browse namespace Q`` carried ``_meta.reason=bad_namespace``
    in its body while the rendered footer was only the token budget —
    meta.py's recovery clause was unreachable through zim_query."""
    handler, ops = _footer_handler()
    ops.browse_namespace.return_value = json.dumps(
        {
            "namespace": "Q",
            "results": [],
            "total": 0,
            "done": True,
            "discovery_method": "rejected_unknown_namespace",
            "_meta": {"chars": 40, "tokens_est": 10, "reason": "bad_namespace"},
        }
    )
    out = handler.handle_zim_query(
        "browse namespace Q",
        zim_file_path="/zim/med.zim",
        options={"compact": True},
    )
    assert isinstance(out, str)
    assert "Unknown namespace." in out
    assert "list namespaces" in out


def test_a_healthy_browse_gets_no_reason_footer() -> None:
    """Negative pair: a normal browse must not grow a recovery clause."""
    handler, ops = _footer_handler()
    ops.browse_namespace.return_value = json.dumps(
        {
            "namespace": "C",
            "results": [{"path": "C/Aspirin", "title": "Aspirin"}],
            "total": 1,
            "done": True,
            "_meta": {"chars": 40, "tokens_est": 10},
        }
    )
    out = handler.handle_zim_query(
        "browse namespace C",
        zim_file_path="/zim/med.zim",
        options={"compact": True},
    )
    assert isinstance(out, str)
    assert "C/Aspirin" in out
    assert "Unknown namespace." not in out


def test_no_content_type_match_reason_reaches_the_filtered_search_footer() -> None:
    """fid 53: the same drop on the filtered-search path — the model that
    filters on an unindexed content type got a bare "No filtered matches"."""
    handler, ops = _footer_handler()
    ops.search_with_filters_data.return_value = {
        "query": "aspirin",
        "results": [],
        "total": 0,
        "done": True,
        "page_info": {"offset": 0, "limit": 10, "returned_count": 0},
        "next_cursor": None,
        "_meta": {"chars": 20, "tokens_est": 5, "reason": "no_content_type_match"},
    }
    ops._format_search_text.return_value = (
        'No filtered matches for "aspirin" (filters: content_type=image)'
    )
    out = handler.handle_zim_query(
        "search aspirin in type image",
        zim_file_path="/zim/med.zim",
        options={"compact": True},
    )
    assert isinstance(out, str)
    assert "No filtered matches" in out
    assert "aren't in the search index" in out
    assert "get binary content of" in out


# ---------------------------------------------------------------------------
# fid 48 / fid 49 — tell_me_about topic extraction
# ---------------------------------------------------------------------------


def _medline_handler() -> Tuple[SimpleToolsHandler, MagicMock]:
    """A one-archive handler that answers any search with one strong hit.

    The hit is deliberately unrelated to any pronoun, so a filler topic
    reaching the auto-pick shows up as a confident, wrong article body.
    """
    ops = MagicMock()
    ops.config.tool_mode = "simple"
    ops.config.meta.footer_enabled = True
    ops.list_zim_files_data.return_value = [{"path": "/zim/med.zim"}]
    ops.search_zim_file.return_value = (
        "Found ~9700 matches, showing 1-3:\n\n"
        "## 1. Can you boost your metabolism?: MedlinePlus\n"
        "Path: medlineplus.gov/ency/patientinstructions/000893.htm\n"
    )
    ops.search_zim_file_data.return_value = {
        "query": "you",
        "results": [
            {
                "path": "medlineplus.gov/ency/patientinstructions/000893.htm",
                "title": "Can you boost your metabolism?: MedlinePlus",
                "snippet": "Your metabolism is the process your body uses…",
                "score": 1.0,
            }
        ],
        "total": 9700,
        "done": True,
        "page_info": {"offset": 0, "limit": 10, "returned_count": 1},
        "next_cursor": None,
    }
    return SimpleToolsHandler(ops), ops


def test_pronoun_only_topic_gets_the_guidance_playbook() -> None:
    """fid 48: ``who are you`` extracted topic ``you`` — every token of it
    already in ``_COMMON_FILLER_TOKENS`` — and answered with 4.7 KB of an
    unrelated article body at cert 0.85, isError=False."""
    handler, ops = _medline_handler()
    out = handler.handle_zim_query("who are you", zim_file_path="/zim/med.zim")
    assert isinstance(out, str)
    assert "intent=meta_only_guidance" in out
    assert "tell me about <topic>" in out
    assert "metabolism" not in out
    ops.search_zim_file.assert_not_called()
    ops.search_zim_file_data.assert_not_called()


def test_anaphoric_topics_get_the_guidance_playbook() -> None:
    """The same shape for the ordinary conversational follow-ups."""
    handler, _ = _medline_handler()
    for q in ("what is it", "tell me about that", "tell me about this"):
        out = handler.handle_zim_query(q, zim_file_path="/zim/med.zim")
        assert isinstance(out, str)
        assert "intent=meta_only_guidance" in out, q


def test_a_capitalized_filler_word_is_still_treated_as_a_title() -> None:
    """Negative pair: ``It`` is a film. A proper-noun signal in what the
    caller actually typed must defer to the parser."""
    handler, ops = _medline_handler()
    out = handler.handle_zim_query("tell me about It", zim_file_path="/zim/med.zim")
    assert isinstance(out, str)
    assert "intent=meta_only_guidance" not in out
    assert ops.search_zim_file.called or ops.search_zim_file_data.called


def test_a_real_topic_is_untouched_by_the_filler_gate() -> None:
    """Negative pair: an ordinary topic still dispatches."""
    handler, ops = _medline_handler()
    out = handler.handle_zim_query(
        "tell me about photosynthesis", zim_file_path="/zim/med.zim"
    )
    assert isinstance(out, str)
    assert "intent=meta_only_guidance" not in out
    assert ops.search_zim_file.called or ops.search_zim_file_data.called


def test_purpose_qualifier_is_stripped_from_the_topic() -> None:
    """fid 49: ``what is X good for?`` searched for ``aspirin good for``,
    which put "Drugs beginning with G" at rank 1 and lost the Aspirin
    article entirely — while ``what is aspirin?`` resolved it first."""
    from openzim_mcp.intent_parser import IntentParser

    for query in (
        "what is aspirin good for?",
        "what is aspirin used for",
        "what is aspirin used to treat",
    ):
        intent, params, _ = IntentParser.parse_intent(query)
        assert intent == "tell_me_about", query
        assert params["topic"] == "aspirin", query
    # …and the same topic the unqualified form produces.
    assert IntentParser.parse_intent("what is aspirin?")[1]["topic"] == "aspirin"


def test_purpose_strip_reaches_the_backend_search_terms() -> None:
    """End to end: the mangled topic used to arrive at the backend."""
    handler, ops = _medline_handler()
    handler.handle_zim_query("what is ibuprofen good for", zim_file_path="/zim/med.zim")
    called = ops.search_zim_file.call_args or ops.search_zim_file_data.call_args
    assert called is not None
    assert "good for" not in " ".join(str(a) for a in called.args)
    assert "ibuprofen" in " ".join(str(a) for a in called.args)


def test_purpose_strip_leaves_ordinary_topics_alone() -> None:
    """Negative pair: a topic that merely CONTAINS the words is safe."""
    from openzim_mcp.intent_parser import IntentParser

    assert (
        IntentParser.parse_intent("tell me about good for nothing")[1]["topic"]
        == "good for nothing"
    )


# ---------------------------------------------------------------------------
# fid 51 — the "Invalid Request" first bullet must name the real constraint
# ---------------------------------------------------------------------------


def test_cursor_rejection_leads_with_dropping_the_cursor() -> None:
    """fid 51: ``walk namespace`` routes every backend validation error
    through ``_render_invalid_request(limit_capable=True)``, so a foreign
    cursor was answered with "Retry with a smaller `limit`" as the most
    prominent bullet — advice that can never clear a stale cursor."""
    from openzim_mcp.exceptions import OpenZimMcpValidationError
    from openzim_mcp.pagination import Cursor

    ops = MagicMock()
    ops.config.tool_mode = "simple"
    ops.config.meta.footer_enabled = True
    ops.list_zim_files_data.return_value = [{"path": "/zim/med.zim"}]
    ops.walk_namespace_data.side_effect = OpenZimMcpValidationError(
        "Cursor for 'walk_namespace' was issued against a different archive. "
        "Drop the cursor and start the paginated call over."
    )
    foreign = Cursor.encode(
        tool="walk_namespace",
        state={"o": 90, "l": 5, "ns": "C", "ai": "dff257258abf"},
    )
    out = SimpleToolsHandler(ops).handle_zim_query(
        "walk namespace C",
        zim_file_path="/zim/med.zim",
        options={"compact": True, "limit": 3, "cursor": foreign},
    )
    assert isinstance(out, str)
    assert "Invalid Request" in out
    bullets = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert bullets, out
    assert "Drop the `cursor`" in bullets[0]
    assert "smaller `limit`" not in bullets[0]


def test_limit_rejection_still_leads_with_a_smaller_limit() -> None:
    """Positive pair: the bullet the branch was written for is unchanged."""
    from openzim_mcp.exceptions import OpenZimMcpValidationError

    ops = MagicMock()
    ops.config.tool_mode = "simple"
    ops.config.meta.footer_enabled = True
    ops.list_zim_files_data.return_value = [{"path": "/zim/med.zim"}]
    ops.walk_namespace_data.side_effect = OpenZimMcpValidationError(
        "limit must be between 1 and 500 (provided: 1000)"
    )
    out = SimpleToolsHandler(ops).handle_zim_query(
        "walk namespace C",
        zim_file_path="/zim/med.zim",
        options={"compact": True, "limit": 1000},
    )
    assert isinstance(out, str)
    bullets = [ln for ln in out.splitlines() if ln.startswith("- ")]
    assert "smaller `limit`" in bullets[0]
    assert "Drop the `cursor`" not in out


# ---------------------------------------------------------------------------
# fid 106 — an empty query is a rejected argument, not a successful retrieval
# ---------------------------------------------------------------------------


def test_empty_query_is_flagged_as_an_error() -> None:
    """fid 106: ``query=null`` / ``123`` / ``["a"]`` already returned
    ``isError=true`` with an ``invalid_argument`` envelope, while ``""``
    and ``"   "`` handed back prose on the success path — so one parameter
    gave opposite machine signals for two equally bad values."""
    ops = MagicMock()
    ops.config.tool_mode = "simple"
    ops.config.meta.footer_enabled = True
    handler = SimpleToolsHandler(ops)
    for empty in ("", "   ", "\t\n  "):
        out = handler.handle_zim_query(empty, zim_file_path="/zim/med.zim")
        assert isinstance(out, dict), repr(empty)
        assert out["error"] is True
        assert out["operation"] == "query_required"
        assert out["invalid_arguments"] == ["query"]
        # The actionable prose the caller needs is preserved.
        assert "**Query Required**" in out["message"]
        assert "list available ZIM files" in out["message"]
    ops.search_zim_file.assert_not_called()


def test_a_real_query_is_still_not_an_error() -> None:
    """Negative pair: the guard must not swallow ordinary queries."""
    ops = MagicMock()
    ops.config.tool_mode = "simple"
    ops.config.meta.footer_enabled = True
    ops.list_zim_files.return_value = "Found 1 ZIM file: /zim/med.zim"
    ops.list_zim_files_data.return_value = [{"path": "/zim/med.zim"}]
    out = SimpleToolsHandler(ops).handle_zim_query("list available ZIM files")
    assert isinstance(out, str)
    assert "Found 1 ZIM file" in out


# ---------------------------------------------------------------------------
# fid 16 — synthesize must cite the section whose heading restates the query
# ---------------------------------------------------------------------------

_VITD_LEAD = (
    "Vitamin D deficiency means you do not have enough vitamin D in your "
    "body. It is common in people who get little sun."
)
_VITD_DOSE = (
    "## How much vitamin D do I need?\n\n"
    "Birth to 12 months: 400 IU. Children 1-13 years: 600 IU. "
    "Teens 14-18: 600 IU. Adults 19-70: 600 IU. Adults 71 and older: 800 IU."
)
_VITD_MD = _VITD_LEAD + "\n\n" + _VITD_DOSE + "\n"


def _vitamin_d_bundle() -> Dict[str, Any]:
    lead_end = len(_VITD_LEAD) + 2
    return {
        "entry_path": "medlineplus.gov/vitaminddeficiency.html",
        "title": "Vitamin D Deficiency",
        "content_type": "text/html",
        "word_count": 60,
        "char_count": len(_VITD_MD),
        "rendered_markdown": _VITD_MD,
        "sections": [
            {
                "id": "start",
                "title": "Vitamin D Deficiency",
                "level": 1,
                "char_start": 0,
                "char_end": lead_end,
                "parent_id": None,
            },
            {
                "id": "how-much-vitamin-d-do-i-need",
                "title": "How much vitamin D do I need?",
                "level": 2,
                "char_start": lead_end,
                "char_end": len(_VITD_MD),
                "parent_id": "start",
            },
        ],
        "links": {"internal": [], "external": [], "media": []},
        "infobox": None,
    }


def _run_synthesize(monkeypatch: Any, query: str, bundle: Dict[str, Any]) -> Any:
    """Drive the real ``synthesize_query`` over one mocked archive.

    The search handler returns the article LEAD as the snippet — which is
    what BM25 highlights for a question-shaped query, and the whole reason
    the answering section never became a passage candidate.
    """
    from pathlib import Path

    from openzim_mcp.config import SynthesizeConfig
    from openzim_mcp.synthesize import synthesize_query

    search_handler = MagicMock()
    search_handler.search_top_k.return_value = [
        {"path": bundle["entry_path"], "snippet": _VITD_LEAD, "score": 1.0}
    ]
    search_handler.title_match_hit.return_value = None

    monkeypatch.setattr(
        "openzim_mcp.bundle.get_or_build_bundle",
        lambda archive, path, **kwargs: bundle,
    )
    content_processor = MagicMock()
    content_processor.html_to_plain_text.side_effect = lambda html: html

    return synthesize_query(
        query,
        archives=[(MagicMock(), Path("/fake/med.zim"))],
        search_handler=search_handler,
        cache=MagicMock(),
        content_processor=content_processor,
        config=SynthesizeConfig(),
    )


def test_synthesize_answers_from_the_section_that_restates_the_query(
    monkeypatch: Any,
) -> None:
    """fid 16: the dose table was one heading away inside the article
    already ranked #1, listed in the response's own ``considered_sections``
    and never cited. The answer contained no IU figure at all."""
    out = _run_synthesize(
        monkeypatch, "how much vitamin D do I need", _vitamin_d_bundle()
    )
    assert "600 IU" in out["answer_markdown"]
    assert "800 IU" in out["answer_markdown"]
    assert out["citations"][0]["section_id"] == "how-much-vitamin-d-do-i-need"
    # …and the section it now answers from is no longer offered as the
    # next-turn pivot, because it is the featured one.
    assert all(
        c["section_id"] != "how-much-vitamin-d-do-i-need"
        for c in out["considered_sections"]
    )


def test_synthesize_leaves_a_title_covered_query_on_the_lead(
    monkeypatch: Any,
) -> None:
    """Negative pair: when the article title already covers the query there
    is nothing left for a heading to answer, and the lead is right."""
    out = _run_synthesize(monkeypatch, "vitamin d deficiency", _vitamin_d_bundle())
    assert "not have enough vitamin D" in out["answer_markdown"]
    assert "600 IU" not in out["answer_markdown"]
    assert out["citations"][0]["section_id"] == "start"


def test_synthesize_does_not_redirect_to_a_merely_adjacent_heading(
    monkeypatch: Any,
) -> None:
    """Negative pair: a heading that shares only SOME of the query's
    remaining content words must not hijack the answer."""
    bundle = _vitamin_d_bundle()
    bundle["sections"][1]["title"] = "Vitamin D and sunlight"
    out = _run_synthesize(monkeypatch, "how much vitamin D do I need", bundle)
    assert "600 IU" not in out["answer_markdown"]
    assert "not have enough vitamin D" in out["answer_markdown"]


def test_synthesize_redirect_survives_a_site_suffixed_article_title(
    monkeypatch: Any,
) -> None:
    """The metformin shape: the article title supplies the drug name, so
    only "side effects" has to be found in the heading."""
    body = (
        "## What side effects can this medication cause?\n\n"
        "Metformin may cause diarrhea, bloating, stomach pain and gas."
    )
    lead = "Metformin is used to treat type 2 diabetes."
    md = lead + "\n\n" + body + "\n"
    bundle = {
        "entry_path": "medlineplus.gov/druginfo/meds/a696005.html",
        "title": "Metformin: MedlinePlus Drug Information",
        "content_type": "text/html",
        "word_count": 40,
        "char_count": len(md),
        "rendered_markdown": md,
        "sections": [
            {
                "id": "important-warning",
                "title": "Important Warning",
                "level": 1,
                "char_start": 0,
                "char_end": len(lead) + 2,
                "parent_id": None,
            },
            {
                "id": "what-side-effects-can-this-medication-cause",
                "title": "What side effects can this medication cause?",
                "level": 2,
                "char_start": len(lead) + 2,
                "char_end": len(md),
                "parent_id": None,
            },
        ],
        "links": {"internal": [], "external": [], "media": []},
        "infobox": None,
    }

    from pathlib import Path

    from openzim_mcp.config import SynthesizeConfig
    from openzim_mcp.synthesize import synthesize_query

    search_handler = MagicMock()
    search_handler.search_top_k.return_value = [
        {"path": bundle["entry_path"], "snippet": lead, "score": 1.0}
    ]
    search_handler.title_match_hit.return_value = None
    monkeypatch.setattr(
        "openzim_mcp.bundle.get_or_build_bundle",
        lambda archive, path, **kwargs: bundle,
    )
    content_processor = MagicMock()
    content_processor.html_to_plain_text.side_effect = lambda html: html
    out = synthesize_query(
        "What are the side effects of metformin?",
        archives=[(MagicMock(), Path("/fake/med.zim"))],
        search_handler=search_handler,
        cache=MagicMock(),
        content_processor=content_processor,
        config=SynthesizeConfig(),
    )
    assert "diarrhea" in out["answer_markdown"]
    assert (
        out["citations"][0]["section_id"]
        == "what-side-effects-can-this-medication-cause"
    )


def test_synthesize_keeps_a_snippet_that_already_spans_the_answer(
    monkeypatch: Any,
) -> None:
    """Negative pair: when BM25's snippet already carries the answering
    section, the answer is present and only the citation label differs —
    trimming to the section would drop the lead the caller can see."""
    from pathlib import Path

    from openzim_mcp.config import SynthesizeConfig
    from openzim_mcp.synthesize import synthesize_query

    bundle = _vitamin_d_bundle()
    search_handler = MagicMock()
    # Snippet spans the lead AND the dose section.
    search_handler.search_top_k.return_value = [
        {"path": bundle["entry_path"], "snippet": _VITD_MD.strip(), "score": 1.0}
    ]
    search_handler.title_match_hit.return_value = None
    monkeypatch.setattr(
        "openzim_mcp.bundle.get_or_build_bundle",
        lambda archive, path, **kwargs: bundle,
    )
    content_processor = MagicMock()
    content_processor.html_to_plain_text.side_effect = lambda html: html
    out = synthesize_query(
        "how much vitamin D do I need",
        archives=[(MagicMock(), Path("/fake/med.zim"))],
        search_handler=search_handler,
        cache=MagicMock(),
        content_processor=content_processor,
        config=SynthesizeConfig(),
    )
    assert "600 IU" in out["answer_markdown"]
    assert "not have enough vitamin D" in out["answer_markdown"]


# ---------------------------------------------------------------------------
# fid 20 — the disambiguation chooser must carry information
# ---------------------------------------------------------------------------


def _disambig_handler() -> Tuple[SimpleToolsHandler, MagicMock]:
    """Two articles that both strong-match "headache", as MedlinePlus has."""
    ops = MagicMock()
    ops.config.tool_mode = "simple"
    ops.config.meta.footer_enabled = True
    ops.list_zim_files_data.return_value = [{"path": "/zim/med.zim"}]
    results = [
        {
            "path": "medlineplus.gov/headache.html",
            "title": "Headache | MedlinePlus",
            "score": 1.0,
            "snippet": (
                "Also called: Cephalalgia. See, Play and Learn. No links "
                "available. Related Issues. Treatment depends on your "
                "diagnosis and symptoms."
            ),
        },
        {
            "path": "medlineplus.gov/ency/article/003024.htm",
            "title": "Headache: MedlinePlus Medical Encyclopedia",
            "score": 0.9,
            "snippet": (
                "A headache is pain or discomfort in the head, scalp, or "
                "neck. When to Contact a Medical Professional."
            ),
        },
    ]
    ops.search_zim_file_data.return_value = {
        "query": "headache",
        "results": results,
        "total": 2,
        "done": True,
        "page_info": {"offset": 0, "limit": 10, "returned_count": 2},
        "next_cursor": None,
    }
    ops.find_entry_by_title_data.return_value = {"results": []}
    return SimpleToolsHandler(ops), ops


def test_disambiguation_menu_carries_a_lead_line_per_candidate() -> None:
    """fid 20: the chooser costs a full round trip and returned nothing but
    two titles — no way to tell a link-only portal page from an article."""
    handler, _ = _disambig_handler()
    out = handler.handle_zim_query(
        "tell me about headache",
        zim_file_path="/zim/med.zim",
        options={"compact": True},
    )
    assert isinstance(out, str)
    assert "Multiple articles match" in out
    # Both candidates are still named…
    assert "medlineplus.gov/headache.html" in out
    assert "medlineplus.gov/ency/article/003024.htm" in out
    # …and each now carries something the caller can choose on.
    assert "Treatment depends on your diagnosis" in out
    assert "pain or discomfort in the head" in out


def test_disambiguation_menu_survives_a_candidate_with_no_snippet() -> None:
    """The title-index canonical row the probe prepends has no snippet; the
    renderer must fall back to the bare title/path line for it."""
    handler, ops = _disambig_handler()
    payload = ops.search_zim_file_data.return_value
    payload["results"][0].pop("snippet")
    out = handler.handle_zim_query(
        "tell me about headache",
        zim_file_path="/zim/med.zim",
        options={"compact": True},
    )
    assert isinstance(out, str)
    assert "medlineplus.gov/headache.html" in out
    assert "pain or discomfort in the head" in out


# ---------------------------------------------------------------------------
# fid 23 — the low-confidence note must name a route, not just "try rephrasing"
# ---------------------------------------------------------------------------


def test_low_confidence_note_offers_the_entities_it_extracted() -> None:
    """fid 23: a raw user sentence runs a stop-word-collision full-text
    search (ten oncology infusion monographs for a headache-and-fever
    question) and the only guidance was "try rephrasing" — advice with no
    operand, though `tell me about headache` resolves in one call."""
    ops = MagicMock()
    ops.config.tool_mode = "simple"
    ops.config.meta.footer_enabled = True
    ops.list_zim_files_data.return_value = [{"path": "/zim/med.zim"}]
    ops.search_zim_file.return_value = (
        "Found ~200 matches, showing 1-2:\n\n"
        "## 1. Ocrelizumab Injection\n## 2. Daratumumab Injection\n"
    )
    out = SimpleToolsHandler(ops).handle_zim_query(
        "I have a headache and a fever, what should I watch for?",
        zim_file_path="/zim/med.zim",
    )
    assert isinstance(out, str)
    assert "Low confidence" in out
    assert "tell me about headache" in out
    assert "tell me about fever" in out


def test_low_confidence_note_degrades_when_there_is_no_entity() -> None:
    """Negative pair: an all-filler query has no operand to name, and the
    note must not grow an empty suggestion."""
    from openzim_mcp.simple_tools import SimpleToolsHandler as _H

    note = _H._confidence_note("search", 0.5, "ok go on")
    assert "Low confidence" in note
    assert "tell me about" not in note


def test_confident_queries_get_no_note_at_all() -> None:
    """Negative pair: the note is still suppressed above the tier floor."""
    from openzim_mcp.simple_tools import SimpleToolsHandler as _H

    assert _H._confidence_note("get_section", 0.95, "section Life of Aristotle") == ""
