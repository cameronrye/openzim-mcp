"""zim_links — outbound/inbound link buckets or related-article suggestions.

Collapses ``extract_article_links`` + ``get_related_articles`` +
``get_inbound_links`` (3 → 1) via a
``direction: Literal["outbound", "inbound", "related"]`` dispatch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Optional

from ..linkgraph.reader import LinkGraphUnavailable
from ..responses import tool_error
from ._common import (
    cursor_context_mismatch,
    decode_cursor_state,
    enforce_rate_limit,
    load_description,
    tool_error_response,
)

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

_DESCRIPTION = load_description("zim_links")

_VALID_DIRECTIONS = {"outbound", "inbound", "related"}
_VALID_KINDS = {"internal", "external", "media"}


def register(server: "OpenZimMcpServer") -> None:
    """Register the `zim_links` tool with the MCP server."""
    from ..async_operations import AsyncZimOperations

    ops = AsyncZimOperations(server.zim_operations)

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_links(
        zim_file_path: str,
        entry_path: str,
        direction: Literal["outbound", "inbound", "related"] = "outbound",
        kind: Literal["internal", "external", "media"] = "internal",
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Any:
        try:
            rl = enforce_rate_limit(server, "zim_links")
            if rl is not None:
                return rl
            if direction not in _VALID_DIRECTIONS:
                return tool_error(
                    operation="invalid_direction",
                    message=(
                        f"`direction` must be one of {sorted(_VALID_DIRECTIONS)} "
                        f"(provided: {direction!r})."
                    ),
                )

            if direction == "outbound":
                if kind not in _VALID_KINDS:
                    return tool_error(
                        operation="invalid_kind",
                        message=(
                            f"`kind` must be one of {sorted(_VALID_KINDS)} "
                            f"(provided: {kind!r})."
                        ),
                    )
                state, cursor_error = decode_cursor_state(
                    cursor, expected_tool="extract_article_links"
                )
                if cursor_error is not None:
                    return cursor_error
                eff_limit = limit if limit is not None else 100
                eff_kind: str = kind
                if state is not None:
                    # Guard against replaying entry A's cursor against entry B,
                    # which would apply A's offset to B's link list.
                    ep_error = cursor_context_mismatch(
                        state, field="ep", expected=entry_path, label="entry"
                    )
                    if ep_error is not None:
                        return ep_error
                    # Honour the bucket the cursor was issued for. A cursor for
                    # the 'external' bucket must not silently resume against
                    # 'internal'; reject an explicit non-default `kind` that
                    # contradicts the cursor's encoded 'k', else adopt it.
                    cursor_kind = state.get("k")
                    if isinstance(cursor_kind, str) and cursor_kind:
                        if kind != "internal" and kind != cursor_kind:
                            return cursor_context_mismatch(
                                state, field="k", expected=kind, label="kind"
                            )
                        eff_kind = cursor_kind
                    return await ops.extract_article_links_data(
                        zim_file_path,
                        entry_path,
                        limit=eff_limit,
                        offset=int(state.get("o", 0) or 0),
                        kind=eff_kind,
                        cursor_archive_identity=state.get("ai"),
                    )
                return await ops.extract_article_links_data(
                    zim_file_path,
                    entry_path,
                    limit=eff_limit,
                    offset=offset,
                    kind=eff_kind,
                )

            if direction == "inbound":
                state, cursor_error = decode_cursor_state(
                    cursor, expected_tool="get_inbound_links"
                )
                if cursor_error is not None:
                    return cursor_error
                eff_offset = offset
                if state is not None:
                    # Guard against replaying entry A's cursor against entry B,
                    # which would apply A's offset to B's inbound list.
                    ep_error = cursor_context_mismatch(
                        state, field="ep", expected=entry_path, label="entry"
                    )
                    if ep_error is not None:
                        return ep_error
                    eff_offset = int(state.get("o", 0) or 0)
                try:
                    return await ops.get_inbound_links_data(
                        zim_file_path,
                        entry_path,
                        limit=limit if limit is not None else 10,
                        offset=eff_offset,
                        cursor_archive_identity=state.get("ai") if state else None,
                    )
                except LinkGraphUnavailable as e:
                    return tool_error(
                        operation="inbound_sidecar_unavailable", message=str(e)
                    )

            # direction == "related" — a single ranked set, never paginated
            # (the data layer always returns next_cursor=None), so a cursor
            # here is a caller error rather than a silent no-op.
            if cursor is not None and str(cursor).strip():
                return tool_error(
                    operation="cursor_unsupported",
                    message=(
                        "`direction='related'` returns a single ranked set and "
                        "does not paginate; omit `cursor`."
                    ),
                )
            return await ops.get_related_articles_data(
                zim_file_path,
                entry_path,
                limit=limit if limit is not None else 10,
            )
        except Exception as e:  # noqa: BLE001 — broad catch matches b13 envelope
            return tool_error_response(
                server,
                operation="zim_links",
                error=e,
                context=f"Path: {entry_path}, Direction: {direction}",
            )
