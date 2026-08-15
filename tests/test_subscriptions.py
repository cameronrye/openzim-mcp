"""Tests for the polling watcher and its bridge onto the SDK subscription bus.

Under the 2026-07-28 revision the server no longer owns any delivery
machinery: ``resources/subscribe`` and protocol sessions are gone, clients
opt in via ``subscriptions/listen``, and the SDK's ``SubscriptionBus`` owns
the listener registry, per-stream filtering, backpressure and teardown. What
remains ours is *detecting* that a ZIM file changed (``MtimeWatcher``) and
*naming* the change as an MCP notification (``publish_change``) — so those
are what this module covers.
"""

import asyncio
from pathlib import Path

import pytest
from mcp.server.subscriptions import (
    InMemorySubscriptionBus,
    ResourcesListChanged,
    ResourceUpdated,
    ServerEvent,
)


@pytest.mark.asyncio
async def test_watcher_detects_new_zim_file(tmp_path: Path) -> None:
    """Polling watcher fires zim://files when a .zim is added."""
    from openzim_mcp.subscriptions import MtimeWatcher

    events: list[tuple[str, str]] = []

    async def emit(uri: str, change_type: str) -> None:
        events.append((uri, change_type))

    watcher = MtimeWatcher([str(tmp_path)], interval=0.05, on_change=emit)
    await watcher.start()
    try:
        await asyncio.sleep(0.15)  # initial scan, no files
        (tmp_path / "test.zim").write_bytes(b"")
        # Up to ~0.5s for the watcher's next pass to notice.
        for _ in range(20):
            await asyncio.sleep(0.05)
            if any(uri == "zim://files" for uri, _ in events):
                break
        assert any(uri == "zim://files" for uri, _ in events)
    finally:
        await watcher.stop()


@pytest.mark.asyncio
async def test_watcher_detects_file_replacement(tmp_path: Path) -> None:
    """Replacing a .zim with different size fires zim://{name}."""
    from openzim_mcp.subscriptions import MtimeWatcher

    target = tmp_path / "archive.zim"
    target.write_bytes(b"v1")

    events: list[tuple[str, str]] = []

    async def emit(uri: str, change_type: str) -> None:
        events.append((uri, change_type))

    watcher = MtimeWatcher([str(tmp_path)], interval=0.05, on_change=emit)
    await watcher.start()
    try:
        await asyncio.sleep(0.1)
        # Write content of a different length — real ZIM replacements always
        # change size (variable-length headers/clusters). The watcher
        # deliberately ignores mtime-only bumps to avoid `touch`-style
        # spurious notifications.
        target.write_bytes(b"v2-with-different-length")
        for _ in range(20):
            await asyncio.sleep(0.05)
            if any(uri == "zim://archive" for uri, _ in events):
                break
        assert any(uri == "zim://archive" for uri, _ in events)
    finally:
        await watcher.stop()


@pytest.mark.asyncio
async def test_watcher_detects_same_size_replacement(tmp_path: Path) -> None:
    """Same-size replacement with different mtime must trigger notification.

    Real ZIM replacements can have identical size (small stub fixtures,
    test fixtures, atomic-rename swaps that happen to match byte-for-byte
    in length). Missing such a replacement is the worse error mode for
    a watcher: a stale subscriber gets stale data forever. A `touch`-style
    bump that triggers an extra refresh is the cheaper trade-off.
    """
    from openzim_mcp.subscriptions import MtimeWatcher

    target = tmp_path / "archive.zim"
    target.write_bytes(b"a" * 1024)

    events: list[tuple[str, str]] = []

    async def emit(uri: str, change_type: str) -> None:
        events.append((uri, change_type))

    watcher = MtimeWatcher([str(tmp_path)], interval=0.05, on_change=emit)
    # Establish baseline snapshot, then drive one polling tick directly
    # so the assertion doesn't depend on sleep/scheduler timing.
    watcher._snapshot = watcher._scan()

    # Replace with same-length but different content; sleep to ensure the
    # mtime delta exceeds filesystem granularity (most FSes give us at
    # least ms resolution; 50ms is comfortably above that).
    await asyncio.sleep(0.05)
    target.write_bytes(b"b" * 1024)

    await watcher._tick()
    assert any(
        uri == "zim://archive" and change_type == "replaced"
        for uri, change_type in events
    ), f"expected replaced notification for same-size rewrite; got {events!r}"


