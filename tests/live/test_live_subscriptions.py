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

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.live.conftest import fresh_token

pytestmark = pytest.mark.live

TOKEN = fresh_token()
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

    # The new streamable_http_client takes a pre-configured httpx.AsyncClient
    # rather than headers/auth kwargs (the old keyword-arg API was deprecated).
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as http_client:
        async with streamable_http_client(
            f"{srv.base_url}/mcp", http_client=http_client
        ) as (read_stream, write_stream, _close):
            async with ClientSession(
                read_stream,
                write_stream,
                message_handler=message_handler,
                read_timeout_seconds=timedelta(seconds=10),
            ) as session:
                await session.initialize()
                # Subscribe to BOTH the file-index URI and the per-archive
                # URI (the watcher emits per-file events for mtime bumps;
                # list-changed events only fire on add/remove).
                zims = sorted(zim_dir.glob("*.zim"))
                assert zims, "no .zim files to touch"
                target = zims[0]
                archive_uri = f"zim://{target.stem}"

                # AnyUrl-typed param accepts a plain str at runtime.
                files_uri = "zim://files"
                await session.subscribe_resource(files_uri)  # type: ignore[arg-type]
                await session.subscribe_resource(archive_uri)  # type: ignore[arg-type]

                # Touch the .zim mtime — content unchanged, just timestamp.
                new_mtime = target.stat().st_mtime + 5
                os.utime(target, (new_mtime, new_mtime))

                # Watch poll is 1s; allow generous slack for notification.
                try:
                    await asyncio.wait_for(notify_event.wait(), timeout=8.0)
                except asyncio.TimeoutError:
                    pytest.fail(
                        f"no notifications/resources/updated received "
                        f"within 8s after mtime bump on {target}"
                    )

    assert received, "expected at least one notification"
    # mtime bump only fires the per-archive update — list_changed only
    # triggers on add/remove. Verify the notification was for THIS archive.
    assert (
        archive_uri in received
    ), f"expected {archive_uri!r} in notifications, got: {received}"
