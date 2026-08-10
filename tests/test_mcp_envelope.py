"""Unit coverage for the ``CallToolResult`` envelope seam.

The discriminator in :mod:`openzim_mcp.mcp_envelope` decides whether a tool's
return value is a failure. Getting it wrong in either direction is worse than
the bug it fixes: a false negative leaves a failure looking successful, and a
false positive flags a working call as an error. These tests pin both edges.
"""

import json

import pytest
from mcp_types import TextContent

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.instructions import (
    ADVANCED_INSTRUCTIONS,
    SIMPLE_INSTRUCTIONS,
    instructions_for,
)
from openzim_mcp.mcp_envelope import error_result, is_tool_error_envelope
from openzim_mcp.responses import tool_error
from openzim_mcp.server import OpenZimMcpServer


def test_recognizes_the_tool_error_envelope():
    assert is_tool_error_envelope(tool_error(operation="zim_search", message="nope"))


def test_recognizes_an_envelope_carrying_optional_fields():
    payload = tool_error(
        operation="zim_get",
        message="nope",
        context="Path: a.zim",
        extras={"available_section_ids": ["s1"]},
    )
    assert is_tool_error_envelope(payload)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"results": [], "total": 0}, id="ordinary-success"),
        pytest.param({"error": False}, id="explicit-non-error"),
        pytest.param(
            {"error": "true", "operation": "x", "message": "y"}, id="stringy-error-flag"
        ),
        pytest.param({"error": True}, id="flag-without-envelope-fields"),
        pytest.param({"error": True, "operation": "x"}, id="envelope-missing-message"),
        pytest.param(
            {"error": True, "operation": 7, "message": "y"}, id="non-string-operation"
        ),
        pytest.param("a markdown string", id="string-return"),
        pytest.param(None, id="none-return"),
    ],
)
def test_does_not_flag_non_envelopes(payload):
    assert not is_tool_error_envelope(payload)


def test_partial_failure_in_search_all_is_not_a_failed_call():
    """A cross-archive search where some archives failed still succeeded.

    ``search_all`` marks unreadable archives with ``error: True`` inside
    ``results[]``, alongside ``error_operation`` / ``error_message``. Those
    rows are per-archive status, not the call's outcome — flagging the whole
    response would tell the client its query failed when it returned hits.
    """
    payload = {
        "query": "aspirin",
        "files_searched": 2,
        "files_with_hits": 1,
        "files_failed": 1,
        "results": [
            {"zim_file_path": "a.zim", "has_hits": True, "error": False},
            {
                "zim_file_path": "b.zim",
                "has_hits": False,
                "result": None,
                "error": True,
                "error_operation": "search_zim_file",
                "error_message": "boom",
            },
        ],
        "total": 2,
        "done": True,
    }

    assert not is_tool_error_envelope(payload)


def test_error_result_preserves_the_envelope_verbatim():
    payload = tool_error(operation="zim_search", message="**Denied**", context="q: x")

    result = error_result(payload)

    assert result.is_error is True
    assert result.structured_content is None
    assert isinstance(result.content[0], TextContent)
    assert json.loads(result.content[0].text) == payload


def test_instructions_match_the_registered_surface():
    """Simple mode must not advertise tools the client cannot call."""
    assert instructions_for("simple") == SIMPLE_INSTRUCTIONS
    assert instructions_for("advanced") == ADVANCED_INSTRUCTIONS

    for absent in ("zim_search", "zim_get", "zim_browse", "zim_links"):
        assert absent not in SIMPLE_INSTRUCTIONS
    assert "zim_query" in SIMPLE_INSTRUCTIONS


def test_server_wires_instructions_for_its_mode(tmp_path):
    for mode in ("simple", "advanced"):
        server = OpenZimMcpServer(
            OpenZimMcpConfig(allowed_directories=[str(tmp_path)], tool_mode=mode)
        )
        assert server.mcp.instructions == instructions_for(mode)


def _register_probe_tools(mcp):
    """Register one tool per return shape the real surface produces."""

    @mcp.tool(description="returns markdown, like zim_query")
    async def markdown_tool() -> str:
        return "# Aspirin\n\nA medication."

    @mcp.tool(description="returns an untyped dict, like the other seven")
    async def dict_tool():
        return {"results": [1, 2], "done": True}

    @mcp.tool(description="returns a typed dict")
    async def typed_dict_tool() -> dict:
        return {"results": [1, 2], "done": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["markdown_tool", "dict_tool", "typed_dict_tool"])
async def test_override_leaves_success_returns_byte_identical(tool_name):
    """The success path must produce exactly what a stock MCPServer produces.

    ``call_tool`` is overridden to inspect the raw return value before
    conversion, so it also owns re-converting it. That detour must be
    invisible: markdown, untyped dicts and typed dicts all have distinct
    conversion rules (typed non-dict returns get wrapped and gain an output
    schema), and getting any of them wrong would silently reshape the wire.
    """
    from mcp.server.mcpserver import MCPServer

    from openzim_mcp.mcp_envelope import EnvelopeAwareMCPServer

    baseline = MCPServer("test")
    overridden = EnvelopeAwareMCPServer("test")
    _register_probe_tools(baseline)
    _register_probe_tools(overridden)

    expected = await baseline.call_tool(tool_name, {})
    actual = await overridden.call_tool(tool_name, {})

    assert actual == expected


@pytest.mark.asyncio
async def test_override_flags_a_returned_envelope():
    from openzim_mcp.mcp_envelope import EnvelopeAwareMCPServer

    mcp = EnvelopeAwareMCPServer("test")

    @mcp.tool(description="fails")
    async def failing_tool():
        return tool_error(operation="failing_tool", message="denied")

    result = await mcp.call_tool("failing_tool", {})

    assert result.is_error is True
    assert json.loads(result.content[0].text)["operation"] == "failing_tool"
