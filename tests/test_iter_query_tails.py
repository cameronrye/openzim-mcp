"""Tests for iter_query_tails — greedy length-down tail iteration over
a natural-language query for entity-resolution title-index probes.

Replaces the M26 4+ token short-circuit in _promote_title_match: instead
of giving up on multi-word prose queries, generate every plausible
entity tail and let the caller probe each one.
"""

from __future__ import annotations

from openzim_mcp.title_promotion import iter_query_tails


def test_iter_query_tails_yields_longest_first():
    """Greedy: 4-token tail before 3-token before 2-token before 1-token."""
    tails = list(iter_query_tails("a b c d e"))
    assert tails == ["b c d e", "c d e", "d e", "e"]


def test_iter_query_tails_caps_at_max_len_4_by_default():
    """A 9-token query yields at most 4 tails (lengths 4, 3, 2, 1)."""
    tails = list(
        iter_query_tails("who are some famous people from big rapids michigan")
    )
    assert tails == [
        "from big rapids michigan",
        "big rapids michigan",
        "rapids michigan",
        "michigan",
    ]


def test_iter_query_tails_short_query_yields_what_fits():
    """3-token query yields tails of length 3, 2, 1."""
    tails = list(iter_query_tails("big rapids michigan"))
    assert tails == ["big rapids michigan", "rapids michigan", "michigan"]


def test_iter_query_tails_single_token_yields_one_tail():
    tails = list(iter_query_tails("detroit"))
    assert tails == ["detroit"]


def test_iter_query_tails_empty_query_yields_nothing():
    assert list(iter_query_tails("")) == []
    assert list(iter_query_tails("   ")) == []


def test_iter_query_tails_normalizes_whitespace():
    """Multiple spaces / tabs collapse; surrounding whitespace stripped."""
    tails = list(iter_query_tails("  big   rapids\tmichigan  "))
    assert tails == ["big rapids michigan", "rapids michigan", "michigan"]


def test_iter_query_tails_lowercases_tails():
    """Tails are lowercased so case-sensitive callers receive a normalized form."""
    tails = list(iter_query_tails("Big Rapids Michigan"))
    assert tails[0] == "big rapids michigan"


def test_iter_query_tails_custom_max_len():
    """Caller can cap the longest tail tried."""
    tails = list(iter_query_tails("a b c d e f", max_len=2))
    assert tails == ["e f", "f"]


def test_iter_query_tails_custom_min_len():
    """Caller can require multi-token tails (skip single-token misfires)."""
    tails = list(iter_query_tails("a b c d e", min_len=2))
    assert tails == ["b c d e", "c d e", "d e"]


def test_iter_query_tails_punctuation_treated_as_token_break():
    """Punctuation between words breaks tokens — 'big rapids, michigan'
    has three tokens, not 'rapids,' as one."""
    tails = list(iter_query_tails("big rapids, michigan"))
    assert tails == ["big rapids michigan", "rapids michigan", "michigan"]


def test_iter_query_tails_underscore_treated_as_token_break():
    """Path-form input like 'Big_Rapids,_Michigan' tokenizes as three
    separate words, not as one underscore-joined token. Critical for
    LLMs that may paste a ZIM entry path verbatim into a query."""
    tails = list(iter_query_tails("Big_Rapids,_Michigan"))
    assert tails == ["big rapids michigan", "rapids michigan", "michigan"]


def test_iter_query_tails_max_len_zero_yields_nothing():
    """max_len=0 (or any value < 1) silently yields nothing. Documents
    the clamping behavior so accidental zero from a config doesn't
    silently break the probe."""
    assert list(iter_query_tails("big rapids michigan", max_len=0)) == []
    assert list(iter_query_tails("big rapids michigan", max_len=-1)) == []
