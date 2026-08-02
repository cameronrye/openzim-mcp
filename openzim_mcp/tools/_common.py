"""Shared helpers for the thin Phase F tool wrappers."""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from ..responses import ToolErrorPayload, tool_error
from ..security import sanitize_context_for_error

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

_DESCRIPTIONS_DIR = pathlib.Path(__file__).parent


def load_description(name: str) -> str:
    """Read the ``<name>_description.md`` markdown next to the tool modules.

    Centralizes the ``(_DIR / "...md").read_text(encoding="utf-8")`` line
    each wrapper repeated.
    """
    return (_DESCRIPTIONS_DIR / f"{name}_description.md").read_text(encoding="utf-8")


def tool_error_response(
    server: "OpenZimMcpServer",
    *,
    operation: str,
    error: Exception,
    context: Optional[str] = None,
) -> ToolErrorPayload:
    """Log + build the standard structured error envelope for a broad ``except``.

    The log is emitted under ``openzim_mcp.tools.<operation>`` so each tool's
    records keep the same logger name they had when every wrapper logged via
    its own module-level ``getLogger(__name__)`` (operation is the module
    basename, e.g. ``zim_links`` → ``...tools.zim_links``).

    L6: returns a ``ToolErrorPayload`` (``{error: True, operation, message}``)
    rather than a bare markdown string, so a data-layer failure shares the SAME
    envelope shape as the parameter/combination errors the wrappers already
    return via ``tool_error``. ``responses.py`` and the tool descriptions
    promise "every tool emits a recognisable envelope on failure"; before this
    a client branching on ``error: true`` silently missed broad-except
    failures. The enhanced markdown is preserved in the ``message`` field.
    """
    import logging

    logging.getLogger(f"openzim_mcp.tools.{operation}").error(
        "Error in %s: %s", operation, error
    )
    enhanced = server._create_enhanced_error_message(
        operation=operation, error=error, context=context or ""
    )
    # Redact absolute paths from the standalone ``context`` field too, so the
    # envelope's ``message`` and ``context`` are consistently sanitized — the
    # ``message`` is already redacted via ``_create_enhanced_error_message``;
    # without this the raw path (e.g. ``Path: /home/.../foo.zim``) leaked here.
    # Null-safe: keep ``None`` as-is so ``tool_error`` still omits the field.
    safe_context = sanitize_context_for_error(context) if context is not None else None
    return tool_error(operation=operation, message=enhanced, context=safe_context)


def _clamp_cost_to_capacity(
    server: "OpenZimMcpServer", operation: str, cost: int
) -> int:
    """Clamp a variable ``cost`` to the smallest relevant bucket capacity.

    ``TokenBucket.acquire`` denies unconditionally when ``cost`` exceeds the
    bucket's capacity — no amount of waiting refills past ``burst_size``. A
    batch cost derived from caller input (``len(entry_paths)``, up to
    ``MAX_BATCH_SIZE`` = 50) therefore exceeds the default ``burst_size`` of
    20 and would make a documented, supported batch size permanently
    impossible rather than merely expensive. Clamping keeps the batch
    "drains the bucket" instead of "can never succeed".
    """
    try:
        limiter_config = server.rate_limiter.config
        capacity = int(limiter_config.burst_size)
        op_config = limiter_config.per_operation_limits.get(operation)
        if op_config is not None:
            capacity = min(capacity, int(op_config.burst_size))
    except Exception:  # pragma: no cover - defensive (mocked limiters in tests)
        return cost
    if capacity <= 0:
        return cost
    return max(1, min(cost, capacity))


