"""Regression tests for code-review 2026-06-10 Phase 4.

H2 (chain detector falsely rejects middle initials / abbreviations) and
M24/M25 (ASCII-only tokenizers mishandle non-Latin titles / possessors).
"""

from unittest.mock import MagicMock

import pytest

from openzim_mcp.simple_tools import SimpleToolsHandler
from openzim_mcp.title_promotion import (
    accept_possessive_promotion,
    is_strong_title_match,
)


# H2 — names with middle initials / abbreviations must not be chain-rejected
@pytest.fixture
def handler():
    return SimpleToolsHandler(MagicMock())


@pytest.mark.parametrize(
    "query",
    [
        "tell me about Franklin D. Roosevelt",
        "John F. Kennedy",
        "Mount St. Helens",
        "the St. Louis Cardinals",
        # Dotted acronyms keep an INTERNAL dot through ``rstrip(".")``, so
        # they are longer than the 1-2 char initial window and were rejected
        # outright — the caller got the chain warning as the entire response.
        "tell me about the U.S. Constitution",
        "tell me about Washington D.C. Metro",
        # Multi-letter honorifics carry no internal dot and are unreachable
        # by shape, so they are enumerated.
        "tell me about the Rev. Martin Luther King",
    ],
)
def test_h2_middle_initial_names_not_chain_rejected(handler, query):
    assert handler._chained_intent_guidance(query) is None


@pytest.mark.parametrize(
    "query",
    [
        "tell me about Berlin. Tell me about Paris",
        "Biology; Chemistry",
        # Pins the acronym-vs-abbreviation boundary: ``DNA`` is 3 chars with
        # no internal dot and is not an enumerated abbreviation, so widening
        # the length window (rather than keying on shape) would have
        # silently suppressed this genuine chain.
        "tell me about DNA. Tell me about RNA",
    ],
)
def test_h2_real_chains_still_detected(handler, query):
    assert handler._chained_intent_guidance(query) is not None


# M24 — is_strong_title_match must not mutilate non-Latin topics into short
# ASCII residues that spuriously exact-match short article titles.
def test_m24_non_latin_topic_not_falsely_matched():
    assert is_strong_title_match("Łódź", "D", "D") is False
    assert is_strong_title_match("café", "CAF", "CAF") is False


def test_m24_ascii_matches_preserved():
    assert is_strong_title_match(
        "Martin Luther King Jr.", "Martin_Luther_King_Jr.", "Martin Luther King Jr."
    )
    assert is_strong_title_match("Berlin", "Berlin_(city)", "Berlin (city)")
    # A genuine non-Latin exact match still works.
    assert is_strong_title_match("Köln", "Köln", "Köln")


# M25 — non-ASCII possessor tokens must intersect their canonical path.
def test_m25_non_ascii_possessor_accepted():
    assert accept_possessive_promotion(
        {"path": "Ampère's_circuital_law", "match_type": "fuzzy_suggest"},
        "Ampère's circuital law",
    )
    assert accept_possessive_promotion(
        {"path": "Gödel's_incompleteness_theorems", "match_type": "fuzzy_suggest"},
        "Gödel's theorems",
    )


def test_m25_ascii_control_unchanged():
    # Legitimate ASCII possessive still accepted.
    assert accept_possessive_promotion(
        {
            "path": "Newton's_law_of_universal_gravitation",
            "match_type": "fuzzy_suggest",
        },
        "Newton's gravity",
    )
    # Unrelated canonical still rejected.
    assert not accept_possessive_promotion(
        {"path": "Czech_philosophy", "match_type": "fuzzy_suggest"},
        "Plato's republic philosophy",
    )
