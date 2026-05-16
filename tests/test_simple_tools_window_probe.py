"""Post-a14 sweep (F4 / A2): _promote_topic_via_title_index falls back
to non-trailing sliding-window probes when no trailing-tail strict
match exists.

The motivating live case: ``"Big Rapids Michigan tourism"`` (entity at
head of prose). The trailing tails ``"michigan tourism"`` and
``"tourism"`` do not resolve to any article. A sliding-window probe
finds the 3-window ``"big rapids michigan"`` → Big_Rapids,_Michigan.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

from openzim_mcp.simple_tools import SimpleToolsHandler


def _make_handler(title_responses: Dict[str, Optional[Dict[str, Any]]]) -> Any:
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


def test_promote_resolves_head_positioned_entity_via_sliding_window():
    """``Big Rapids Michigan`` at the head of the prose, with no
    trailing-tail match — sliding-window fallback finds the entity."""
    handler = _make_handler(
        {
            # Only the head-positioned entity resolves; all trailing
            # tails and shorter sliding windows miss.
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
        "Big Rapids Michigan tourism information",
    )
    assert result is not None
    assert result["path"] == "Big_Rapids,_Michigan"


def test_promote_prefers_trailing_strict_over_sliding_window():
    """When BOTH a trailing-tail strict match AND a sliding-window
    strict match exist, the trailing-tail match wins (preserves a14
    motivating-query behavior)."""
    handler = _make_handler(
        {
            # Trailing 2-tail "ferris state" matches before the sliding
            # 3-window "big rapids michigan" gets a chance.
            "ferris state": {
                "path": "Ferris_State_University",
                "title": "Ferris State University",
                "score": 1.0,
                "zim_file": "wiki.zim",
            },
            "big rapids michigan": {
                "path": "Big_Rapids,_Michigan",
                "title": "Big Rapids, Michigan",
                "score": 1.0,
                "zim_file": "wiki.zim",
            },
        }
    )
    result = handler._promote_topic_via_title_index(
        "/fake/wiki.zim",
        "Big Rapids Michigan Ferris State",
    )
    assert result is not None
    # The 2-tail trailing match is preferred over the 3-window head
    # match because tail-strict runs first.
    assert result["path"] == "Ferris_State_University"


def test_promote_falls_back_to_fuzzy_when_sliding_window_misses_too():
    """Pass order: trailing-strict → window-strict → trailing-fuzzy.
    With no strict matches anywhere, fuzzy still fires."""
    fuzzy_call_responses: Dict[str, Optional[Dict[str, Any]]] = {
        "photosythesis": {
            "path": "Photosynthesis",
            "title": "Photosynthesis",
            "score": 0.85,
            "zim_file": "wiki.zim",
        }
    }
    handler = SimpleToolsHandler.__new__(SimpleToolsHandler)
    handler.zim_operations = MagicMock()

    def fake_find(
        zim_path: str,
        topic: str,
        *,
        cross_file: bool = False,
        limit: int = 3,
    ):
        result = fuzzy_call_responses.get(topic)
        if result is None:
            return {"results": []}
        return {"results": [result]}

    handler.zim_operations.find_entry_by_title_data.side_effect = fake_find

    result = handler._promote_topic_via_title_index("/fake/wiki.zim", "Photosythesis")
    assert result is not None
    assert result["path"] == "Photosynthesis"
