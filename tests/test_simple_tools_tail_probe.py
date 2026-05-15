"""Tests that the default-mode tell_me_about title-promotion path
probes greedy tails of a prose-shaped topic before giving up.

Without the tail probe, "some famous people from big rapids michigan"
is passed verbatim to find_title_match, which returns nothing because
no article has that exact title. The probe falls back to shorter tails
and resolves "big rapids michigan" → Big_Rapids,_Michigan.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

from openzim_mcp.simple_tools import SimpleToolsHandler


def _make_handler(title_responses: Dict[str, Optional[Dict[str, Any]]]) -> Any:
    """Construct a SimpleToolsHandler whose find_entry_by_title_data
    consults a topic→result dict. Returns the handler with mocked
    zim_operations.find_entry_by_title_data.

    The keys in title_responses are *lowercase* — find_title_match
    inside _promote_topic_via_title_index sees whatever string the
    caller passes, but iter_query_tails lowercases tails before
    handing them to find_title_match. So this fixture matches against
    lowercase keys to mirror real call behavior.
    """
    handler = SimpleToolsHandler.__new__(SimpleToolsHandler)
    handler.zim_operations = MagicMock()

    def fake_find(
        zim_path: str, topic: str, *, cross_file: bool = False, limit: int = 3
    ):
        result = title_responses.get(topic)
        if result is None:
            return {"results": []}
        return {"results": [result]}

    handler.zim_operations.find_entry_by_title_data.side_effect = fake_find
    return handler


def test_promote_resolves_via_shorter_tail():
    """Full prose topic misses; 3-token tail hits."""
    handler = _make_handler(
        {
            "big rapids michigan": {
                "path": "Big_Rapids,_Michigan",
                "title": "Big Rapids, Michigan",
                "score": 1.0,
                "zim_file": "wiki.zim",
            }
        }
    )
    result = handler._promote_topic_via_title_index(
        "/fake/wiki.zim",
        "some famous people from big rapids michigan",
    )
    assert result is not None
    assert result["path"] == "Big_Rapids,_Michigan"


def test_promote_resolves_via_single_token_tail():
    """A 1-token entity at the end ('detroit') resolves when longer
    tails miss."""
    handler = _make_handler(
        {
            "detroit": {
                "path": "Detroit",
                "title": "Detroit",
                "score": 1.0,
                "zim_file": "wiki.zim",
            }
        }
    )
    result = handler._promote_topic_via_title_index(
        "/fake/wiki.zim",
        "what is the population of detroit",
    )
    assert result is not None
    assert result["path"] == "Detroit"


def test_promote_prefers_longest_resolving_tail():
    """When both 'big rapids michigan' and 'michigan' resolve, the
    longer (more specific) one wins."""
    handler = _make_handler(
        {
            "big rapids michigan": {
                "path": "Big_Rapids,_Michigan",
                "title": "Big Rapids, Michigan",
                "score": 1.0,
                "zim_file": "wiki.zim",
            },
            "michigan": {
                "path": "Michigan",
                "title": "Michigan",
                "score": 1.0,
                "zim_file": "wiki.zim",
            },
        }
    )
    result = handler._promote_topic_via_title_index(
        "/fake/wiki.zim",
        "famous people from big rapids michigan",
    )
    assert result is not None
    assert result["path"] == "Big_Rapids,_Michigan"


def test_promote_returns_none_when_no_tail_resolves():
    """All tails miss → None, caller falls back to BM25 search."""
    handler = _make_handler({})
    result = handler._promote_topic_via_title_index(
        "/fake/wiki.zim", "completely unknown phrase here"
    )
    assert result is None


def test_promote_single_token_topic_still_works():
    """The existing exact-topic case (single-word topic) still
    resolves via the 1-token tail (which equals the whole query)."""
    handler = _make_handler(
        {
            "berlin": {
                "path": "Berlin",
                "title": "Berlin",
                "score": 1.0,
                "zim_file": "wiki.zim",
            }
        }
    )
    result = handler._promote_topic_via_title_index("/fake/wiki.zim", "berlin")
    assert result is not None
    assert result["path"] == "Berlin"


def test_promote_strict_gate_wins_over_fuzzy_on_longer_tail():
    """A 1.0 exact match on a short clean tail beats a 0.8 fuzzy
    match on a longer noisier tail. Without the two-pass structure,
    fuzzy-gate firing on tail N would beat strict-gate firing on
    tail N+1 (shorter). This regression-locks the desired ordering."""
    # 'big rapids michigan' (3-token tail) has an EXACT 1.0 match.
    # 'from big rapids michigan' (4-token tail) would FUZZY-match
    # something unrelated at 0.85 if the gates interleaved per tail —
    # but two-pass structure puts strict-gate-on-shorter-tail before
    # fuzzy-gate-on-longer-tail.
    handler = SimpleToolsHandler.__new__(SimpleToolsHandler)
    handler.zim_operations = MagicMock()

    def fake_find(
        zim_path: str, topic: str, *, cross_file: bool = False, limit: int = 3
    ):
        # Strict 1.0 hit on the clean 3-token tail
        if topic == "big rapids michigan":
            return {
                "results": [
                    {
                        "path": "Big_Rapids,_Michigan",
                        "title": "Big Rapids, Michigan",
                        "score": 1.0,
                        "zim_file": "wiki.zim",
                    }
                ]
            }
        # Fuzzy 0.85 hit on the noisier 4-token tail
        if topic == "from big rapids michigan":
            return {
                "results": [
                    {
                        "path": "From_Big_Mistake_Article",
                        "title": "From Big Mistake Article",
                        "score": 0.85,
                        "zim_file": "wiki.zim",
                    }
                ]
            }
        return {"results": []}

    handler.zim_operations.find_entry_by_title_data.side_effect = fake_find

    result = handler._promote_topic_via_title_index(
        "/fake/wiki.zim",
        "some famous people from big rapids michigan",
    )
    # Two-pass: strict gate clears all tails first → 1.0 hit on the
    # 3-token tail wins. The fuzzy hit never gets a chance.
    assert result is not None
    assert result["path"] == "Big_Rapids,_Michigan"
