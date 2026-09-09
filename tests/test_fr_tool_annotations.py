"""Every published tool declares the read-only MCP annotations.

v3.3.1 field report: "No tool declares MCP annotations (``readOnlyHint``,
``idempotentHint``, ``openWorldHint``) though all eight are read-only — free
signal for any client that reads them."

The pair that carries weight is ``readOnlyHint: true`` + ``openWorldHint:
false``: a client deciding whether a call needs human approval reads the
first, and one deciding whether the result can be cached or replayed reads
the second. ``destructiveHint`` and ``idempotentHint`` are deliberately
absent — the MCP spec defines both as meaningful only when ``readOnlyHint``
is false, so shipping them here would be noise a client has to ignore.

The assertions below drive ``mcp.list_tools()``, the same coroutine that
answers a real ``tools/list``, rather than reading the registration kwarg
back out of the tool manager: the kwarg is only worth anything if it
survives to the wire.
"""

from __future__ import annotations

import tempfile

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

ADVANCED_TOOLS = {
    "zim_query",
    "zim_search",
    "zim_get",
    "zim_get_section",
    "zim_browse",
    "zim_metadata",
    "zim_links",
    "zim_health",
}


def _server(mode: str) -> OpenZimMcpServer:
    allowed = tempfile.mkdtemp(prefix="openzim_mcp_annotations_")
    return OpenZimMcpServer(
        OpenZimMcpConfig(allowed_directories=[allowed], tool_mode=mode)
    )


@pytest.mark.asyncio
async def test_every_advanced_tool_is_published_as_read_only():
    tools = await _server("advanced").mcp.list_tools()

    assert {t.name for t in tools} == ADVANCED_TOOLS

    missing = [t.name for t in tools if t.annotations is None]
    assert not missing, f"tools published with no annotations at all: {missing}"

    not_read_only = [
        f"{t.name}: readOnlyHint={t.annotations.read_only_hint!r}"
        for t in tools
        if t.annotations is not None and t.annotations.read_only_hint is not True
    ]
    assert not not_read_only, (
        "every openzim-mcp tool reads from a local archive and writes "
        "nothing, so each must publish readOnlyHint=true: " + str(not_read_only)
    )


@pytest.mark.asyncio
async def test_the_surface_is_published_as_a_closed_world():
    """No tool reaches the network, so no tool may claim an open world.

    ``openWorldHint`` defaults to *true* when absent, so leaving it unset is
    not neutral — it advertises the opposite of what this server does. That
    is the whole reason the field is worth its bytes.
    """
    tools = await _server("advanced").mcp.list_tools()

    open_world = [
        f"{t.name}: openWorldHint={t.annotations.open_world_hint!r}"
        for t in tools
        if t.annotations is None or t.annotations.open_world_hint is not False
    ]
    assert not open_world, (
        "openzim-mcp is offline-first — every tool's domain of interaction is "
        "the archives on disk: " + str(open_world)
    )


@pytest.mark.asyncio
async def test_hints_that_only_mean_something_for_writers_are_omitted():
    """``destructiveHint``/``idempotentHint`` are read-only-false vocabulary.

    Pinned so a later "declare everything" sweep cannot quietly add two
    fields per tool that the spec tells clients to ignore here — the bytes
    come out of a schema budget with a hard cap.
    """
    tools = await _server("advanced").mcp.list_tools()

    noisy = [
        f"{t.name}: destructive={t.annotations.destructive_hint!r} "
        f"idempotent={t.annotations.idempotent_hint!r}"
        for t in tools
        if t.annotations is not None
        and (
            t.annotations.destructive_hint is not None
            or t.annotations.idempotent_hint is not None
        )
    ]
    assert not noisy, (
        "destructiveHint/idempotentHint are defined by the MCP spec as "
        "meaningful only when readOnlyHint is false: " + str(noisy)
    )


@pytest.mark.asyncio
async def test_simple_modes_one_tool_carries_them_too():
    """Simple mode is the documented default and publishes one tool.

    A client that gates auto-approval on ``readOnlyHint`` gains nothing from
    an annotated advanced surface if the default mode's sole tool is bare.
    """
    tools = await _server("simple").mcp.list_tools()

    assert [t.name for t in tools] == ["zim_query"]
    zim_query = tools[0]
    assert zim_query.annotations is not None, "simple mode's only tool is bare"
    assert zim_query.annotations.read_only_hint is True
    assert zim_query.annotations.open_world_hint is False
