"""Shared helpers for the thin Phase F tool wrappers."""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from ..responses import ToolErrorPayload, tool_error

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
) -> str:
    """Log + build the standard enhanced error payload for a broad ``except``.

    Mirrors the b13 envelope every wrapper repeats. The log is emitted under
    ``openzim_mcp.tools.<operation>`` so each tool's records keep the same
    logger name they had when every wrapper logged via its own module-level
    ``getLogger(__name__)`` (operation is the module basename, e.g.
    ``zim_links`` → ``...tools.zim_links``).
    """
    import logging

    logging.getLogger(f"openzim_mcp.tools.{operation}").error(
        "Error in %s: %s", operation, error
    )
    return server._create_enhanced_error_message(
        operation=operation, error=error, context=context or ""
    )


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
