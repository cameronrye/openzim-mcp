"""Mechanics of the SDK ping keepalive shim, and the SDK stance it pins.

The shim works around a deliberate spec decision, not an upstream defect:
2026-07-28 drops ping (``PingRequest`` is absent from that revision's schema),
SDK 2.0.0's per-version method tables lack ``("ping", "2026-07-28")`` to
match, and python-sdk#3273 was closed not-planned on 2026-08-20 as intended
behaviour. Left alone, every modern-negotiated connection would have its
keepalive rejected with -32601; this server answers it regardless, for clients
that ping on a timer. The wire tests proving that work live in
``test_mcp_session.py``; this file pins how the shim installs and — via the
canary — that upstream's stance has not moved. Whether to keep the deviation
or drop ping on modern connections was settled in issue #371 (2026-08-24):
keep, permanently, because dropping it regresses keepalive-pinging clients
and saves nothing.
"""

from mcp_types.methods import CLIENT_REQUESTS, SERVER_RESULTS

from openzim_mcp import sdk_compat
from openzim_mcp.sdk_compat import MODERN_PING_ROW


def test_canary_upstream_still_lacks_modern_ping() -> None:
    """Fails if the locked SDK ever defines modern ping — a reversal, not a fix.

    Membership is captured at ``sdk_compat`` import time, which necessarily
    precedes any install call, so it observes the SDK as shipped rather than
    our own patch. 2026-07-28 omits ping on purpose, so this is expected to
    hold for as long as the pin does; a failure means upstream reversed that
    stance, which retires the shim rather than reopening the keep-or-drop call
    issue #371 settled: ``install_ping_keepalive_shim`` no-ops against an SDK
    that defines the rows itself, so the install simply becomes dead code.
    Either way the wire tests in ``test_mcp_session.py`` assert the behavior
    clients see.
    """
    assert sdk_compat.UPSTREAM_DEFINES_MODERN_PING is False


def test_install_fills_both_tables() -> None:
    """The gate (requests) and the sieve (results) both need the row.

    Filling only ``CLIENT_REQUESTS`` is the tempting half-fix: the request
    passes the version gate, the handler runs, and then ``_serialize`` raises
    ``KeyError`` out of ``SERVER_RESULTS`` — an unhandled server fault instead
    of a clean -32601, which is strictly worse than not installing at all.
    """
    sdk_compat.install_ping_keepalive_shim()

    assert MODERN_PING_ROW in CLIENT_REQUESTS
    assert MODERN_PING_ROW in SERVER_RESULTS


def test_install_is_idempotent() -> None:
    """A second install is a no-op — every ``OpenZimMcpServer`` constructed in
    a process installs, and tests construct hundreds."""
    sdk_compat.install_ping_keepalive_shim()

    assert sdk_compat.install_ping_keepalive_shim() is False


def test_shim_reuses_the_previous_revision_frame_models() -> None:
    """The modern rows are copies of the 2025-11-25 rows, not new models.

    2026-07-28 defines no ping at all, so there is no modern frame model to
    reach for. Copying the newest revision that has one keeps the shim free of
    ``mcp_types._v*`` internals and guarantees the modern path validates
    exactly what the legacy path already accepts.
    """
    sdk_compat.install_ping_keepalive_shim()

    previous = ("ping", "2025-11-25")
    assert CLIENT_REQUESTS[MODERN_PING_ROW] is CLIENT_REQUESTS[previous]
    assert SERVER_RESULTS[MODERN_PING_ROW] is SERVER_RESULTS[previous]
