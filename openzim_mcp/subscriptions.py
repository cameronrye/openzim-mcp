"""Resource-change detection for OpenZIM MCP.

The server watches its allowed directories for ``.zim`` files appearing,
disappearing, or being replaced, and publishes the corresponding MCP
notification so subscribed clients can invalidate what they cached.

Under the 2026-07-28 revision the delivery half of that job belongs to the
SDK. Clients opt in with ``subscriptions/listen`` (naming the notification
kinds they want) and the SDK's ``SubscriptionBus`` owns the listener registry,
per-stream filtering, backpressure, and stream teardown. This module therefore
keeps only the part the SDK cannot know about — *when* a ZIM file changed — and
hands each change to the bus.

That replaces a substantial amount of hand-rolled machinery this module used to
carry against the 1.x SDK: a URI-keyed registry of live ``ServerSession``
objects held in ``WeakSet``s, a concurrent fan-out with per-subscriber send
timeouts and dead-session eviction, and a monkey-patch of
``create_initialization_options`` to advertise a capability the SDK hardcoded
to ``False``. None of it has a 2026-07-28 analogue: sessions no longer exist,
``resources/subscribe`` is gone, and capabilities are advertised through
``server/discover``.

The registry's DoS caps (``MAX_URIS_TOTAL`` / ``MAX_URIS_PER_SESSION``) went
with it: they bounded a *server-global, session-lifetime* structure keyed by
client-supplied URIs, which no longer exists. The SDK's ``ListenHandler``
supplies part of the replacement — it caps concurrent listen streams
(``max_subscriptions``) and per-stream event backlog (``max_buffered_events``),
ending a stream that outruns its consumer — but it is *not* the whole of it,
because it never looks at the requested URI set. That set is held for the
stream's lifetime in a ``frozenset``, so with the SDK's caps alone the ceiling
is ``max_subscriptions`` (1024) × the transport's 4 MiB body limit. That is
three orders of magnitude looser than what it replaced, on a method the
project's rate limiter does not cover (it wraps tool calls only). So the
per-stream half is restored here — see :func:`install_bounded_listen_handler`.
"""

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Iterable, Optional
from urllib.parse import quote

if TYPE_CHECKING:
    from mcp.server.subscriptions import SubscriptionBus

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_SUBSCRIPTION_URIS",
    "MAX_SUBSCRIPTION_URI_LENGTH",
    "MtimeWatcher",
    "OnChange",
    "install_bounded_listen_handler",
    "publish_change",
]

# Change kinds emitted by :class:`MtimeWatcher`, mapped to MCP notifications
# by :func:`publish_change`.
CHANGE_LIST_CHANGED = "list_changed"
CHANGE_REPLACED = "replaced"

# Per-stream ceilings on the client-supplied ``resource_subscriptions`` list,
# carried over from the 1.x registry's ``MAX_URIS_PER_SESSION`` /
# ``MAX_URI_LENGTH``. Both are far above any real client: this server serves
# three URI shapes (``zim://files``, ``zim://{name}``,
# ``zim://{name}/entry/{path}``), so 256 distinct URIs is a client watching 255
# archives at once, and 2048 characters is well past any path libzim will
# accept (``INPUT_LIMIT_ENTRY_PATH`` is 500).
MAX_SUBSCRIPTION_URIS = 256
MAX_SUBSCRIPTION_URI_LENGTH = 2048

OnChange = Callable[[str, str], Awaitable[None]]


