"""Real-world-test regression: ``links in <name>`` ignored ``offset``.

The compact links handler hardcoded ``offset=0`` when calling the data
layer, so ``offset=25`` returned the same first page and the tail links
were unreachable through the tool's own documented pagination (the footer
literally says "pass offset=25 for the next page").
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from openzim_mcp.simple_tools import SimpleToolsHandler


def _links_payload(done: bool = False) -> Dict[str, Any]:
    return {
        "title": "Quantum computing",
        "path": "Quantum_computing",
        "results": [{"text": "Qubit", "url": "Qubit"}],
        "category_totals": {"internal": 1793, "external": 10},
        "next_cursor": None,
        "done": done,
        "page_info": {"offset": 0, "limit": 25, "returned_count": 1},
    }


@pytest.fixture
def handler() -> SimpleToolsHandler:
    ops = MagicMock()
    ops.extract_article_links_data.return_value = _links_payload()
    h = SimpleToolsHandler(ops)
    # Resolve the natural-language path to itself so the test doesn't depend
    # on a live archive.
    h._resolve_natural_language_path = lambda _zim, path: path  # type: ignore[assignment]
    return h


def test_links_handler_forwards_caller_offset(handler: SimpleToolsHandler):
    ops = handler.zim_operations
    handler._handle_links(
        "links in Quantum computing",
        "/test/file.zim",
        {"entry_path": "Quantum_computing"},
        {"compact": True, "offset": 25, "limit": 25},
    )
    # Both internal and external fetches must use the caller's offset, not 0.
    offsets = {
        call.kwargs.get("offset")
        for call in ops.extract_article_links_data.call_args_list
    }
    assert offsets == {25}, (
        f"links handler ignored offset; called with offsets {offsets} "
        "(expected the caller's offset=25)"
    )


def test_links_handler_defaults_offset_zero(handler: SimpleToolsHandler):
    ops = handler.zim_operations
    handler._handle_links(
        "links in Quantum computing",
        "/test/file.zim",
        {"entry_path": "Quantum_computing"},
        {"compact": True, "limit": 25},
    )
    offsets = {
        call.kwargs.get("offset")
        for call in ops.extract_article_links_data.call_args_list
    }
    assert offsets == {0}
