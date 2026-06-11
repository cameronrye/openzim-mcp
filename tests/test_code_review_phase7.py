"""Regression tests for code-review 2026-06-10 Phase 7 (simple_tools dispatch).

H11 (search-tail overwrite reverts query rewrites), H12 (cached payload mutated
in place), M15 (find_by_title upfront redirect blocks real slash titles).
M14 is covered in tests/test_zim_query.py.
"""

from unittest.mock import MagicMock

import openzim_mcp.simple_tools as simple_tools
from openzim_mcp.simple_tools import SimpleToolsHandler


def _handler() -> SimpleToolsHandler:
    mock = MagicMock()
    mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
    mock.config.meta.footer_enabled = False
    return SimpleToolsHandler(mock)


# H11 — the recomputed raw tail must not overwrite the rewritten query
def test_h11_param_leak_not_reintroduced_into_search_query():
    handler = _handler()
    # parse_intent strips ``limit=10`` (param-leak) and produces "biology".
    params = {"query": "biology"}
    out = handler._normalize_and_validate_query_params(
        "search for biology limit=10", "search", params
    )
    assert out is None  # no validation error
    assert params["query"] == "biology"  # not "biology limit=10"


def test_h11_misspelling_rewrite_preserved():
    handler = _handler()
    # parse_intent's Rule-2 misspelling map already produced "photosynthesis".
    params = {"query": "photosynthesis"}
    handler._normalize_and_validate_query_params(
        "search for photosythesis", "search", params
    )
    assert params["query"] == "photosynthesis"  # not the raw "photosythesis"


def test_h11_verb_prefixed_search_q_falls_back_to_tail():
    handler = _handler()
    # If extraction failed and left the verb prefix in search_q, fall back to
    # the verb-stripped tail so the handler never searches "search for ...".
    params = {"query": "search for biology"}
    handler._normalize_and_validate_query_params("search for biology", "search", params)
    assert params["query"] == "biology"


# H12 — _splice_title_match_into_search must not mutate the cached payload
def test_h12_splice_does_not_mutate_input_payload(monkeypatch):
    handler = _handler()
    # Force the splice path: top hit is NOT a strong title match, and the
    # title index promotes a canonical not already present.
    monkeypatch.setattr(simple_tools, "is_strong_title_match", lambda *a, **k: False)
    monkeypatch.setattr(
        simple_tools,
        "find_title_match",
        lambda *a, **k: {"path": "Canonical", "title": "Canonical"},
    )
    original = {
        "results": [
            {"path": "A/one", "title": "One", "snippet": "s1"},
            {"path": "A/two", "title": "Two", "snippet": "s2"},
            {"path": "A/three", "title": "Three", "snippet": "s3"},
        ],
        "page_info": {"limit": 3, "offset": 0, "returned_count": 3},
        "total": 3,
    }
    import copy

    snapshot = copy.deepcopy(original)
    out = handler._splice_title_match_into_search(original, "/x.zim", "canonical topic")

    # The returned payload was spliced...
    assert out["results"][0]["path"] == "Canonical"
    # ...but the input (cached) payload is byte-identical to before.
    assert original == snapshot
    assert original["results"][0]["path"] == "A/one"
    assert original["page_info"]["returned_count"] == 3


# M15 — a real lowercase-first slash title must be found, not redirected
def test_m15_real_slash_title_found_not_redirected():
    mock = MagicMock()
    mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
    mock.config.meta.footer_enabled = False
    # The title index DOES have a hit for "a/b testing" → render, no redirect.
    mock.find_entry_by_title_data.return_value = {
        "results": [{"path": "A/B_testing", "title": "A/B testing"}],
        "total": 1,
    }
    handler = SimpleToolsHandler(mock)
    out = handler.handle_zim_query(
        "find article titled a/b testing",
        zim_file_path="/x.zim",
        options={"compact": True},
    )
    assert "Namespace Path, Not a Title" not in out
    mock.find_entry_by_title_data.assert_called_once()


def test_m15_genuine_namespace_path_still_redirects():
    mock = MagicMock()
    mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
    mock.config.meta.footer_enabled = False
    # No title-index hit → genuine misrouted namespace path → redirect.
    mock.find_entry_by_title_data.return_value = {"results": [], "total": 0}
    handler = SimpleToolsHandler(mock)
    out = handler.handle_zim_query(
        "find article titled m/some_entry",
        zim_file_path="/x.zim",
        options={"compact": True},
    )
    assert "Namespace Path, Not a Title" in out
