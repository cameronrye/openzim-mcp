"""Mechanics and retirement condition of the SDK ping keepalive shim.

The shim exists because of a concrete upstream defect
(https://github.com/modelcontextprotocol/python-sdk/issues/3273): SDK 2.0.0's
per-version method tables lack ``("ping", "2026-07-28")``, so every
modern-negotiated connection has its keepalive rejected with -32601. The wire
tests proving the fix works live in ``test_mcp_session.py``; this file pins
how the shim installs and — via the canary — when it must be deleted.
"""

from mcp_types.methods import CLIENT_REQUESTS, SERVER_RESULTS

from openzim_mcp import sdk_compat
from openzim_mcp.sdk_compat import MODERN_PING_ROW


def test_canary_upstream_still_lacks_modern_ping() -> None:
    """Fails the day the locked SDK defines modern ping: delete the shim then.

    Membership is captured at ``sdk_compat`` import time, which necessarily
    precedes any install call, so it observes the SDK as shipped rather than
    our own patch. When this fails: remove ``sdk_compat.py``, its install
    call in ``server.py``, and this file. Keep the wire tests in
    ``test_mcp_session.py`` — they assert the behavior either way.
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

    Ping's wire shape did not change between revisions — the upstream gap is
    a missing table entry, not a missing schema. Copying the newest pre-2026
    row keeps the shim free of ``mcp_types._v*`` internals and guarantees the
    modern path validates exactly what the legacy path already accepts.
    """
    sdk_compat.install_ping_keepalive_shim()

    previous = ("ping", "2025-11-25")
    assert CLIENT_REQUESTS[MODERN_PING_ROW] is CLIENT_REQUESTS[previous]
    assert SERVER_RESULTS[MODERN_PING_ROW] is SERVER_RESULTS[previous]
