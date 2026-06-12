"""Real-world-test regression: ``synthesize=True`` ran a fuzzy full-text
search for EVERY query, including structural/navigation intents. ``show
main page`` was searched as the words show/main/page and returned an actor
named "Page Kennedy", demoting the real Main_Page. Synthesis is a content
operation — structural intents are now refused with a clear pointer to the
non-synthesize call.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from openzim_mcp.simple_tools import SimpleToolsHandler


def _handler():
    ops = MagicMock()
    ops.list_zim_files_data.return_value = [
        {"path": "/data/zim_0.zim", "name": "zim_0.zim"}
    ]
    ops.list_zim_files.return_value = "Found 1 ZIM file."
    ops.find_entry_by_title_data.return_value = {"results": []}
    ops.config = MagicMock()
    ops.config.query_rewrite = MagicMock()
    ops.config.query_rewrite.enabled = False
    return SimpleToolsHandler(ops)


def test_synthesize_refuses_structural_show_main_page():
    h = _handler()
    result = h.handle_zim_query(
        "show main page", options={"synthesize": True, "compact": True}
    )
    assert isinstance(result, dict), f"expected a structured error, got {result!r}"
    assert result.get("error") is True
    assert result.get("operation") == "synthesize_not_applicable"


def test_synthesize_refuses_structural_list_namespaces():
    h = _handler()
    result = h.handle_zim_query("list namespaces", options={"synthesize": True})
    assert isinstance(result, dict)
    assert result.get("operation") == "synthesize_not_applicable"


def test_synthesize_does_not_refuse_a_topic_query():
    h = _handler()
    result = h.handle_zim_query(
        "tell me about photosynthesis", options={"synthesize": True}
    )
    # A content query must NOT hit the structural-intent refusal (it proceeds
    # into the synthesize pipeline, whatever that returns against the mock).
    if isinstance(result, dict):
        assert result.get("operation") != "synthesize_not_applicable"
