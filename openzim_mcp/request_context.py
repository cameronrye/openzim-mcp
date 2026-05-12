"""Per-request context for tool dispatch.

The rate limiter's per-(client_id, operation) bucket isolation only
matters if tools call ``check_rate_limit`` with a stable per-connection
identifier. Stdio transport has exactly one client (the parent process),
so ``"default"`` is correct. HTTP transport routinely serves multiple
clients concurrently; without per-client isolation, one aggressive
caller exhausts the shared bucket for everyone else.

This module exposes a ``ContextVar`` set by the HTTP middleware on each
request and read by tool call sites that hand off to ``check_rate_limit``.
ContextVar values propagate cleanly across ``await`` boundaries within
the same asyncio task — the standard ASGI middleware pattern — so a
value set in the middleware is visible inside every tool handler
dispatched for that request.

When unset (stdio mode, library use, tests), the var reads ``"default"``
so the existing single-bucket behavior is preserved.
"""

from __future__ import annotations

import contextvars

_DEFAULT_CLIENT_ID = "default"

# Per-task client identifier. HTTP middleware sets this from the
# Bearer-token hash or the remote address; tools read it via
# ``current_client_id`` and pass it to ``check_rate_limit``.
client_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "openzim_mcp_client_id", default=_DEFAULT_CLIENT_ID
)


def current_client_id() -> str:
    """Return the request-scoped client identifier.

    Falls back to ``"default"`` when no value has been set (stdio mode,
    direct library use, unit tests).
    """
    return client_id_var.get()


def set_client_id(client_id: str) -> contextvars.Token[str]:
    """Set the request-scoped client identifier.

    Returns a ``Token`` the caller can pass to ``client_id_var.reset()``
    to restore the previous value. Most callers should not need to
    reset manually — when the request's asyncio task ends, the var
    naturally falls out of scope.
    """
    return client_id_var.set(client_id)
