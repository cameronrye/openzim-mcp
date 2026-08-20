"""Process-global patches for defects in the pinned MCP SDK.

One resident: the ping keepalive shim for
https://github.com/modelcontextprotocol/python-sdk/issues/3273. SDK 2.0.0's
per-version method tables lack ``("ping", "2026-07-28")``, in both directions
that matter to a server: ``CLIENT_REQUESTS`` (the runner's version gate, so
the request dies as -32601 before the SDK's own ping handler is consulted)
and ``SERVER_RESULTS`` (the outbound sieve, so fixing only the gate would
turn the miss into an unhandled ``KeyError`` mid-response). A modern client
that pings on a keepalive timer — FastMCP 4 does — sees an error per ping
and flaps the connection.

The tables are ``MappingProxyType`` views over module-private dicts, and the
SDK binds them as call-time *defaults*, so neither rebinding the module
attribute nor passing ``surface=`` from our layer can reach the runner's
calls. The one seam that reaches every consumer is the dict under the proxy:
a proxy is a live view, so inserting the missing rows there is exactly the
edit upstream's fix will make to the literal. ``gc.get_referents`` is how
CPython hands out that dict; it is deliberate surgery on SDK internals,
confined to this module and covered by ``tests/test_sdk_ping_shim.py``.

Retirement: the canary test fails the day the locked SDK ships the rows
itself. Delete this module, its install call in ``server.py``, and the
canary file; the wire tests in ``test_mcp_session.py`` stay.
"""

import gc
import logging
from collections.abc import Mapping
from typing import Any, cast

from mcp_types.methods import CLIENT_REQUESTS, SERVER_RESULTS

logger = logging.getLogger(__name__)

MODERN_PING_ROW = ("ping", "2026-07-28")

# The newest revision whose ping rows upstream does define. Ping's wire shape
# did not change in 2026 — the gap is a missing table entry, not a missing
# schema — so the modern rows are copies of these, which also keeps this
# module off the ``mcp_types._v*`` internal packages.
_PREVIOUS_PING_ROW = ("ping", "2025-11-25")

# Captured before ``install_ping_keepalive_shim`` can have run: the module
# body executes on first import and the only caller lives below it. The
# canary test asserts this is still False; when it flips, the SDK has fixed
# python-sdk#3273 and this module must be deleted.
UPSTREAM_DEFINES_MODERN_PING = (
    MODERN_PING_ROW in CLIENT_REQUESTS and MODERN_PING_ROW in SERVER_RESULTS
)


def _underlying_dict(proxy: Mapping[Any, Any]) -> dict[Any, Any]:
    """The mutable dict a ``MappingProxyType`` is a view of."""
    return cast(dict[Any, Any], gc.get_referents(proxy)[0])


def install_ping_keepalive_shim() -> bool:
    """Add ping's 2026-07-28 rows to the SDK's method tables.

    Idempotent, and a no-op against an SDK that defines the rows itself.
    Returns True when anything was added, so a caller (or test) can tell a
    real install from a redundant one.
    """
    added = False
    for table in (CLIENT_REQUESTS, SERVER_RESULTS):
        rows = _underlying_dict(table)
        if MODERN_PING_ROW not in rows:
            rows[MODERN_PING_ROW] = rows[_PREVIOUS_PING_ROW]
            added = True
    if added:
        logger.debug(
            "Installed ping keepalive shim for python-sdk#3273; "
            "modern connections can now be kept alive"
        )
    return added
