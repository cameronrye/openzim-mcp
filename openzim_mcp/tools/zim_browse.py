"""zim_browse — paginated browse or full walk of a ZIM namespace.

Collapses ``browse_namespace`` + ``walk_namespace`` (2 → 1) via a
``mode: Literal["page", "walk"]`` dispatch.
"""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING, Any, Literal, Optional

from ..responses import tool_error

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)

_DIR = pathlib.Path(__file__).parent
_DESCRIPTION = (_DIR / "zim_browse_description.md").read_text(encoding="utf-8")

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
            logger.error(f"Error in zim_browse: {e}")
            return server._create_enhanced_error_message(
                operation="zim_browse",
                error=e,
                context=f"Namespace: {namespace}, Mode: {mode}",
            )