class MtimeWatcher:
    """Polls allowed dirs and fires events when ``.zim`` files change.

    Events emitted:
      * ``zim://files`` — directory contents changed (file added/removed).
      * ``zim://{name}`` — a specific file's mtime changed (replacement).
        ``{name}`` is the basename without the ``.zim`` extension,
        percent-encoded as the ``zim://{name}`` template expands it.

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
        # _scan walks the tree + stat syscalls that block on network-mounted
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
        # Drive the task to completion so the cancellation actually propagates
        # before we drop the reference. Cancellation raises CancelledError;
        # any other late exception during teardown is swallowed deliberately.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._task
        self._task = None

    def _scan(self) -> dict[str, tuple[float, int]]:
        """Snapshot ``{path: (mtime, size)}`` for ``.zim`` files in allowed dirs.

        Walks subdirectories recursively to mirror ``_scan_zim_files`` in
        ``zim/archive.py`` (``directory.glob("**/*.zim")``). Without this,
        ``list_zim_files`` would surface ZIMs in subdirectories but the
        watcher would never fire ``zim://files`` updates for them.
        """
        snap: dict[str, tuple[float, int]] = {}
        for d in self._dirs:
            try:
                for path in Path(d).glob("**/*.zim"):
                    with contextlib.suppress(OSError):
                        if path.is_file():
                            stat = path.stat()
                            snap[str(path)] = (stat.st_mtime, stat.st_size)
            except OSError:
                continue
        return snap

    async def _tick(self) -> None:
        """Diff a fresh scan against the snapshot and dispatch any changes.

        Extracted from the polling loop so tests can drive a single pass
        deterministically without depending on sleep/scheduler timing.
        """
        # ``_scan`` walks the tree + ``stat`` syscalls that block on
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
            await self._on_change("zim://files", CHANGE_LIST_CHANGED)
        # Per-file content replacements (or mtime bumps) → zim://{name}.
        # The stem is percent-encoded exactly as RFC 6570 expansion of the
        # advertised ``zim://{name}`` template would produce it (``quote``
        # with ``safe=""`` keeps the same unreserved set), because the SDK
        # delivers events by exact string match against the URIs the client
        # subscribed with.
        #
        # BOTH spellings are published when they differ, because both READ:
        # ``UriTemplate.match`` percent-decodes before matching, so a client
        # that built ``zim://my archive`` from the ``zim://files`` listing gets
        # a successful ``resources/read`` and will naturally subscribe with the
        # same string. Publishing only the encoded form leaves that client
        # subscribed to a URI nothing ever fires on — a silent stale read for
        # the life of the stream, made worse by the hour-long resource TTL.
        # Exact-string delivery means a client sees only the spelling it asked
        # for, so the extra publish is a no-op for everyone else.
        for path in changed:
            stem = Path(path).stem
            encoded = quote(stem, safe="")
            await self._on_change(f"zim://{encoded}", CHANGE_REPLACED)
            if encoded != stem:
                await self._on_change(f"zim://{stem}", CHANGE_REPLACED)
        self._snapshot = new_snap

    async def _loop(self) -> None:
        """Run the polling loop: diff against snapshot, dispatch, repeat.

        ``asyncio.CancelledError`` is allowed to propagate so the cancelling
        caller can observe completion; asyncio Tasks rely on CancelledError
        propagating to mark themselves cancelled rather than completed-with-result.
        """
        while not self._stop_event.is_set():
            await asyncio.sleep(self._interval)
            if self._stop_event.is_set():
                return
            await self._tick()


async def publish_change(
    bus: "SubscriptionBus",
    uri: str,
    change_type: str,
) -> None:
    """Publish one watcher change onto the SDK's subscription bus.

    The bus fans out to whichever ``subscriptions/listen`` streams opted into
    that notification kind; a change nobody subscribed to costs one predicate
    call and is dropped. ``publish`` is a coroutine (the bus interface is async
    so an out-of-process backend can do network I/O to fan out across
    replicas), so both calls below must be awaited — an un-awaited publish
    delivers nothing and merely warns.

    The two change kinds map onto *different* MCP notifications, which the 1.x
    implementation could not express: a file appearing or disappearing changes
    the membership of ``zim://files``, so it is a
    ``notifications/resources/list_changed``, while a file replaced in place
    leaves the list intact and only invalidates that one resource, so it is a
    ``notifications/resources/updated`` for its URI. Previously both were sent
    as an ``updated`` for ``zim://files``, because ``resources/subscribe`` gave
    clients no way to ask for list-membership changes.

    Both kinds are matched explicitly and anything else is dropped with a
    warning, rather than falling through to ``ResourceUpdated``. A third change
    kind added to the watcher would otherwise be delivered as an ``updated``
    for whatever URI accompanied it — silently re-creating the conflation the
    2026-07-28 split exists to end, in the one place no test is looking.
    """
    from mcp.server.subscriptions import ResourcesListChanged, ResourceUpdated

    if change_type == CHANGE_LIST_CHANGED:
        await bus.publish(ResourcesListChanged())
        return
    if change_type == CHANGE_REPLACED:
        await bus.publish(ResourceUpdated(uri=uri))
        return
    logger.warning(
        "Dropping change of unknown kind %r for %r; no notification mapping",
        change_type,
        uri,
    )


def _bounded_listen_handler_class() -> type:
    """Build the ``ListenHandler`` subclass, importing the SDK lazily.

    Deferred so importing this module (which the watcher half needs) doesn't
    drag in the SDK's subscription stack — the same lazy-import shape
    ``publish_change`` uses.
    """
    from mcp.server.subscriptions import ListenHandler

    class BoundedListenHandler(ListenHandler):
        """``ListenHandler`` that rejects an oversized requested URI set.

        The one dimension the SDK's own caps leave unbounded (see the module
        docstring). Validation happens before ``super().__call__`` takes a
        subscription slot or acks, so a rejected request costs nothing beyond
        the parse the transport already did.

        Rejection is ``INVALID_PARAMS`` rather than the SDK's
        ``INTERNAL_ERROR``-for-capacity: an over-long URI list is the client's
        request being wrong, not the server being full, and the two want
        opposite client behavior (fix the request vs. retry later).
        """

        async def __call__(self, ctx: Any, params: Any) -> Any:
            """Validate the requested URI set, then serve the stream."""
            from mcp.shared.exceptions import MCPError
            from mcp_types import INVALID_PARAMS

            uris = getattr(params.notifications, "resource_subscriptions", None) or ()
            if len(uris) > MAX_SUBSCRIPTION_URIS:
                raise MCPError(
                    INVALID_PARAMS,
                    f"subscriptions/listen accepts at most "
                    f"{MAX_SUBSCRIPTION_URIS} resource subscriptions per "
                    f"stream; {len(uris)} were requested.",
                )
            for uri in uris:
                if len(uri) > MAX_SUBSCRIPTION_URI_LENGTH:
                    raise MCPError(
                        INVALID_PARAMS,
                        f"Subscription URI exceeds "
                        f"{MAX_SUBSCRIPTION_URI_LENGTH} characters.",
                    )
            return await super().__call__(ctx, params)

    return BoundedListenHandler


def install_bounded_listen_handler(mcp: Any, bus: "SubscriptionBus") -> None:
    """Swap the SDK's ``subscriptions/listen`` handler for the bounded one.

    ``MCPServer`` constructs its ``ListenHandler`` internally and exposes no
    seam for supplying one, so the registration is replaced after the fact —
    the same private-registry seam ``server.py`` already uses to *withhold* the
    handler when subscriptions are disabled, and the reason both live behind
    named helpers rather than inline attribute pokes.

    Silently does nothing if the SDK stops registering the method under this
    name; the capability itself is derived from that same registry entry, so a
    missing entry means the server isn't advertising subscriptions either.
    """
    from mcp.server.lowlevel.server import HandlerEntry
    from mcp_types import SubscriptionsListenRequestParams

    handlers = mcp._lowlevel_server._request_handlers
    if "subscriptions/listen" not in handlers:
        return
    handlers["subscriptions/listen"] = HandlerEntry(
        SubscriptionsListenRequestParams,
        _bounded_listen_handler_class()(bus),
    )
