"""
Shared timeout utilities for OpenZIM MCP server.

Provides cross-platform timeout functionality using threading.
"""

import signal
import sys
import threading
from contextlib import contextmanager
from typing import Callable, Generator, Type, TypeVar

from .exceptions import OpenZimMcpTimeoutError, RegexTimeoutError

T = TypeVar("T")


def run_with_timeout(
    func: Callable[[], T],
    timeout_seconds: float,
    timeout_message: str,
    timeout_exception: Type[OpenZimMcpTimeoutError] = OpenZimMcpTimeoutError,
) -> T:
    """
    Run a function with a timeout using threading (cross-platform).

    This is a cross-platform timeout mechanism that works on both Unix and Windows.
    Note that this cannot truly interrupt blocking Python operations, but it
    provides a best-effort timeout mechanism.

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
    # Use a sentinel to distinguish "no result yet" from "returned None"
    _SENTINEL = object()
    result: list[T | object] = [_SENTINEL]
    exception: list[Exception] = []

    def worker() -> None:
        try:
            result[0] = func()
        except Exception as e:
            exception.append(e)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        # Thread is still running - timeout occurred
        # Note: We cannot forcibly kill the thread, but marking it as daemon
        # means it will be cleaned up when the main thread exits.
        raise timeout_exception(timeout_message)

    if exception:
        raise exception[0]

    if result[0] is not _SENTINEL:
        return result[0]  # type: ignore[return-value]

    # Worker completed but didn't set result - should not happen in normal operation
    raise timeout_exception(timeout_message)


@contextmanager
def regex_timeout(seconds: float) -> Generator[None, None, None]:
    """Context manager for regex operations with timeout protection.

    This provides protection against ReDoS (Regular Expression Denial of Service)
    attacks by limiting the time spent on regex matching.

    Cross-platform implementation:
    - On Unix-like systems: Uses SIGALRM for precise interruption
    - On Windows: Uses threading-based timeout (best-effort)

    Args:
        seconds: Maximum time allowed for regex operation

    Raises:
        RegexTimeoutError: If the operation exceeds the time limit

    Example:
        with regex_timeout(1.0):
            result = re.search(pattern, text)
    """
    if sys.platform != "win32":
        # Unix-like systems: Use signal-based timeout for precise control

        def timeout_handler(signum: int, frame: object) -> None:
            raise RegexTimeoutError(
                f"Regex operation timed out after {seconds} seconds"
            )

        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)
    else:
        # Windows: No signal-based timeout available.
        # IMPORTANT: This context manager provides NO timeout protection on Windows.
        # Callers that need Windows support MUST use run_with_timeout() instead.
        # See simple_tools.safe_regex_search() for the correct pattern.
        import logging

        logging.getLogger(__name__).debug(
            "regex_timeout: No timeout enforcement on Windows - "
            "use run_with_timeout() for cross-platform support"
        )
        yield
