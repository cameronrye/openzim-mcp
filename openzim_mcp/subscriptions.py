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
import logging
from typing import Any, Hashable, List

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
