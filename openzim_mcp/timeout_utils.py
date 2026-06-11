"""
Shared timeout utilities for OpenZIM MCP server.

Provides cross-platform timeout functionality. Workers run in bounded
``ThreadPoolExecutor`` pools so a sustained timeout rate can't accumulate
unkillable worker threads. Two SEPARATE pools are kept so the two very
different workloads can't starve each other (M20/M23):

* ``"io"`` — long-running libzim work (archive opens, ~30s timeout).
* ``"regex"`` — sub-second ReDoS guards on pre-compiled patterns (~1s timeout).

A single shared pool let ~16 wedged archive opens (e.g. a dead NFS mount)
permanently fill every slot, after which every regex op queued behind them and
spuriously raised ``RegexTimeoutError`` after 1s of QUEUE wait without the
regex ever running — degrading intent classification for requests against
perfectly healthy archives.

Worker threads are daemon threads (M21) so a worker stuck inside an
uninterruptible libzim call can never block interpreter exit. Timed-out
futures are cancelled (M22) so still-queued work is discarded rather than run
to completion after the caller has already given up.
"""

import contextlib
import logging
import os
import threading
import weakref
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Dict, Type, TypeVar

from .exceptions import OpenZimMcpTimeoutError

logger = logging.getLogger(__name__)

T = TypeVar("T")


# CPython internals used to spawn daemon worker threads. Guarded so a future
# interpreter that renames them degrades to the (non-daemon) stdlib executor
# rather than failing to import.
try:  # pragma: no cover - import-time capability probe
    from concurrent.futures.thread import _worker

    _DAEMON_INTERNALS_AVAILABLE = True
except Exception:  # pragma: no cover
    _DAEMON_INTERNALS_AVAILABLE = False


class _DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """A ``ThreadPoolExecutor`` whose worker threads are daemon threads.

    M21: a worker stuck inside an uninterruptible libzim call (an archive open
    on a wedged NFS/SMB mount — exactly the scenario this module guards) would
    otherwise block interpreter exit forever. ``concurrent.futures`` registers
    an atexit hook that puts a shutdown sentinel on each worker's queue and
    JOINS it, and ``threading._shutdown()`` joins every non-daemon thread
    regardless. A hung worker never dequeues the sentinel, so the join never
    returns: Ctrl-C prints the shutdown logs and then the process hangs and
    must be SIGKILLed. Daemon threads are skipped by both join paths, so the
    process can always exit; the hung worker is abandoned (the OS reclaims it
    on exit), which is the correct outcome for a dead mount.
    """

    def _adjust_thread_count(self) -> None:  # pragma: no cover - thread spawn
        # Mirrors CPython 3.12/3.13 ThreadPoolExecutor._adjust_thread_count but
        # marks the worker daemon and intentionally does NOT register it in
        # ``_threads_queues`` (so the atexit join hook ignores it).
        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_: object, q: object = self._work_queue) -> None:
            q.put(None)  # type: ignore[attr-defined]

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = "%s_%d" % (self._thread_name_prefix or self, num_threads)
            t = threading.Thread(
                name=thread_name,
                target=_worker,
                args=(
                    weakref.ref(self, weakref_cb),
                    self._work_queue,
                    self._initializer,
                    self._initargs,
                ),
                daemon=True,
            )
            t.start()
            self._threads.add(t)  # type: ignore[attr-defined]
            # Deliberately NOT added to ``_threads_queues``: a daemon worker
            # must never be joined at interpreter shutdown.


