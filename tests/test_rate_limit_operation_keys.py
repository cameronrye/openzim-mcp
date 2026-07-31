"""Every operation key a live v2 tool passes to the limiter must be priced.

Regression for the "rate-limit cost table keyed on deleted legacy names" bug:
all 8 Phase F wrappers passed their WIRE tool name (``zim_get``, ``zim_search``,
...) while ``RATE_LIMIT_COSTS`` held only pre-Phase-F INTERNAL names. The
intersection was empty, so every operation silently resolved to
``default: 1`` — a 10MB binary fetch and a 50-article batch were priced the
same as a one-line entry read, and every documented ``per_operation_limits``
override was inert because the bucket was keyed on a name no operator writes.

These tests drive the real wrappers and capture what the limiter actually
receives, so a future branch that forgets to resolve its key fails here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.async_operations import AsyncZimOperations
from openzim_mcp.defaults import RATE_LIMIT_COSTS


@pytest.fixture
def spy_server() -> MagicMock:
    """A server whose ``mcp.tool`` collects functions and whose limiter records
    every ``check_rate_limit`` call instead of enforcing anything."""
    srv = MagicMock()
    tools_store: Dict[str, Any] = {}
    calls: List[Tuple[str, Any]] = []

    def _tool(*, description: str = ""):
        def decorate(fn: Any) -> Any:
            tools_store[fn.__name__] = fn
            return fn

        return decorate

    def _check(operation: str = "default", cost: Any = None, **_kw: Any) -> None:
        calls.append((operation, cost))

    srv.mcp.tool = _tool
    srv._tools_store = tools_store
    srv._rl_calls = calls
    srv.rate_limiter.check_rate_limit = _check
    # ``enforce_rate_limit`` clamps a caller-derived cost to the bucket
    # capacity; give the mock a realistic default burst.
    srv.rate_limiter.config.burst_size = 20
    srv.rate_limiter.config.per_operation_limits = {}
    return srv


def _patch_async_ops(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace the async data layer with a mock whose every method is awaitable."""
    mock_ops = MagicMock()
    mock_ops.configure_mock(
        **{
            name: AsyncMock(return_value={})
            for name in dir(AsyncZimOperations)
            if not name.startswith("_")
        }
    )
    monkeypatch.setattr(
        "openzim_mcp.async_operations.AsyncZimOperations",
        lambda _zim_ops: mock_ops,
    )
    return mock_ops


# Each entry: (register fn import path, tool name, kwargs, expected operation).
_BRANCHES = [
    ("zim_search", dict(query="a b c d"), "search"),
    ("zim_search", dict(query="a", mode="title"), "find_entry_by_title"),
    ("zim_search", dict(query="a", mode="suggest"), "suggestions"),
    ("zim_search", dict(query="a", namespace="C"), "search_with_filters"),
    ("zim_get", dict(zim_file_path="/x.zim", entry_path="A/Cat"), "get_entry"),
    (
        "zim_get",
        dict(zim_file_path="/x.zim", entry_path="A/Cat", view="summary"),
        "get_structure",
    ),
    (
        "zim_get",
        dict(zim_file_path="/x.zim", entry_path="A/Cat", binary=True),
        "get_binary_entry",
    ),
    (
        "zim_get",
        dict(zim_file_path="/x.zim", entry_paths=["A/Cat", "A/Dog"]),
        "get_zim_entries",
    ),
    (
        "zim_links",
        dict(zim_file_path="/x.zim", entry_path="A/Cat"),
        "extract_article_links",
    ),
    (
        "zim_links",
        dict(zim_file_path="/x.zim", entry_path="A/Cat", direction="inbound"),
        "get_inbound_links",
    ),
    (
        "zim_links",
        dict(zim_file_path="/x.zim", entry_path="A/Cat", direction="related"),
        "get_related_articles",
    ),
    ("zim_browse", dict(zim_file_path="/x.zim", namespace="C"), "browse_namespace"),
    ("zim_metadata", dict(zim_file_path="/x.zim"), "get_metadata"),
]

