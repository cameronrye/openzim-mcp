"""Session-layer MCP protocol conformance tests.

Every other test in this suite calls a tool's ``*_data`` function directly or
goes through ``server.mcp.call_tool()``, which returns the tool's *return
value* — not the ``CallToolResult`` envelope the client actually receives. The
envelope fields (``isError``, ``structuredContent``) and the server's
``instructions`` are therefore invisible to all of them.

These tests drive a real client session over an in-memory transport so the
assertions are on what a client sees on the wire.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import pydantic_core
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

# The advanced surface's whole design premise is staying under the "MCP Tax"
# pain band (25-50KB of schema), a claim the README and four website pages
# repeat. Nothing measured it, and it had drifted to 28.9KB. This ceiling is
# the enforcement: it fails the build when a description grows past the band
# edge, so the documented figure and the wire stay in sync.
MCP_TAX_BAND_FLOOR_BYTES = 25 * 1024


@asynccontextmanager
async def session_for(tmp_path: Path, tool_mode: str) -> AsyncIterator[Any]:
    """A connected client session against the given tool surface.

    Deliberately a context manager rather than a pytest fixture: the session's
    anyio task group has to be entered and exited from the same task, and an
    async yield fixture tears down in a different one.
    """
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        tool_mode=tool_mode,
    )
    server = OpenZimMcpServer(config)
    async with create_connected_server_and_client_session(
        server.mcp._mcp_server
    ) as session:
        yield session


def advanced_session(tmp_path: Path) -> Any:
    """The 8-tool advanced surface."""
    return session_for(tmp_path, "advanced")


def _text(result: Any) -> str:
    """The concatenated text of a CallToolResult's content blocks."""
    return "".join(b.text for b in result.content if isinstance(b, TextContent))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments, expected_operation",
    [
        # A path outside allowed_directories. Reading as success is the worst
        # of these: a client cannot tell a denied read from an empty one.
        ({"query": "x", "zim_file_path": "/etc/passwd"}, "zim_search"),
        # Archive that does not exist.
        ({"query": "x", "zim_file_path": "/nonexistent/archive.zim"}, "zim_search"),
        # Handler-side argument validation (no archive resolvable).
        ({"query": "x"}, "missing_archive"),
        # Out-of-range limit — rejected by the handler, not by the input schema.
        (
            {"query": "x", "mode": "title", "limit": 10_000},
            "invalid_limit",
        ),
        # Mutually exclusive arguments.
        (
            {"query": "x", "cross_file": True, "zim_file_path": "/tmp/a.zim"},
            "invalid_combination",
        ),
    ],
)
async def test_tool_originated_errors_set_is_error(
    tmp_path: Path, arguments: dict, expected_operation: str
) -> None:
    """A failed tool call must set ``isError``.

    Agent frameworks branch on ``isError`` to decide whether to surface, retry
    or stop. Returning the error envelope with ``isError=False`` makes every
    failure read as a successful call whose payload happens to say otherwise.
    """
    async with advanced_session(tmp_path) as session:
        result = await session.call_tool("zim_search", arguments)

    assert result.isError is True, (
        f"{expected_operation} returned isError={result.isError}; "
        "a client cannot distinguish this failure from a success"
    )
    payload = json.loads(_text(result))
    assert payload["error"] is True
    assert payload["operation"] == expected_operation


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        pytest.param("x", id="ascii"),
        # Non-ASCII rides into the envelope through the ``context`` field
        # ("Query: ..."), which is where the two candidate serializers diverge.
        pytest.param("фотосинтез 光合作用 café", id="non-ascii"),
    ],
)
async def test_error_body_keeps_the_structured_envelope(
    tmp_path: Path, query: str
) -> None:
    """Setting ``isError`` must not reshape the body.

    The JSON error envelope is a documented contract (``error`` / ``operation``
    / ``message``, optional ``context``). Flipping the flag is a protocol fix;
    it must not become a payload change that breaks parsing clients.

    The serializer is asserted against ``pydantic_core.to_json`` — the exact
    call FastMCP's dict-return path used — rather than ``json.dumps``. The two
    agree only on ASCII: ``json.dumps`` defaults to ``ensure_ascii=True`` and
    would escape a Cyrillic or CJK query to ``\\uXXXX``, silently changing the
    bytes for every non-English caller. Asserting against ``json.dumps`` here
    would pass on the ASCII case and pin the wrong contract.
    """
    async with advanced_session(tmp_path) as session:
        result = await session.call_tool(
            "zim_search", {"query": query, "zim_file_path": "/etc/passwd"}
        )

    text = _text(result)
    payload = json.loads(text)
    assert set(payload) >= {"error", "operation", "message"}
    assert isinstance(payload["message"], str) and payload["message"]
    assert text == pydantic_core.to_json(payload, fallback=str, indent=2).decode()
    # Raw UTF-8 on the wire, as before the fix — not \\uXXXX escapes.
    assert query in text