@pytest.mark.asyncio
async def test_watcher_triggers_on_mtime_only_change(tmp_path: Path) -> None:
    """An mtime-only bump now triggers (false positive accepted by design).

    Previously the watcher ignored mtime-only changes to suppress
    `touch`-style spurious notifications. That suppression also silently
    dropped real same-size replacements. We accept the false-positive
    trade-off because eliminating false negatives is the priority for a
    watcher whose job is to alert on changes.
    """
    import os
    import time

    from openzim_mcp.subscriptions import MtimeWatcher

    target = tmp_path / "archive.zim"
    target.write_bytes(b"some-content-that-stays-the-same")

    events: list[tuple[str, str]] = []

    async def emit(uri: str, change_type: str) -> None:
        events.append((uri, change_type))

    watcher = MtimeWatcher([str(tmp_path)], interval=0.05, on_change=emit)
    watcher._snapshot = watcher._scan()

    # Bump mtime without altering byte content. `touch` and backup tools
    # cause this; the new policy treats it as a change.
    future = time.time() + 5
    os.utime(target, (future, future))

    await watcher._tick()
    assert any(uri == "zim://archive" for uri, _ in events)


@pytest.mark.asyncio
async def test_watcher_stop_is_idempotent(tmp_path: Path) -> None:
    """Calling stop() twice doesn't blow up."""
    from openzim_mcp.subscriptions import MtimeWatcher

    async def emit(uri: str, change_type: str) -> None:
        # No-op handler — this test only exercises stop() idempotency.
        return

    watcher = MtimeWatcher([str(tmp_path)], interval=0.05, on_change=emit)
    await watcher.start()
    await watcher.stop()
    await watcher.stop()  # second call is fine


class _RecordingBus:
    """Minimal ``SubscriptionBus`` stand-in that records published events.

    ``publish_change`` only ever calls ``publish``; using a stub keeps the
    mapping assertions independent of the SDK bus's fan-out machinery, which
    has its own tests upstream. ``publish`` is async to match the protocol —
    the bus interface is async so an out-of-process backend can do network
    I/O — which also means a stub that forgot to await would be caught here.
    """

    def __init__(self) -> None:
        """Start with an empty event log."""
        self.events: list[ServerEvent] = []

    async def publish(self, event: ServerEvent) -> None:
        """Record one published event."""
        self.events.append(event)


@pytest.mark.asyncio
async def test_publish_change_maps_list_changed_to_resources_list_changed() -> None:
    """A file appearing/disappearing changes the membership of ``zim://files``.

    That is a ``notifications/resources/list_changed``, not an ``updated``.
    The 1.x implementation could not express the distinction — ``resources/
    subscribe`` gave clients no way to ask for list-membership changes, so
    both watcher change kinds went out as an ``updated`` for ``zim://files``.
    This mapping is therefore new behavior in the 2.0 port.
    """
    from openzim_mcp.subscriptions import publish_change

    bus = _RecordingBus()
    await publish_change(bus, "zim://files", "list_changed")

    assert bus.events == [ResourcesListChanged()]


@pytest.mark.asyncio
async def test_publish_change_maps_replaced_to_resource_updated() -> None:
    """A file replaced in place leaves the list intact and invalidates one
    resource, so it must become an ``updated`` carrying that file's URI —
    not a list_changed, which would make every client re-list needlessly.
    """
    from openzim_mcp.subscriptions import publish_change

    bus = _RecordingBus()
    await publish_change(bus, "zim://wikipedia_en", "replaced")

    assert bus.events == [ResourceUpdated(uri="zim://wikipedia_en")]


@pytest.mark.asyncio
async def test_publish_change_reaches_real_bus_listeners() -> None:
    """The two kinds must survive a real ``InMemorySubscriptionBus`` round
    trip, pinning that ``publish_change`` emits event objects the SDK bus
    actually accepts (rather than only satisfying our stub's duck type).
    """
    from openzim_mcp.subscriptions import publish_change

    bus = InMemorySubscriptionBus()
    seen: list[ServerEvent] = []
    unsubscribe = bus.subscribe(seen.append)
    try:
        await publish_change(bus, "zim://files", "list_changed")
        await publish_change(bus, "zim://archive", "replaced")
    finally:
        unsubscribe()

    assert seen == [ResourcesListChanged(), ResourceUpdated(uri="zim://archive")]


