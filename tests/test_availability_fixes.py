"""Regression tests for the availability batch (P3 / P6 / P29).

* P3 — quadratic ReDoS in ``IntentParser._PARAM_LEAK_RE`` (the nominal 1s
  ``safe_regex_sub`` guard cannot interrupt a running ``re`` match).
* P6 — ``/readyz`` probe timeouts leaking default-executor threads, wedging
  every MCP tool call.
* P29 — ``SubscriberRegistry`` never reclaiming per-URI containers.
"""

import gc
import os
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpValidationError

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


# ---------------------------------------------------------------------------
# P29 — SubscriberRegistry container reclamation, URI validation, caps
# ---------------------------------------------------------------------------


class _Session:  # weak-referenceable ServerSession stand-in
    pass


@pytest.mark.asyncio
async def test_prune_reclaims_containers_left_by_a_disconnected_session():
    """The ``WeakSet`` empties itself on GC but the DICT ENTRY survives — and
    nothing ever revisits a URI that is never broadcast.
    """
    from openzim_mcp.subscriptions import SubscriberRegistry

    registry = SubscriberRegistry()
    sess = _Session()
    for i in range(50):
        await registry.subscribe(f"zim://junk{i}", sess)
    assert len(registry._weak_by_uri) == 50

    del sess
    gc.collect()

    # The leak: no live sessions, but every container is still keyed.
    assert await registry.sessions_for("zim://junk0") == []
    assert len(registry._weak_by_uri) == 50

    assert await registry.prune() == 50
    assert registry._weak_by_uri == {}
    assert registry._strong_by_uri == {}


@pytest.mark.asyncio
async def test_prune_keeps_live_subscriptions():
    from openzim_mcp.subscriptions import SubscriberRegistry

    registry = SubscriberRegistry()
    sess = _Session()
    await registry.subscribe("zim://files", sess)
    await registry.prune()
    assert await registry.sessions_for("zim://files") == [sess]


@pytest.mark.asyncio
async def test_watcher_tick_drives_the_registry_sweep(tmp_path):
    """The watcher loop is the only periodic task, so it owns the sweep.
    ``sessions_for`` / ``clear_session`` cannot: they hold the non-reentrant
    registry lock and would deadlock.
    """
    from openzim_mcp.subscriptions import MtimeWatcher, SubscriberRegistry

    registry = SubscriberRegistry()
    sess = _Session()
    await registry.subscribe("zim://junk", sess)
    del sess
    gc.collect()

    async def emit(uri: str, change_type: str) -> None:  # pragma: no cover
        pass

    watcher = MtimeWatcher(
        [str(tmp_path)], interval=0.05, on_change=emit, registry=registry
    )
    await watcher._tick()
    assert registry._weak_by_uri == {}


@pytest.mark.asyncio
async def test_watcher_tick_survives_a_failing_sweep(tmp_path):
    from openzim_mcp.subscriptions import MtimeWatcher

    registry = MagicMock()

    async def boom() -> int:
        raise RuntimeError("nope")

    registry.prune = boom
    events: list[tuple[str, str]] = []

    async def emit(uri: str, change_type: str) -> None:
        events.append((uri, change_type))

    (tmp_path / "a.zim").write_bytes(b"")
    watcher = MtimeWatcher(
        [str(tmp_path)], interval=0.05, on_change=emit, registry=registry
    )
    await watcher._tick()  # must not raise
    assert events == [("zim://files", "list_changed")]


@pytest.mark.parametrize(
    "uri",
    [
        "zim://files",
        "zim://files/",
        "zim://wikipedia_en",
        "zim://wikipedia_en/entry/C%2FClimate_change",
    ],
)
def test_validate_subscription_uri_accepts_served_shapes(uri):
    from openzim_mcp.subscriptions import validate_subscription_uri

    assert validate_subscription_uri(uri) == uri


@pytest.mark.parametrize(
    "uri",
    [
        "",
        "zim://",
        "zim://name/other",
        "zim://name/entry",
        "http://evil.example/x",
        "file:///etc/passwd",
        "zim://name with space",
    ],
)
def test_validate_subscription_uri_rejects_everything_else(uri):
    from openzim_mcp.subscriptions import validate_subscription_uri

    with pytest.raises(OpenZimMcpValidationError):
        validate_subscription_uri(uri)


def test_validate_subscription_uri_rejects_oversized():
    from openzim_mcp.subscriptions import MAX_URI_LENGTH, validate_subscription_uri

    with pytest.raises(OpenZimMcpValidationError):
        validate_subscription_uri("zim://" + "a" * MAX_URI_LENGTH)


@pytest.mark.asyncio
async def test_subscribe_handler_validates_uri():
    """The handler seam is the gate: the SDK forwards ``req.params.uri``
    verbatim and ``resources/subscribe`` bypasses the rate limiter.
    """
    import mcp.types as t
    from mcp.server.fastmcp import FastMCP
    from mcp.server.lowlevel.server import request_ctx

    from openzim_mcp.subscriptions import (
        SubscriberRegistry,
        register_subscription_handlers,
    )

    mcp_server = FastMCP("test")
    registry = SubscriberRegistry()
    register_subscription_handlers(mcp_server, registry)
    handler = mcp_server._mcp_server.request_handlers[t.SubscribeRequest]

    ctx = MagicMock()
    ctx.session = _Session()
    token = request_ctx.set(ctx)
    try:
        with pytest.raises(OpenZimMcpValidationError):
            await handler(
                t.SubscribeRequest(
                    method="resources/subscribe",
                    params=t.SubscribeRequestParams(uri="http://evil.example/x"),
                )
            )
        assert registry._weak_by_uri == {}

        await handler(
            t.SubscribeRequest(
                method="resources/subscribe",
                params=t.SubscribeRequestParams(uri="zim://files"),
            )
        )
        assert await registry.sessions_for("zim://files") == [ctx.session]
    finally:
        request_ctx.reset(token)


@pytest.mark.asyncio
async def test_total_distinct_uri_cap_enforced(monkeypatch):
    from openzim_mcp import subscriptions

    monkeypatch.setattr(subscriptions, "MAX_URIS_TOTAL", 3)
    registry = subscriptions.SubscriberRegistry()
    sess = _Session()
    for i in range(3):
        await registry.subscribe(f"zim://n{i}", sess)
    with pytest.raises(OpenZimMcpValidationError):
        await registry.subscribe("zim://n3", sess)
    # An already-known URI is still accepted (no new key is minted).
    await registry.subscribe("zim://n0", _Session())


@pytest.mark.asyncio
async def test_per_session_distinct_uri_cap_enforced(monkeypatch):
    from openzim_mcp import subscriptions

    monkeypatch.setattr(subscriptions, "MAX_URIS_PER_SESSION", 2)
    registry = subscriptions.SubscriberRegistry()
    greedy = _Session()
    for i in range(2):
        await registry.subscribe(f"zim://n{i}", greedy)
    with pytest.raises(OpenZimMcpValidationError):
        await registry.subscribe("zim://n2", greedy)
    # A different session is unaffected by the greedy one's budget.
    await registry.subscribe("zim://n2", _Session())


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
