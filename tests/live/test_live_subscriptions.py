"""Live MCP change-notification test over streamable-HTTP.

Covers the ``subscriptions/listen`` flow end to end against a real server
process: the ``MtimeWatcher`` detects a change on disk, publishes it to the
SDK's subscription bus, and the SDK delivers it on the client's open listen
stream.

Both notification kinds are exercised, because the 2026-07-28 revision made
them distinct and openzim-mcp maps them differently. Replacing a ``.zim`` file
in place emits ``notifications/resources/updated`` for that archive's own URI;
adding or removing one changes the membership of ``zim://files`` and emits
``notifications/resources/list_changed``, which carries no URI. Before this
revision both were flattened into an ``updated`` for ``zim://files``, so a test
that only checked the per-archive case would not notice the list-membership
path regressing.

This is the only coverage of the delivery path over real HTTP — everything else
publishes to an in-process bus — so it is also what would catch the SDK's
listen stream not being wired up at all.

The watch interval is configurable via ``OPENZIM_MCP_WATCH_INTERVAL_SECONDS``
(min 1s); we run with the lowest value to keep the test fast.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any, List

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.client.subscriptions import listen
from mcp.server.subscriptions import ResourcesListChanged, ResourceUpdated

from tests.live.conftest import fresh_token

pytestmark = pytest.mark.live

TOKEN = fresh_token()
WATCH_INTERVAL = "1"  # seconds; minimum permitted by config validator

# The watcher polls every WATCH_INTERVAL seconds; allow generous slack so a
# loaded CI box doesn't fail on scheduling jitter rather than on behavior.
NOTIFY_TIMEOUT_SECONDS = 15.0


async def _collect(subscription: Any, events: List[Any], seen: asyncio.Event) -> None:
    """Drain ``subscription`` into ``events``, setting ``seen`` on each event."""
    async for event in subscription:
        events.append(event)
        seen.set()


@pytest.mark.asyncio
async def test_listen_stream_receives_both_notification_kinds(
    spawn_live_server, zim_dir: Path
) -> None:
    """A replace fires ``updated``; an add fires ``list_changed``."""
    srv = spawn_live_server(
        transport="http",
        token=TOKEN,
        extra_env={"OPENZIM_MCP_WATCH_INTERVAL_SECONDS": WATCH_INTERVAL},
    )

    zims = sorted(zim_dir.glob("*.zim"))
    assert zims, "no .zim files to exercise"
    target = zims[0]
    archive_uri = f"zim://{target.stem}"

    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as http_client:
        async with streamable_http_client(
            f"{srv.base_url}/mcp", http_client=http_client
        ) as (read_stream, write_stream):
            async with ClientSession(
                read_stream,
                write_stream,
                # v2 takes a float; 1.x took a timedelta.
                read_timeout_seconds=30.0,
            ) as session:
                # No initialize(): subscriptions/listen is 2026-07-28 only, so
                # this half of the test also pins that the stateless path works
                # against a real server over real HTTP.
                await session.discover()

                # Keepalive on the modern connection: the exact call
                # python-sdk#3273 rejects with -32601. One ping here pins the
                # sdk_compat shim working in a *spawned* server process over
                # real HTTP, where the in-memory tests cannot see it.
                await session.send_ping()

                # Opt into both kinds. resource_subscriptions names URIs for
                # `updated`; resources_list_changed is a separate flag because
                # a membership change has no URI to name.
                async with listen(
                    session,
                    resources_list_changed=True,
                    resource_subscriptions=[archive_uri],
                ) as subscription:
                    events: List[Any] = []
                    seen = asyncio.Event()
                    collector = asyncio.create_task(
                        _collect(subscription, events, seen)
                    )
                    try:
                        # (1) Replace in place -> updated for this archive.
                        # Rewriting the bytes moves mtime and keeps size, the
                        # case a mtime-only comparison would miss.
                        target.write_bytes(target.read_bytes())
                        await asyncio.wait_for(
                            seen.wait(), timeout=NOTIFY_TIMEOUT_SECONDS
                        )

                        # (2) Add a new file -> list_changed.
                        seen.clear()
                        added = zim_dir / "live_subscription_probe.zim"
                        shutil.copyfile(target, added)
                        try:
                            await asyncio.wait_for(
                                seen.wait(), timeout=NOTIFY_TIMEOUT_SECONDS
                            )
                        finally:
                            added.unlink(missing_ok=True)
                    finally:
                        collector.cancel()
                        with pytest.raises(
                            (asyncio.CancelledError, StopAsyncIteration)
                        ):
                            await collector

    # `listen()` yields the SDK's typed ServerEvent objects, not raw JSON-RPC
    # notification envelopes — the wire framing is the SDK's business.
    kinds = [type(event).__name__ for event in events]
    assert events, "no notifications delivered on the listen stream"

    updated = [e for e in events if isinstance(e, ResourceUpdated)]
    list_changed = [e for e in events if isinstance(e, ResourcesListChanged)]
    assert updated, f"expected a ResourceUpdated for the in-place replace; got {kinds}"
    assert list_changed, f"expected a ResourcesListChanged for the add; got {kinds}"

    # The updated event must name the archive that actually changed — a
    # publisher that ignored the URI would still satisfy the count check.
    assert archive_uri in {
        e.uri for e in updated
    }, f"expected {archive_uri!r} in {[e.uri for e in updated]}"
