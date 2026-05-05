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

    @pytest.mark.xfail(
        reason="awaiting Phase 2 migration of list_namespaces",
        strict=False,
    )
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
        assert "namespaces" in structured
        assert isinstance(structured["namespaces"], dict)
