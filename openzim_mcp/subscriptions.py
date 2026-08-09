"""Resource subscription support for OpenZIM MCP.

Tracks per-session interest in MCP resource URIs so that the polling watcher
can dispatch ``notifications/resources/updated`` to the right sessions.

This module reaches into one private FastMCP attribute (``_mcp_server``) to
register subscribe/unsubscribe handlers on the underlying lowlevel ``Server``
and to capture the active ``ServerSession`` at subscribe time. FastMCP 1.26
exposes no public surface for this.

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
import re
import weakref
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
from .exceptions import OpenZimMcpValidationError

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


# The only resource URI shapes this server actually serves (see
# ``tools/resource_tools.py``): ``zim://files``, ``zim://{name}`` and
# ``zim://{name}/entry/{path}``. The MCP SDK forwards ``req.params.uri``
# verbatim with no check that it names a registered resource, and
# ``resources/subscribe`` bypasses the rate limiter entirely, so without a
# check here any client could mint unbounded distinct registry keys.
# The optional bare ``/`` tail tolerates a client (or URL normaliser) that
# appends one to the authority-only forms.
_URI_RE = re.compile(r"^zim://[^/\s]+(?:/(?:entry/[^\s]+)?)?$")

# Hard bound on the length of an accepted URI, so a single accepted key can't
# retain an unbounded string.
MAX_URI_LENGTH = 2048

# Caps on DISTINCT URIs, the registry's only unbounded dimension. The sweep in
# ``prune`` reclaims empty containers once per watcher tick; these caps bound
# what an attacker can burst BETWEEN ticks.
MAX_URIS_TOTAL = 4096
MAX_URIS_PER_SESSION = 256


def validate_subscription_uri(uri: str) -> str:
    """Return ``uri`` if it names a resource shape this server serves.

    Raises:
        OpenZimMcpValidationError: for any other string.
    """
    if len(uri) > MAX_URI_LENGTH:
        raise OpenZimMcpValidationError(
            f"Subscription URI exceeds {MAX_URI_LENGTH} characters."
        )
    if not _URI_RE.match(uri):
        raise OpenZimMcpValidationError(
            f"Unsupported subscription URI: {uri!r}. Subscribable resources are "
            "'zim://files', 'zim://{name}' and 'zim://{name}/entry/{path}'."
        )
    return uri


class SubscriberRegistry:
    """Maps URI strings to the set of sessions interested in that URI.

    Sessions are stored as opaque hashable values — typically the active
    ``ServerSession`` captured during a subscribe request, but any hashable
    object works (tests use plain strings).

    All operations are coroutine-safe via an ``asyncio.Lock``.
    """

    def __init__(self) -> None:
        """Create an empty registry.

        M16: a live ``ServerSession`` is held WEAKLY (in a per-URI
        ``WeakSet``) so a client that disconnects without ever triggering a
        broadcast — the common case when the watched ``.zim`` files rarely
        change — is dropped automatically when its session is garbage
        collected, instead of accumulating dead sessions (and their streams /
        buffers) without bound. ``clear_session`` only ran on a failed
        broadcast send, so it could never reclaim those.

        The public contract still accepts "any hashable" session, but a
        non-weak-referenceable value (e.g. a plain ``str`` / ``int`` used in
        tests) can't go in a ``WeakSet``, so those fall back to a strong set —
        bounded by construction and never the production leak source.
        """
        self._weak_by_uri: dict[str, "weakref.WeakSet[Any]"] = {}
        self._strong_by_uri: dict[str, set[Hashable]] = {}
        self._lock = asyncio.Lock()

    def _is_known_uri(self, uri: str) -> bool:
        return uri in self._weak_by_uri or uri in self._strong_by_uri

    def _distinct_uri_count(self) -> int:
        return len(set(self._weak_by_uri) | set(self._strong_by_uri))

    def _session_holds_uri(self, uri: str, session: Hashable) -> bool:
        """True iff ``session`` is already subscribed to ``uri``."""
        for store in (self._weak_by_uri, self._strong_by_uri):
            sessions = store.get(uri)
            if sessions is None:
                continue
            # ``in`` on a WeakSet weak-refs its arg; a non-weak-
            # referenceable session (never in the weak set) raises
            # TypeError — it simply isn't a member.
            with contextlib.suppress(TypeError):
                if session in sessions:
                    return True
        return False

    def _uri_count_for_session(self, session: Hashable) -> int:
        """Count the distinct URIs ``session`` is already subscribed to.

        Scans the URI keys (bounded by ``MAX_URIS_TOTAL``) and does an O(1)
        membership test in each container, so this stays cheap even with many
        thousands of sessions on a single URI.
        """
        count = 0
        for store in (self._weak_by_uri, self._strong_by_uri):
            for sessions in store.values():
                # ``in`` on a WeakSet weak-refs its arg; a non-weak-
                # referenceable session (never in the weak set) raises
                # TypeError — it simply isn't a member.
                with contextlib.suppress(TypeError):
                    if session in sessions:
                        count += 1
        return count

    async def subscribe(self, uri: str, session: Hashable) -> None:
        """Register interest. Idempotent for the same (uri, session) pair.

        Raises:
            OpenZimMcpValidationError: when accepting ``uri`` would push this
                session — or the registry as a whole — past its distinct-URI
                cap. ``resources/subscribe`` is not rate limited and URIs are
                fully client-controlled, so an unbounded registry is a remote
                memory-exhaustion vector; the caps bound what a client can
                burst between watcher sweeps.
        """
        async with self._lock:
            if not self._is_known_uri(uri):
                if self._distinct_uri_count() >= MAX_URIS_TOTAL:
                    raise OpenZimMcpValidationError(
                        "Subscription registry is at its "
                        f"{MAX_URIS_TOTAL}-URI capacity; "
                        "unsubscribe from unused resources first."
                    )
            # Sweep follow-up: the per-session cap must cover KNOWN URIs
            # too — it used to sit inside the not-known branch, so a
            # session at its cap could keep adding any URI some other
            # session had already registered. Idempotent re-subscribes
            # (URI already held by this session) stay exempt.
            if (
                not self._session_holds_uri(uri, session)
                and self._uri_count_for_session(session) >= MAX_URIS_PER_SESSION
            ):
                raise OpenZimMcpValidationError(
                    "This session is already subscribed to the maximum of "
                    f"{MAX_URIS_PER_SESSION} distinct resource URIs."
                )
            try:
                self._weak_by_uri.setdefault(uri, weakref.WeakSet()).add(session)
            except TypeError:
                # Not weak-referenceable (e.g. a str/int session stand-in).
                self._strong_by_uri.setdefault(uri, set()).add(session)
            logger.debug("subscribe uri=%s session=%r", uri, session)

    async def unsubscribe(self, uri: str, session: Hashable) -> None:
        """Drop interest. Silent if the (uri, session) pair was never registered."""
        async with self._lock:
            weak = self._weak_by_uri.get(uri)
            if weak is not None:
                # WeakSet.discard weak-refs its arg, so a non-weak-referenceable
                # session (never in the weak set) raises TypeError — ignore it.
                with contextlib.suppress(TypeError):
                    weak.discard(session)
                if not weak:
                    self._weak_by_uri.pop(uri, None)
            strong = self._strong_by_uri.get(uri)
            if strong is not None:
                strong.discard(session)
                if not strong:
                    self._strong_by_uri.pop(uri, None)

    async def sessions_for(self, uri: str) -> List[Any]:
        """Return a snapshot of the LIVE sessions subscribed to ``uri``.

        Order is not guaranteed; callers (the broadcast fan-out in particular)
        don't rely on ordering. Garbage-collected weak sessions are absent.
        """
        async with self._lock:
            return [*self._weak_by_uri.get(uri, ()), *self._strong_by_uri.get(uri, ())]

    async def clear_session(self, session: Hashable) -> None:
        """Drop ``session`` from every URI (called on broadcast-send failure)."""
        async with self._lock:
            for store in (self._weak_by_uri, self._strong_by_uri):
                empty_uris = []
                for uri, sessions in store.items():
                    # ``discard`` on a WeakSet weak-refs its arg; a
                    # non-weak-referenceable session raises TypeError (it was
                    # never in the weak set) — ignore it.
                    with contextlib.suppress(TypeError):
                        sessions.discard(session)
                    if not sessions:
                        empty_uris.append(uri)
                for uri in empty_uris:
                    store.pop(uri, None)

    async def prune(self) -> int:
        """Drop every now-empty per-URI container. Returns the number dropped.

        The ``WeakSet`` empties itself when a session is garbage-collected, but
        the DICT ENTRY is only popped by ``unsubscribe`` / ``clear_session`` —
        neither of which runs on a bare client disconnect, and
        ``broadcast_resource_updated`` returns early on an empty
        ``sessions_for``, so a URI that never gets broadcast is never revisited.
        The keys are client-controlled, so the residue grows without bound.

        Call this from a background sweep only — NOT from ``sessions_for`` or
        ``clear_session``. Those already hold ``self._lock``, which is a
        non-reentrant ``asyncio.Lock``: re-acquiring it here would deadlock.
        """
        async with self._lock:
            dropped = 0
            for store in (self._weak_by_uri, self._strong_by_uri):
                for uri in [u for u, s in store.items() if not s]:
                    store.pop(uri, None)
                    dropped += 1
            if dropped:
                logger.debug("pruned %d empty subscription container(s)", dropped)
            return dropped


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
        registry: optional ``SubscriberRegistry`` to sweep once per tick. The
            watcher loop is the only periodic task in the process, so it is
            also the only place the registry's empty-container reclamation can
            be driven from (``sessions_for`` / ``clear_session`` already hold
            the registry lock and would deadlock).
    """

    def __init__(
        self,
        dirs: Iterable[str],
        interval: float,
        on_change: OnChange,
        registry: Optional["SubscriberRegistry"] = None,
    ) -> None:
        """Capture the watch list, interval, dispatch callback, and registry."""
        self._dirs = [str(d) for d in dirs]
        self._interval = interval
        self._on_change = on_change
        self._registry = registry
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
            await self._on_change("zim://files", "list_changed")
        # Per-file content replacements (or mtime bumps) → zim://{name}
        for path in changed:
            name = Path(path).stem
            await self._on_change(f"zim://{name}", "replaced")
        self._snapshot = new_snap
        # Sweep the registry's dead per-URI containers. This is the ONLY place
        # the sweep can run: pruning inside ``sessions_for`` would never see a
        # URI that is subscribed but never broadcast (the exact leak), and both
        # ``sessions_for`` and ``clear_session`` hold the registry's
        # non-reentrant lock. A sweep failure must not kill the watcher loop.
        if self._registry is not None:
            try:
                await self._registry.prune()
            except Exception as e:  # noqa: BLE001 - sweep is best-effort
                logger.warning("subscription registry prune failed: %s", e)

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

    The subscribe seam is where the URI is validated: the SDK passes
    ``req.params.uri`` through untouched, and ``resources/subscribe`` is not
    rate limited, so this is the only gate between a client and an unbounded
    number of registry keys.
    """
    low = mcp._mcp_server

    @low.subscribe_resource()
    async def _on_subscribe(uri: Any) -> None:  # type: ignore[misc]
        session = low.request_context.session
        await registry.subscribe(validate_subscription_uri(str(uri)), session)

    @low.unsubscribe_resource()
    async def _on_unsubscribe(uri: Any) -> None:  # type: ignore[misc]
        # NOT validated: unsubscribe only ever REMOVES state, and rejecting a
        # malformed URI here would strand any entry a laxer past version let in.
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
