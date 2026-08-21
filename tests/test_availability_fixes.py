"""Regression tests for the availability batch (P3 / P6).

* P3 — quadratic ReDoS in ``IntentParser._PARAM_LEAK_RE`` (the nominal 1s
  ``safe_regex_sub`` guard cannot interrupt a running ``re`` match).
* P6 — ``/readyz`` probe timeouts leaking default-executor threads, wedging
  every MCP tool call.

The batch's third item, P29 (``SubscriberRegistry`` never reclaiming per-URI
containers), no longer has a subject: the 2026-07-28 revision dropped
``resources/subscribe`` and protocol sessions, so the registry and its prune
sweep were deleted and the SDK's ``SubscriptionBus`` owns listener lifetime.
"""

import os
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from openzim_mcp.config import OpenZimMcpConfig

# ---------------------------------------------------------------------------
# P3 — long whitespace runs must not backtrack quadratically
# ---------------------------------------------------------------------------


def test_parse_intent_long_whitespace_run_is_linear():
    """8k+ trailing spaces used to backtrack for seconds inside
    ``_PARAM_LEAK_RE`` / ``_TRAILING_POLITENESS_RE`` and raise
    ``RegexTimeoutError`` out of ``parse_intent``.
    """
    from openzim_mcp.intent_parser import IntentParser

    started = time.monotonic()
    intent, params, _ = IntentParser.parse_intent("Berlin" + " " * 20000)
    elapsed = time.monotonic() - started

    assert intent == "tell_me_about"
    assert params["topic"] == "berlin"
    assert elapsed < 0.5, f"parse_intent took {elapsed:.2f}s"


def test_parse_intent_interior_whitespace_run_is_linear():
    """The collapse must also defuse a run in the MIDDLE of the query, where
    the param-leak strip's failing alternation is what backtracks.
    """
    from openzim_mcp.intent_parser import IntentParser

    started = time.monotonic()
    intent, params, _ = IntentParser.parse_intent(
        "tell me about Berlin" + " " * 20000 + "limit=x"
    )
    elapsed = time.monotonic() - started

    assert intent == "tell_me_about"
    assert params["topic"] == "berlin"
    assert elapsed < 0.5, f"parse_intent took {elapsed:.2f}s"


def test_param_leak_strip_still_works_with_single_width_leading_atom():
    """Fix B narrowed ``\\s+`` to ``\\s``; the loop + strip keep behaviour."""
    from openzim_mcp.intent_parser import IntentParser

    assert (
        IntentParser._strip_param_leaks("tell me about Photosynthesis  limit=10")
        == "tell me about Photosynthesis"
    )
    assert (
        IntentParser._strip_param_leaks("Berlin limit=10 compact_budget=200")
        == "Berlin"
    )


@pytest.mark.asyncio
async def test_zim_query_rejects_oversized_query():
    """Fix C — the front door caps the query length, since no timeout can
    interrupt a running ``re`` match.
    """
    from openzim_mcp.tools import zim_query as zim_query_tool
    from openzim_mcp.tools.zim_query import MAX_QUERY_LENGTH

    captured = {}

    class _FakeMcp:
        def tool(self, description=None):
            def deco(fn):
                captured["fn"] = fn
                return fn

            return deco

    server = MagicMock()
    server.mcp = _FakeMcp()
    server.rate_limiter.check_rate_limit.return_value = None
    zim_query_tool.register(server)

    result = await captured["fn"]("x" * (MAX_QUERY_LENGTH + 1))
    assert result["error"] is True
    assert result["operation"] == "invalid_query"
    server.simple_tools_handler.handle_zim_query.assert_not_called()


# ---------------------------------------------------------------------------
# P6 — /readyz must not consume the default executor
# ---------------------------------------------------------------------------


@pytest.fixture
def readyz_mock_server(tmp_path):
    config = OpenZimMcpConfig(
        allowed_directories=[tempfile.gettempdir()], transport="http"
    )
    config.allowed_directories = [str(tmp_path)]
    server = MagicMock()
    server.config = config
    return server


def test_readyz_pool_is_dedicated_and_single_flight(readyz_mock_server, monkeypatch):
    """A wedged probe must (a) run on the dedicated ``readyz`` pool rather than
    the loop's default executor — which also serves every MCP tool call — and
    (b) never be re-submitted while it is still running. ``asyncio.wait_for``
    cannot cancel a running thread, so each re-submission would permanently
    burn a worker.

    The gate is a ``threading.Event`` that the test never sets until teardown:
    ``time.sleep`` would return on its own and hide the leak entirely.
    """
    import openzim_mcp.http_app as http_app

    monkeypatch.setattr(http_app, "READYZ_PROBE_TIMEOUT_SECONDS", 0.05)

    gate = threading.Event()
    probe_threads: list[str] = []

    def blocking_isdir(_d):
        probe_threads.append(threading.current_thread().name)
        gate.wait(30)
        return True

    monkeypatch.setattr(http_app.os.path, "isdir", blocking_isdir)

    app = http_app.build_starlette_app(readyz_mock_server)
    client = TestClient(app)
    try:
        for _ in range(8):
            resp = client.get("/readyz")
            assert resp.status_code == 503
            assert "timed out" in resp.json()["reason"]

        assert len(probe_threads) == 1, (
            "each timed-out probe re-submitted work: " f"{probe_threads}"
        )
        assert probe_threads[0].startswith(
            "openzim-timeout-readyz"
        ), f"probe ran on the default executor: {probe_threads[0]}"
    finally:
        # Release the worker so the module-level single-slot pool is reusable.
        gate.set()


