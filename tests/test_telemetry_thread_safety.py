"""Telemetry counters must not lose increments across worker threads.

``handle_zim_query`` runs on ``asyncio.to_thread`` workers, so ``_track``
is called from multiple threads concurrently. Incrementing an *existing*
``Counter`` key is effectively atomic on GIL builds, but the first-ever
increment of a key routes through ``Counter.__missing__`` — a pure-Python
call with a preemption point between reading 0 and storing 1 — so two
threads both recording a key's first occurrence can leave it at 1.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from unittest.mock import MagicMock

from openzim_mcp.simple_tools import SimpleToolsHandler


class _SlowMissingCounter(Counter):
    """Counter whose ``__missing__`` holds the read-0/store-1 window open.

    This makes the preemption point CPython provides inside ``__missing__``
    deterministic instead of a lottery: without synchronization in
    ``_track``, both threads read 0 and both store 1.
    """

    def __missing__(self, key: str) -> int:
        time.sleep(0.05)
        return 0


def test_first_increment_of_a_key_is_not_lost_across_threads() -> None:
    """Two threads bumping a fresh key once each must always total 2."""
    handler = SimpleToolsHandler(MagicMock())
    handler._telemetry = _SlowMissingCounter()
    barrier = threading.Barrier(2)

    def worker() -> None:
        barrier.wait()
        handler._track("fresh_event")

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert handler.get_telemetry()["fresh_event"] == 2
