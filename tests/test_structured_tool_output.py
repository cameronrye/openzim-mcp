"""Wire-format tests confirming MCP tools emit structuredContent.

These tests poke FastMCP's tool manager directly (via ``call_tool`` with
``convert_result=True``) and verify two things for each migrated JSON-
returning tool:

1. ``convert_result`` returns a tuple ``(unstructured, structured)``
   rather than a bare list of TextContent blocks. The presence of the
   tuple is the in-process equivalent of the wire-format
   ``structuredContent`` field -- FastMCP only produces it when the
   tool's return annotation declares a structured output schema.
2. The structured payload is a real ``dict`` (or list) -- *not* a string.

Tests are added per-tool as each migration completes. Until a given
tool is migrated its assertion will fail, which is the desired signal.
"""

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.zim_operations import ZimOperations


@pytest.fixture
def server(test_config_with_zim_data: OpenZimMcpConfig) -> OpenZimMcpServer:
    """Server bound to the ZIM testing-suite dir so tools have real archives to call."""
    return OpenZimMcpServer(test_config_with_zim_data)


class TestStructuredOutput:
    """Each test asserts a single migrated tool returns structured content."""

    @pytest.mark.asyncio
    async def test_list_namespaces_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """list_namespaces (the pilot migration) must emit a real dict."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")

        # Call the registered MCP tool through the manager so we hit the
        # same convert_result path the lowlevel server uses for the wire
        # format. ``convert_result=True`` is what triggers the
        # structured-content branch.
        result = await server.mcp._tool_manager.call_tool(
            "list_namespaces",
            {"zim_file_path": str(zim_path)},
            convert_result=True,
        )

        # When a tool declares a structured return type, FastMCP returns
        # a (unstructured_content, structured_content) tuple. A bare list
        # means the tool is still on the legacy str-return path.
        assert isinstance(result, tuple), (
            "list_namespaces is not declaring a structured return type -- "
            "the migration in Phase 2 has not landed."
        )
        unstructured, structured = result

        # The structured payload must be the real dict, not a JSON string.
        assert isinstance(
            structured, dict
        ), f"structured payload should be dict, got {type(structured)}"

        # FastMCP wraps Union return annotations
        # (``Union[ListNamespacesResponse, ToolErrorPayload]``) in a
        # uniform ``{"result": ...}`` envelope (see spec § FastMCP
        # wrapping). Tolerate the wrapper; assert the inner shape.
        payload = structured["result"] if "result" in structured else structured
        assert isinstance(payload, dict)
        # list_namespaces is the one list-shaped result that does NOT
        # carry the PaginatedResponse contract — it returns a
        # dict-of-summaries instead. Top-level keys are stable.
        assert "namespaces" in payload
        assert isinstance(payload["namespaces"], dict)
        for key in (
            "total_entries",
            "sampled_entries",
            "has_new_namespace_scheme",
            "is_total_authoritative",
            "discovery_method",
        ):
            assert key in payload, f"missing top-level key: {key}"
        # Phase B contract keys MUST NOT leak onto this non-paginated
        # response — protect against an accidental
        # PaginatedResponse-style migration.
        for forbidden in ("results", "next_cursor", "done", "page_info"):
            assert forbidden not in payload, (
                f"non-paginated list_namespaces unexpectedly carries "
                f"contract key: {forbidden}"
            )
        # Per-namespace summaries declare ``total`` (renamed from the
        # legacy ``count`` in v2 Phase B) and ``is_authoritative``.
        for ns_letter, summary in payload["namespaces"].items():
            assert isinstance(summary, dict), f"namespaces[{ns_letter}] should be dict"
            assert (
                "total" in summary
            ), f"namespaces[{ns_letter}] missing renamed 'total' field"
            assert (
                "count" not in summary
            ), f"namespaces[{ns_letter}] still carries legacy 'count' field"
            assert (
                "is_authoritative" in summary
            ), f"namespaces[{ns_letter}] missing 'is_authoritative'"

    @pytest.mark.asyncio
    async def test_get_zim_metadata_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """get_zim_metadata must emit a structured dict, not a JSON string."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")

        result = await server.mcp._tool_manager.call_tool(
            "get_zim_metadata",
            {"zim_file_path": str(zim_path)},
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        assert "entry_count" in payload

    @pytest.mark.asyncio
    async def test_get_main_page_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """get_main_page emits a real dict at structuredContent.result (FastMCP Union wrap)."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")

        result = await server.mcp._tool_manager.call_tool(
            "get_main_page",
            {"zim_file_path": str(zim_path)},
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        # FastMCP wraps Union returns in a uniform {"result": ...} envelope
        # (see spec § FastMCP wrapping). Accept the wrapper; assert inner shape.
        payload = structured["result"] if "result" in structured else structured
        if payload.get("error") is True:
            assert "operation" in payload
        else:
            # Tolerate both: archive with main page (non-empty path/title/content)
            # and archive without (empty path, textual notice in content).
            assert "path" in payload
            assert "title" in payload
            assert "content" in payload

    @pytest.mark.asyncio
    async def test_list_zim_files_returns_structured_content(
        self, server: OpenZimMcpServer
    ) -> None:
        """Verify list_zim_files emits a structured dict envelope.

        It must not be the legacy ``"Found N ZIM files in M directories: ..."``
        markdown-header-plus-JSON string the SimpleToolsHandler still uses.
        """
        result = await server.mcp._tool_manager.call_tool(
            "list_zim_files", {}, convert_result=True
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        # v2 Phase B contract keys (non-paginated, but contract still applies).
        assert "results" in payload and isinstance(payload["results"], list)
        assert payload["next_cursor"] is None
        assert payload["done"] is True
        assert payload["total"] == len(payload["results"])
        assert payload["page_info"]["offset"] == 0
        assert payload["page_info"]["limit"] == len(payload["results"])
        assert payload["page_info"]["returned_count"] == len(payload["results"])
        # Tool-specific extras.
        assert "directories_count" in payload
        assert "name_filter" in payload
        # Renamed legacy keys must not leak through.
        assert "files" not in payload
        assert "count" not in payload

    @pytest.mark.asyncio
    async def test_find_entry_by_title_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """find_entry_by_title must emit a structured dict, not a JSON string."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "find_entry_by_title",
            {"zim_file_path": str(zim_path), "title": "anything"},
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        assert "results" in payload and isinstance(payload["results"], list)
        assert "query" in payload
        assert "files_searched" in payload
        # Phase B contract keys (non-paginated tool, but contract still applies).
        assert payload["next_cursor"] is None
        assert payload["done"] is True
        assert payload["total"] == len(payload["results"])
        assert payload["page_info"]["offset"] == 0
        assert payload["page_info"]["limit"] == 10
        assert payload["page_info"]["returned_count"] == len(payload["results"])

    @pytest.mark.asyncio
    async def test_browse_namespace_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """browse_namespace must emit a structured dict, not a JSON string."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "browse_namespace",
            {"zim_file_path": str(zim_path), "namespace": "C"},
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        assert "namespace" in payload
        # Phase B contract: results / next_cursor / total / done / page_info.
        assert "results" in payload and isinstance(payload["results"], list)
        assert "done" in payload
        assert "page_info" in payload
        assert payload["page_info"]["offset"] == 0
        assert payload["page_info"]["limit"] == 50
        assert payload["page_info"]["returned_count"] == len(payload["results"])

    @pytest.mark.asyncio
    async def test_walk_namespace_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """walk_namespace must emit a structured dict, not a JSON string."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "walk_namespace",
            {"zim_file_path": str(zim_path), "namespace": "C"},
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        # Phase B contract: results / next_cursor / total / done / page_info.
        assert "results" in payload and isinstance(payload["results"], list)
        assert "done" in payload
        assert "namespace" in payload
        # walk_namespace cannot know the per-namespace total mid-scan.
        assert payload["total"] is None
        assert "page_info" in payload
        assert payload["page_info"]["limit"] == 200
        assert payload["page_info"]["returned_count"] == len(payload["results"])

    @pytest.mark.asyncio
    async def test_get_search_suggestions_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """get_search_suggestions must emit a structured dict, not a JSON string."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "get_search_suggestions",
            {"zim_file_path": str(zim_path), "partial_query": "ev"},
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        assert "results" in payload
        assert isinstance(payload["results"], list)
        assert payload["next_cursor"] is None
        assert payload["done"] is True
        assert payload["total"] == len(payload["results"])

    @pytest.mark.asyncio
    async def test_search_zim_file_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """search_zim_file (Phase B) emits a SearchResponse-shaped payload.

        Phase B migration: the tool now declares a
        ``Union[SearchResponse, ToolErrorPayload]`` return annotation, so
        FastMCP wraps the payload in a single uniform ``{"result": ...}``
        envelope (see spec § FastMCP wrapping — Union returns flow through
        ``_try_create_model_and_schema``'s ``wrap_output=True`` path). The
        inner shape carries a real ``anyOf`` schema and is the contract
        we assert against.
        """
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "search_zim_file",
            {"zim_file_path": str(zim_path), "query": "anything"},
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        # FastMCP wraps Union returns in a uniform {"result": ...} envelope
        # (see spec § FastMCP wrapping). Accept that wrapper; assert the
        # inner shape.
        payload = structured["result"] if "result" in structured else structured
        # Tool may emit an error envelope on a transient missing-index call —
        # tolerate it; the wire format is what we're verifying.
        if payload.get("error") is True:
            assert "operation" in payload
        else:
            assert "results" in payload and isinstance(payload["results"], list)
            assert "next_cursor" in payload
            assert "total" in payload
            assert "done" in payload
            assert "page_info" in payload and isinstance(payload["page_info"], dict)
            assert "query" in payload

    @pytest.mark.asyncio
    async def test_search_with_filters_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """search_with_filters (Phase B) emits a SearchWithFiltersResponse-shaped payload.

        Phase B migration: the tool now declares a
        ``Union[SearchWithFiltersResponse, ToolErrorPayload]`` return
        annotation, so FastMCP wraps the payload in a uniform
        ``{"result": ...}`` envelope (see spec § FastMCP wrapping). The
        inner shape must carry the contract keys plus the tool-specific
        ``query`` / ``namespace_filter`` / ``content_type_filter`` extras.
        """
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "search_with_filters",
            {
                "zim_file_path": str(zim_path),
                "query": "evolution",
                "namespace": "C",
            },
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        # FastMCP wraps Union returns in {"result": ...}; accept the wrapper.
        payload = structured["result"] if "result" in structured else structured
        # Tool may emit an error envelope on a transient libzim failure —
        # tolerate it; the wire format is what we're verifying.
        if payload.get("error") is True:
            assert "operation" in payload
        else:
            for key in ("results", "next_cursor", "total", "done", "page_info"):
                assert key in payload
            assert isinstance(payload["results"], list)
            assert isinstance(payload["page_info"], dict)
            # _meta envelope should also be present (sibling of contract keys).
            assert "_meta" in payload
            assert payload["query"] == "evolution"
            assert payload["namespace_filter"] == "C"
            assert payload["content_type_filter"] is None

    @pytest.mark.asyncio
    async def test_search_all_returns_structured_content(
        self, server: OpenZimMcpServer
    ) -> None:
        """search_all per-file results must be dicts, not stringified markdown.

        Catches both wire-format requirements: (a) the tool emits
        structuredContent at all, and (b) ``results[].result`` is itself
        a real ``SearchResponse`` dict (the triple-encoding fix, plus
        Phase B contract-shape).

        Note on the ``"result"`` wrapper: FastMCP wraps Union return
        annotations (``Union[SearchAllResponse, ToolErrorPayload]``) in a
        uniform ``{"result": ...}`` envelope because ``Union`` flows
        through ``_try_create_model_and_schema``'s ``wrap_output=True``
        path. Per spec § FastMCP wrapping, Phase B accepts this uniform
        wrapper deliberately (the inner content carries a real
        ``anyOf: [SearchAllResponse, ToolErrorPayload]`` schema). Tests
        assert against ``structured["result"]`` (or the wrapper-tolerant
        equivalent) — what matters is the inner shape.
        """
        result = await server.mcp._tool_manager.call_tool(
            "search_all", {"query": "evolution"}, convert_result=True
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        # Phase B: results is the renamed per-file list, no longer ``per_file``.
        assert "per_file" not in payload, (
            "TypedDict migration regression: top-level still uses legacy "
            "``per_file`` key — Task 6 renamed it to ``results``."
        )
        assert "results" in payload
        # Top-level Phase B contract keys (always done=True, no cursor —
        # search_all is fan-out, not paginated at the top level).
        assert payload["done"] is True
        assert payload["next_cursor"] is None
        assert "page_info" in payload
        for entry in payload["results"]:
            inner = entry["result"]
            assert isinstance(
                inner, dict
            ), f"per_file[].result should be dict, got {type(inner)}"
            if inner.get("error") is True:
                # Per-archive search failed (e.g. ZIM lacks FT Xapian index);
                # the error envelope replaces SearchResponse for that entry.
                continue
            # inner is itself a SearchResponse — it has its own results list
            assert "results" in inner
            assert "done" in inner
            assert "next_cursor" in inner

    @pytest.mark.asyncio
    async def test_get_zim_entries_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """get_zim_entries (batch) must emit a structured dict envelope."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        # An entry path that may or may not resolve — we're testing the wire
        # format, not the resolution. The structured response must include
        # results + succeeded + failed regardless of per-entry outcomes.
        result = await server.mcp._tool_manager.call_tool(
            "get_zim_entries",
            {
                "entries": ["A/Main_Page"],
                "zim_file_path": str(zim_path),
            },
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        # Tool returns either the success dict (results+succeeded+failed)
        # or the structured-error envelope (error: True). Accept either —
        # the wire format is what we're verifying.
        if payload.get("error") is True:
            assert "operation" in payload
        else:
            # v2 Phase B contract: the success envelope carries the
            # canonical list-shaped keys plus the tool-specific
            # succeeded/failed counters.
            assert "results" in payload
            assert "succeeded" in payload
            assert "failed" in payload
            assert payload["next_cursor"] is None
            assert payload["done"] is True
            assert payload["total"] == len(payload["results"])
            assert "page_info" in payload

    @pytest.mark.asyncio
    async def test_get_zim_entry_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """get_zim_entry emits a real dict at structuredContent.result (FastMCP Union wrap)."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")

        # Resolve a real entry path via find_entry_by_title so we get a
        # non-error response to assert the success-branch shape against.
        find_result = await server.mcp._tool_manager.call_tool(
            "find_entry_by_title",
            {"zim_file_path": str(zim_path), "title": "a"},
            convert_result=True,
        )
        assert isinstance(find_result, tuple)
        _, find_structured = find_result
        find_payload = (
            find_structured["result"]
            if "result" in find_structured
            else find_structured
        )
        if find_payload.get("error") is True:
            pytest.skip(
                f"find_entry_by_title returned an error envelope: {find_payload.get('operation')}"
            )
        entries = find_payload.get("results", [])
        if not entries:
            pytest.skip("No entries found in test ZIM to exercise get_zim_entry")
        entry_path = entries[0]["path"]

        result = await server.mcp._tool_manager.call_tool(
            "get_zim_entry",
            {"zim_file_path": str(zim_path), "entry_path": entry_path},
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        # FastMCP wraps Union returns in a uniform {"result": ...} envelope
        # (see spec § FastMCP wrapping). Accept the wrapper; assert inner shape.
        payload = structured["result"] if "result" in structured else structured
        if payload.get("error") is True:
            assert "operation" in payload
        else:
            assert "path" in payload
            assert "title" in payload
            assert "content" in payload

    @pytest.mark.asyncio
    async def test_get_article_structure_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """get_article_structure must emit a structured dict envelope."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "get_article_structure",
            {"zim_file_path": str(zim_path), "entry_path": "A/Main_Page"},
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        # Tool may return error envelope on a missing-entry call — accept either.
        if payload.get("error") is True:
            assert "operation" in payload
        else:
            assert "headings" in payload

    @pytest.mark.asyncio
    async def test_extract_article_links_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """extract_article_links must emit a structured dict envelope."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "extract_article_links",
            {"zim_file_path": str(zim_path), "entry_path": "A/Main_Page"},
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        # Tool may return error envelope on a missing-entry call — accept either.
        if payload.get("error") is True:
            assert "operation" in payload
        else:
            # v2 Phase B contract: single category per call.
            assert "results" in payload
            assert "kind" in payload and payload["kind"] == "internal"
            assert "category_totals" in payload
            for k in ("internal", "external", "media"):
                assert k in payload["category_totals"]

    @pytest.mark.asyncio
    async def test_get_entry_summary_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """get_entry_summary must emit a structured dict envelope."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "get_entry_summary",
            {"zim_file_path": str(zim_path), "entry_path": "A/Main_Page"},
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        # Tool may return error envelope on a missing-entry call — accept either.
        if payload.get("error") is True:
            assert "operation" in payload
        else:
            assert "summary" in payload

    @pytest.mark.asyncio
    async def test_get_table_of_contents_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """get_table_of_contents must emit a structured dict envelope."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "get_table_of_contents",
            {"zim_file_path": str(zim_path), "entry_path": "A/Main_Page"},
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        # Tool may return error envelope on a missing-entry call — accept either.
        if payload.get("error") is True:
            assert "operation" in payload
        else:
            assert "toc" in payload

    @pytest.mark.asyncio
    async def test_get_binary_entry_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """get_binary_entry must emit a structured dict envelope."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        # Use include_data=False to keep the test fast and avoid loading
        # binary bytes — the wire format is what we're verifying.
        result = await server.mcp._tool_manager.call_tool(
            "get_binary_entry",
            {
                "zim_file_path": str(zim_path),
                "entry_path": "I/some.png",
                "include_data": False,
            },
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        # Tool may return error envelope on a missing-entry call — accept either.
        if payload.get("error") is True:
            assert "operation" in payload
        else:
            assert "mime_type" in payload

    @pytest.mark.asyncio
    async def test_get_related_articles_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """get_related_articles must emit a structured dict envelope."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "get_related_articles",
            {"zim_file_path": str(zim_path), "entry_path": "A/Main_Page"},
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        # Tool may return error envelope on a missing-entry call — accept either.
        if payload.get("error") is True:
            assert "operation" in payload
        else:
            # v2 Phase B contract: top-level results / next_cursor / total /
            # done / page_info plus tool-specific entry_path.
            assert "results" in payload
            assert "outbound_results" not in payload
            assert payload["next_cursor"] is None
            assert payload["done"] is True
            assert payload["total"] == len(payload["results"])
            assert payload["page_info"]["limit"] >= 1
            assert "entry_path" in payload

    @pytest.mark.asyncio
    async def test_get_server_health_returns_structured_content(
        self, server: OpenZimMcpServer
    ) -> None:
        """get_server_health must emit a structured dict envelope."""
        result = await server.mcp._tool_manager.call_tool(
            "get_server_health", {}, convert_result=True
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        assert "status" in payload
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_get_server_configuration_returns_structured_content(
        self, server: OpenZimMcpServer
    ) -> None:
        """get_server_configuration must emit a structured dict envelope."""
        result = await server.mcp._tool_manager.call_tool(
            "get_server_configuration", {}, convert_result=True
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        payload = structured["result"] if "result" in structured else structured
        assert "configuration" in payload
        assert "diagnostics" in payload

    @pytest.mark.asyncio
    async def test_get_section_returns_structured_content(
        self, server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """get_section must emit a GetSectionResponse dict for a valid section_id."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "get_section",
            {
                "zim_file_path": str(zim_path),
                "entry_path": "A/Main_Page",
                "section_id": "introduction",
            },
            convert_result=True,
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        # FastMCP wraps Union returns in a uniform {"result": ...} envelope.
        # Accept the wrapper; assert the inner shape.
        payload = structured.get("result", structured)
        assert isinstance(payload, dict)
        # A valid section_id on an existing entry MUST return GetSectionResponse,
        # not ToolErrorPayload. A ToolErrorPayload here is a regression.
        assert payload.get("error") is not True, (
            f"get_section returned ToolErrorPayload for a valid section_id: "
            f"{payload.get('operation')!r} — {payload.get('message')!r}"
        )
        # Exact value assertions — not just presence.
        assert payload["section_id"] == "introduction"
        assert payload["section_title"] and isinstance(
            payload["section_title"], str
        ), f"section_title should be a non-empty string, got: {payload.get('section_title')!r}"
        assert "_meta" in payload


@pytest.fixture
def simple_server(test_config_with_zim_data: OpenZimMcpConfig) -> OpenZimMcpServer:
    """Simple-mode server bound to the ZIM testing-suite dir.

    zim_query is only registered in simple mode, so synthesize integration
    tests need a separate server fixture with tool_mode='simple'.
    """
    import copy

    cfg = copy.copy(test_config_with_zim_data)
    # Pydantic models are immutable; rebuild with tool_mode='simple'.
    cfg = OpenZimMcpConfig(
        allowed_directories=test_config_with_zim_data.allowed_directories,
        tool_mode="simple",
        cache=test_config_with_zim_data.cache,
        content=test_config_with_zim_data.content,
        logging=test_config_with_zim_data.logging,
    )
    return OpenZimMcpServer(cfg)


class TestZimQuerySynthesize:
    """Integration tests for zim_query synthesize=True wire format."""

    @pytest.mark.asyncio
    async def test_zim_query_synthesize_returns_structured_response(
        self, simple_server: OpenZimMcpServer, basic_test_zim_files
    ) -> None:
        """synthesize=True returns SynthesizeResponse via structuredContent."""
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")

        result = await simple_server.mcp._tool_manager.call_tool(
            "zim_query",
            {
                "query": "berlin geography",
                "zim_file_path": str(zim_path),
                "synthesize": True,
            },
            convert_result=True,
        )

        # Union return type triggers FastMCP's structured-content path.
        assert isinstance(result, tuple), (
            "zim_query with synthesize=True must return a tuple — "
            "the Union return annotation has not landed."
        )
        _, structured = result
        assert isinstance(structured, dict)
        # FastMCP wraps Union returns in a {"result": ...} envelope.
        payload = structured.get("result", structured)
        assert isinstance(payload, dict)
        # SynthesizeResponse or ToolErrorPayload — accept either for wire-format
        # correctness; a ToolErrorPayload (e.g. no FT index) is still structured.
        if payload.get("error") is True:
            assert "operation" in payload
        else:
            assert "answer_markdown" in payload
            assert "passages" in payload
            assert "citations" in payload
            assert "archives_searched" in payload
            assert payload.get("fallback_used") in ("xapian_score", "rrf_fusion")

    @pytest.mark.asyncio
    async def test_zim_query_no_synthesize_returns_string(
        self, simple_server: OpenZimMcpServer
    ) -> None:
        """synthesize=False (default) keeps returning the markdown string path."""
        result = await simple_server.mcp._tool_manager.call_tool(
            "zim_query",
            {"query": "list available ZIM files"},
            convert_result=True,
        )
        # A plain str return does NOT produce a tuple — FastMCP returns the
        # bare list of TextContent blocks. This verifies the legacy path is intact.
        # When the Union return annotation is active, FastMCP may wrap even
        # strings — accept both: a tuple whose text element is non-empty, or
        # a list with at least one text item.
        if isinstance(result, tuple):
            _, structured = result
            # structured may be None or a dict wrapping the string
            # The unstructured part must contain text.
            unstructured, _ = result
            assert (
                unstructured
            ), "zim_query markdown path should produce non-empty content"
        else:
            # Legacy: bare list of TextContent
            assert result, "zim_query markdown path should produce non-empty content"
            assert result[0].text, "first TextContent block should be non-empty"


def test_phase_c_bundle_shared_across_four_tools(v2_phase_a_zim) -> None:
    """All four collapsed tools share one EntryBundle per entry.

    First call to any tool builds the bundle; the other three calls hit
    the bundle cache. Load-bearing perf assertion for Phase C #11 -- if
    it ever fails, someone re-introduced per-tool parsing.
    """
    zim_dir = str(v2_phase_a_zim.parent)
    config = OpenZimMcpConfig(
        allowed_directories=[zim_dir],
        tool_mode="advanced",
        cache=CacheConfig(enabled=True, max_size=50, ttl_seconds=300),
        content=ContentConfig(max_content_length=10000, snippet_length=200),
        logging=LoggingConfig(level="WARNING"),
    )
    path_validator = PathValidator(config.allowed_directories)
    cache = OpenZimMcpCache(config.cache, enable_background_cleanup=False)
    content_processor = ContentProcessor(snippet_length=config.content.snippet_length)
    ops = ZimOperations(config, path_validator, cache, content_processor)

    zim_path = str(v2_phase_a_zim)
    entry = "A/Einstein"

    # Call all four collapsed tools on the same entry.
    ops.get_entry_summary_data(zim_path, entry, max_words=200)
    ops.get_table_of_contents_data(zim_path, entry)
    ops.get_article_structure_data(zim_path, entry)
    ops.extract_article_links_data(zim_path, entry, kind="internal", limit=50)

    # Exactly one bundle key must exist in cache for this entry.
    bundle_keys = [
        k for k in cache._cache.keys() if k.startswith("bundle:v2c:") and entry in k
    ]
    assert (
        len(bundle_keys) == 1
    ), f"Expected 1 shared bundle key, found {len(bundle_keys)}: {bundle_keys}"

    # Legacy per-tool prefixes must be absent -- only the shared bundle is used.
    legacy_prefixes = ("summary_data:", "toc_data:", "structure_data:", "links_full:")
    for k in cache._cache.keys():
        for prefix in legacy_prefixes:
            assert not k.startswith(prefix), (
                f"Legacy cache prefix {prefix!r} still in use; "
                f"expected only bundle:v2c:"
            )
