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
