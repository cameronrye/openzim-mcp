"""zim_links — outbound link buckets or related-article suggestions.

Collapses ``extract_article_links`` + ``get_related_articles`` (2 → 1)
via a ``direction: Literal["outbound", "related"]`` dispatch.
v2.0 omits ``"inbound"`` per spec — see description file.
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

_DESCRIPTION = load_description("zim_links")

_VALID_DIRECTIONS = {"outbound", "related"}


def register(server: "OpenZimMcpServer") -> None:
    """Register the `zim_links` tool with the MCP server."""
    from ..async_operations import AsyncZimOperations

    ops = AsyncZimOperations(server.zim_operations)

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_links(
        zim_file_path: str,
        entry_path: str,
        direction: Literal["outbound", "related"] = "outbound",
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Any:
        try:
            if direction not in _VALID_DIRECTIONS:
                return tool_error(
                    operation="invalid_direction",
                    message=(
                        f"`direction` must be one of {sorted(_VALID_DIRECTIONS)} "
                        f"(provided: {direction!r}). 'inbound' lands in v2.5 "
                        "with the link-graph sidecar."
                    ),
                )

            if direction == "outbound":
                state, cursor_error = decode_cursor_state(
                    cursor, expected_tool="extract_article_links"
                )
                if cursor_error is not None:
                    return cursor_error
                eff_limit = limit if limit is not None else 100
                if state is not None:
                    # Guard against replaying entry A's cursor against entry B,
                    # which would apply A's offset to B's link list.
                    ep_error = cursor_context_mismatch(
                        state, field="ep", expected=entry_path, label="entry"
                    )
                    if ep_error is not None:
                        return ep_error
                    return await ops.extract_article_links_data(
                        zim_file_path,
                        entry_path,
                        limit=eff_limit,
                        offset=int(state.get("o", 0) or 0),
                        cursor_archive_identity=state.get("ai"),
                    )
                return await ops.extract_article_links_data(
                    zim_file_path,
                    entry_path,
                    limit=eff_limit,
                    offset=offset,
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
