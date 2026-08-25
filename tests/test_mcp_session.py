"""Session-layer MCP protocol conformance tests.

Every other test in this suite calls a tool's ``*_data`` function directly or
goes through ``server.mcp.call_tool()``, which returns the tool's *return
value* — not the ``CallToolResult`` envelope the client actually receives. The
envelope fields (``is_error``, ``structured_content``) and the server's
``instructions`` are therefore invisible to all of them.

These tests drive a real client session over an in-memory transport so the
assertions are on what a client sees on the wire.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import anyio
import pydantic_core
import pytest
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from mcp_types import EmptyResult, TextContent

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
    async with _connected_client(server) as session:
        yield session


@asynccontextmanager
async def _connected_client(server: OpenZimMcpServer) -> AsyncIterator[Any]:
    """A ``ClientSession`` wired to ``server`` over in-memory streams.

    The 1.x SDK shipped ``create_connected_server_and_client_session``; v2
    exposes only the stream pair, so the wiring lives here. ``initialize()``
    exercises the *legacy* handshake, which the v2 server still answers — the
    dual-era behavior that lets 2025-era clients keep working against this
    build (see ``test_serves_both_protocol_eras``).
    """
    low = server.mcp._lowlevel_server
    async with create_client_server_memory_streams() as (
        client_streams,
        server_streams,
    ):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(
                low.run,
                server_read,
                server_write,
                low.create_initialization_options(),
                True,  # raise_exceptions - surface server faults in tests
            )
            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                yield session
            task_group.cancel_scope.cancel()


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
    """A failed tool call must set ``is_error``.

    Agent frameworks branch on ``is_error`` to decide whether to surface, retry
    or stop. Returning the error envelope with ``is_error=False`` makes every
    failure read as a successful call whose payload happens to say otherwise.
    """
    async with advanced_session(tmp_path) as session:
        result = await session.call_tool("zim_search", arguments)

    assert result.is_error is True, (
        f"{expected_operation} returned is_error={result.is_error}; "
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
    """Setting ``is_error`` must not reshape the body.

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

    assert result.is_error is False
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
    """``output_schema`` is a promise to deliver ``structured_content``.

    ``zim_query`` returned markdown wrapped as ``{"result": "<str>"}`` — a
    schema that cost 4.7KB of the surface budget and told clients nothing. The
    seven tools returning real dicts advertised nothing at all. Until output
    schemas describe the actual payloads, no tool should claim one.
    """
    async with advanced_session(tmp_path) as session:
        tools = (await session.list_tools()).tools

    advertising = [t.name for t in tools if t.output_schema is not None]
    assert advertising == [], (
        f"{advertising} advertise an output_schema; "
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

    assert result.is_error is True
    assert json.loads(_text(result))["operation"] == "invalid_limit"


@asynccontextmanager
async def _modern_client(
    tmp_path: Path, stub_read: bool = False, **config_kwargs: Any
) -> AsyncIterator[Any]:
    """A client that opens with ``server/discover`` instead of ``initialize``.

    ``_connected_client`` drives the legacy handshake, which is what most of
    this file asserts against. The 2026-07-28 era has no handshake at all: a
    client may call ``server/discover`` up front and otherwise just sends
    requests. Cache hints are era-gated (see the tests below), so telling the
    two apart needs a client that opens the modern way.

    ``stub_read`` replaces the archive read with a fixed body. The per-URI TTL
    tests need a *successful* read of a ``zim://{name}`` URI, which otherwise
    requires a real ZIM file on disk; the archive layer is not what those tests
    are about. Everything the assertion depends on — URI routing, the TTL the
    handler stamps, the SDK's hint application, and the wire encoding — is the
    real code path.
    """
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)], tool_mode="advanced", **config_kwargs
    )
    server = OpenZimMcpServer(config)
    if stub_read:
        from mcp.server.lowlevel.helper_types import ReadResourceContents

        async def _stub(uri: Any, context: Any = None) -> Any:
            return [ReadResourceContents(content="stub", mime_type="text/plain")]

        server.mcp.read_resource = _stub  # type: ignore[method-assign]
    low = server.mcp._lowlevel_server
    async with create_client_server_memory_streams() as (
        client_streams,
        server_streams,
    ):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(
                low.run,
                server_read,
                server_write,
                low.create_initialization_options(),
                True,
            )
            async with ClientSession(client_read, client_write) as session:
                await session.discover()
                yield session
            task_group.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_cache_hints_are_served_to_modern_clients(tmp_path: Path) -> None:
    """List results carry the TTL that lets a client cache them.

    A wrong or missing ``ttlMs`` is invisible in ordinary use — the server
    still answers every request correctly, it just never gets to skip one — so
    nothing else in the suite would notice the hints silently not applying.
    """
    async with _modern_client(tmp_path, watch_interval_seconds=5) as session:
        tools = await session.list_tools()
        resources = await session.list_resources()
        prompts = await session.list_prompts()
        read = await session.read_resource("zim://files")

    # Registration tables cannot change without a restart.
    one_hour_ms = 60 * 60 * 1000
    assert tools.ttl_ms == one_hour_ms
    assert resources.ttl_ms == one_hour_ms
    assert prompts.ttl_ms == one_hour_ms

    # A read is bounded by how fast the watcher could notice a change, so a
    # cached copy is never staler than the server's own view.
    assert read.ttl_ms == 5 * 1000

    # Every payload embeds server-local paths and config: never shared-cacheable.
    for result in (tools, resources, prompts, read):
        assert result.cache_scope == "private"


