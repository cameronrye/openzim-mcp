"""zim_health — combined server-state introspection.

Collapses ``get_server_health`` + ``get_server_configuration`` +
``list_zim_files`` (3 → 1) via the D2 combined wrapper
``AsyncZimOperations.get_health_data``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from ._common import load_description, tool_error_response

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)

_DESCRIPTION = load_description("zim_health")


def register(server: "OpenZimMcpServer") -> None:
    """Register the `zim_health` tool with the MCP server."""
    from ..async_operations import AsyncZimOperations

    ops = AsyncZimOperations(server.zim_operations)

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_health(zim_file_path: Optional[str] = None) -> Any:
        try:
            # No argument → combined server state (health + config + files).
            # With a path → validate/diagnose that one archive
            # (Archive.check() + checksum + index/identity).
            if zim_file_path is None:
                return await ops.get_health_data(server)
            return await ops.get_archive_validation_data(zim_file_path)
        except Exception as e:  # noqa: BLE001 — broad catch matches b13 envelope
            return tool_error_response(
                server,
                operation="zim_health",
                error=e,
                context=(
                    f"validation for {zim_file_path}"
                    if zim_file_path is not None
                    else "combined server-state introspection"
                ),
            )