def enforce_rate_limit(
    server: "OpenZimMcpServer",
    operation: str,
    *,
    cost: Optional[int] = None,
) -> Optional[ToolErrorPayload]:
    """Apply the configured rate limit for ``operation`` to the current client.

    Returns ``None`` when the call is allowed, or a structured
    ``ToolErrorPayload`` the wrapper should return directly when the limit is
    exceeded. Buckets are keyed on ``(client_id, operation)``; the client id is
    read from ``request_context`` (set per-request by the HTTP auth middleware),
    so concurrent HTTP callers are isolated while stdio shares the ``"default"``
    bucket. A no-op when ``rate_limit.enabled`` is False.

    ``operation`` must be an INTERNAL operation name (``search``,
    ``get_binary_entry``, ...), not the wire-level v2 tool name. The v2 tools
    are multiplexers, so each wrapper resolves the name for the branch it is
    about to dispatch: passing ``"zim_get"`` matched nothing in
    ``RATE_LIMIT_COSTS`` and silently priced every call at the ``default``
    cost of 1, and made every documented ``per_operation_limits`` override
    inert because the bucket was keyed on a name no operator writes.

    ``cost`` overrides the table lookup for calls whose weight is not fixed —
    a batch ``zim_get(entry_paths=[...])`` debits one token per requested
    entry rather than one for the whole batch.

    This is the enforcement seam the limiter was missing — it was constructed in
    ``OpenZimMcpServer.__init__`` but never called, so configured
    ``OPENZIM_MCP_RATE_LIMIT__*`` limits were silently inert.
    """
    from ..exceptions import OpenZimMcpRateLimitError

    if cost is not None:
        cost = _clamp_cost_to_capacity(server, operation, cost)
    try:
        server.rate_limiter.check_rate_limit(operation=operation, cost=cost)
    except OpenZimMcpRateLimitError as exc:
        return tool_error(
            operation="rate_limited",
            message=str(exc),
            context=str(getattr(exc, "details", "") or "") or None,
        )
    return None


def decode_cursor_state(
    cursor: Optional[str], *, expected_tool: str
) -> Tuple[Optional[Dict[str, Any]], Optional[ToolErrorPayload]]:
    """Decode an advanced-tool pagination cursor into its state dict.

    Returns ``(state, None)`` on success — ``state`` is the cursor's decoded
    ``s`` payload, or ``None`` when ``cursor`` is empty/absent (a fresh,
    unpaginated call). Returns ``(None, error)`` when the cursor is malformed,
    carries an unsupported version, or was issued by a different tool. Callers
    project the returned state into their data-layer call: ``s['o']`` is the
    resume offset (browse page / links), ``s['scan_at']`` the walk resume id,
    and ``s['ai']`` the archive identity to verify against.
    """
    if cursor is None or not str(cursor).strip():
        return None, None
    from ..pagination import Cursor, CursorMismatchError

    try:
        payload = Cursor.decode(str(cursor).strip(), expected_tool=expected_tool)
    except CursorMismatchError as exc:
        return None, tool_error(
            operation="cursor_mismatch",
            message=(
                f"{exc}. Drop the `cursor` and call again with an explicit "
                "`offset` (or no pagination arg)."
            ),
            context=f"expected_tool={expected_tool}",
        )
    except ValueError as exc:
        return None, tool_error(
            operation="cursor_decode",
            message=(
                "The `cursor` value could not be decoded. Drop the `cursor` "
                "and call again with an explicit `offset` (or no pagination "
                "arg)."
            ),
            context=str(exc),
        )
    return dict(payload["s"]), None


def cursor_context_mismatch(
    state: Dict[str, Any], *, field: str, expected: str, label: str
) -> Optional[ToolErrorPayload]:
    """Reject a cursor whose ``field`` names a context this call doesn't target.

    Guards ``ns`` / ``ep``: a replayed cursor must not silently apply one
    resume position to the wrong namespace or article. Returns ``None`` when
    the cursor omits the field or it matches the call.
    """
    value = state.get(field)
    if isinstance(value, str) and value and value != expected:
        return tool_error(
            operation="cursor_context_mismatch",
            message=(
                f"Cursor was issued for {label} {value!r}; this call targets "
                f"{expected!r}. Drop the `cursor` and start over for the new "
                f"{label}."
            ),
            context=f"{field}={value!r}",
        )
    return None
