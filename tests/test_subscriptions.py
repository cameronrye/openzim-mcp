"""Tests for SubscriberRegistry and the polling watcher."""

import asyncio
from typing import Any

import pytest


@pytest.mark.asyncio
async def test_subscribe_then_lookup():
    """Subscribing a session for a URI makes it appear in sessions_for()."""
    from openzim_mcp.subscriptions import SubscriberRegistry

    reg = SubscriberRegistry()
    await reg.subscribe("zim://files", "session1")
    sessions = await reg.sessions_for("zim://files")
    assert sessions == ["session1"]


@pytest.mark.asyncio
async def test_subscribe_is_idempotent():
    """Re-subscribing the same session for the same URI is a no-op."""
    from openzim_mcp.subscriptions import SubscriberRegistry

    reg = SubscriberRegistry()
    await reg.subscribe("zim://files", "session1")
    await reg.subscribe("zim://files", "session1")
    sessions = await reg.sessions_for("zim://files")
    assert sessions == ["session1"]


@pytest.mark.asyncio
async def test_unsubscribe_removes_session():
    """Unsubscribing drops only the matching (uri, session) pair."""
    from openzim_mcp.subscriptions import SubscriberRegistry

    reg = SubscriberRegistry()
    await reg.subscribe("zim://files", "session1")
    await reg.unsubscribe("zim://files", "session1")
    sessions = await reg.sessions_for("zim://files")
    assert sessions == []


@pytest.mark.asyncio
async def test_clear_session_drops_all():
    """Clearing a session drops it from every URI it subscribed to."""
    from openzim_mcp.subscriptions import SubscriberRegistry

    reg = SubscriberRegistry()
    await reg.subscribe("zim://files", "session1")
    await reg.subscribe("zim://archive1", "session1")
    await reg.subscribe("zim://files", "session2")
    await reg.clear_session("session1")
    assert await reg.sessions_for("zim://files") == ["session2"]
    assert await reg.sessions_for("zim://archive1") == []


@pytest.mark.asyncio
async def test_unsubscribe_unknown_is_silent():
    """Unsubscribing a session that wasn't subscribed is a no-op."""
    from openzim_mcp.subscriptions import SubscriberRegistry

    reg = SubscriberRegistry()
    await reg.unsubscribe("zim://files", "session1")  # no error


@pytest.mark.asyncio
async def test_concurrent_subscribe_unsubscribe():
    """Many concurrent subscribe/unsubscribe calls don't corrupt state."""
    from openzim_mcp.subscriptions import SubscriberRegistry

    reg = SubscriberRegistry()
    tasks = []
    for i in range(50):
        tasks.append(reg.subscribe("zim://files", f"s{i}"))
    await asyncio.gather(*tasks)
    sessions = await reg.sessions_for("zim://files")
    assert len(sessions) == 50


@pytest.mark.asyncio
async def test_registry_uses_set_backed_storage_for_o1_membership():
    """Backing store must be a set so subscribe/unsubscribe are O(1)."""
    from openzim_mcp.subscriptions import SubscriberRegistry

    registry = SubscriberRegistry()
    sessions = [f"session-{i}" for i in range(10000)]
    for s in sessions:
        await registry.subscribe("zim://x", s)
    # Re-subscribe all — must remain idempotent and not double-count.
    for s in sessions:
        await registry.subscribe("zim://x", s)

    backing = registry._by_uri["zim://x"]
    assert isinstance(backing, set), f"expected set, got {type(backing).__name__}"
    assert len(backing) == 10000


@pytest.mark.asyncio
async def test_watcher_detects_new_zim_file(tmp_path):
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
async def test_watcher_detects_file_replacement(tmp_path):
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
async def test_watcher_detects_same_size_replacement(tmp_path):
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
async def test_watcher_triggers_on_mtime_only_change(tmp_path):
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
async def test_watcher_stop_is_idempotent(tmp_path):
    """Calling stop() twice doesn't blow up."""
    from openzim_mcp.subscriptions import MtimeWatcher

    async def emit(uri: str, change_type: str) -> None:
        pass

    watcher = MtimeWatcher([str(tmp_path)], interval=0.05, on_change=emit)
    await watcher.start()
    await watcher.stop()
    await watcher.stop()  # second call is fine


@pytest.mark.asyncio
async def test_broadcast_calls_send_for_each_subscriber():
    """broadcast_resource_updated emits one notification per subscriber."""
    from openzim_mcp.subscriptions import (
        SubscriberRegistry,
        broadcast_resource_updated,
    )

    sent: list[tuple[Any, str]] = []

    class FakeSession:
        def __init__(self, label: str):
            self.label = label

        async def send_resource_updated(self, uri):
            sent.append((self.label, str(uri)))

        def __hash__(self):
            return hash(self.label)

        def __eq__(self, other):
            return isinstance(other, FakeSession) and self.label == other.label

    reg = SubscriberRegistry()
    s1, s2 = FakeSession("s1"), FakeSession("s2")
    await reg.subscribe("zim://files", s1)
    await reg.subscribe("zim://files", s2)

    await broadcast_resource_updated(reg, "zim://files")
    assert sorted(sent) == [("s1", "zim://files"), ("s2", "zim://files")]


