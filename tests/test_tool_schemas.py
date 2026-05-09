"""Structural tests for openzim_mcp.tool_schemas.

These tests don't assert behavior — they assert the TypedDict surface
exists and the contract keys are present on every list-returning response.
The dynamic per-tool wire-format checks live in test_response_contract.py.
"""

from __future__ import annotations

from typing import get_type_hints

from openzim_mcp import tool_schemas as ts

# Every list-returning response TypedDict must declare these five keys
# plus _meta. The interpretation of each is documented in the spec.
CONTRACT_KEYS = {"results", "next_cursor", "total", "done", "page_info", "_meta"}


def test_page_info_has_required_fields() -> None:
    hints = get_type_hints(ts.PageInfo)
    assert "offset" in hints
    assert "limit" in hints
    assert "returned_count" in hints
    # total_is_lower_bound is NotRequired — get_type_hints still surfaces it.
    assert "total_is_lower_bound" in hints


def test_meta_envelope_has_phase_a_fields() -> None:
    hints = get_type_hints(ts.MetaEnvelope)
    for key in (
        "tokens_est",
        "chars",
        "truncated",
        "more_at_offset",
        "total_chars",
        "suggestions",
        "reason",
    ):
        assert key in hints, f"MetaEnvelope missing {key}"


def test_paginated_responses_carry_contract_keys() -> None:
    paginated = [
        ts.SearchResponse,
        ts.SearchAllResponse,
        ts.SearchWithFiltersResponse,
        ts.FindEntryResponse,
        ts.SearchSuggestionsResponse,
        ts.BrowseNamespaceResponse,
        ts.WalkNamespaceResponse,
        ts.LinksResponse,
        ts.ListZimFilesResponse,
        ts.RelatedArticlesResponse,
        ts.BatchEntryResponse,
    ]
    for cls in paginated:
        hints = get_type_hints(cls)
        missing = CONTRACT_KEYS - set(hints.keys())
        assert not missing, f"{cls.__name__} missing contract keys: {missing}"


def test_non_paginated_responses_do_not_carry_results() -> None:
    """list_namespaces and the entry/metadata tools don't get the contract."""
    non_paginated = [
        ts.ZimMetadataResponse,
        ts.ListNamespacesResponse,
        ts.EntryResponse,
        ts.EntrySummaryResponse,
        ts.TableOfContentsResponse,
        ts.ArticleStructureResponse,
        ts.BinaryEntryResponse,
    ]
    for cls in non_paginated:
        hints = get_type_hints(cls)
        # _meta is universal; the rest of the contract keys must NOT be present.
        leaked = {"results", "next_cursor", "done", "page_info"} & set(hints.keys())
        assert not leaked, f"{cls.__name__} unexpectedly has paginated keys: {leaked}"
        assert "_meta" in hints, f"{cls.__name__} missing _meta envelope"