@pytest.mark.asyncio
async def test_watcher_changes_reach_the_bus_end_to_end(tmp_path: Path) -> None:
    """The watcher and the bus bridge compose the way ``http_app`` wires them.

    ``MtimeWatcher`` is deliberately bus-agnostic (it takes a plain
    ``on_change`` callback), so nothing else pins that a detected change
    turns into the right notification kind on the wire.
    """
    from openzim_mcp.subscriptions import MtimeWatcher, publish_change

    bus = InMemorySubscriptionBus()
    seen: list[ServerEvent] = []
    unsubscribe = bus.subscribe(seen.append)

    async def on_change(uri: str, change_type: str) -> None:
        await publish_change(bus, uri, change_type)

    watcher = MtimeWatcher([str(tmp_path)], interval=0.05, on_change=on_change)
    watcher._snapshot = watcher._scan()
    try:
        (tmp_path / "archive.zim").write_bytes(b"v1")
        await watcher._tick()
    finally:
        unsubscribe()

    assert seen == [ResourcesListChanged()]


@pytest.mark.asyncio
async def test_watcher_replacement_uri_matches_template_expansion(
    tmp_path: Path,
) -> None:
    """Stems outside RFC 6570's unreserved set are percent-encoded in events.

    SDK delivery (``event_matches``) compares the event URI against the
    client's subscribed URIs as exact strings, and a conformant client derives
    those strings by expanding the advertised ``zim://{name}`` template —
    which percent-encodes everything outside ALPHA / DIGIT / ``-._~``. A
    watcher that publishes the raw stem would never match such a
    subscription, silently dropping every replacement notification for
    archives with spaces or non-ASCII in their names.
    """
    from mcp.shared.uri_template import UriTemplate

    from openzim_mcp.subscriptions import MtimeWatcher

    stem = "wikipedia_es_niños"
    target = tmp_path / f"{stem}.zim"
    target.write_bytes(b"v1")

    events: list[tuple[str, str]] = []

    async def emit(uri: str, change_type: str) -> None:
        events.append((uri, change_type))

    watcher = MtimeWatcher([str(tmp_path)], interval=100, on_change=emit)
    await watcher.start()
    try:
        target.write_bytes(b"v2-with-different-length")
        await watcher._tick()
    finally:
        await watcher.stop()

    expected = UriTemplate.parse("zim://{name}").expand({"name": stem})
    assert (expected, "replaced") in events


@pytest.mark.asyncio
async def test_watcher_also_publishes_the_readable_raw_spelling(
    tmp_path: Path,
) -> None:
    """Both spellings that READ must also be spellings that NOTIFY.

    ``UriTemplate.match`` percent-decodes before matching, so
    ``zim://wikipedia_es_niños`` is a *successful* ``resources/read`` — which
    means a client that built its URI from the ``zim://files`` listing rather
    than by RFC 6570 expansion gets a working read and will subscribe with that
    same string. Delivery is exact-string, so publishing only the encoded form
    leaves that client on a URI nothing ever fires on: no notification, and
    (with the hour-long resource TTL) a stale overview for the life of the
    stream. Both forms are published when they differ.
    """
    from mcp.shared.uri_template import UriTemplate

    from openzim_mcp.subscriptions import MtimeWatcher

    stem = "wikipedia_es_niños"
    target = tmp_path / f"{stem}.zim"
    target.write_bytes(b"v1")

    events: list[tuple[str, str]] = []

    async def emit(uri: str, change_type: str) -> None:
        events.append((uri, change_type))

    watcher = MtimeWatcher([str(tmp_path)], interval=100, on_change=emit)
    await watcher.start()
    try:
        target.write_bytes(b"v2-with-different-length")
        await watcher._tick()
    finally:
        await watcher.stop()

    raw = f"zim://{stem}"
    encoded = UriTemplate.parse("zim://{name}").expand({"name": stem})
    assert raw != encoded  # guards the premise: this stem needs encoding
    # Both read, so both must notify.
    assert UriTemplate.parse("zim://{name}").match(raw) == {"name": stem}
    assert (raw, "replaced") in events
    assert (encoded, "replaced") in events


