"""zim_metadata — archive M-namespace fields + namespace inventory.

Collapses ``get_zim_metadata`` + ``list_namespaces`` (2 → 1; the
legacy ``get_main_page`` moves to ``zim_get(main_page=True)``).
Delegates to the D2 combined wrapper
``AsyncZimOperations.get_archive_metadata_data``.
"""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)

_DIR = pathlib.Path(__file__).parent
_DESCRIPTION = (_DIR / "zim_metadata_description.md").read_text(encoding="utf-8")


def register(server: "OpenZimMcpServer") -> None:
    """Register the `zim_metadata` tool with the MCP server."""
    from ..async_operations import AsyncZimOperations

    ops = AsyncZimOperations(server.zim_operations)

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_metadata(zim_file_path: str) -> Any:
        try:
            return await ops.get_archive_metadata_data(zim_file_path)
        except Exception as e:  # noqa: BLE001 — broad catch matches b13 envelope
            logger.error(f"Error in zim_metadata: {e}")
            return server._create_enhanced_error_message(
                operation="zim_metadata",
                error=e,
                context=f"Path: {zim_file_path}",
            )
