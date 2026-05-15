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
        ts.GetSectionResponse,
        ts.SynthesizeResponse,
    ]
    for cls in non_paginated:
        hints = get_type_hints(cls)
        # _meta is universal; the rest of the contract keys must NOT be present.
        leaked = {"results", "next_cursor", "done", "page_info"} & set(hints.keys())
        assert not leaked, f"{cls.__name__} unexpectedly has paginated keys: {leaked}"
        assert "_meta" in hints, f"{cls.__name__} missing _meta envelope"


# ---------------------------------------------------------------------------
# Phase C TypedDicts — structural assertions
# ---------------------------------------------------------------------------


def test_section_meta_has_required_fields() -> None:
    hints = get_type_hints(ts.SectionMeta)
    for key in ("id", "title", "level", "char_start", "char_end", "parent_id"):
        assert key in hints, f"SectionMeta missing {key}"


def test_entry_bundle_has_required_fields() -> None:
    hints = get_type_hints(ts.EntryBundle)
    for key in (
        "entry_path",
        "title",
        "content_type",
        "word_count",
        "char_count",
        "rendered_markdown",
        "sections",
        "links",
        "infobox",
    ):
        assert key in hints, f"EntryBundle missing {key}"


def test_link_buckets_has_three_categories() -> None:
    hints = get_type_hints(ts.LinkBuckets)
    for key in ("internal", "external", "media"):
        assert key in hints, f"LinkBuckets missing {key}"


def test_infobox_data_shape() -> None:
    field_hints = get_type_hints(ts.InfoboxField)
    assert {"label", "value"} <= set(field_hints.keys())
    data_hints = get_type_hints(ts.InfoboxData)
    assert "fields" in data_hints
    assert "title" in data_hints  # NotRequired but get_type_hints surfaces it


def test_toc_heading_uses_section_id_not_id() -> None:
    hints = get_type_hints(ts.TocHeading)
    assert "section_id" in hints, "TocHeading must use section_id (Phase C rename)"
    assert "id" not in hints, "TocHeading must not retain the old `id` field"
    for key in ("text", "level", "children"):  # id_source dropped
        assert key in hints, f"TocHeading missing {key}"


def test_table_of_contents_response_uses_typed_toc() -> None:
    """Phase C tightens toc from list[dict[str, Any]] to list[TocHeading]."""
    hints = get_type_hints(ts.TableOfContentsResponse)
    # The annotation should be list[TocHeading] (or List[TocHeading]).
    toc_annotation = hints["toc"]
    # repr captures both new-style and List[]-style.
    assert "TocHeading" in repr(
        toc_annotation
    ), f"TableOfContentsResponse.toc must be list[TocHeading], got {toc_annotation!r}"


def test_get_section_response_has_required_fields() -> None:
    hints = get_type_hints(ts.GetSectionResponse)
    for key in (
        "entry_path",
        "title",
        "section_id",
        "section_title",
        "level",
        "parent_id",
        "content_markdown",
        "char_count",
        "word_count",
        "truncated",
        "_meta",
    ):
        assert key in hints, f"GetSectionResponse missing {key}"


def test_citation_has_required_fields() -> None:
    hints = get_type_hints(ts.Citation)
    for key in (
        "cite_id",
        "archive",
        "entry_path",
        "title",
        "section_id",
        "section_title",
    ):
        assert key in hints, f"Citation missing {key}"


def test_synthesize_passage_has_required_fields() -> None:
    hints = get_type_hints(ts.SynthesizePassage)
    for key in ("cite_id", "text_markdown", "rank", "score"):
        assert key in hints, f"SynthesizePassage missing {key}"


def test_synthesize_response_has_required_fields() -> None:
    hints = get_type_hints(ts.SynthesizeResponse)
    for key in (
        "query",
        "answer_markdown",
        "passages",
        "citations",
        "archives_searched",
        "fallback_used",
        "total_chars",
        "total_words",
        "_meta",
    ):
        assert key in hints, f"SynthesizeResponse missing {key}"


def test_synthesize_response_accepts_considered_articles_and_sections():
    """A14: SynthesizeResponse exposes considered_articles and
    considered_sections for multi-round refinement. Both fields are
    optional (total=False) so existing callers aren't forced to set
    them."""
    from openzim_mcp.tool_schemas import (
        ConsideredArticle,
        ConsideredSection,
        SynthesizeResponse,
    )

    article: ConsideredArticle = {
        "archive": "wiki",
        "entry_path": "Big_Rapids_Township,_Michigan",
        "title": "Big Rapids Township, Michigan",
        "score": 0.42,
    }
    section: ConsideredSection = {
        "section_id": "History",
        "title": "History",
    }
    response: SynthesizeResponse = {
        "query": "q",
        "answer_markdown": "a",
        "passages": [],
        "citations": [],
        "archives_searched": ["wiki"],
        "fallback_used": "rrf_fusion",
        "total_chars": 1,
        "total_words": 1,
        "_meta": {},  # type: ignore[typeddict-item]
        "considered_articles": [article],
        "considered_sections": [section],
    }
    # Structural assertion: the TypedDict shape accepts these fields.
    assert (
        response["considered_articles"][0]["title"] == "Big Rapids Township, Michigan"
    )
    assert response["considered_sections"][0]["title"] == "History"
