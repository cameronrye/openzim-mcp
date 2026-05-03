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
import functools
import logging
import os
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Hashable,
    Iterable,
    List,
    Optional,
)

from .defaults import TIMEOUTS

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

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
        # Set-backed storage so subscribe/unsubscribe/clear_session are all
        # O(1) per (uri, session) pair. The previous list-based backing made
        # subscribe O(n) (linear `not in` scan for idempotency), unsubscribe
        # O(n) (linear search + shift), and clear_session O(URIs * sessions).
        self._by_uri: dict[str, set[Hashable]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, uri: str, session: Hashable) -> None:
        """Register interest. Idempotent for the same (uri, session) pair."""
        async with self._lock:
            # ``set.add`` is inherently idempotent — no membership pre-check needed.
            self._by_uri.setdefault(uri, set()).add(session)
            logger.debug("subscribe uri=%s session=%r", uri, session)

    async def unsubscribe(self, uri: str, session: Hashable) -> None:
        """Drop interest. Silent if the (uri, session) pair was never registered."""
        async with self._lock:
            sessions = self._by_uri.get(uri)
            if not sessions:
                return
            sessions.discard(session)  # silent on missing
            if not sessions:
                self._by_uri.pop(uri, None)

    async def sessions_for(self, uri: str) -> List[Any]:
        """Return a snapshot of sessions subscribed to ``uri``.

        Order is not guaranteed (set iteration order); callers (the broadcast
        fan-out in particular) don't rely on ordering.
        """
        async with self._lock:
            return list(self._by_uri.get(uri, ()))

    async def clear_session(self, session: Hashable) -> None:
        """Drop ``session`` from every URI (called on session teardown)."""
        async with self._lock:
            empty_uris = []
            for uri, sessions in self._by_uri.items():
                # ``discard`` is O(1) and silent on missing membership, so
                # this loop is O(URIs) rather than O(URIs * sessions_per_uri).
                sessions.discard(session)
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
        # Snapshot maps path → (mtime, size). Both fields are compared on
        # each tick so that same-size replacements (different mtime) and
        # in-place rewrites (different size) are both detected. See the
        # change-detection comment in ``_tick`` for the false-positive vs.
        # false-negative trade-off.
        self._snapshot: dict[str, tuple[float, int]] = {}
        self._task: Optional[asyncio.Task[None]] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Take an initial snapshot and begin polling."""
        if self._task is not None:
            return  # already running
        # _scan does os.scandir + stat syscalls that block on network-mounted
        # filesystems. Offload to match _tick so startup doesn't stall the
        # event loop during the ASGI lifespan.
        self._snapshot = await asyncio.to_thread(self._scan)
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

    def _scan(self) -> dict[str, tuple[float, int]]:
        """Snapshot ``{path: (mtime, size)}`` for ``.zim`` files in allowed dirs."""
        snap: dict[str, tuple[float, int]] = {}
        for d in self._dirs:
            try:
                for entry in os.scandir(d):
                    if entry.is_file() and entry.name.endswith(".zim"):
                        with contextlib.suppress(OSError):
                            stat = entry.stat()
                            snap[entry.path] = (stat.st_mtime, stat.st_size)
            except OSError:
                continue
        return snap

    async def _tick(self) -> None:
        """Diff a fresh scan against the snapshot and dispatch any changes.

        Extracted from the polling loop so tests can drive a single pass
        deterministically without depending on sleep/scheduler timing.
        """
        # ``_scan`` runs ``os.scandir`` + ``stat`` syscalls that block on
        # network-mounted filesystems and under inode pressure. Offload
        # to a thread so the event loop keeps making progress.
        new_snap = await asyncio.to_thread(self._scan)
        added = set(new_snap) - set(self._snapshot)
        removed = set(self._snapshot) - set(new_snap)
        # Trigger on size OR mtime change. The earlier policy of size-only
        # detection suppressed `touch`-style false positives but also missed
        # real same-size replacements (small stub fixtures, atomic-rename
        # swaps where the new payload happens to match the old length).
        # For a watcher whose job is to alert subscribers to changes, a
        # false negative — a stale subscriber stuck on stale data forever —
        # is strictly worse than a false positive (one redundant refresh).
        changed = {
            p
            for p in (set(new_snap) & set(self._snapshot))
            if (
                new_snap[p][0] != self._snapshot[p][0]  # mtime
                or new_snap[p][1] != self._snapshot[p][1]  # size
            )
        }
        # Directory listing changes → zim://files
        if added or removed:
            await self._on_change("zim://files", "list_changed")
        # Per-file content replacements (or mtime bumps) → zim://{name}
        for path in changed:
            name = Path(path).stem
            await self._on_change(f"zim://{name}", "replaced")
        self._snapshot = new_snap

    async def _loop(self) -> None:
        """Run the polling loop: diff against snapshot, dispatch, repeat."""
        try:
            while not self._stop_event.is_set():
                await asyncio.sleep(self._interval)
                if self._stop_event.is_set():
                    return
                await self._tick()
        except asyncio.CancelledError:
            return


# Per-subscriber timeout for ``send_resource_updated`` during broadcast. See
# ``TimeoutDefaults.SUBSCRIPTION_SEND_SECONDS`` in ``defaults.py``. The
# module-level alias is preserved so tests can monkeypatch this value.
SEND_TIMEOUT_SECONDS: float = TIMEOUTS.SUBSCRIPTION_SEND_SECONDS


async def _safe_clear_session(registry: "SubscriberRegistry", session: Any) -> None:
    """Drop ``session`` from the registry, logging (but swallowing) failures.

    ``gather(..., return_exceptions=True)`` discards exceptions from
    ``_send_one``, so a raise in ``clear_session`` would silently leave a
    dead session in the registry — every subsequent broadcast would burn
    ``SEND_TIMEOUT_SECONDS`` on it. Catching here keeps the registry in
    sync even if the inner ``asyncio.Lock`` acquisition raises (e.g. lock
    contention during shutdown).
    """
    try:
        await registry.clear_session(session)
    except Exception as e:  # noqa: BLE001
        logger.warning("clear_session failed during fan-out cleanup: %s", e)


async def _send_one(
    registry: "SubscriberRegistry",
    session: Any,
    uri: str,
) -> None:
    """Deliver one notification, dropping the session on failure or timeout."""
    try:
        await asyncio.wait_for(
            session.send_resource_updated(uri),
            timeout=SEND_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        # CancelledError is BaseException since 3.8 — must re-raise so
        # gather(return_exceptions=True) does NOT swallow it. Otherwise the
        # watcher task continues running after stop() cancels it, and the
        # await self._task in stop() blocks until the next sleep yields.
        raise
    except asyncio.TimeoutError:
        logger.warning(
            "send_resource_updated timed out after %ss; dropping session",
            SEND_TIMEOUT_SECONDS,
        )
        await _safe_clear_session(registry, session)
    except Exception as e:  # noqa: BLE001 - drop on any send failure
        logger.warning("send_resource_updated failed; dropping session: %s", e)
        await _safe_clear_session(registry, session)


async def broadcast_resource_updated(
    registry: "SubscriberRegistry",
    uri: str,
) -> None:
    """Notify every subscriber of ``uri`` via ``send_resource_updated``.

    Sends are fanned out concurrently with ``asyncio.gather`` and bounded
    per-subscriber by ``SEND_TIMEOUT_SECONDS`` so that one slow or hung
    session never stalls the watcher loop or delays delivery to other
    subscribers.

    Sessions whose ``send_resource_updated`` raises or times out (typically
    because the session has been torn down) are dropped from the registry —
    that's the only signal we have for "this session is gone" since FastMCP
    doesn't expose a session-shutdown callback.
    """
    sessions = await registry.sessions_for(uri)
    if not sessions:
        return
    results = await asyncio.gather(
        *(_send_one(registry, session, uri) for session in sessions),
        return_exceptions=True,
    )
    # gather(return_exceptions=True) collects CancelledError as a value rather
    # than propagating it. _send_one re-raises CancelledError specifically so
    # the caller can observe cancellation; preserve that signal here, otherwise
    # the watcher task continues running after stop() cancels it and the
    # await self._task in stop() blocks until the next sleep yields.
    for r in results:
        if isinstance(r, asyncio.CancelledError):
            raise r


def register_subscription_handlers(
    mcp: "FastMCP",
    registry: "SubscriberRegistry",
) -> None:
    """Install subscribe/unsubscribe handlers on the lowlevel ``Server``.

    Reaches through ``mcp._mcp_server`` (a stable single-underscore attribute,
    documented in the spike note as the only access path in mcp 1.26).

    Subscribe handlers run inside an active request context, so we use
    ``mcp._mcp_server.request_context.session`` to capture the calling
    ``ServerSession`` and store it in the registry, keyed by URI.
    """
    low = mcp._mcp_server

    @low.subscribe_resource()
    async def _on_subscribe(uri: Any) -> None:  # type: ignore[misc]
        session = low.request_context.session
        await registry.subscribe(str(uri), session)

    @low.unsubscribe_resource()
    async def _on_unsubscribe(uri: Any) -> None:  # type: ignore[misc]
        session = low.request_context.session
        await registry.unsubscribe(str(uri), session)


def patch_capabilities_to_advertise_subscribe(mcp: "FastMCP") -> None:
    """Make ``get_capabilities()`` advertise ``resources.subscribe = True``.

    The lowlevel ``Server.get_capabilities`` hardcodes ``subscribe=False``
    even when subscribe handlers are registered. Without this patch, well-
    behaved clients won't issue ``resources/subscribe`` and our handlers
    are never reached. We monkey-patch ``create_initialization_options`` to
    flip the flag post-construction; ``ResourcesCapability`` allows extra
    attributes (``model_config = ConfigDict(extra="allow")``), so this is
    well-defined pydantic, not a hack.
    """
    low = mcp._mcp_server
    original = low.create_initialization_options

    @functools.wraps(original)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        init = original(*args, **kwargs)
        if init.capabilities.resources is not None:
            init.capabilities.resources.subscribe = True
        else:
            # Resources capability can be None when no list-resources handler
            # is registered; in that case we have nothing to subscribe to,
            # but we still flip the flag for completeness.
            from mcp.types import ResourcesCapability

            init.capabilities.resources = ResourcesCapability(
                subscribe=True, listChanged=False
            )
        return init

    low.create_initialization_options = wrapped  # type: ignore[assignment]