def _env_int(name: str, default: int) -> int:
    """Parse a positive-int env var, falling back to ``default`` on garbage."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        logger.warning("Invalid %s=%r; using default %d", name, raw, default)
        return default


# A timed-out worker can't be killed (CPython exposes no thread cancellation);
# the surviving thread keeps doing libzim work and holds its archive ref. The
# per-pool cap sets a hard ceiling so sustained timeouts back up visibly
# (rising queue depth) instead of exhausting OS threads. Sized for a typical
# 4-8 vCPU server; override via the env vars below.
_IO_MAX_WORKERS = _env_int("OPENZIM_MCP_TIMEOUT_MAX_WORKERS", 16)
_REGEX_MAX_WORKERS = _env_int("OPENZIM_MCP_REGEX_MAX_WORKERS", 8)
_POOL_SIZES: Dict[str, int] = {"io": _IO_MAX_WORKERS, "regex": _REGEX_MAX_WORKERS}

_EXECUTORS: Dict[str, ThreadPoolExecutor] = {}
_EXECUTOR_LOCK = threading.Lock()


def _make_executor(max_workers: int, name: str) -> ThreadPoolExecutor:
    if _DAEMON_INTERNALS_AVAILABLE:
        try:
            return _DaemonThreadPoolExecutor(
                max_workers=max_workers, thread_name_prefix=name
            )
        except Exception:  # pragma: no cover - defensive fallback
            logger.warning(
                "daemon timeout pool unavailable; using default ThreadPoolExecutor"
            )
    return ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=name)


def _get_executor(pool: str) -> ThreadPoolExecutor:
    """Return the executor for ``pool`` ("io" / "regex"), creating it lazily.

    Lazy so ``import openzim_mcp.timeout_utils`` doesn't start threads in
    environments that never call ``run_with_timeout``.
    """
    existing = _EXECUTORS.get(pool)
    if existing is not None:
        return existing
    with _EXECUTOR_LOCK:
        existing = _EXECUTORS.get(pool)
        if existing is None:
            size = _POOL_SIZES.get(pool, _IO_MAX_WORKERS)
            existing = _make_executor(size, f"openzim-timeout-{pool}")
            _EXECUTORS[pool] = existing
        return existing


def run_with_timeout(
    func: Callable[[], T],
    timeout_seconds: float,
    timeout_message: str,
    timeout_exception: Type[OpenZimMcpTimeoutError] = OpenZimMcpTimeoutError,
    *,
    pool: str = "io",
) -> T:
    """
    Run a function with a timeout in a bounded daemon thread pool.

    Best-effort interrupt: Python can't truly cancel a RUNNING worker thread,
    so on timeout a still-queued future is cancelled and a running one is
    abandoned (it continues until libzim returns, but on a daemon thread can no
    longer block process exit).

    Args:
        func: The function to execute
        timeout_seconds: Maximum time allowed
        timeout_message: Message for timeout error
        timeout_exception: The exception class to raise on timeout
        pool: Which executor to use — ``"io"`` (default; long libzim work) or
            ``"regex"`` (sub-second ReDoS guards). Keeping them separate stops
            wedged archive opens from spuriously timing out unrelated regex ops.

    Returns:
        The result of func()

    Raises:
        OpenZimMcpTimeoutError: (or subclass) If the operation exceeds the time limit
    """
    executor = _get_executor(pool)
    future: Future[T] = executor.submit(func)
    try:
        return future.result(timeout=timeout_seconds)
    except TimeoutError as e:
        # M22: cancel the future so a still-PENDING (queued) item is discarded
        # and never occupies a worker slot after the caller has given up. A
        # running worker can't be cancelled — it continues until libzim returns
        # — but it runs on a daemon thread, so it can't block process exit.
        future.cancel()
        logger.warning(
            "run_with_timeout: worker timed out after %.1fs (%s); "
            "pending future cancelled, any running thread continues until "
            "libzim returns",
            timeout_seconds,
            timeout_message,
        )
        raise timeout_exception(timeout_message) from e


def shutdown_timeout_executors() -> None:
    """Best-effort shutdown of the timeout pools (M21).

    Intended for ``OpenZimMcpServer.run()``'s finally block. Cancels queued
    work and returns immediately (``wait=False``) — daemon workers stuck in
    libzim are abandoned rather than joined, so shutdown never hangs.
    """
    with _EXECUTOR_LOCK:
        executors = list(_EXECUTORS.values())
        _EXECUTORS.clear()
    for ex in executors:
        # Shutdown is best-effort; never let a teardown error escape.
        with contextlib.suppress(Exception):  # pragma: no cover
            ex.shutdown(wait=False, cancel_futures=True)
