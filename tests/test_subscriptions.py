"""Tests for SubscriberRegistry and the polling watcher."""

import asyncio

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
    """Replacing a .zim atomically fires zim://{name}."""
    import os
    import time

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
        target.write_bytes(b"v2")
        # Force a clearly-different mtime even on filesystems with coarse
        # mtime resolution.
        os.utime(target, (time.time(), time.time() + 1))
        for _ in range(20):
            await asyncio.sleep(0.05)
            if any(uri == "zim://archive" for uri, _ in events):
                break
        assert any(uri == "zim://archive" for uri, _ in events)
    finally:
        await watcher.stop()


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


def test_capability_patch_flips_subscribe_to_true():
    """patch_capabilities_to_advertise_subscribe makes get_capabilities() advertise subscribe=True."""
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
