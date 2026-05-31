"""
Shared timeout utilities for OpenZIM MCP server.

Provides cross-platform timeout functionality. Workers run in a bounded
``ThreadPoolExecutor`` so a sustained timeout rate can't accumulate
unkillable worker threads — concurrent calls past the cap block instead
of spawning, which makes the overload mode observable to the operator
and bounds resource pressure when libzim is slow on a large archive.
"""

import logging
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional, Type, TypeVar

from .exceptions import OpenZimMcpTimeoutError

logger = logging.getLogger(__name__)

T = TypeVar("T")


# A timed-out worker can't be killed (CPython doesn't expose thread
# cancellation); the surviving thread keeps doing libzim work and holds
# its archive ref. Without a cap, sustained timeouts pile threads up
# until the OS runs out of file handles or the GIL contention swamps the
# server. The cap sets a hard ceiling: when all worker slots are busy
# (live + orphaned-but-still-running), new submissions block on the
# pool's queue instead of allocating new OS threads. Operators see the
# pressure (rising queue depth, falling throughput) rather than discovering
# it post-mortem in an OOM dump. Override via the env var below if a
# specific deployment needs more headroom; the default is sized for a
# typical 4-8 vCPU server with a handful of concurrent ZIM queries.
_DEFAULT_MAX_WORKERS = 16
_MAX_WORKERS = int(
    os.environ.get("OPENZIM_MCP_TIMEOUT_MAX_WORKERS", _DEFAULT_MAX_WORKERS)
)
_EXECUTOR: Optional[ThreadPoolExecutor] = None
_EXECUTOR_LOCK = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    """Return the module-level executor, creating it on first use.

    Lazy so ``import openzim_mcp.timeout_utils`` doesn't start threads
    in environments that never call ``run_with_timeout``.
    """
    global _EXECUTOR
    if _EXECUTOR is not None:
        return _EXECUTOR
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None:
            _EXECUTOR = ThreadPoolExecutor(
                max_workers=_MAX_WORKERS,
                thread_name_prefix="openzim-timeout",
            )
        return _EXECUTOR


def run_with_timeout(
    func: Callable[[], T],
    timeout_seconds: float,
    timeout_message: str,
    timeout_exception: Type[OpenZimMcpTimeoutError] = OpenZimMcpTimeoutError,
) -> T:
    """
    Run a function with a timeout.

    Best-effort interrupt: Python can't truly cancel a worker thread, so on
    timeout the future is dropped and the worker continues until libzim
    returns (or the interpreter shuts down). The bounded pool caps the
    number of orphaned workers so a high-timeout-rate workload backs up
    visibly rather than silently exhausting OS threads.

    Args:
        func: The function to execute
        timeout_seconds: Maximum time allowed
        timeout_message: Message for timeout error
        timeout_exception: The exception class to raise on timeout

    Returns:
        The result of func()

    Raises:
        OpenZimMcpTimeoutError: (or subclass) If the operation exceeds the time limit
    """
    executor = _get_executor()
    future: Future[T] = executor.submit(func)
    try:
        return future.result(timeout=timeout_seconds)
    except TimeoutError as e:
        # The future keeps running in the worker; we drop the reference and
        # let it complete. Log it so a runaway can be correlated with the
        # request that timed out without sprinkling timing prints across
        # callers.
        logger.warning(
            "run_with_timeout: worker timed out after %.1fs (%s); "
            "thread continues until libzim returns",
            timeout_seconds,
            timeout_message,
        )
        raise timeout_exception(timeout_message) from e
