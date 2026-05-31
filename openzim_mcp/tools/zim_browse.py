"""zim_browse — paginated browse or full walk of a ZIM namespace.

Collapses ``browse_namespace`` + ``walk_namespace`` (2 → 1) via a
``mode: Literal["page", "walk"]`` dispatch.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal, Optional

from ..responses import tool_error
from ._common import load_description, tool_error_response

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)

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

            if mode == "page":
                return await ops.browse_namespace_data(
                    zim_file_path,
                    namespace=namespace,
                    limit=limit if limit is not None else 50,
                    offset=offset,
                )
            # mode == "walk"
            return await ops.walk_namespace_data(
                zim_file_path,
                namespace,
                limit=limit if limit is not None else 200,
            )
        except Exception as e:  # noqa: BLE001 — broad catch matches b13 envelope
            return tool_error_response(
                server,
                operation="zim_browse",
                error=e,
                context=f"Namespace: {namespace}, Mode: {mode}",
            )
