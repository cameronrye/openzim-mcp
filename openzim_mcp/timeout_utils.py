"""
Shared timeout utilities for OpenZIM MCP server.

Provides cross-platform timeout functionality using threading.
"""

import threading
from typing import Callable, Type, TypeVar

from .exceptions import OpenZimMcpTimeoutError

T = TypeVar("T")


def run_with_timeout(
    func: Callable[[], T],
    timeout_seconds: float,
    timeout_message: str,
    timeout_exception: Type[OpenZimMcpTimeoutError] = OpenZimMcpTimeoutError,
) -> T:
    """
    Run a function with a timeout using threading (cross-platform).

    Works on any thread (no main-thread restriction) and on all platforms,
    making it safe to call from asyncio executors and worker threads.
    Note: this cannot truly interrupt blocking Python operations; it provides
    a best-effort timeout — the worker is left as a daemon thread to be
    reclaimed at interpreter shutdown.

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
    # Sentinel distinguishes "no result yet" from "returned None".
    _SENTINEL = object()
    result: list[T | object] = [_SENTINEL]
    exception: list[BaseException] = []

    def worker() -> None:
        # Catch ``KeyboardInterrupt`` / ``SystemExit`` alongside ``Exception``
        # so a Ctrl-C or ``sys.exit()`` raised inside ``func()`` is propagated
        # by the caller via ``exception[0]`` below rather than masked as a
        # misleading timeout. Catching ``BaseException`` directly would do
        # the same but trips CodeQL's ``py/catch-base-exception`` — naming
        # the three concrete types is equivalent for a sync worker (no
        # ``GeneratorExit`` semantics here).
        try:
            result[0] = func()
        except (KeyboardInterrupt, SystemExit, Exception) as e:
            exception.append(e)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        # Cannot forcibly kill the thread; daemon=True ensures it doesn't
        # block interpreter shutdown.
        raise timeout_exception(timeout_message)

    if exception:
        raise exception[0]

    return result[0]  # type: ignore[return-value]
