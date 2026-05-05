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

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


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

        # FastMCP wraps generic ``Dict[str, Any]`` return types under a
        # ``"result"`` key (see ``_try_create_model_and_schema`` in
        # ``mcp.server.fastmcp.utilities.func_metadata``). TypedDict /
        # Pydantic returns would land at the top level instead. The pilot
        # uses ``Dict[str, Any]`` so the payload sits one level down.
        payload = structured["result"] if "result" in structured else structured
        assert isinstance(payload, dict)
        assert "namespaces" in payload
        assert isinstance(payload["namespaces"], dict)

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
        assert "files" in payload and isinstance(payload["files"], list)
        assert "count" in payload

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
        assert "entries" in payload and isinstance(payload["entries"], list)

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
        assert "entries" in payload and isinstance(payload["entries"], list)
        assert "done" in payload
        assert "namespace" in payload

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
        assert "suggestions" in payload
        assert isinstance(payload["suggestions"], list)

    @pytest.mark.asyncio
    async def test_search_all_returns_structured_content(
        self, server: OpenZimMcpServer
    ) -> None:
        """search_all per-file results must be dicts, not stringified markdown.

        Catches both wire-format requirements: (a) the tool emits
        structuredContent at all, and (b) ``per_file[].result`` is itself
        a real dict (the triple-encoding fix).
        """
        result = await server.mcp._tool_manager.call_tool(
            "search_all", {"query": "evolution"}, convert_result=True
        )
        assert isinstance(result, tuple)
        _, structured = result
        assert isinstance(structured, dict)
        # The previous tool migration revealed FastMCP wraps
        # ``Dict[str, Any]`` returns under a ``"result"`` key. Tolerate that.
        payload = structured["result"] if "result" in structured else structured
        assert "per_file" in payload
        for entry in payload.get("per_file", []):
            if "result" in entry:
                assert isinstance(
                    entry["result"], dict
                ), f"per_file[].result should be dict, got {type(entry['result'])}"
                assert "results" in entry["result"]

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
            assert "results" in payload
            assert "succeeded" in payload
            assert "failed" in payload

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
            assert "internal_links" in payload

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
