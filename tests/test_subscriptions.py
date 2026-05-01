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