@pytest.mark.asyncio
async def test_watcher_publishes_one_event_for_an_unreserved_stem(
    tmp_path: Path,
) -> None:
    """A stem needing no encoding must not be published twice.

    The dual publish above is conditional on the two spellings differing. If it
    were unconditional, every ordinary archive would deliver each replacement
    twice to the same subscriber.
    """
    from openzim_mcp.subscriptions import MtimeWatcher

    target = tmp_path / "wikipedia_en.zim"
    target.write_bytes(b"v1")

    events: list[tuple[str, str]] = []

    async def emit(uri: str, change_type: str) -> None:
        events.append((uri, change_type))

    watcher = MtimeWatcher([str(tmp_path)], interval=100, on_change=emit)
    await watcher.start()
    try:
        target.write_bytes(b"v2-with-different-length")
        await watcher._tick()
    finally:
        await watcher.stop()

    assert events == [("zim://wikipedia_en", "replaced")]


@pytest.mark.asyncio
async def test_publish_change_drops_an_unknown_change_kind() -> None:
    """An unrecognised kind must publish nothing, not a fallthrough ``updated``.

    ``publish_change`` used to treat "not list_changed" as "replaced", so a
    third watcher change kind — a removal carrying ``zim://files``, say —
    would have been delivered as a ``resources/updated`` for that URI: exactly
    the conflation of list-membership with content that the 2026-07-28 split
    exists to end, silently reintroduced at the one seam nothing asserts on.
    """
    from openzim_mcp.subscriptions import publish_change

    bus = _RecordingBus()
    await publish_change(bus, "zim://files", "removed")

    assert bus.events == []


class TestBoundedListenHandler:
    """The per-stream ceiling on the client-supplied subscription URI set.

    The 1.x registry capped distinct URIs (``MAX_URIS_PER_SESSION``) and URI
    length; the port dropped both with the registry. The SDK's ``ListenHandler``
    does not replace them — it bounds stream count and event backlog and never
    inspects the URI list, which it then holds for the stream's lifetime. So
    the ceiling on that list is restored here, and ``subscriptions/listen`` is
    not covered by the project's rate limiter (it wraps tool calls only).
    """

    @staticmethod
    def _params(uris: list[str]) -> object:
        """A ``subscriptions/listen`` params object carrying ``uris``."""
        from mcp_types import SubscriptionFilter, SubscriptionsListenRequestParams

        return SubscriptionsListenRequestParams(
            notifications=SubscriptionFilter(resource_subscriptions=uris)
        )

    @pytest.mark.asyncio
    async def test_rejects_an_oversized_uri_set(self) -> None:
        """More URIs than the cap is INVALID_PARAMS, refused before the ack."""
        from mcp.shared.exceptions import MCPError
        from mcp_types import INVALID_PARAMS

        from openzim_mcp.subscriptions import (
            MAX_SUBSCRIPTION_URIS,
            _bounded_listen_handler_class,
        )

        handler = _bounded_listen_handler_class()(InMemorySubscriptionBus())
        uris = [f"zim://a{i}" for i in range(MAX_SUBSCRIPTION_URIS + 1)]

        with pytest.raises(MCPError) as excinfo:
            await handler(object(), self._params(uris))

        assert excinfo.value.error.code == INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_rejects_an_overlong_uri(self) -> None:
        """One absurdly long URI is refused even inside a small set."""
        from mcp.shared.exceptions import MCPError
        from mcp_types import INVALID_PARAMS

        from openzim_mcp.subscriptions import (
            MAX_SUBSCRIPTION_URI_LENGTH,
            _bounded_listen_handler_class,
        )

        handler = _bounded_listen_handler_class()(InMemorySubscriptionBus())
        uris = ["zim://" + "x" * MAX_SUBSCRIPTION_URI_LENGTH]

        with pytest.raises(MCPError) as excinfo:
            await handler(object(), self._params(uris))

        assert excinfo.value.error.code == INVALID_PARAMS

    @pytest.mark.asyncio
    async def test_accepts_a_set_within_the_caps(self) -> None:
        """A normal request must reach the SDK handler untouched.

        Pinned via the SDK's own rejection: a stream with no request id raises
        INVALID_REQUEST from ``ListenHandler``, which can only happen if the
        bounded subclass delegated rather than short-circuiting.
        """
        from mcp.shared.exceptions import MCPError
        from mcp_types import INVALID_REQUEST

        from openzim_mcp.subscriptions import _bounded_listen_handler_class

        handler = _bounded_listen_handler_class()(InMemorySubscriptionBus())

        class _Ctx:
            request_id = None

        with pytest.raises(MCPError) as excinfo:
            await handler(_Ctx(), self._params(["zim://files"]))

        assert excinfo.value.error.code == INVALID_REQUEST

    def test_the_server_installs_it_when_subscriptions_are_live(
        self, tmp_path: Path
    ) -> None:
        """The bound is only worth having if it is the registered handler."""
        from openzim_mcp.config import OpenZimMcpConfig
        from openzim_mcp.server import OpenZimMcpServer
        from openzim_mcp.subscriptions import _bounded_listen_handler_class

        config = OpenZimMcpConfig(
            allowed_directories=[str(tmp_path)],
            transport="http",
            subscriptions_enabled=True,
        )
        server = OpenZimMcpServer(config)
        entry = server.mcp._lowlevel_server._request_handlers["subscriptions/listen"]

        assert isinstance(entry.handler, _bounded_listen_handler_class().__mro__[1])
        assert type(entry.handler).__name__ == "BoundedListenHandler"


