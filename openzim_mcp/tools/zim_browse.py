"""zim_browse — paginated browse or full walk of a ZIM namespace.

Collapses ``browse_namespace`` + ``walk_namespace`` (2 → 1) via a
``mode: Literal["page", "walk"]`` dispatch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Optional

from pydantic import Field

from ..responses import tool_error
from ._common import (
    cursor_context_mismatch,
    decode_cursor_state,
    effective_limit,
    enforce_rate_limit,
    load_description,
    tool_error_response,
)

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

_DESCRIPTION = load_description("zim_browse")

_VALID_MODES = {"page", "walk"}

# ``mode`` is typed ``str`` with the enum attached as schema metadata rather
# than as ``Literal["page", "walk"]``. The wire schema is byte-identical
# (``enum: ["page", "walk"]`` — the prototype-parity snapshot pins it), but a
# ``Literal`` let pydantic reject an unknown value before the handler ran,
# so the documented ``invalid_mode`` envelope below was unreachable over MCP
# and callers got ``Error executing tool zim_browse: 1 validation error ...
# errors.pydantic.dev`` instead.
_ModeArg = Annotated[str, Field(json_schema_extra={"enum": sorted(_VALID_MODES)})]


def register(server: "OpenZimMcpServer") -> None:
    """Register the `zim_browse` tool with the MCP server."""
    from ..async_operations import AsyncZimOperations
    from ..zim.namespace import _NamespaceMixin

    ops = AsyncZimOperations(server.zim_operations)

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_browse(
        zim_file_path: str,
        namespace: str,
        mode: _ModeArg = "page",
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        include_assets: bool = False,
    ) -> Any:
        try:
            # Internal operation name, not the wire name — see
            # ``RATE_LIMIT_COSTS`` in ``defaults.py``. Both ``page`` and
            # ``walk`` modes are namespace enumeration.
            rl = enforce_rate_limit(server, "browse_namespace")
            if rl is not None:
                return rl
            if mode not in _VALID_MODES:
                return tool_error(
                    operation="invalid_mode",
                    message=(
                        f"`mode` must be one of {sorted(_VALID_MODES)} "
                        f"(provided: {mode!r})."
                    ),
                )
            # Walk iterates by entry id from the position its own cursor
            # encodes, and ``walk_namespace_data`` has no offset parameter —
            # so an ``offset`` here was accepted and dropped, handing back
            # page one to a caller who believed it had advanced. Reject it and
            # name the cursor, which is the only thing that does advance a
            # walk. (Page mode's offset is load-bearing and unaffected.)
            if mode == "walk" and offset:
                return tool_error(
                    operation="invalid_combination",
                    message=(
                        "`mode='walk'` iterates by entry id and does not "
                        f"accept `offset` (provided: {offset}); it would "
                        "return the first page again. Follow `next_cursor` to "
                        "advance a walk, or use `mode='page'` to seek by "
                        "`offset`."
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
            eff_assets = include_assets
            if state is not None:
                # The cursor's ``ns`` is canonical (the data layer maps
                # "c"/"content" → "C" before encoding), so canonicalise the
                # caller's namespace the same way before comparing —
                # otherwise a lowercase or long-form namespace that
                # succeeded on page 1 falsely rejects its own cursor.
                canonical_ns = _NamespaceMixin._canonicalise_namespace(
                    namespace.strip()
                )
                ns_error = cursor_context_mismatch(
                    state, field="ns", expected=canonical_ns, label="namespace"
                )
                if ns_error is not None:
                    return ns_error
                # Honour the asset visibility the cursor was issued under:
                # a browse offset is counted against the filtered row
                # stream, so resuming with the flag flipped skips or
                # repeats rows. Reject an explicit include_assets=True that
                # contradicts the cursor, else adopt the pinned flag (the
                # same shape zim_links uses for its 'k' bucket).
                cursor_assets = state.get("as")
                if isinstance(cursor_assets, bool):
                    if include_assets and not cursor_assets:
                        return tool_error(
                            operation="cursor_context_mismatch",
                            message=(
                                "Cursor was issued with include_assets=False; "
                                "this call passed include_assets=True. Drop "
                                "the `cursor` and start over to change asset "
                                "visibility."
                            ),
                            context=f"as={cursor_assets!r}",
                        )
                    eff_assets = cursor_assets

            if mode == "page":
                eff_limit = effective_limit(limit, state, 50)
                if state is not None:
                    return await ops.browse_namespace_data(
                        zim_file_path,
                        namespace=namespace,
                        limit=eff_limit,
                        offset=int(state.get("o", 0) or 0),
                        cursor_archive_identity=state.get("ai"),
                        include_assets=eff_assets,
                    )
                return await ops.browse_namespace_data(
                    zim_file_path,
                    namespace=namespace,
                    limit=eff_limit,
                    offset=offset,
                    include_assets=eff_assets,
                )

            # mode == "walk" — v2 walk takes the decoded cursor-state dict
            # directly (``scan_at`` resume id + limit), so callers never have
            # to round-trip through base64 themselves.
            eff_limit = effective_limit(limit, state, 200)
            if state is not None:
                # Walk cursors encode the resume entry id under the wire key
                # ``o`` (see the walkers in zim/namespace.py), which
                # walk_namespace_data expects back as ``scan_at``.
                cursor_state: dict[str, Any] = {
                    "scan_at": int(state.get("o", state.get("scan_at", 0)) or 0),
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
                    include_assets=eff_assets,
                )
            return await ops.walk_namespace_data(
                zim_file_path,
                namespace,
                limit=eff_limit,
                include_assets=eff_assets,
            )
        except Exception as e:  # noqa: BLE001 — broad catch matches b13 envelope
            return tool_error_response(
                server,
                operation="zim_browse",
                error=e,
                context=f"Namespace: {namespace}, Mode: {mode}",
            )
