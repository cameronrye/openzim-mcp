"""zim_browse — paginated browse or full walk of a ZIM namespace.

Collapses ``browse_namespace`` + ``walk_namespace`` (2 → 1) via a
``mode: Literal["page", "walk"]`` dispatch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Optional

from ..responses import tool_error
from ._common import (
    cursor_context_mismatch,
    decode_cursor_state,
    load_description,
    tool_error_response,
)

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

_DESCRIPTION = load_description("zim_browse")

_VALID_MODES = {"page", "walk"}


def register(server: "OpenZimMcpServer") -> None:
    """Register the `zim_browse` tool with the MCP server."""
    from ..async_operations import AsyncZimOperations

    ops = AsyncZimOperations(server.zim_operations)

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_browse(
        zim_file_path: str,
        namespace: str,
        mode: Literal["page", "walk"] = "page",
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Any:
        try:
            if mode not in _VALID_MODES:
                return tool_error(
                    operation="invalid_mode",
                    message=(
                        f"`mode` must be one of {sorted(_VALID_MODES)} "
                        f"(provided: {mode!r})."
                    ),
                )

            # A cursor is bound to the issuing tool (browse vs walk) so a
            # replayed handle can't apply one mode's resume position to the
            # other; the namespace check then blocks a C-cursor resuming an M
            # browse (the P3-D7 live defect the simple-mode router already
            # guards against).
            expected_tool = "browse_namespace" if mode == "page" else "walk_namespace"
            state, cursor_error = decode_cursor_state(
                cursor, expected_tool=expected_tool
            )
            if cursor_error is not None:
                return cursor_error
            if state is not None:
                ns_error = cursor_context_mismatch(
                    state, field="ns", expected=namespace, label="namespace"
                )
                if ns_error is not None:
                    return ns_error

            if mode == "page":
                eff_limit = limit if limit is not None else 50
                if state is not None:
                    return await ops.browse_namespace_data(
                        zim_file_path,
                        namespace=namespace,
                        limit=eff_limit,
                        offset=int(state.get("o", 0) or 0),
                        cursor_archive_identity=state.get("ai"),
                    )
                return await ops.browse_namespace_data(
                    zim_file_path,
                    namespace=namespace,
                    limit=eff_limit,
                    offset=offset,
                )

            # mode == "walk" — v2 walk takes the decoded cursor-state dict
            # directly (``scan_at`` resume id + limit), so callers never have
            # to round-trip through base64 themselves.
            eff_limit = limit if limit is not None else 200
            if state is not None:
                cursor_state: dict[str, Any] = {
                    "scan_at": int(state.get("scan_at", 0) or 0),
                    "l": eff_limit,
                }
                ai = state.get("ai")
                if isinstance(ai, str) and ai:
                    cursor_state["ai"] = ai
                ns = state.get("ns")
                if isinstance(ns, str) and ns:
                    cursor_state["ns"] = ns
                return await ops.walk_namespace_data(
                    zim_file_path,
                    namespace,
                    cursor_state=cursor_state,
                    limit=eff_limit,
                )
            return await ops.walk_namespace_data(
                zim_file_path,
                namespace,
                limit=eff_limit,
            )
        except Exception as e:  # noqa: BLE001 — broad catch matches b13 envelope
            return tool_error_response(
                server,
                operation="zim_browse",
                error=e,
                context=f"Namespace: {namespace}, Mode: {mode}",
            )
