"""Live MCP resource-subscription test over streamable-HTTP.

Covers v1.0 item 4: ``zim://files`` and ``zim://{name}`` subscription
flow. The ``MtimeWatcher`` must detect mtime changes and broadcast
``notifications/resources/updated`` to every active subscriber.

The watch interval is configurable via ``OPENZIM_MCP_WATCH_INTERVAL_SECONDS``
(min 1s); we run with the lowest value to keep the test fast.
"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from pathlib import Path
from typing import List

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

pytestmark = pytest.mark.live

TOKEN = "subscription-test-token"
WATCH_INTERVAL = "1"  # seconds; minimum permitted by config validator


@pytest.mark.asyncio
async def test_subscription_fires_on_zim_mtime_bump(
    spawn_live_server, zim_dir: Path
) -> None:
    """Bumping a .zim mtime fires notifications/resources/updated."""
    srv = spawn_live_server(
        transport="http",
        token=TOKEN,
        extra_env={"OPENZIM_MCP_WATCH_INTERVAL_SECONDS": WATCH_INTERVAL},
    )

    received: List[str] = []
    notify_event = asyncio.Event()

    async def message_handler(message) -> None:  # noqa: ANN001 — SDK uses Any
        # The notification we want is ServerNotification(NotificationParams)
        # with method "notifications/resources/updated".
        try:
            payload = getattr(message, "root", message)
            method = getattr(payload, "method", None)
            if method == "notifications/resources/updated":
                params = getattr(payload, "params", None)
                uri = getattr(params, "uri", None)
                if uri is not None:
                    received.append(str(uri))
                    notify_event.set()
        except Exception:
            pass

    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with streamablehttp_client(f"{srv.base_url}/mcp", headers=headers) as (
        read_stream,
        write_stream,
        _close,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
            message_handler=message_handler,
            read_timeout_seconds=timedelta(seconds=10),
        ) as session:
            await session.initialize()
            # Pick a target zim and subscribe to BOTH the file-index URI and
            # the per-archive URI (the watcher emits per-file events for
            # mtime bumps; list-changed events only fire on add/remove).
            zims = sorted(zim_dir.glob("*.zim"))
            assert zims, "no .zim files to touch"
            target = zims[0]
            archive_uri = f"zim://{target.stem}"

            await session.subscribe_resource("zim://files")  # type: ignore[arg-type]
            await session.subscribe_resource(archive_uri)  # type: ignore[arg-type]

            # Touch the .zim mtime — content unchanged, just timestamp.
            new_mtime = target.stat().st_mtime + 5
            os.utime(target, (new_mtime, new_mtime))

            # Wait for notification — watch poll is 1s, allow generous slack.
            try:
                await asyncio.wait_for(notify_event.wait(), timeout=8.0)
            except asyncio.TimeoutError:
                pytest.fail(
                    f"no notifications/resources/updated received within 8s "
                    f"after mtime bump on {target}"
                )

    assert received, "expected at least one notification"
    # The notification could be for zim://files (directory-level) or for
    # the per-archive resource zim://{name}; both are valid signals here.
    assert any("zim://" in u for u in received), f"unexpected uris: {received}"