def test_readyz_single_flight_releases_after_probe_completes(
    readyz_mock_server, monkeypatch
):
    """Single-flight must track the concurrent Future, and must not wedge the
    endpoint once a probe finishes normally.
    """
    import openzim_mcp.http_app as http_app

    app = http_app.build_starlette_app(readyz_mock_server)
    client = TestClient(app)
    assert client.get("/readyz").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_readyz_pool_is_registered_with_one_worker():
    from openzim_mcp import timeout_utils

    assert timeout_utils._POOL_SIZES["readyz"] == 1


def test_readyz_concurrent_probes_on_healthy_server_all_succeed():
    """Overlapping probes must share the result, not get a false 503.

    Single-flight exists to stop a wedged stat from burning workers. It must
    not turn "another probe is in flight" into "probe timed out" — that fails
    a readiness check on a healthy instance and pulls it from rotation.
    """
    import asyncio as _asyncio
    import threading as _threading

    from openzim_mcp.http_app import _make_readyz

    released = _threading.Event()
    calls: list[int] = []

    # A real directory, not a hard-coded "/tmp": on Windows that path does
    # not exist, so `_any_readable_dir()` correctly reported "not ready" and
    # the 503 under test was indistinguishable from the bug it pins.
    _allowed = tempfile.mkdtemp(prefix="openzim_mcp_readyz_")

    class _Cfg:
        allowed_directories = [_allowed]

    class _Server:
        config = _Cfg()

    readyz = _make_readyz(_Server())

    real_isdir = os.path.isdir

    def _slow_isdir(p):
        calls.append(1)
        released.wait(timeout=5)
        return real_isdir(p)

    async def _drive():
        with patch("openzim_mcp.http_app.os.path.isdir", _slow_isdir):
            tasks = [_asyncio.create_task(readyz(None)) for _ in range(5)]
            # Let all five reach the shared probe, then let the stat finish.
            await _asyncio.sleep(0.2)
            released.set()
            return await _asyncio.gather(*tasks)

    responses = _asyncio.run(_drive())

    assert [r.status_code for r in responses] == [200] * 5, (
        "concurrent probes on a healthy server must all report ready, "
        f"got {[r.status_code for r in responses]}"
    )
    # Single-flight preserved: one shared probe, not five submissions.
    assert len(calls) == 1, f"expected one shared probe, got {len(calls)}"


def test_readyz_queued_probe_timeout_does_not_cancel_co_waiters():
    """A waiter timing out must not discard a still-QUEUED shared probe.

    All waiters share one ``concurrent.futures.Future``. ``wrap_future``
    chains cancellation back to it, and ``Future.cancel()`` returns False
    while the work is RUNNING but SUCCEEDS while it is still queued. So the
    first waiter to expire discards the shared work item and cancels every
    peer. ``CancelledError`` is a ``BaseException``, so it slips past
    ``except asyncio.TimeoutError`` and escapes the handler entirely — a
    dropped request instead of a 503.

    Reproducing it needs THREE conditions, and getting any one wrong hides
    the defect:
      * the probe must be QUEUED, not running — so the single-worker pool is
        occupied first; ``cancel()`` returns False on a RUNNING future;
      * both waiters must be in flight at once, so the stagger has to be
        SMALLER than the timeout — otherwise the first waiter finishes and
        the second is handed a freshly submitted probe;
      * the stagger must still be non-zero and comfortably above timer
        granularity (~15.6 ms on some platforms), or both deadlines land in
        one loop iteration and each waiter converts its own cancellation
        into a clean TimeoutError.
    """
    import asyncio as _asyncio

    from openzim_mcp import http_app as _http_app
    from openzim_mcp.timeout_utils import _get_executor

    _allowed = tempfile.mkdtemp(prefix="openzim_mcp_readyz_queued_")

    class _Cfg:
        allowed_directories = [_allowed]

    class _Server:
        config = _Cfg()

    release = threading.Event()
    readyz = _http_app._make_readyz(_Server())

    # Occupy the dedicated single-worker pool so the probe below can only be
    # QUEUED, never RUNNING — the state in which cancel() succeeds.
    blocker = _get_executor("readyz").submit(release.wait, 30)

    async def _drive():
        with patch.object(_http_app, "READYZ_PROBE_TIMEOUT_SECONDS", 0.5):
            first = _asyncio.create_task(readyz(None))
            # Inside the 0.5s timeout so both share one probe, but well above
            # timer granularity so their deadlines are distinct.
            await _asyncio.sleep(0.1)
            second = _asyncio.create_task(readyz(None))
            return await _asyncio.gather(first, second, return_exceptions=True)

    try:
        results = _asyncio.run(_drive())
    finally:
        release.set()
        blocker.result(timeout=30)

    for r in results:
        assert not isinstance(
            r, BaseException
        ), f"a waiter escaped the handler instead of answering 503: {r!r}"
    assert [r.status_code for r in results] == [503, 503]
