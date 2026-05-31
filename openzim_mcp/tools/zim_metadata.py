"""zim_metadata — archive M-namespace fields + namespace inventory.

Collapses ``get_zim_metadata`` + ``list_namespaces`` (2 → 1; the
legacy ``get_main_page`` moves to ``zim_get(main_page=True)``).
Delegates to the D2 combined wrapper
``AsyncZimOperations.get_archive_metadata_data``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ._common import load_description, tool_error_response

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)

_DESCRIPTION = load_description("zim_metadata")


def register(server: "OpenZimMcpServer") -> None:
    """Register the `zim_metadata` tool with the MCP server."""
    from ..async_operations import AsyncZimOperations

    ops = AsyncZimOperations(server.zim_operations)

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_metadata(zim_file_path: str) -> Any:
        try:
            return await ops.get_archive_metadata_data(zim_file_path)
        except Exception as e:  # noqa: BLE001 — broad catch matches b13 envelope
            return tool_error_response(
                server,
                operation="zim_metadata",
                error=e,
                context=f"Path: {zim_file_path}",
            )