@pytest.mark.asyncio
async def test_successful_call_does_not_set_is_error(tmp_path: Path) -> None:
    """The flag has to discriminate — a healthy call must stay ``False``."""
    async with advanced_session(tmp_path) as session:
        result = await session.call_tool("zim_health", {})

    assert result.isError is False
    assert _text(result)


@pytest.mark.asyncio
async def test_advanced_surface_stays_under_the_mcp_tax_band(
    tmp_path: Path,
) -> None:
    """The advertised schema must stay below the 25-50KB pain band.

    This is the number README.md and four website pages quote. Pinning it here
    means the docs can cite a measured value instead of a stale one.
    """
    async with advanced_session(tmp_path) as session:
        tools = (await session.list_tools()).tools

    assert len(tools) == 8

    wire = json.dumps(
        [t.model_dump(exclude_none=True) for t in tools], separators=(",", ":")
    )
    assert len(wire) < MCP_TAX_BAND_FLOOR_BYTES, (
        f"advanced tools/list is {len(wire) / 1024:.1f}KB, at or above the "
        f"{MCP_TAX_BAND_FLOOR_BYTES / 1024:.0f}KB MCP Tax band floor the docs "
        "claim it clears"
    )


@pytest.mark.asyncio
async def test_no_tool_advertises_an_output_schema_it_does_not_honor(
    tmp_path: Path,
) -> None:
    """``outputSchema`` is a promise to deliver ``structuredContent``.

    ``zim_query`` returned markdown wrapped as ``{"result": "<str>"}`` — a
    schema that cost 4.7KB of the surface budget and told clients nothing. The
    seven tools returning real dicts advertised nothing at all. Until output
    schemas describe the actual payloads, no tool should claim one.
    """
    async with advanced_session(tmp_path) as session:
        tools = (await session.list_tools()).tools

    advertising = [t.name for t in tools if t.outputSchema is not None]
    assert advertising == [], (
        f"{advertising} advertise an outputSchema; "
        "either deliver conforming structuredContent or drop it"
    )


@pytest.mark.asyncio
async def test_server_advertises_routing_instructions(tmp_path: Path) -> None:
    """``instructions`` rides in ``initialize`` and was previously unset.

    It is the one place to put cross-tool routing guidance without paying for
    it in every tool description, and the dispatch eval shows exactly which
    confusions need it.
    """
    async with session_for(tmp_path, "advanced") as session:
        result = await session.initialize()

    assert result.instructions, "server advertises no instructions"
    for tool in ("zim_query", "zim_search", "zim_get"):
        assert tool in result.instructions


@pytest.mark.asyncio
async def test_simple_mode_advertises_only_what_it_registers(tmp_path: Path) -> None:
    """Simple mode is the default surface and needs its own session coverage.

    Every other test here drives advanced mode, so nothing would notice if the
    server handed simple-mode clients the 8-tool routing guide — describing
    seven tools they cannot call, in the mode most callers actually get.
    """
    async with session_for(tmp_path, "simple") as session:
        result = await session.initialize()
        tools = (await session.list_tools()).tools

    assert [t.name for t in tools] == ["zim_query"]
    assert result.instructions
    assert "zim_query" in result.instructions
    for unregistered in ("zim_search", "zim_get", "zim_browse", "zim_links"):
        assert unregistered not in result.instructions


@pytest.mark.asyncio
async def test_simple_mode_flags_rejected_arguments(tmp_path: Path) -> None:
    """The envelope fix has to hold on the default surface too."""
    async with session_for(tmp_path, "simple") as session:
        result = await session.call_tool("zim_query", {"query": "x", "limit": 10_000})

    assert result.isError is True
    assert json.loads(_text(result))["operation"] == "invalid_limit"
