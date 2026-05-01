"""Resource subscription support for OpenZIM MCP.

Tracks per-session interest in MCP resource URIs so that the polling watcher
can dispatch ``notifications/resources/updated`` to the right sessions.

This module reaches into one private FastMCP attribute (``_mcp_server``) to
register subscribe/unsubscribe handlers on the underlying lowlevel ``Server``
and to capture the active ``ServerSession`` at subscribe time. FastMCP 1.26
exposes no public surface for this; see
``docs/superpowers/notes/2026-05-01-subscription-api-spike.md`` for the full
SDK-behaviour analysis.

Stable surfaces this module depends on:
- ``mcp.server.fastmcp.FastMCP._mcp_server`` (private but widely used)
- ``mcp.server.lowlevel.Server.subscribe_resource()`` decorator
- ``mcp.server.lowlevel.Server.unsubscribe_resource()`` decorator
- ``mcp.server.lowlevel.Server.request_context.session`` (set during
  request dispatch — valid inside subscribe handlers)
- ``mcp.server.session.ServerSession.send_resource_updated(uri)``
- ``mcp.server.lowlevel.Server.create_initialization_options()`` (we patch
  the result post-construction to flip ``capabilities.resources.subscribe``
  from the hardcoded ``False`` to ``True``)
"""

import asyncio
import contextlib
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Hashable, Iterable, List, Optional

logger = logging.getLogger(__name__)


class SubscriberRegistry:
    """Maps URI strings to the set of sessions interested in that URI.

    Sessions are stored as opaque hashable values — typically the active
    ``ServerSession`` captured during a subscribe request, but any hashable
    object works (tests use plain strings).

    All operations are coroutine-safe via an ``asyncio.Lock``.
    """

    def __init__(self) -> None:
        """Create an empty registry."""
        self._by_uri: dict[str, list[Hashable]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, uri: str, session: Hashable) -> None:
        """Register interest. Idempotent for the same (uri, session) pair."""
        async with self._lock:
            sessions = self._by_uri.setdefault(uri, [])
            if session not in sessions:
                sessions.append(session)
            logger.debug("subscribe uri=%s session=%r", uri, session)

    async def unsubscribe(self, uri: str, session: Hashable) -> None:
        """Drop interest. Silent if the (uri, session) pair was never registered."""
        async with self._lock:
            sessions = self._by_uri.get(uri)
            if not sessions:
                return
            try:
                sessions.remove(session)
            except ValueError:
                return
            if not sessions:
                self._by_uri.pop(uri, None)

    async def sessions_for(self, uri: str) -> List[Any]:
        """Return a snapshot of sessions subscribed to ``uri`` (in insertion order)."""
        async with self._lock:
            return list(self._by_uri.get(uri, []))

    async def clear_session(self, session: Hashable) -> None:
        """Drop ``session`` from every URI (called on session teardown)."""
        async with self._lock:
            empty_uris = []
            for uri, sessions in self._by_uri.items():
                try:
                    sessions.remove(session)
                except ValueError:
                    continue
                if not sessions:
                    empty_uris.append(uri)
            for uri in empty_uris:
                self._by_uri.pop(uri, None)


OnChange = Callable[[str, str], Awaitable[None]]


class MtimeWatcher:
    """Polls allowed dirs and fires events when ``.zim`` files change.

    Events emitted:
      * ``zim://files`` — directory contents changed (file added/removed).
      * ``zim://{name}`` — a specific file's mtime changed (replacement).
        ``{name}`` is the bare basename without the ``.zim`` extension.

    The watcher runs as a single asyncio task. Calling ``stop()`` cancels
    the task and waits for it to unwind. ``stop()`` is idempotent.

    Args:
        dirs: list of allowed directories to watch.
        interval: polling interval in seconds.
        on_change: async callback ``(uri, change_type) -> None``.
    """

    def __init__(
        self,
        dirs: Iterable[str],
        interval: float,
        on_change: OnChange,
    ) -> None:
        """Capture the watch list, interval, and dispatch callback."""
        self._dirs = [str(d) for d in dirs]
        self._interval = interval
        self._on_change = on_change
        self._snapshot: dict[str, float] = {}
        self._task: Optional[asyncio.Task[None]] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Take an initial snapshot and begin polling."""
        if self._task is not None:
            return  # already running
        self._snapshot = self._scan()
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Cancel the polling task. Idempotent."""
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        # Cancellation always raises CancelledError on the awaited task; any
        # other late exception during teardown is swallowed deliberately.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._task
        self._task = None

    def _scan(self) -> dict[str, float]:
        """Snapshot ``{path: mtime}`` for all ``.zim`` files in allowed dirs."""
        snap: dict[str, float] = {}
        for d in self._dirs:
            try:
                for entry in os.scandir(d):
                    if entry.is_file() and entry.name.endswith(".zim"):
                        with contextlib.suppress(OSError):
                            snap[entry.path] = entry.stat().st_mtime
            except OSError:
                continue
        return snap

    async def _loop(self) -> None:
        """Run the polling loop: diff against snapshot, dispatch, repeat."""
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(self._interval)
                if self._stop_event.is_set():
                    return
                new_snap = self._scan()
                added = set(new_snap) - set(self._snapshot)
                removed = set(self._snapshot) - set(new_snap)
                changed = {
                    p
                    for p in (set(new_snap) & set(self._snapshot))
                    if new_snap[p] != self._snapshot[p]
                }
                # Directory listing changes → zim://files
                if added or removed:
                    await self._on_change("zim://files", "list_changed")
                # Per-file mtime changes → zim://{name}
                for path in changed:
                    name = Path(path).stem
                    await self._on_change(f"zim://{name}", "replaced")
                self._snapshot = new_snap
        except asyncio.CancelledError:
            return