# The three v2-only surfaces with no internal equivalent. They are documented
# as charging the ``default`` cost, and their buckets are keyed on the tool
# name so ``per_operation_limits`` overrides still reach them.
_DEFAULT_COST_TOOLS = [
    (
        "zim_get_section",
        dict(zim_file_path="/x.zim", entry_path="A/Cat", section_id="s1"),
    ),
    ("zim_health", dict()),
    ("zim_query", dict(query="tell me about cats")),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name,kwargs,expected_operation", _BRANCHES)
async def test_branch_passes_a_priced_operation_key(
    spy_server: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    kwargs: Dict[str, Any],
    expected_operation: str,
) -> None:
    import importlib

    _patch_async_ops(monkeypatch)
    module = importlib.import_module(f"openzim_mcp.tools.{module_name}")
    module.register(spy_server)
    fn = spy_server._tools_store[module_name]

    try:
        await fn(**kwargs)
    except Exception:
        # The dispatch target is a bare MagicMock; only the limiter call
        # (which happens first) is under test here.
        pass

    assert spy_server._rl_calls, f"{module_name} never called the rate limiter"
    operation, _cost = spy_server._rl_calls[0]
    assert operation == expected_operation
    assert operation in RATE_LIMIT_COSTS, (
        f"{module_name} passes operation={operation!r}, which is absent from "
        f"RATE_LIMIT_COSTS and therefore silently priced at the default cost "
        f"and unreachable from `per_operation_limits`."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name,kwargs", _DEFAULT_COST_TOOLS)
async def test_v2_only_surfaces_charge_the_default_cost(
    spy_server: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    kwargs: Dict[str, Any],
) -> None:
    import importlib

    _patch_async_ops(monkeypatch)
    module = importlib.import_module(f"openzim_mcp.tools.{module_name}")
    module.register(spy_server)
    fn = spy_server._tools_store[module_name]
    try:
        await fn(**kwargs)
    except Exception:
        pass

    operation, cost = spy_server._rl_calls[0]
    assert operation == module_name
    assert cost is None  # resolved by the limiter
    assert operation not in RATE_LIMIT_COSTS
    assert (
        RATE_LIMIT_COSTS.get(operation, RATE_LIMIT_COSTS["default"])
        == RATE_LIMIT_COSTS["default"]
    )


def _total_debited(spy_server: MagicMock) -> int:
    """Sum every token actually charged, resolving ``None`` via the table.

    ``zim_get`` splits the batch debit in two — a flat table cost before
    validation (so a malformed call is never free) plus the batch remainder
    once the request is known dispatchable — so the price of a call is the
    sum of its debits, not the first one.
    """
    total = 0
    for operation, cost in spy_server._rl_calls:
        total += (
            RATE_LIMIT_COSTS.get(operation, RATE_LIMIT_COSTS["default"])
            if cost is None
            else int(cost)
        )
    return total


@pytest.mark.asyncio
async def test_batch_get_debits_one_token_per_entry(
    spy_server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``zim_get(entry_paths=[...])`` is N reads and must cost N tokens."""
    from openzim_mcp.tools.zim_get import register as register_zim_get

    _patch_async_ops(monkeypatch)
    register_zim_get(spy_server)
    fn = spy_server._tools_store["zim_get"]
    try:
        await fn(zim_file_path="/x.zim", entry_paths=[f"A/{i}" for i in range(5)])
    except Exception:
        pass

    operation, _cost = spy_server._rl_calls[0]
    assert operation == "get_zim_entries"
    assert all(op == "get_zim_entries" for op, _c in spy_server._rl_calls)
    assert _total_debited(spy_server) == 5 * RATE_LIMIT_COSTS["get_zim_entries"]


@pytest.mark.asyncio
async def test_batch_cost_is_clamped_to_the_bucket_capacity(
    spy_server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``TokenBucket.acquire`` denies unconditionally when cost exceeds
    capacity — no wait refills past ``burst_size``. A max-size batch (50)
    must therefore drain the default 20-token bucket, not become impossible.
    """
    from openzim_mcp.tools.zim_get import register as register_zim_get

    _patch_async_ops(monkeypatch)
    register_zim_get(spy_server)
    fn = spy_server._tools_store["zim_get"]
    try:
        await fn(zim_file_path="/x.zim", entry_paths=[f"A/{i}" for i in range(50)])
    except Exception:
        pass

    # Exactly one bucket's worth in total — never more, or the second debit
    # could never be satisfied and the legal max batch would be impossible.
    assert _total_debited(spy_server) == 20


@pytest.mark.asyncio
async def test_oversize_batch_is_priced_at_the_batch_limit_not_caller_input(
    spy_server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``len(entry_paths)`` is unvalidated caller input; the data layer refuses
    anything above ``MAX_BATCH_SIZE``, so pricing must not scale past it."""
    from openzim_mcp.constants import MAX_BATCH_SIZE
    from openzim_mcp.tools.zim_get import register as register_zim_get

    _patch_async_ops(monkeypatch)
    spy_server.rate_limiter.config.burst_size = 10_000
    register_zim_get(spy_server)
    fn = spy_server._tools_store["zim_get"]
    try:
        await fn(zim_file_path="/x.zim", entry_paths=[f"A/{i}" for i in range(5000)])
    except Exception:
        pass

    assert (
        _total_debited(spy_server)
        == MAX_BATCH_SIZE * RATE_LIMIT_COSTS["get_zim_entries"]
    )


@pytest.fixture
def live_limiter_server(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """A server carrying a REAL ``RateLimiter`` at shipped defaults.

    The spy fixture records costs; this one actually debits tokens, which is
    the only way to observe what a rejected call leaves behind.
    """
    from openzim_mcp.rate_limiter import RateLimitConfig, RateLimiter

    srv = MagicMock()
    tools_store: Dict[str, Any] = {}

    def _tool(*, description: str = ""):
        def decorate(fn: Any) -> Any:
            tools_store[fn.__name__] = fn
            return fn

        return decorate

    srv.mcp.tool = _tool
    srv._tools_store = tools_store
    srv.rate_limiter = RateLimiter(RateLimitConfig())
    _patch_async_ops(monkeypatch)
    from openzim_mcp.tools.zim_get import register as register_zim_get

    register_zim_get(srv)
    return srv


def _global_tokens(server: MagicMock) -> float:
    return float(server.rate_limiter.get_status()["global_tokens_available"])


@pytest.mark.asyncio
async def test_rejected_batch_does_not_drain_the_bucket(
    live_limiter_server: MagicMock,
) -> None:
    """A request that dispatches nothing must not cost full bucket capacity.

    Charging ``len(entry_paths)`` tokens up front, before
    ``_validate_branch_combination``, meant one malformed call (mutually
    exclusive ``entry_path`` + ``entry_paths``) emptied the whole 20-token
    bucket while doing zero work, so the caller's next legitimate single-entry
    get came back ``rate_limited``. The flat table cost is still charged —
    garbage must not be free — but not the batch price.
    """
    fn = live_limiter_server._tools_store["zim_get"]
    before = _global_tokens(live_limiter_server)

    rejected = await fn(
        zim_file_path="/x.zim",
        entry_path="A/Cat",
        entry_paths=[f"A/{i}" for i in range(60)],
    )
    assert rejected["operation"] == "invalid_path_combination"

    consumed = before - _global_tokens(live_limiter_server)
    # abs tolerance absorbs the bucket's continuous refill; it is far below
    # one token, so the pre-fix 20-token drain still fails this.
    assert consumed == pytest.approx(RATE_LIMIT_COSTS["get_zim_entries"], abs=0.5)
    assert _global_tokens(live_limiter_server) > 1

    # ... and the next well-formed call still goes through.
    allowed = await fn(zim_file_path="/x.zim", entry_path="A/Cat")
    assert allowed.get("operation") != "rate_limited"


@pytest.mark.asyncio
async def test_rejected_batch_view_and_offset_envelopes_are_cheap(
    live_limiter_server: MagicMock,
) -> None:
    """Every early-return envelope on the batch branch costs the flat price."""
    fn = live_limiter_server._tools_store["zim_get"]
    paths = [f"A/{i}" for i in range(60)]

    for kwargs, expected_operation in (
        (dict(entry_paths=paths, view="summary"), "invalid_path_combination"),
        (dict(entry_paths=paths, content_offset=10), "invalid_path_combination"),
        (dict(entry_paths=paths, content_offset=-1), "invalid_content_offset"),
        (dict(entry_paths=paths, max_content_length=0), "invalid_max_content_length"),
    ):
        live_limiter_server.rate_limiter.reset()
        before = _global_tokens(live_limiter_server)
        resp = await fn(zim_file_path="/x.zim", **kwargs)
        assert resp["operation"] == expected_operation, kwargs
        assert before - _global_tokens(live_limiter_server) == pytest.approx(
            RATE_LIMIT_COSTS["get_zim_entries"], abs=0.5
        ), kwargs


@pytest.mark.asyncio
async def test_dispatchable_batch_still_pays_the_full_per_entry_price(
    live_limiter_server: MagicMock,
) -> None:
    """The P28 pricing itself must survive: a real batch is still N reads."""
    fn = live_limiter_server._tools_store["zim_get"]
    before = _global_tokens(live_limiter_server)

    resp = await fn(zim_file_path="/x.zim", entry_paths=[f"A/{i}" for i in range(5)])

    assert resp.get("operation") != "rate_limited"
    assert before - _global_tokens(live_limiter_server) == pytest.approx(
        5 * RATE_LIMIT_COSTS["get_zim_entries"], abs=0.5
    )


@pytest.mark.asyncio
async def test_max_size_batch_is_expensive_but_never_impossible(
    live_limiter_server: MagicMock,
) -> None:
    """The split debit must not push the total past ``burst_size`` — a legal
    50-entry batch has to succeed on a full bucket, not be denied forever."""
    fn = live_limiter_server._tools_store["zim_get"]
    capacity = float(live_limiter_server.rate_limiter.config.burst_size)

    resp = await fn(zim_file_path="/x.zim", entry_paths=[f"A/{i}" for i in range(50)])

    assert resp.get("operation") != "rate_limited"
    assert capacity == 40.0
    assert _global_tokens(live_limiter_server) < 0.5