@pytest.mark.asyncio
async def test_read_ttl_tracks_the_watch_interval(tmp_path: Path) -> None:
    """The read TTL is derived from config, not a hardcoded constant."""
    async with _modern_client(tmp_path, watch_interval_seconds=30) as session:
        read = await session.read_resource("zim://files")

    assert read.ttl_ms == 30 * 1000


@pytest.mark.asyncio
async def test_archive_overview_reads_carry_the_long_ttl(tmp_path: Path) -> None:
    """A ``zim://{name}`` read is cacheable for far longer than a poll interval.

    The method-wide hint bounds every read by the watcher interval because the
    same method also serves ``zim://files``. An archive URI has no such
    constraint — the file behind it is sealed — so it carries its own TTL.
    """
    async with _modern_client(
        tmp_path,
        stub_read=True,
        watch_interval_seconds=5,
        resource_cache_ttl_seconds=7200,
    ) as session:
        read = await session.read_resource("zim://wiki")

    assert read.ttl_ms == 7200 * 1000
    # Still server-local paths and config: the scope must survive the override.
    assert read.cache_scope == "private"


@pytest.mark.asyncio
async def test_entry_reads_keep_the_watcher_bounded_ttl(tmp_path: Path) -> None:
    """A per-entry read must NOT take the long TTL: nothing can invalidate it.

    The hour-long hint on ``zim://{name}`` is honest because a replacement
    publishes ``resources/updated`` for exactly that URI. Entry URIs have no
    such story: the watcher never publishes them, and both SDK delivery and
    client-side cache eviction are exact-URI, so a long-TTL entry read would
    simply sit stale for the full TTL after an archive replacement.
    """
    async with _modern_client(
        tmp_path,
        stub_read=True,
        watch_interval_seconds=5,
        resource_cache_ttl_seconds=7200,
    ) as session:
        read = await session.read_resource("zim://wiki/entry/A%2FArticle")

    assert read.ttl_ms == 5 * 1000


@pytest.mark.asyncio
async def test_overview_error_bodies_keep_the_watcher_bounded_ttl(
    tmp_path: Path,
) -> None:
    """A ``zim://{name}`` read that failed inside its body gets the short TTL.

    The overview deliberately reports failure as a *successful* JSON body
    (``{"error": ...}`` — a contract pinned in ``test_resources.py``), so the
    long-TTL stamp cannot key on the result status alone. A cached "ZIM file
    not found" body must not outlive the moment the operator drops the
    archive into place: membership changes publish only
    ``resources/list_changed``, which never evicts a cached read of this URI.
    """
    async with _modern_client(
        tmp_path, watch_interval_seconds=5, resource_cache_ttl_seconds=7200
    ) as session:
        read = await session.read_resource("zim://does_not_exist")

    body = json.loads(read.contents[0].text)
    assert "error" in body  # precondition: the error-body contract held
    assert read.ttl_ms == 5 * 1000


@pytest.mark.asyncio
async def test_overview_partial_failure_bodies_keep_the_watcher_bounded_ttl(
    tmp_path: Path,
) -> None:
    """The ``*_error`` partial-failure shape is excluded from the long TTL too.

    An overview of an archive that resolves but cannot be read reports each
    failed section as a ``*_error`` key with no top-level ``"error"`` — a
    transient condition, not the sealed archive, so an hour-long hint on it
    would freeze the failure. A bogus ``.zim`` file produces the shape
    naturally: name resolution globs the directory and succeeds, then every
    section read fails.
    """
    (tmp_path / "bogus.zim").write_bytes(b"not a zim archive")

    async with _modern_client(
        tmp_path, watch_interval_seconds=5, resource_cache_ttl_seconds=7200
    ) as session:
        read = await session.read_resource("zim://bogus")

    body = json.loads(read.contents[0].text)
    assert "error" not in body  # precondition: this is the partial shape,
    assert any(key.endswith("_error") for key in body)  # not the total one
    assert read.ttl_ms == 5 * 1000