class TestSubscriptionCapabilityGate:
    """The wire advertisement must track the subscriptions gate.

    ``OpenZimMcpServer`` withholds the subscription bus outside
    HTTP-with-subscriptions-enabled, but SDK v2 substitutes its own private
    bus for ``None`` and registers ``subscriptions/listen`` regardless — and
    the modern capability derivation reports ``resources.subscribe`` and every
    ``listChanged`` flag purely from that handler's presence. Unless the
    handler is dropped too, a stdio (default) deployment advertises a
    capability whose events can never fire: the MtimeWatcher only runs under
    the HTTP lifespan, so an acked listen stream stays silent forever.
    """

    @staticmethod
    def _server(tmp_path: Path, **kwargs):
        from openzim_mcp.config import OpenZimMcpConfig
        from openzim_mcp.server import OpenZimMcpServer

        config = OpenZimMcpConfig(
            allowed_directories=[str(tmp_path)], tool_mode="advanced", **kwargs
        )
        return OpenZimMcpServer(config)

    @staticmethod
    def _modern_caps(server):
        return server.mcp._lowlevel_server.get_capabilities(
            protocol_version="2026-07-28"
        )

    def _assert_not_advertised(self, server) -> None:
        assert server.subscription_bus is None
        low = server.mcp._lowlevel_server
        assert "subscriptions/listen" not in low._request_handlers
        caps = self._modern_caps(server)
        assert not caps.resources.subscribe
        assert not caps.resources.list_changed
        assert not caps.tools.list_changed
        assert not caps.prompts.list_changed

    def test_stdio_server_does_not_advertise_subscriptions(self, tmp_path: Path):
        self._assert_not_advertised(self._server(tmp_path))

    def test_http_with_subscriptions_disabled_does_not_advertise(self, tmp_path: Path):
        self._assert_not_advertised(
            self._server(tmp_path, transport="http", subscriptions_enabled=False)
        )

    def test_sse_does_not_advertise_subscriptions(self, tmp_path: Path):
        """SSE never runs the watcher either — the gate is http-only, not
        merely non-stdio, and the docs promise method-not-found on SSE."""
        self._assert_not_advertised(self._server(tmp_path, transport="sse"))

    def test_http_with_subscriptions_enabled_advertises(self, tmp_path: Path):
        server = self._server(tmp_path, transport="http")
        assert server.subscription_bus is not None
        low = server.mcp._lowlevel_server
        assert "subscriptions/listen" in low._request_handlers
        caps = self._modern_caps(server)
        assert caps.resources.subscribe
        assert caps.resources.list_changed
