"""Regression tests for code-review 2026-06-10 Phase 3 (intent_parser).

H5/H6/H7/H8 and M7/M8/M9/M10 — extraction-truncation and mis-routing bugs.
"""

from openzim_mcp.intent_parser import (
    IntentParser,
    _extract_binary,
    _extract_entry_path_keyworded,
    _extract_get_section,
    _extract_get_zim_entries,
)


def _intent(query: str) -> str:
    return IntentParser.parse_intent(query)[0]


# H5 — missing word boundary truncated filtered-search queries at any "in" word
def test_h5_filtered_search_keeps_full_query():
    _, params, _ = IntentParser.parse_intent(
        "search for history of the internet in namespace A"
    )
    assert params.get("query") == "history of the internet"
    _, params2, _ = IntentParser.parse_intent(
        "search for protein insulin in namespace A"
    )
    assert params2.get("query") == "protein insulin"


def test_filtered_search_keeps_possessive_query():
    """A possessive apostrophe must not be read as a value delimiter.

    Pre-fix the capture excluded every quote char, so the regex matched
    nothing at all and no ``query`` key was set — the handler then sent the
    ENTIRE command sentence (verb + ``in namespace C`` clause) to Xapian and
    echoed it back in the result header.
    """
    for query, expected in [
        ("search for Murphy's law in namespace C", "murphy's law"),
        ("search for Earth's atmosphere in namespace A", "earth's atmosphere"),
        ("search for O'Brien in namespace C", "o'brien"),
        # Curly apostrophe (copy-pasted / LLM-generated text). The value is
        # non-ASCII, so ``_restore_nonascii_case`` also puts the caller's
        # typed casing back.
        ("search for Murphy’s law in namespace C", "Murphy’s law"),
    ]:
        intent, params, _ = IntentParser.parse_intent(query)
        assert intent == "filtered_search", query
        assert params.get("query") == expected, query
        assert params.get("namespace") in {"A", "C"}, query


def test_filtered_search_explicitly_quoted_value_still_peels():
    _, params, _ = IntentParser.parse_intent(
        'search for "quantum mechanics" in namespace A'
    )
    assert params.get("query") == "quantum mechanics"


def test_search_keeps_possessive_query():
    """Sibling of the filtered-search fix: bare ``search for`` truncated at
    the first apostrophe (``Murphy's law`` -> ``Murphy``, ``O'Brien`` ->
    ``o``)."""
    for query, expected in [
        ("search for Murphy's law", "murphy's law"),
        ("search for O'Brien", "o'brien"),
        ("search for Rock 'n' Roll", "rock 'n' roll"),
    ]:
        intent, params, _ = IntentParser.parse_intent(query)
        assert intent == "search", query
        assert params.get("query") == expected, query


def test_search_quoted_value_still_peels():
    _, params, _ = IntentParser.parse_intent("search for 'World War II'")
    assert params.get("query") == "world war ii"
    _, params2, _ = IntentParser.parse_intent('search for "quantum mechanics"')
    assert params2.get("query") == "quantum mechanics"


def test_search_with_no_terms_still_captures_verb_connector():
    """The degenerate ``search for `` case must keep yielding ``for`` so the
    A11-B4 "Search Terms Required" guard in the handler stays reachable."""
    _, params, _ = IntentParser.parse_intent("search for ")
    assert params.get("query") == "for"


# H6 — last-keyword anchor truncated titles containing of/for/in/from/to
def test_h6_object_keyword_preserves_title_internal_prepositions():
    d = {}
    _extract_entry_path_keyworded("get article History of France", d)
    assert d["entry_path"] == "History of France"
    d = {}
    _extract_entry_path_keyworded("get article Lord of the Rings", d)
    assert d["entry_path"] == "Lord of the Rings"


def test_h6_table_of_contents_for_still_anchors_on_for():
    d = {}
    _extract_entry_path_keyworded("table of contents for Biology", d)
    assert d["entry_path"] == "Biology"


# H7 — binary extractor captured the connector word as the entry path
def test_h7_binary_connector_not_captured_as_path():
    d = {}
    _extract_binary("get binary content from I/image.png", d)
    assert d["entry_path"] == "I/image.png"
    d = {}
    _extract_binary("raw data from X", d)
    assert d["entry_path"] == "X"
    # No-connector form still works.
    d = {}
    _extract_binary("extract pdf I/document.pdf", d)
    assert d["entry_path"] == "I/document.pdf"


# H8 — "info about X"/"details of X" must route to tell_me_about, not metadata
def test_h8_bare_topic_info_routes_to_tell_me_about():
    assert _intent("info about Python") == "tell_me_about"
    assert _intent("info about the Apollo program") == "tell_me_about"
    assert _intent("details of the French Revolution") == "tell_me_about"


def test_h8_file_shaped_metadata_still_routes_to_metadata():
    assert _intent("metadata for file.zim") == "metadata"
    assert _intent("info about this zim") == "metadata"
    assert _intent("details of the archive") == "metadata"
    assert _intent("info for wikipedia_en_all_maxi_2026-02.zim") == "metadata"
    # The binary metadata-only modifier is not stolen by the metadata route.
    assert _intent("get binary content metadata only for I/image.png") == "binary"


# M7 — batch entry extractor captured "d/or" from "and/or"
def test_m7_entry_extractor_anchors_namespace_letter():
    d = {}
    _extract_get_zim_entries("get entries A/Foo and/or B/Bar", d)
    assert d["entries"] == ["A/Foo", "B/Bar"]


# M8 — apostrophes were treated as quote delimiters
def test_m8_possessive_section_name_extracted():
    d = {}
    _extract_get_section("section Earth's atmosphere of Earth", d)
    assert d["section_name"] == "Earth's atmosphere"
    assert d["entry_path"] == "Earth"


def test_m8_possessive_links_not_split_on_apostrophes():
    d = {}
    _extract_entry_path_keyworded("links in Murphy's law and Sod's law", d)
    # The old bug captured "s law and Sod" (span between the two apostrophes).
    assert d["entry_path"] == "Murphy's law and Sod's law"


# M9 — bare verb "complete" hijacked "complete X" into autocomplete
def test_m9_complete_adjective_not_routed_to_suggestions():
    assert _intent("get article complete works of Shakespeare") == "get_article"
    # autocomplete still routes to suggestions.
    assert _intent("autocomplete evol") == "suggestions"


# M10 — Rule-4 decomposition baked politeness/param junk into the entity hint
def test_m10_decomposition_hint_entity_is_clean():
    _, params, _ = IntentParser.parse_intent("population of berlin please")
    assert params["decomposition_hint"]["entity"] == "berlin"
    _, params2, _ = IntentParser.parse_intent("population of berlin limit=5")
    assert params2["decomposition_hint"]["entity"] == "berlin"
