"""Regression tests for code-review 2026-06-10 Phase 8 (timeout_utils).

M20/M23 (single pool shared by regex + libzim opens causes head-of-line
blocking), M21 (pool never shut down; non-daemon workers block exit),
M22 (timed-out futures never cancelled).
"""

import threading
import time
from concurrent.futures import thread as _cf_thread

import pytest

from openzim_mcp import timeout_utils as tu
from openzim_mcp.exceptions import OpenZimMcpTimeoutError


@pytest.fixture(autouse=True)
def _clean_pools():
    tu.shutdown_timeout_executors()
    yield
    tu.shutdown_timeout_executors()


# M20/M23 — io and regex use SEPARATE executors
def test_io_and_regex_pools_are_separate():
    tu.run_with_timeout(lambda: None, 1.0, "x", pool="io")
    tu.run_with_timeout(lambda: None, 1.0, "x", pool="regex")
    assert tu._get_executor("io") is not tu._get_executor("regex")


def test_regex_pool_not_starved_by_saturated_io_pool():
    """A wedged io pool must not cause regex-pool ops to time out (M20/M23)."""
    release = threading.Event()
    io = tu._get_executor("io")
    # Occupy every io worker slot with a task blocked on the event.
    for _ in range(tu._IO_MAX_WORKERS):
        io.submit(release.wait)
    try:
        # The regex pool is independent, so this completes well under its
        # timeout even though the io pool is fully saturated.
        result = tu.run_with_timeout(
            lambda: 7, 1.0, "should not time out", pool="regex"
        )
        assert result == 7
    finally:
        release.set()


# M21 — worker threads are daemon and are not joined at interpreter exit
def test_worker_threads_are_daemon_and_unjoined():
    tu.run_with_timeout(lambda: None, 1.0, "x", pool="io")
    io = tu._get_executor("io")
    assert io._threads, "expected at least one worker thread"
    assert all(t.daemon for t in io._threads)
    # Not registered in concurrent.futures' atexit join set.
    assert all(t not in _cf_thread._threads_queues for t in io._threads)


def test_shutdown_is_idempotent_and_clears_pools():
    tu.run_with_timeout(lambda: None, 1.0, "x", pool="io")
    tu.shutdown_timeout_executors()
    assert tu._EXECUTORS == {}
    # Safe to call again with nothing to do.
    tu.shutdown_timeout_executors()


# M22 — a timeout raises promptly and the pending future is cancelled
def test_timeout_raises_without_hanging():
    start = time.monotonic()
    with pytest.raises(OpenZimMcpTimeoutError):
        tu.run_with_timeout(lambda: time.sleep(5), 0.1, "timed out", pool="regex")
    # Returned quickly — did not wait for the 5s sleep.
    assert time.monotonic() - start < 2.0


def test_pending_future_is_cancelled_on_timeout():
    """A queued (not-yet-running) item is cancelled, not run after timeout."""
    release = threading.Event()
    ran = threading.Event()
    io = tu._get_executor("io")
    # Fill every slot so the next submission stays PENDING.
    for _ in range(tu._IO_MAX_WORKERS):
        io.submit(release.wait)
    try:
        # This submission queues behind the blockers and its result(timeout)
        # expires while still pending → run_with_timeout cancels it.
        with pytest.raises(OpenZimMcpTimeoutError):
            tu.run_with_timeout(ran.set, 0.1, "queued, timed out", pool="io")
        # Give a moment; the cancelled item must never execute.
        time.sleep(0.2)
        assert not ran.is_set()
    finally:
        release.set()
