"""Tests for ``iter_query_windows`` — sliding-window non-trailing token
windows used as a head/middle-entity fallback when ``iter_query_tails``
finds no match.

Post-a14 beta-test sweep finding (A2): the trailing-tail probe alone
cannot resolve queries whose entity sits at the head of the prose
(``"Big Rapids, Michigan tourism"`` — the entity tokens are the first
three of five). The sliding-window probe is run *after* the trailing-
tail strict pass to preserve a14's motivating-query behavior; only
non-trailing windows are emitted because the trailing windows are
already covered.
"""

from __future__ import annotations

from openzim_mcp.title_promotion import iter_query_windows


def test_iter_query_windows_yields_non_trailing_windows_longest_first():
    """For a 5-token query, yields non-trailing 4-windows, then non-
    trailing 3-windows, etc., in decreasing length order."""
    windows = list(iter_query_windows("a b c d e"))
    # 4-windows (excluding the trailing "b c d e"):
    #   ["a b c d"]
    # 3-windows (excluding the trailing "c d e"):
    #   ["a b c", "b c d"]
    # 2-windows (excluding the trailing "d e"):
    #   ["a b", "b c", "c d"]
    # 1-windows (excluding the trailing "e"):
    #   ["a", "b", "c", "d"]
    assert windows == [
        "a b c d",
        "a b c",
        "b c d",
        "a b",
        "b c",
        "c d",
        "a",
        "b",
        "c",
        "d",
    ]


def test_iter_query_windows_caps_at_max_len_4_by_default():
    """A long prose query yields at most non-trailing 4-windows down."""
    windows = list(iter_query_windows("big rapids michigan notable people"))
    # 5 tokens → 4-windows: 2 total, [-trailing] = 1
    # 3-windows: 3 total, [-trailing] = 2
    # 2-windows: 4 total, [-trailing] = 3
    # 1-windows: 5 total, [-trailing] = 4
    assert "big rapids michigan notable" in windows  # non-trailing 4-window
    assert "rapids michigan notable people" not in windows  # is trailing
    assert "big rapids michigan" in windows  # non-trailing 3-window
    assert "michigan notable people" not in windows  # is trailing


def test_iter_query_windows_skips_trailing_so_iter_tails_handles_those():
    """No window yielded by iter_query_windows should match the trailing
    tail at the same length; the caller composes iter_query_tails first."""
    query = "big rapids michigan notable people"
    windows = list(iter_query_windows(query))
    tails = {
        " ".join(query.split()[-n:])
        for n in range(1, min(5, len(query.split())) + 1)
    }
    assert not (set(windows) & tails)


def test_iter_query_windows_short_query_yields_nothing_extra():
    """A 1-token query has no non-trailing windows."""
    assert list(iter_query_windows("detroit")) == []


def test_iter_query_windows_empty_query_yields_nothing():
    assert list(iter_query_windows("")) == []
    assert list(iter_query_windows("   ")) == []


def test_iter_query_windows_lowercases():
    """Tokens lowercased like iter_query_tails — title-index lookups
    consume the same case-folded form."""
    windows = list(iter_query_windows("Big Rapids Michigan Tourism"))
    # 4 tokens, length 3 non-trailing window: "Big Rapids Michigan"
    assert "big rapids michigan" in windows