@pytest.mark.asyncio
async def test_files_listing_keeps_the_watcher_bounded_ttl(tmp_path: Path) -> None:
    """``zim://files`` is a live directory scan and must not take the long TTL.

    This is the whole reason the hint could not simply be raised method-wide.
    """
    async with _modern_client(
        tmp_path, watch_interval_seconds=5, resource_cache_ttl_seconds=7200
    ) as session:
        read = await session.read_resource("zim://files")

    assert read.ttl_ms == 5 * 1000


@pytest.mark.asyncio
async def test_zero_ttl_falls_back_to_the_watcher_bound(tmp_path: Path) -> None:
    """``0`` turns the override off rather than making reads uncacheable.

    An operator who hot-swaps archives wants the conservative behavior back,
    not a stricter one: the watcher's own detection latency is already the
    tightest bound the server can honestly promise.
    """
    async with _modern_client(
        tmp_path,
        stub_read=True,
        watch_interval_seconds=5,
        resource_cache_ttl_seconds=0,
    ) as session:
        read = await session.read_resource("zim://wiki")

    assert read.ttl_ms == 5 * 1000


@pytest.mark.asyncio
async def test_legacy_clients_are_not_served_cache_hints(tmp_path: Path) -> None:
    """A 2025-era session gets no ``ttlMs`` — the field postdates its revision.

    Pinned because it is the SDK doing era-appropriate framing on our behalf,
    not something this server implements: if that ever regressed, we would be
    sending a legacy client a field its protocol has no meaning for.
    """
    async with session_for(tmp_path, "advanced") as session:
        tools = await session.list_tools()

    assert tools.ttl_ms == 0


def test_every_registered_resource_has_a_deliberate_ttl(tmp_path: Path) -> None:
    """Guards the one assumption the per-URI TTL rests on.

    ``_handle_read_resource`` states the policy as an exception: everything
    except ``zim://files`` is backed by a sealed archive and may be cached for
    an hour. That is true of the current registrations and silently wrong for
    any future resource that is computed rather than read from a ZIM — it
    would inherit the long TTL without anyone deciding it should. Registering
    one fails here, which is the prompt to classify it.
    """
    from openzim_mcp.mcp_envelope import _LIVE_SCAN_URI

    config = OpenZimMcpConfig(allowed_directories=[str(tmp_path)], tool_mode="advanced")
    server = OpenZimMcpServer(config)
    manager = server.mcp._resource_manager

    assert set(manager._resources) == {_LIVE_SCAN_URI}
    assert set(manager._templates) == {
        "zim://{name}",
        "zim://{name}/entry/{path}",
    }


@pytest.mark.asyncio
async def test_legacy_clients_are_not_served_the_per_uri_ttl(tmp_path: Path) -> None:
    """The per-URI stamp must not leak a 2026-only field into a legacy session.

    The method-wide hints are applied by the SDK, which does the era gating; an
    explicit ``ttl_ms`` set by our own handler bypasses that decision point, so
    the gating is worth pinning on this path specifically rather than assuming
    it from the list-endpoint test above.
    """
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        tool_mode="advanced",
        resource_cache_ttl_seconds=7200,
    )
    server = OpenZimMcpServer(config)

    from mcp.server.lowlevel.helper_types import ReadResourceContents

    async def _stub(uri: Any, context: Any = None) -> Any:
        return [ReadResourceContents(content="stub", mime_type="text/plain")]

    server.mcp.read_resource = _stub  # type: ignore[method-assign]

    async with _connected_client(server) as session:
        read = await session.read_resource("zim://wiki")

    assert read.ttl_ms == 0


@pytest.mark.asyncio
async def test_modern_clients_can_ping(tmp_path: Path) -> None:
    """A keepalive ping on a 2026-07-28 connection is answered, not -32601.

    2026-07-28 drops ping, and SDK 2.0.0 ships its modern method tables
    without a ping row to match (python-sdk#3273, closed not-planned as
    intended spec behaviour), so a keepalive-pinging modern client — the kind
    this port exists to serve — would see METHOD_NOT_FOUND on every ping and
    flap its connection. ``install_ping_keepalive_shim`` answers it anyway at
    server construction: a deliberate, standing deviation from the revision,
    kept permanently per the decision in issue #371. This test asserts the
    behavior clients see, not the mechanism.
    """
    async with _modern_client(tmp_path) as session:
        result = await session.send_ping()

    assert isinstance(result, EmptyResult)


@pytest.mark.asyncio
async def test_legacy_clients_can_still_ping(tmp_path: Path) -> None:
    """The shim's table rows are modern-only; the legacy ping path must not move."""
    async with session_for(tmp_path, "advanced") as session:
        result = await session.send_ping()

    assert isinstance(result, EmptyResult)