@pytest.mark.asyncio
async def test_broadcast_drops_failed_sessions():
    """A session whose send_resource_updated raises is evicted from the registry."""
    from openzim_mcp.subscriptions import (
        SubscriberRegistry,
        broadcast_resource_updated,
    )

    class DeadSession:
        async def send_resource_updated(self, uri):
            raise RuntimeError("session closed")

        def __hash__(self):
            return id(self)

        def __eq__(self, other):
            return self is other

    class LiveSession:
        def __init__(self):
            self.calls = []

        async def send_resource_updated(self, uri):
            self.calls.append(str(uri))

        def __hash__(self):
            return id(self)

        def __eq__(self, other):
            return self is other

    reg = SubscriberRegistry()
    dead = DeadSession()
    live = LiveSession()
    await reg.subscribe("zim://files", dead)
    await reg.subscribe("zim://files", live)

    await broadcast_resource_updated(reg, "zim://files")

    remaining = await reg.sessions_for("zim://files")
    assert dead not in remaining
    assert live in remaining
    assert live.calls == ["zim://files"]


@pytest.mark.asyncio
async def test_broadcast_does_not_serialize_on_slow_subscriber():
    """Slow subscribers must not delay other subscribers — fan-out is concurrent."""
    import time

    from openzim_mcp.subscriptions import (
        SubscriberRegistry,
        broadcast_resource_updated,
    )

    fast_calls: list[str] = []
    slow_calls: list[str] = []

    class Slow:
        async def send_resource_updated(self, uri):
            await asyncio.sleep(0.5)
            slow_calls.append(str(uri))

        def __hash__(self):
            return id(self)

        def __eq__(self, other):
            return self is other

    class Fast:
        async def send_resource_updated(self, uri):
            fast_calls.append(str(uri))

        def __hash__(self):
            return id(self)

        def __eq__(self, other):
            return self is other

    reg = SubscriberRegistry()
    fast, slow = Fast(), Slow()
    await reg.subscribe("zim://x", fast)
    await reg.subscribe("zim://x", slow)

    start = time.monotonic()
    await broadcast_resource_updated(reg, "zim://x")
    elapsed = time.monotonic() - start

    # Both subscribers received the notification; total wall time is bounded
    # by the single slow sleep (~0.5s) regardless of order. The stronger
    # concurrency proof lives in the next test (N slow subscribers).
    assert fast_calls == ["zim://x"]
    assert slow_calls == ["zim://x"]
    assert elapsed < 0.9, f"broadcast took unexpectedly long: {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_broadcast_fans_out_concurrently_many_slow_subscribers():
    """Multiple slow subscribers complete in ~one sleep, not N sleeps."""
    import time

    from openzim_mcp.subscriptions import (
        SubscriberRegistry,
        broadcast_resource_updated,
    )

    SLEEP = 0.3
    N = 5

    class Slow:
        def __init__(self):
            self.called = False

        async def send_resource_updated(self, uri):
            await asyncio.sleep(SLEEP)
            self.called = True

        def __hash__(self):
            return id(self)

        def __eq__(self, other):
            return self is other

    reg = SubscriberRegistry()
    subs = [Slow() for _ in range(N)]
    for s in subs:
        await reg.subscribe("zim://x", s)

    start = time.monotonic()
    await broadcast_resource_updated(reg, "zim://x")
    elapsed = time.monotonic() - start

    # Serial: N * SLEEP = 1.5s. Concurrent: ~SLEEP = 0.3s.
    # Allow generous slack for CI scheduler jitter.
    assert elapsed < (SLEEP * N) / 2, (
        f"broadcast was serial (or near-serial): {elapsed:.3f}s for "
        f"{N} subscribers @ {SLEEP}s each"
    )
    assert all(s.called for s in subs)


@pytest.mark.asyncio
async def test_broadcast_drops_session_after_timeout(monkeypatch):
    """A session whose send_resource_updated hangs is dropped after the timeout."""
    from openzim_mcp import subscriptions as subs_mod
    from openzim_mcp.subscriptions import (
        SubscriberRegistry,
        broadcast_resource_updated,
    )

    # Shrink the per-send timeout so the test runs quickly.
    monkeypatch.setattr(subs_mod, "SEND_TIMEOUT_SECONDS", 0.1)

    class Hanging:
        async def send_resource_updated(self, uri):
            await asyncio.sleep(60)  # never returns within test

        def __hash__(self):
            return id(self)

        def __eq__(self, other):
            return self is other

    reg = SubscriberRegistry()
    hung = Hanging()
    await reg.subscribe("zim://x", hung)

    await broadcast_resource_updated(reg, "zim://x")

    remaining = await reg.sessions_for("zim://x")
    assert hung not in remaining


def test_capability_patch_flips_subscribe_to_true():
    """The capability patch makes get_capabilities() advertise subscribe=True."""
    from mcp.server.fastmcp import FastMCP

    from openzim_mcp.subscriptions import patch_capabilities_to_advertise_subscribe

    mcp = FastMCP("test")
    # Sanity: before patch, the SDK hardcodes False (this is the spike's
    # pinned assumption — if it ever flips upstream, this test catches it).
    init = mcp._mcp_server.create_initialization_options()
    assert init.capabilities.resources is None or (
        init.capabilities.resources.subscribe is False
    )

    patch_capabilities_to_advertise_subscribe(mcp)

    init = mcp._mcp_server.create_initialization_options()
    assert init.capabilities.resources is not None
    assert init.capabilities.resources.subscribe is True


def test_register_subscription_handlers_installs_entries():
    """register_subscription_handlers adds Subscribe/Unsubscribe to request_handlers."""
    import mcp.types as t
    from mcp.server.fastmcp import FastMCP

    from openzim_mcp.subscriptions import (
        SubscriberRegistry,
        register_subscription_handlers,
    )

    mcp = FastMCP("test")
    reg = SubscriberRegistry()
    register_subscription_handlers(mcp, reg)

    handlers = mcp._mcp_server.request_handlers
    assert t.SubscribeRequest in handlers
    assert t.UnsubscribeRequest in handlers
